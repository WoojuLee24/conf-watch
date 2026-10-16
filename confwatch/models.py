from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field


@dataclass
class Challenge:
    conf: str               # 표시 이름 (CVPR)
    conf_key: str           # ccf key (cvpr)
    year: int
    title: str
    url: str                # 대표 링크 (워크숍/challenge 사이트)
    detail_url: str = ""    # 학회 사이트의 상세 페이지
    keywords: list[str] = field(default_factory=list)
    platforms: list[str] = field(default_factory=list)
    snippet: str = ""
    source: str = ""        # crawl / evalai
    end_date: str = ""      # 플랫폼이 알려주는 제출 마감 (evalai)

    @property
    def id(self) -> str:
        u = re.sub(r"^https?://(www\.)?", "", self.url).rstrip("/").lower()
        return f"{self.conf_key}{self.year}|{u}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["id"] = self.id
        return d
