"""HTTP 요청 + 디스크 캐시."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import requests

log = logging.getLogger(__name__)

UA = "Mozilla/5.0 (X11; Linux x86_64) conf-watch/0.1 (+https://github.com/)"
MAX_BYTES = 4_000_000


@dataclass
class Page:
    url: str        # 리다이렉트 후 최종 URL
    status: int
    text: str
    content_type: str


class Fetcher:
    def __init__(self, cache_dir: str | os.PathLike = ".cache/http", cache_hours: float = 72, timeout: float = 20):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_sec = cache_hours * 3600
        self.timeout = timeout
        self._local = threading.local()
        self.stats = {"net": 0, "cache": 0, "fail": 0}

    @property
    def session(self) -> requests.Session:
        # requests.Session 은 스레드 간 공유가 안전하지 않으므로 스레드별로 둔다
        s = getattr(self._local, "s", None)
        if s is None:
            s = self._local.s = requests.Session()
            s.headers.update({"User-Agent": UA, "Accept-Language": "en"})
        return s

    def _key(self, url: str) -> Path:
        return self.cache_dir / (hashlib.sha1(url.encode()).hexdigest() + ".json")

    def get(self, url: str) -> Page | None:
        """HTML/텍스트 페이지만 반환. 실패하거나 HTML 이 아니면 None."""
        key = self._key(url)
        if key.exists() and time.time() - key.stat().st_mtime < self.cache_sec:
            try:
                d = json.loads(key.read_text())
                self.stats["cache"] += 1
                return Page(**d) if d else None
            except (OSError, ValueError, TypeError):
                pass
        page = self._download(url)
        try:
            key.write_text(json.dumps(page.__dict__ if page else None))
        except OSError:
            pass
        return page

    def _download(self, url: str) -> Page | None:
        for attempt in range(2):
            try:
                r = self.session.get(url, timeout=self.timeout, stream=True, allow_redirects=True)
                ctype = r.headers.get("content-type", "")
                if r.status_code >= 400:
                    self.stats["fail"] += 1
                    log.debug("HTTP %s %s", r.status_code, url)
                    return None
                if not any(t in ctype for t in ("html", "text", "json", "xml")) and ctype:
                    return None
                body = r.raw.read(MAX_BYTES, decode_content=True)
                enc = r.encoding or "utf-8"
                self.stats["net"] += 1
                return Page(url=r.url, status=r.status_code, text=body.decode(enc, errors="replace"), content_type=ctype)
            except requests.RequestException as e:
                log.debug("fetch error %s (%s)", url, e)
                time.sleep(1 + attempt)
        self.stats["fail"] += 1
        return None

    def get_json(self, url: str):
        p = self.get(url)
        if not p:
            return None
        try:
            return json.loads(p.text)
        except ValueError:
            return None
