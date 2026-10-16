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
a{color:#0969da}
"""


def esc(s) -> str:
    return html.escape(str(s or ""))


def d_day(when: dt.datetime, now: dt.datetime) -> str:
    days = (when - now).days
    return "D-day" if days == 0 else f"D-{days}"


def challenge_rows(chs: list[Challenge], new_ids: set[str]) -> str:
    rows = []
    for c in chs:
        tags = "".join(f'<span class="tag">{esc(k)}</span>' for k in c.keywords)
        extra = []
        if c.end_date:
            extra.append(f"제출 마감 {esc(c.end_date)}")
        for p in c.platforms[:2]:
            extra.append(f'<a href="{esc(p)}">{esc(p.split("/")[2])}</a>')
        if c.detail_url and c.detail_url != c.url:
            extra.append(f'<a href="{esc(c.detail_url)}">학회 페이지</a>')
        rows.append(
            f'<tr class="{"new" if c.id in new_ids else ""}"><td>{esc(c.conf)} {c.year}</td>'
            f'<td><a href="{esc(c.url)}"><b>{esc(c.title)}</b></a> {tags}<br>'
            f'<span class="muted">{esc(c.snippet[:280])}</span><br><span class="muted">{" · ".join(extra)}</span></td></tr>')
    return "<table><tr><th>학회</th><th>Challenge / Workshop</th></tr>" + "".join(rows) + "</table>"


def build_html(now: dt.datetime, challenges: list[Challenge], new_ids: set[str],
               upcoming: list[tuple[Edition, object]], dl_changes: list[str], scanned: list[str],
               errors: list[str]) -> str:
    new = [c for c in challenges if c.id in new_ids]
    parts = [f"<h1>학회 Challenge · 마감일 주간 리포트</h1>"
             f'<div class="muted">{now.astimezone(KST):%Y-%m-%d %H:%M} KST · 새 challenge {len(new)}건 · '
             f"마감일 변경 {len(dl_changes)}건</div>"]

    parts.append(f"<h2>🆕 새로 발견된 challenge ({len(new)})</h2>")
    parts.append(challenge_rows(new, new_ids) if new else '<p class="muted">이번 주 새 항목 없음</p>')

    if dl_changes:
        parts.append(f"<h2>📌 마감일 추가/변경 ({len(dl_changes)})</h2><ul>"
                     + "".join(f"<li>{esc(x)}</li>" for x in dl_changes) + "</ul>")

    parts.append("<h2>⏰ 다가오는 논문 마감일</h2>")
    if upcoming:
        rows = "".join(
            f"<tr><td>{d_day(d.when_utc, now)}</td><td><a href=\"{esc(e.link)}\">{esc(e.name)} {e.year}</a></td>"
            f"<td>{KIND_KO.get(d.kind, d.kind)}</td><td>{d.when_utc.astimezone(KST):%Y-%m-%d %H:%M} KST"
            f'<br><span class="muted">{esc(d.raw)} {esc(d.tz)}</span></td>'
            f'<td class="muted">{esc(e.date)}<br>{esc(e.place)}</td></tr>'
            for e, d in upcoming)
        parts.append("<table><tr><th></th><th>학회</th><th>구분</th><th>마감 (KST)</th><th>개최</th></tr>"
                     + rows + "</table>")
    else:
        parts.append('<p class="muted">예정된 마감일 없음</p>')

    parts.append(f"<h2>📋 추적 중인 전체 challenge ({len(challenges)})</h2>")
    parts.append(challenge_rows(challenges, new_ids) if challenges else '<p class="muted">없음</p>')

    parts.append(f'<p class="muted">탐색한 회차: {esc(", ".join(scanned))}</p>')
    if errors:
        parts.append('<p class="muted">⚠️ ' + "<br>".join(esc(e) for e in errors) + "</p>")
    parts.append('<p class="muted">마감일 출처: ccfddl/ccf-deadlines · challenge 출처: 학회 workshop/competition 페이지, EvalAI</p>')
    return f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>conf-watch</title><style>{CSS}</style></head><body>{"".join(parts)}</body></html>'
