"""학회 논문 마감일: ccfddl/ccf-deadlines 데이터 사용."""
from __future__ import annotations

import datetime as dt
import logging
import re
from dataclasses import dataclass, field

import yaml

from .fetch import Fetcher

log = logging.getLogger(__name__)

CCF_RAW = "https://raw.githubusercontent.com/ccfddl/ccf-deadlines/main/conference/AI/{key}.yml"

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], start=1)}

DEADLINE_KINDS = ("abstract_deadline", "deadline", "rebuttal_deadline", "decision_deadline")


@dataclass
class Deadline:
    kind: str                       # abstract_deadline / deadline / ...
    when_utc: dt.datetime | None    # None 이면 TBD
    raw: str
    tz: str
    comment: str = ""


@dataclass
class Edition:
    key: str            # ccf key (cvpr, nips, ...)
    name: str           # 표시 이름 (CVPR, NeurIPS, ...)
    year: int
    link: str
    date: str           # 개최일 원문
    place: str
    start: dt.date | None
    deadlines: list[Deadline] = field(default_factory=list)

    @property
    def id(self) -> str:
        return f"{self.key}{self.year}"


def parse_tz(tz: str) -> dt.timezone:
    tz = (tz or "").strip()
    if tz.upper() == "AOE":
        return dt.timezone(dt.timedelta(hours=-12))
    m = re.fullmatch(r"UTC([+-]\d{1,2})(?::?(\d{2}))?", tz.replace(" ", ""), re.I)
    if m:
        h = int(m.group(1))
        mins = int(m.group(2) or 0) * (1 if h >= 0 else -1)
        return dt.timezone(dt.timedelta(hours=h, minutes=mins))
    return dt.timezone.utc


def parse_deadline(raw, tz: str) -> dt.datetime | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or s.upper() == "TBD":
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            t = dt.datetime.strptime(s, fmt)
            return t.replace(tzinfo=parse_tz(tz)).astimezone(dt.timezone.utc)
        except ValueError:
            continue
    return None


def parse_start(date_str: str, year: int) -> dt.date | None:
    """'June 5-7, 2026' / 'September 27 - October 1, 2026' / 'December 8-10 (Sydney), ...' -> 시작일."""
    if not date_str:
        return None
    m = re.search(r"([A-Za-z]+)\.?\s+(\d{1,2})", date_str)
    if not m or m.group(1).lower() not in MONTHS:
        return None
    ys = re.findall(r"(20\d\d)", date_str)
    y = int(ys[-1]) if ys else year
    try:
        return dt.date(y, MONTHS[m.group(1).lower()], int(m.group(2)))
    except ValueError:
        return None


def parse_ccf_yaml(key: str, name: str, text: str) -> list[Edition]:
    data = yaml.safe_load(text)
    if not data:
        return []
    out = []
    for conf in data[0].get("confs", []):
        year = int(conf["year"])
        tz = str(conf.get("timezone", "UTC"))
        ed = Edition(key=key, name=name, year=year, link=conf.get("link", ""),
                     date=str(conf.get("date", "")), place=str(conf.get("place", "")),
                     start=parse_start(str(conf.get("date", "")), year))
        for tl in conf.get("timeline") or []:
            for kind in DEADLINE_KINDS:
                if kind in tl:
                    ed.deadlines.append(Deadline(kind, parse_deadline(tl[kind], tz), str(tl[kind]), tz,
                                                 str(tl.get("comment", "") or "")))
        out.append(ed)
    return out


def load_editions(fetcher: Fetcher, conferences: dict) -> list[Edition]:
    eds: list[Edition] = []
    for key, c in conferences.items():
        page = fetcher.get(CCF_RAW.format(key=key))
        if not page:
            log.warning("ccf-deadlines 데이터를 못 받음: %s", key)
            continue
        try:
            eds += parse_ccf_yaml(key, c.get("name", key.upper()), page.text)
        except Exception as e:  # noqa: BLE001 - 한 학회 실패가 전체를 막지 않게
            log.warning("ccf-deadlines 파싱 실패 %s: %s", key, e)
    return eds


def upcoming_deadlines(editions: list[Edition], now: dt.datetime, horizon_days: int):
    """(edition, deadline) 중 now ~ now+horizon 사이, 시간순."""
    end = now + dt.timedelta(days=horizon_days)
    rows = [(e, d) for e in editions for d in e.deadlines if d.when_utc and now <= d.when_utc <= end]
    return sorted(rows, key=lambda r: r[1].when_utc)


def deadline_snapshot(editions: list[Edition]) -> dict[str, str]:
    """변경 감지용: '<edition>/<kind>' -> 원문."""
    return {f"{e.id}/{d.kind}": f"{d.raw} {d.tz}" for e in editions for d in e.deadlines}
