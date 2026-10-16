"""EvalAI 공개 challenge API → 대상 학회와 연결된 challenge."""
from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from ..deadlines import Edition
from ..fetch import Fetcher
from ..match import Matcher
from ..models import Challenge

log = logging.getLogger(__name__)

API = "https://eval.ai/api/challenges/challenge/{kind}/approved/public"
PAGE = "https://eval.ai/web/challenges/challenge-page/{id}/overview"

# 본문에서 학회명을 찾는 패턴 (RSS 는 일반 단어라 연도와 붙어 있을 때만)
ALIASES = {
    "cvpr": r"CVPR", "iccv": r"ICCV", "eccv": r"ECCV", "aaai": r"AAAI", "iclr": r"ICLR", "icml": r"ICML",
    "nips": r"NeurIPS|NIPS", "iros": r"IROS", "icra": r"ICRA", "rss": r"RSS", "corl": r"CoRL",
}


def conf_year_re(key: str, year: int) -> re.Pattern:
    yy = f"{year % 100:02d}"
    return re.compile(rf"\b(?:{ALIASES[key]})\s*[-'’ ]?\s*(?:{year}|{yy})\b", re.I if key != "rss" else 0)


def fetch_all(fetcher: Fetcher, kinds=("present", "past", "future")) -> list[dict]:
    out = []
    for kind in kinds:
        url = API.format(kind=kind)
        for _ in range(100):
            d = fetcher.get_json(url)
            if not d:
                break
            out += d.get("results", [])
            url = d.get("next")
            if not url:
                break
    log.info("EvalAI challenge %d개", len(out))
    return out


def find(fetcher: Fetcher, matcher: Matcher, editions: list[Edition], raw: list[dict] | None = None) -> list[Challenge]:
    raw = raw if raw is not None else fetch_all(fetcher)
    pats = [(e, conf_year_re(e.key, e.year)) for e in editions]
    out, seen = [], set()
    for c in raw:
        desc = BeautifulSoup(c.get("description") or "", "lxml").get_text(" ")
        text = " ".join([c.get("title") or "", c.get("short_description") or "", desc])
        text = re.sub(r"\s+", " ", text)
        for e, rx in pats:
            if not rx.search(text) or (c["id"], e.id) in seen:
                continue
            hits = matcher.keyword_hits(text)
            if not hits:
                continue
            seen.add((c["id"], e.id))
            out.append(Challenge(
                conf=e.name, conf_key=e.key, year=e.year, title=c.get("title", ""),
                url=PAGE.format(id=c["id"]), keywords=hits, platforms=[PAGE.format(id=c["id"])],
                snippet=matcher.snippet(text), source="evalai", end_date=(c.get("end_date") or "")[:10],
            ))
    return out
