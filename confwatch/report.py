"""메일/웹용 HTML 보고서."""
from __future__ import annotations

import datetime as dt
import html

from .deadlines import Edition
from .models import Challenge

KST = dt.timezone(dt.timedelta(hours=9))
KIND_KO = {"abstract_deadline": "초록 마감", "deadline": "논문 마감",
           "rebuttal_deadline": "rebuttal", "decision_deadline": "결과 발표"}

CSS = """
body{font-family:-apple-system,Segoe UI,Roboto,'Noto Sans KR',sans-serif;color:#1f2328;max-width:760px;margin:0 auto;padding:12px;line-height:1.5}
h1{font-size:20px;margin:0 0 4px} h2{font-size:16px;margin:24px 0 8px;border-bottom:1px solid #d0d7de;padding-bottom:4px}
table{border-collapse:collapse;width:100%;font-size:13px} td,th{border-bottom:1px solid #eaeef2;padding:6px 4px;text-align:left;vertical-align:top}
th{background:#f6f8fa} .muted{color:#656d76;font-size:12px} .new{background:#fff8c5} .tag{display:inline-block;background:#ddf4ff;color:#0969da;border-radius:10px;padding:0 6px;margin:1px;font-size:11px}
a{color:#0969da} .newb{background:#cf222e;color:#fff;border-radius:4px;padding:0 4px;font-size:10px;font-weight:bold}
.st{border-radius:10px;padding:1px 7px;font-size:11px;white-space:nowrap} .st.on{background:#dafbe1;color:#1a7f37} .st.soon{background:#ddf4ff;color:#0969da} .st.unk{background:#eaeef2;color:#57606a}
td:first-child{white-space:nowrap}
"""


def esc(s) -> str:
    return html.escape(str(s or ""))


def d_day(when: dt.datetime, now: dt.datetime) -> str:
    days = (when - now).days
    return "D-day" if days == 0 else f"D-{days}"


STATUS_STYLE = {"진행 중": "on", "예정": "soon", "기간 미확인": "unk"}


def fmt_day(iso: str) -> str:
    if not iso:
        return "?"
    d = dt.date.fromisoformat(iso)
    return f"{d:%Y-%m-%d}({'월화수목금토일'[d.weekday()]})"


def challenge_sort_key(c: Challenge):
    # 마감일 있는 것 → 마감 임박순, 없는 것 → 학회 개최일순
    return (0, c.end) if c.end else (1, c.conf_start or "9999", c.title.lower())


def challenge_table(chs: list[Challenge], new_ids: set[str], today: dt.date) -> str:
    rows = []
    for c in sorted(chs, key=challenge_sort_key):
        if c.end:
            dd = (dt.date.fromisoformat(c.end) - today).days
            dday = "D-day" if dd == 0 else f"D-{dd}"
        else:
            dday = "–"
        tags = "".join(f'<span class="tag">{esc(k)}</span>' for k in c.keywords)
        new = '<span class="newb">NEW</span> ' if c.id in new_ids else ""
        links = [f'<a href="{esc(p)}">{esc(p.split("/")[2])}</a>' for p in c.platforms[:2] if p != c.url]
        if c.detail_url and c.detail_url != c.url:
            links.append(f'<a href="{esc(c.detail_url)}">학회 페이지</a>')
        period = f"{fmt_day(c.start)}<br>~ {fmt_day(c.end)}" if (c.start or c.end) else \
            f'<span class="muted">사이트에 일정 없음<br>학회 {fmt_day(c.conf_start)}</span>'
        src = {"site": "challenge 사이트", "evalai": "EvalAI"}.get(c.date_source, "")
        rows.append(
            f'<tr class="{"new" if c.id in new_ids else ""}"><td><b>{dday}</b></td>'
            f"<td>{esc(c.conf)} {c.year}</td>"
            f'<td>{new}<a href="{esc(c.url)}"><b>{esc(c.title)}</b></a> {tags}'
            f'<br><span class="muted">{esc(c.snippet[:200])}</span>'
            + (f'<br><span class="muted">{" · ".join(links)}</span>' if links else "") + "</td>"
            f'<td>{period}' + (f'<br><span class="muted">출처: {src}</span>' if src else "") + "</td>"
            f'<td><span class="st {STATUS_STYLE.get(c.status, "unk")}">{esc(c.status)}</span></td></tr>')
    return ("<table><tr><th>마감</th><th>학회</th><th>Challenge</th><th>기간 (시작 ~ 제출 마감)</th><th>상태</th></tr>"
            + "".join(rows) + "</table>")


def build_html(now: dt.datetime, challenges: list[Challenge], new_ids: set[str],
               upcoming: list[tuple[Edition, object]], dl_changes: list[str], scanned: list[str],
               errors: list[str], hidden: int = 0) -> str:
    today = now.astimezone(KST).date()
    n_new = sum(c.id in new_ids for c in challenges)
    parts = [f"<h1>학회 Challenge · 마감일 주간 리포트</h1>"
             f'<div class="muted">{now.astimezone(KST):%Y-%m-%d %H:%M} KST · 진행 중·예정 challenge {len(challenges)}건'
             f"(새로 발견 {n_new}) · 마감일 변경 {len(dl_changes)}건</div>"]

    parts.append(f"<h2>🏁 진행 중·예정 challenge ({len(challenges)})</h2>")
    parts.append(challenge_table(challenges, new_ids, today) if challenges
                 else '<p class="muted">검색어에 맞는 진행 중 challenge 없음</p>')
    parts.append(f'<p class="muted">기간은 challenge 사이트의 일정표나 EvalAI 에서 자동 추출한 값이라 틀릴 수 있음 — 참가 전 사이트에서 확인. '
                 f"이미 끝난 challenge {hidden}건은 숨김.</p>")

    if dl_changes:
        parts.append(f"<h2>📌 마감일 추가/변경 ({len(dl_changes)})</h2><ul>"
                     + "".join(f"<li>{esc(x)}</li>" for x in dl_changes) + "</ul>")

    parts.append("<h2>⏰ 다가오는 논문 마감일</h2>")
    if upcoming:
        rows = "".join(
            f"<tr><td><b>{d_day(d.when_utc, now)}</b></td><td><a href=\"{esc(e.link)}\">{esc(e.name)} {e.year}</a></td>"
            f"<td>{KIND_KO.get(d.kind, d.kind)}</td><td>{d.when_utc.astimezone(KST):%Y-%m-%d %H:%M} KST"
            f'<br><span class="muted">{esc(d.raw)} {esc(d.tz)}</span></td>'
            f'<td class="muted">{esc(e.date)}<br>{esc(e.place)}</td></tr>'
            for e, d in upcoming)
        parts.append("<table><tr><th>마감</th><th>학회</th><th>구분</th><th>마감 (KST)</th><th>개최</th></tr>"
                     + rows + "</table>")
    else:
        parts.append('<p class="muted">예정된 마감일 없음</p>')

    parts.append(f'<p class="muted">탐색한 회차: {esc(", ".join(scanned))}</p>')
    if errors:
        parts.append('<p class="muted">⚠️ ' + "<br>".join(esc(e) for e in errors) + "</p>")
    parts.append('<p class="muted">마감일 출처: ccfddl/ccf-deadlines · challenge 출처: 학회 workshop/competition 페이지, EvalAI</p>')
    return f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>conf-watch</title><style>{CSS}</style></head><body>{"".join(parts)}</body></html>'
