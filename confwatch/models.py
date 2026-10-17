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
    start: str = ""         # challenge 시작일 (YYYY-MM-DD, 모르면 "")
    end: str = ""           # challenge 제출 마감일
    date_source: str = ""   # site / evalai
    end_strong: bool = True # 마감일 근거가 challenge 라벨인지 (약하면 지났어도 학회 전까진 숨기지 않음)
    conf_start: str = ""    # 학회 개최 시작일 (기간 미상일 때 종료 추정용)
    status: str = ""        # 진행 중 / 예정 / 기간 미확인 / 종료

    @property
    def id(self) -> str:
        u = re.sub(r"^https?://(www\.)?", "", self.url).rstrip("/").lower()
        return f"{self.conf_key}{self.year}|{u}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["id"] = self.id
        return d
