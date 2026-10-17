"""conf-watch 실행 진입점.

  python -m confwatch run       # 7일 주기 본 실행 (GitHub Actions)
  python -m confwatch run --no-mail --no-state   # 미리보기
  python -m confwatch verify    # 검증 모드 (verify/ground_truth.yaml)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import re
import sys
from pathlib import Path

import yaml

from . import mailer
from .deadlines import Edition, deadline_snapshot, load_editions, upcoming_deadlines
from .fetch import Fetcher
from .match import Matcher
from .models import Challenge
from .report import KIND_KO, KST, build_html
from .sources import evalai
from .sources.crawl import Crawler

log = logging.getLogger("confwatch")
ROOT = Path(__file__).resolve().parent.parent


def load_config(path: str | Path) -> dict:
    return yaml.safe_load(Path(path).read_text())


def make_fetcher(cfg: dict) -> Fetcher:
    c = cfg.get("crawl", {})
    return Fetcher(os.environ.get("CONFWATCH_CACHE", ROOT / ".cache/http"),
                   cache_hours=c.get("cache_hours", 72), timeout=c.get("timeout", 20))


def latest_years(editions: list[Edition]) -> dict[str, int]:
    out: dict[str, int] = {}
    for e in editions:
        out[e.key] = max(out.get(e.key, 0), e.year)
    return out


def active_editions(editions: list[Edition], today: dt.date, past_days: int) -> list[Edition]:
    """개최일이 (오늘 - past_days) 이후인 회차. 개최일 미상이면 올해 이후."""
    cut = today - dt.timedelta(days=past_days)
    return [e for e in editions if (e.start >= cut if e.start else e.year >= today.year)]


def scan_challenges(cfg: dict, fetcher: Fetcher, matcher: Matcher, targets: list[Edition],
                    all_editions: list[Edition], errors: list[str]) -> list[Challenge]:
    confs = cfg["conferences"]
    crawl_cfg = cfg.get("crawl", {})
    crawler = Crawler(fetcher, matcher, crawl_cfg.get("max_items_per_edition", 400), crawl_cfg.get("workers", 8))
    newest = latest_years(all_editions)
    found: dict[str, Challenge] = {}
    for ed in targets:
        log.info("[%s %d] 탐색", ed.name, ed.year)
        try:
            res = crawler.run(ed, confs[ed.key].get("seeds", []), latest=ed.year == newest.get(ed.key))
        except Exception as e:  # noqa: BLE001
            errors.append(f"{ed.name} {ed.year} 크롤링 실패: {e}")
            log.exception("crawl 실패")
            continue
        log.info("  → %d건", len(res))
        for c in res:
            found.setdefault(c.id, c)
    try:
        for c in evalai.find(fetcher, matcher, targets):
            found.setdefault(c.id, c)
    except Exception as e:  # noqa: BLE001
        errors.append(f"EvalAI 조회 실패: {e}")
    order = {k: i for i, k in enumerate(confs)}
    return sorted(found.values(), key=lambda c: (order.get(c.conf_key, 99), -c.year, c.title.lower()))


# ------------------------------------------------------------------ run
def cmd_run(args) -> int:
    cfg = load_config(args.config)
    fetcher = make_fetcher(cfg)
    matcher = Matcher.from_config(cfg)
    now = dt.datetime.now(dt.timezone.utc)
    errors: list[str] = []

    editions = load_editions(fetcher, cfg["conferences"])
    if not editions:
        log.error("ccf-deadlines 데이터를 하나도 받지 못함")
        return 2
    targets = active_editions(editions, now.date(), cfg.get("editions", {}).get("past_days", 30))
    if args.only:
        targets = [e for e in targets if e.key in args.only.split(",")]
    log.info("탐색 회차: %s", ", ".join(f"{e.name}{e.year}" for e in targets))

    challenges = scan_challenges(cfg, fetcher, matcher, targets, editions, errors)

    state_path = Path(args.state)
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    first_run = not state
    seen: dict = state.get("challenges", {})
    new_ids = {c.id for c in challenges if c.id not in seen}

    snap = deadline_snapshot(editions)
    old_snap: dict = state.get("deadlines", {})
    by_id = {e.id: e for e in editions}
    dl_changes = []
    if old_snap:
        for k, v in snap.items():
            if old_snap.get(k) != v:
                eid, kind = k.split("/")
                e = by_id[eid]
                before = f" (이전: {old_snap[k]})" if k in old_snap else ""
                dl_changes.append(f"{e.name} {e.year} {KIND_KO.get(kind, kind)}: {v}{before}")

    upcoming = upcoming_deadlines(editions, now, cfg.get("mail", {}).get("deadline_horizon_days", 365))
    scanned = [f"{e.name} {e.year}" for e in targets]
    html_body = build_html(now, challenges, new_ids, upcoming, dl_changes, scanned, errors)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.html").write_text(html_body)
    (out_dir / "latest.json").write_text(json.dumps({
        "generated": now.isoformat(), "new": sorted(new_ids),
        "challenges": [c.to_dict() for c in challenges],
        "upcoming_deadlines": [{"conf": e.name, "year": e.year, "kind": d.kind, "utc": d.when_utc.isoformat(),
                                "raw": d.raw, "tz": d.tz, "link": e.link} for e, d in upcoming],
    }, ensure_ascii=False, indent=1))
    log.info("보고서: %s (challenge %d건, 신규 %d건, 마감일 변경 %d건, fetch %s)",
             out_dir / "report.html", len(challenges), len(new_ids), len(dl_changes), fetcher.stats)

    def save_state():
        if args.no_state:
            return
        today = now.date().isoformat()
        for c in challenges:
            seen.setdefault(c.id, today)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps({"challenges": seen, "deadlines": snap, "updated": now.isoformat()},
                                         ensure_ascii=False, indent=1, sort_keys=True))

    has_news = bool(new_ids or dl_changes)
    if args.no_mail:
        save_state()
        return 0
    if not has_news and not cfg.get("mail", {}).get("send_when_no_news", True):
        log.info("새 소식 없음 → 메일 생략")
        save_state()
        return 0
    prefix = cfg.get("mail", {}).get("subject_prefix", "[conf-watch]")
    tag = "첫 실행" if first_run else f"새 challenge {len(new_ids)} · 마감 변경 {len(dl_changes)}"
    subject = f"{prefix} {now.astimezone(KST):%Y-%m-%d} 주간 리포트 ({tag})"
    text = "\n".join([subject, "", *[f"- [{c.conf} {c.year}] {c.title}\n  {c.url}" for c in challenges if c.id in new_ids],
                      "", *[f"- {x}" for x in dl_changes],
                      "", *[f"- {e.name} {e.year} {KIND_KO.get(d.kind, d.kind)} {d.when_utc.astimezone(KST):%Y-%m-%d %H:%M} KST"
                            for e, d in upcoming[:15]]])
    # 메일이 실제로 나간 뒤에만 state 를 갱신한다 (실패 시 다음 실행에서 같은 소식을 다시 보냄)
    st = mailer.settings(cfg.get("mail", {}))
    if mailer.missing(st):
        log.error("메일 설정 누락: %s → 메일을 보낼 수 없음 (미리보기만 하려면 --no-mail)", ", ".join(mailer.missing(st)))
        return 1
    mailer.send(subject, html_body, text, st)
    save_state()
    return 0


# ------------------------------------------------------------------ verify
def cmd_verify(args) -> int:
    """정답 세트(과거/진행 중 challenge, 알려진 마감일)를 실제로 찾아내는지 확인."""
    cfg = load_config(args.config)
    gt = yaml.safe_load(Path(args.truth).read_text())
    fetcher = make_fetcher(cfg)
    editions = load_editions(fetcher, cfg["conferences"])
    by_id = {e.id: e for e in editions}
    failures = 0

    print("\n=== 1. 논문 마감일 (ccf-deadlines) ===")
    for d in gt.get("deadlines", []):
        e = by_id.get(f"{d['conf']}{d['year']}")
        got = next((x for x in (e.deadlines if e else []) if x.kind == d.get("kind", "deadline")), None)
        ok = bool(got and got.when_utc and got.when_utc.strftime("%Y-%m-%d") == d["utc_date"])
        failures += not ok
        print(f"  {'PASS' if ok else 'FAIL'}  {d['conf']}{d['year']} {d.get('kind', 'deadline')}: "
              f"기대 {d['utc_date']} / 실제 {got.when_utc.strftime('%Y-%m-%d %H:%M UTC') if got and got.when_utc else None}")

    print("\n=== 2. Challenge 탐지 ===")
    cases = gt.get("challenges", [])
    if args.case:
        cases = [c for c in cases if re.search(args.case, c["name"], re.I)]
    groups: dict[tuple, list] = {}
    for c in cases:
        groups.setdefault((c["conf"], c["year"], tuple(c.get("keywords") or cfg.get("keywords") or [])), []).append(c)

    n_ok = 0
    newest = latest_years(editions)
    for (conf, year, kws), cs in groups.items():
        e = by_id.get(f"{conf}{year}")
        if not e:
            for c in cs:
                print(f"  FAIL  {c['name']}: ccf-deadlines 에 {conf}{year} 없음")
            continue
        matcher = Matcher.from_config({**cfg, "keywords": list(kws)})
        errors: list[str] = []
        found = scan_challenges(cfg, fetcher, matcher, [e], editions, errors)
        for c in cs:
            pat = re.compile(c["expect"], re.I)
            hit = next((f for f in found if pat.search(f.url) or pat.search(f.title)
                        or any(pat.search(p) for p in f.platforms)), None)
            n_ok += bool(hit)
            status = "PASS" if hit else "FAIL"
            tag = "진행중" if c.get("status") == "ongoing" else "과거"
            print(f"  {status}  [{tag}] {c['name']} ({e.name} {year}, 검색어={list(kws)})")
            if hit:
                print(f"         → {hit.title[:80]} | {hit.url} | {hit.source} | 매칭 {hit.keywords}")
            else:
                print(f"         → 탐지 실패. 후보 {len(found)}건: " + "; ".join(f.title[:40] for f in found[:5]))
        if errors:
            print("  ⚠️ " + " / ".join(errors))
    total = len(cases)
    recall = n_ok / total if total else 1.0
    print(f"\nChallenge recall: {n_ok}/{total} = {recall:.0%} (기준 {args.min_recall:.0%})")
    print(f"마감일 실패: {failures}건 · fetch {fetcher.stats}")
    return 0 if failures == 0 and recall >= args.min_recall else 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="confwatch")
    p.add_argument("--config", default=str(ROOT / "config.yaml"))
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="주간 실행: 수집 → 보고서 → 메일")
    r.add_argument("--state", default=str(ROOT / "state/seen.json"))
    r.add_argument("--out", default=str(ROOT / "docs"))
    r.add_argument("--no-mail", action="store_true")
    r.add_argument("--no-state", action="store_true", help="state 파일을 갱신하지 않음 (미리보기)")
    r.add_argument("--only", help="특정 학회만 (쉼표 구분 ccf key, 예: cvpr,corl)")
    r.set_defaults(func=cmd_run)

    v = sub.add_parser("verify", help="검증 모드: 알려진 challenge/마감일을 찾아내는지 확인")
    v.add_argument("--truth", default=str(ROOT / "verify/ground_truth.yaml"))
    v.add_argument("--case", help="이름에 매칭되는 케이스만 (정규식)")
    v.add_argument("--min-recall", type=float, default=0.8)
    v.set_defaults(func=cmd_verify)

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
