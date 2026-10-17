"""challenge 페이지 본문에서 시작일/마감일 추출."""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

MONTHS = {}
for i, names in enumerate([("january", "jan"), ("february", "feb"), ("march", "mar"), ("april", "apr"),
                           ("may",), ("june", "jun"), ("july", "jul"), ("august", "aug"),
                           ("september", "sep", "sept"), ("october", "oct"), ("november", "nov"),
                           ("december", "dec")], start=1):
    for n in names:
        MONTHS[n] = i

_MON = r"(?P<mon>" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\.?"
_DAY = r"(?P<day>[0-3]?\d)(?:st|nd|rd|th)?"
_YEAR = r"(?:,?\s*(?P<year>20\d\d))?"
DATE_RES = [
    re.compile(rf"\b(?P<iy>20\d\d)[-/.](?P<im>[01]?\d)[-/.](?P<id>[0-3]?\d)\b"),          # 2026-03-15
    re.compile(rf"\b{_MON}\s+{_DAY}\b(?!\s*(?:am|pm|:))(?:\s*[-–—]\s*(?P<day2>[0-3]?\d)\b(?!\s*(?:am|pm|:)))?{_YEAR}", re.I),  # March 15, 2026
    re.compile(rf"\b{_DAY}\s+(?:of\s+)?{_MON}{_YEAR}\b", re.I),                           # 15 March 2026
]

PAPER_RE = re.compile(r"paper|camera|notification|abstract|author|extended|poster|archival|cfp|call for", re.I)
CHAL_RE = re.compile(r"challenge|competition|leaderboard|test (?:phase|set|server)|phase|track|result|evaluation|"
                     r"dev(?:elopment)? (?:phase|set)|validation|final|team|winner|technical report", re.I)
END_RE = re.compile(r"deadline|due\b|clos(?:e|es|ed|ing)|ends?\b|end of|freeze|last day|until|final submission|"
                    r"submission|submit", re.I)
START_RE = re.compile(r"launch|open(?:s|ing)?\b|start|release|begin|available|kick-?off|registration", re.I)
# 대회 종료 후 제출물(기술 보고서 등) 마감은 약한 신호
REPORT_RE = re.compile(r"technical report|fact ?sheet|\breport\b|code release|presentation|video|notif|announce|winners?", re.I)
# 대회 당일 (결선, 레이스, 해커톤 등)
EVENT_RE = re.compile(r"final|competition|race|hackathon|match|day \d|finals?\b|award", re.I)
SKIP_RE = re.compile(r"workshop (?:date|day)|conference|held on|copyright|updated|posted|news|©", re.I)


@dataclass
class Window:
    start: dt.date | None = None
    end: dt.date | None = None
    source: str = ""        # site / evalai
    end_strong: bool = False  # 마감일 라벨에 challenge 관련 단어가 있었는지 (약하면 숨김 판단에 쓰지 않음)

    @property
    def known(self) -> bool:
        return bool(self.start or self.end)


def infer_year(month: int, day: int, anchor: dt.date) -> dt.date | None:
    """연도 없는 날짜: 학회 개최일 기준 [-330일, +45일] 안에 들어오는 해."""
    for y in (anchor.year, anchor.year - 1, anchor.year + 1):
        try:
            d = dt.date(y, month, day)
        except ValueError:
            return None
        if anchor - dt.timedelta(days=330) <= d <= anchor + dt.timedelta(days=45):
            return d
    return None


def find_dates(line: str, anchor: dt.date) -> list[tuple[dt.date, int, int]]:
    out, taken = [], []
    for rx in DATE_RES:
        for m in rx.finditer(line):
            if any(a <= m.start() < b for a, b in taken):
                continue
            g = m.groupdict()
            try:
                if g.get("iy"):
                    d = dt.date(int(g["iy"]), int(g["im"]), int(g["id"]))
                else:
                    mon, day = MONTHS[g["mon"].lower().rstrip(".")], int(g["day"])
                    d = dt.date(int(g["year"]), mon, day) if g.get("year") else infer_year(mon, day, anchor)
            except (ValueError, KeyError):
                continue
            if d and abs((d - anchor).days) < 500:
                out.append((d, m.start(), m.end()))
                taken.append((m.start(), m.end()))
                if g.get("day2") and int(g["day2"]) > d.day:      # "Sept 28 – 30" → 30일도
                    try:
                        out.append((d.replace(day=int(g["day2"])), m.start(), m.end()))
                    except ValueError:
                        pass
    return out


HEADINGS = ["h1", "h2", "h3", "h4", "h5", "h6"]
# 그룹 이름이 겹치므로 이름 없는 그룹으로 바꿔 합친다
DATE_ANY = re.compile("|".join(re.sub(r"\(\?P<\w+>", "(?:", r.pattern) for r in DATE_RES), re.I)


def _label(text: str) -> str:
    return DATE_ANY.sub(" ", text)


def date_contexts(soup, anchor: dt.date):
    """(날짜, 라벨 문맥, 섹션 제목) — 날짜가 든 텍스트에서 라벨이 생길 때까지 부모 블록으로 올라간다.
    '날짜 | 라벨' 표, '라벨: 날짜' 목록, '날짜' 다음 줄 '라벨' 카드 모두 처리."""
    for node in soup.find_all(string=DATE_ANY):
        txt = re.sub(r"\s+", " ", str(node)).strip()
        if not txt or len(txt) > 400:
            continue
        dates = find_dates(txt, anchor)
        if not dates:
            continue
        el, ctx = node.parent, txt
        for _ in range(4):
            if el is None or re.search(r"[A-Za-z]{4,}", _label(ctx)):
                break
            parent = el.parent
            ptxt = re.sub(r"\s+", " ", parent.get_text(" ", strip=True)) if parent is not None else ""
            if not ptxt or len(ptxt) > 300:
                break
            el, ctx = parent, ptxt
        h = el.find_previous(HEADINGS) if el is not None else None
        heading = re.sub(r"\s+", " ", h.get_text(" ", strip=True))[:120] if h else ""
        for d, a, b in dates:
            # 긴 문장이면 날짜 주변만
            local = ctx if len(ctx) <= 200 else ctx[max(0, ctx.find(txt) + a - 100): ctx.find(txt) + b + 60]
            yield d, local, heading


CHAL_WORD_RE = re.compile(r"challenge|competition|leaderboard|test (?:phase|set|server)|policy|track|evaluation", re.I)


def extract_window(soups, anchor: dt.date) -> Window:
    """challenge 시작·마감.

    마감: 마감 라벨(deadline/close/end/last day/submission)이 붙은 날짜 중 학회 이전의 가장 늦은 날짜.
          라벨이나 섹션 제목에 challenge 관련 단어가 있으면 '강한' 마감. 논문 마감은 제외.
    시작: launch/open/start/release 라벨이 붙은 가장 이른 날짜.
    """
    strong_end, weak_end, starts = [], [], []
    for soup in soups:
        for d, ctx, heading in date_contexts(soup, anchor):
            if d > anchor + dt.timedelta(days=7):      # 학회 이후 날짜는 challenge 기간이 아님
                continue
            if SKIP_RE.search(ctx) and not CHAL_WORD_RE.search(ctx):
                continue
            chal_ctx = bool(CHAL_WORD_RE.search(ctx))
            chal_head = bool(CHAL_WORD_RE.search(heading)) and not PAPER_RE.search(heading)
            paper = bool(PAPER_RE.search(ctx)) or (bool(PAPER_RE.search(heading)) and not chal_head)
            if paper and not chal_ctx:
                continue
            closing = re.search(r"deadline|due\b|clos|ends?\b|last day|freeze", ctx, re.I)
            if START_RE.search(ctx) and not closing:
                if chal_ctx or chal_head or not paper:
                    starts.append(d)
            elif (chal_ctx or chal_head) and (closing or END_RE.search(ctx) or EVENT_RE.search(ctx)):
                # challenge 마감 / 리더보드 종료 / 결선 대회일 → challenge 가 끝나는 날
                if closing or not REPORT_RE.search(ctx):
                    strong_end.append(d)
            elif END_RE.search(ctx) and not REPORT_RE.search(ctx):
                weak_end.append(d)
    end = max(strong_end) if strong_end else (max(weak_end) if weak_end else None)
    start = min(starts) if starts else None
    if start and end and start > end:
        start = None
    return Window(start, end, "site" if (start or end) else "", bool(strong_end))
