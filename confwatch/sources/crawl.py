"""학회 workshop/competition 페이지 크롤링 → challenge 후보."""
from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup

import datetime as dt

from ..dates import Window, extract_window
from ..deadlines import Edition
from ..fetch import Fetcher
from ..match import Matcher, platform_links
from ..models import Challenge
from .evalai import ALIASES

log = logging.getLogger(__name__)

LISTING_RE = re.compile(r"workshop|competition|challenge", re.I)
# CVF/NeurIPS/ICML/ICLR 공통 "virtual" 플랫폼의 상세 페이지
VIRTUAL_ITEM_RE = re.compile(r"/virtual/\d{4}/(?:[\w-]+/)*(workshop|competition)/\d+", re.I)

SKIP_DOMAINS = (
    "twitter.com", "x.com", "facebook.com", "linkedin.com", "instagram.com", "youtube.com", "youtu.be",
    "www.google.com", "docs.google.com", "drive.google.com", "maps.google", "calendar.google", "goo.gl", "forms.gle", "bit.ly", "cdn.", "jsdelivr", "googleapis", "gstatic", "cloudflare",
    "computer.org", "ieee.org", "thecvf.com", "ecva.net", "neurips.cc", "icml.cc", "iclr.cc", "openreview.net",
    "zoom.us", "slack.com", "discord", "wechat", "weibo", "apple.com", "microsoft.com/en-us/research/event",
    "cmt3.research.microsoft.com", "conferences.computer.org", "eventbrite", "ieeexplore", "arxiv.org",
    "visitdenver", "booking.com", "hotel", "mercu-wgp",
)
# 페이지가 JS 데이터(JSON)로 목록을 그리는 경우 (IROS 2026 등): "websiteUrl": "https://..."
JSON_LINK_RE = re.compile(r'"(website|websiteUrl|website_url|url|link|homepage)"\s*:\s*"(https?://[^"]+)"')
GENERIC_ANCHOR_RE = re.compile(r"https?://\S+|(?:visit|link|go)?\s*(?:to\s+)?(?:the\s+)?(?:workshop\s+)?"
                               r"(?:website|webpage|site|page|link|here|details|more|view full details|project page)", re.I)
NOISE_TAGS = ("script", "style", "nav", "header", "footer", "noscript", "svg", "form")


@dataclass
class Item:
    url: str
    title: str
    context: str            # 목록 페이지에서 링크 주변 텍스트
    listing: str            # 발견된 목록 페이지
    texts: list[str] = field(default_factory=list)
    hrefs: list[str] = field(default_factory=list)
    site: str = ""          # 워크숍/challenge 외부 사이트
    soups: list = field(default_factory=list)        # 날짜 추출용 (노이즈 태그 제거된 soup)
    site_soup_links: list[tuple[str, str]] = field(default_factory=list)  # (href, 링크 문구) 타임라인 페이지 탐색용


def domain(u: str) -> str:
    return urlparse(u).netloc.lower().removeprefix("www.")


def base_domain(u: str) -> str:
    parts = domain(u).split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else domain(u)


def skip_url(u: str) -> bool:
    if not u.startswith("http"):
        return True
    d = domain(u)
    if any(s in d or s in u for s in SKIP_DOMAINS):
        return True
    return bool(re.search(r"\.(pdf|png|jpe?g|gif|svg|zip|mp4|ics|css|js)(\?|$)", u, re.I))


def links_of(base: str, soup: BeautifulSoup) -> list[tuple[str, str]]:
    return [(urldefrag(urljoin(base, a["href"]))[0], a.get_text(" ", strip=True)) for a in soup.find_all("a", href=True)]


TIMELINE_LINK_RE = re.compile(r"challenge|competition|timeline|dates|schedule|important|track|leaderboard|participat", re.I)


def clean_text(soup: BeautifulSoup) -> str:
    for t in soup(NOISE_TAGS):
        t.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ")).strip()


def page_title(soup: BeautifulSoup) -> str:
    cands = [re.sub(r"\s+", " ", el.get_text(" ", strip=True))[:200]
             for el in (soup.find("h1"), soup.find("title"), soup.find("h2")) if el]
    good = [c for c in cands if len(c) >= 8 and not re.fullmatch(r"(?i)home|welcome|index|untitled", c)]
    return good[0] if good else (cands[0] if cands else "")


def block_text(a) -> str:
    """링크를 감싼 가장 가까운 블록의 텍스트 (워크숍 카드/목록 항목)."""
    el = a
    for _ in range(6):
        el = el.parent
        if el is None:
            break
        if el.name in ("li", "tr", "article", "div", "p", "section", "td"):
            t = re.sub(r"\s+", " ", el.get_text(" ", strip=True))
            if len(t) > len(a.get_text(strip=True)) + 20:
                return t[:2000]
    return a.get_text(" ", strip=True)


def year_ok(body: str, ed: Edition) -> bool:
    """다른 해 내용이 그대로 남아 있는 페이지(ICRA 2027 사이트의 2025 워크숍 등) 제외."""
    name = ALIASES.get(ed.key, re.escape(ed.name))
    yy = f"{ed.year % 100:02d}"
    if str(ed.year) not in body and not re.search(rf"(?:{name})\s*['’]?\s*{yy}\b", body, re.I):
        return False
    years = re.findall(rf"\b(?:{name})\s*['’]?\s*(20\d\d|\d\d)\b", body, re.I)
    return not years or any(y in (str(ed.year), yy) for y in years)


def other_year_url(url: str, year: int) -> bool:
    ys = re.findall(r"(?<!\d)(20\d\d)(?!\d)", urlparse(url).path + urlparse(url).netloc)
    return bool(ys) and str(year) not in ys


def year_variants(year: int) -> list[str]:
    return [str(year), f"{year % 100:02d}"]


def is_versioned(url: str, year: int) -> bool:
    return any(re.search(rf"(?<!\d){v}(?!\d)", url) for v in year_variants(year))


class Crawler:
    def __init__(self, fetcher: Fetcher, matcher: Matcher, max_items: int = 400, workers: int = 8):
        self.f = fetcher
        self.m = matcher
        self.max_items = max_items
        self.workers = workers

    # ---------- 1단계: 목록 페이지 찾기 ----------
    def listing_pages(self, ed: Edition, seeds: list[str], latest: bool) -> list[tuple[str, BeautifulSoup]]:
        urls = []
        for s in seeds:
            u = s.format(year=ed.year, yy=f"{ed.year % 100:02d}")
            if u not in urls:
                urls.append(u)
        if ed.link and ed.link not in urls:
            urls.append(ed.link)

        out, seen = [], set()
        for u in urls:
            # 연도가 URL 에 없는 페이지(www.corl.org 등)는 최신 회차에만, 본문에 연도가 있을 때만 쓴다
            versioned = is_versioned(u, ed.year)
            if not versioned and not latest:
                continue
            p = self.f.get(u)
            if not p or p.url in seen:
                continue
            if versioned and not is_versioned(p.url, ed.year):
                log.info("  %s → %s: 다른 해로 리다이렉트 → 제외", u, p.url)
                continue
            seen.add(p.url)
            soup = BeautifulSoup(p.text, "lxml")
            if not versioned and str(ed.year) not in p.text:
                log.info("  %s: 연도 %s 미표기 → 제외", u, ed.year)
                continue
            if LISTING_RE.search(urlparse(p.url).path):
                out.append((p.url, soup))
            # 홈페이지/메뉴에서 workshop/competition/challenge 페이지를 찾아 따라간다
            for a in soup.find_all("a", href=True):
                href = urldefrag(urljoin(p.url, a["href"]))[0]
                label = a.get_text(" ", strip=True)
                if (base_domain(href) == base_domain(p.url) and href not in seen
                        and LISTING_RE.search(urlparse(href).path + " " + label)
                        and not VIRTUAL_ITEM_RE.search(href)
                        and len(out) < 25
                        and (is_versioned(href, ed.year) or not re.search(r"/(19|20)\d\d/", href))):
                    seen.add(href)
                    q = self.f.get(href)
                    if q and q.url not in {o[0] for o in out} and not other_year_url(q.url, ed.year) \
                            and not (is_versioned(href, ed.year) and not is_versioned(q.url, ed.year)):
                        out.append((q.url, BeautifulSoup(q.text, "lxml")))
        return out

    # ---------- 2단계: 목록에서 항목 추출 ----------
    def items_from_listing(self, url: str, soup: BeautifulSoup) -> list[Item]:
        items = []
        for a in soup.find_all("a", href=True):
            href = urldefrag(urljoin(url, a["href"]))[0]
            title = a.get_text(" ", strip=True)
            if VIRTUAL_ITEM_RE.search(href):
                items.append(Item(href, title, block_text(a), url))
            elif base_domain(href) != base_domain(url) and not skip_url(href):
                items.append(Item(href, title, block_text(a), url, site=href))
            elif (base_domain(href) == base_domain(url) and href.rstrip("/") != url.rstrip("/")
                  and LISTING_RE.search(urlparse(href).path)
                  and urlparse(href).path.rstrip("/").count("/") > urlparse(url).path.rstrip("/").count("/")):
                items.append(Item(href, title, block_text(a), url))
        items += self.items_from_json(url, str(soup))
        return items

    @staticmethod
    def items_from_json(url: str, raw: str) -> list[Item]:
        items = []
        for m in JSON_LINK_RE.finditer(raw):
            href = m.group(2).replace("\\/", "/")
            if base_domain(href) == base_domain(url) or skip_url(href):
                continue
            # 링크가 속한 JSON 객체 주변 텍스트 (전시업체 등은 제외: workshop/competition 언급 필수)
            start = raw.rfind("{", max(0, m.start() - 3000), m.start())
            ctx = raw[start if start >= 0 else m.start() - 1500: m.end() + 300]
            t = re.search(r'"(?:title|name)"\s*:\s*"([^"]{5,200})"', ctx)
            ctx = re.sub(r"\\n|\\u[0-9a-f]{4}|[\"{}\[\]]", " ", ctx)
            if not LISTING_RE.search(ctx):
                continue
            items.append(Item(href, t.group(1).strip() if t else "", re.sub(r"\s+", " ", ctx)[:2000], url, site=href))
        return items

    # ---------- 3단계: 항목 페이지(+외부 워크숍 사이트) 수집 ----------
    def expand(self, it: Item) -> Item:
        p = self.f.get(it.url)
        if not p:
            return it
        soup = BeautifulSoup(p.text, "lxml")
        t = page_title(soup)
        if t and (not it.title or len(it.title) < 8 or GENERIC_ANCHOR_RE.fullmatch(it.title)):
            it.title = t
        if VIRTUAL_ITEM_RE.search(it.url):
            # virtual 상세 페이지: 아래쪽 채택 논문 초록은 버리고 상단 소개(hero-card)만 사용
            hero = soup.select_one("div.hero-card") or soup
            hrefs = [urljoin(p.url, a["href"]) for a in hero.find_all("a", href=True)]
            it.hrefs = hrefs
            it.texts.append(clean_text(hero))
            it.soups.append(hero)
            ext = [h for h in hrefs if domain(h) != domain(p.url) and not skip_url(h)]
            if ext:
                it.site = ext[0]
                q = self.f.get(ext[0])
                if q:
                    s2 = BeautifulSoup(q.text, "lxml")
                    it.site_soup_links = links_of(q.url, s2)
                    it.hrefs += [h for h, _ in it.site_soup_links]
                    it.texts.append(clean_text(s2))
                    it.soups.append(s2)
        else:
            it.site_soup_links = links_of(p.url, soup)
            it.hrefs = [h for h, _ in it.site_soup_links]
            it.texts.append(clean_text(soup))
            it.soups.append(soup)
        return it

    def window(self, it: Item, ed: Edition) -> Window:
        """challenge 사이트 + 같은 사이트의 challenge/timeline 하위 페이지(최대 3개)에서 기간 추출."""
        anchor = ed.start or dt.date(ed.year, 6, 1)
        soups = list(it.soups)
        site = it.site or it.url
        extra = []
        for h, label in it.site_soup_links:
            if (domain(h) == domain(site) and h.rstrip("/") != site.rstrip("/") and h not in extra
                    and TIMELINE_LINK_RE.search(label + " " + urlparse(h).path) and not skip_url(h)):
                extra.append(h)
        for h in extra[:3]:
            q = self.f.get(h)
            if q:
                s = BeautifulSoup(q.text, "lxml")
                for t in s(NOISE_TAGS):
                    t.decompose()
                soups.append(s)
        return extract_window(soups, anchor)

    def run(self, ed: Edition, seeds: list[str], latest: bool) -> list[Challenge]:
        listings = self.listing_pages(ed, seeds, latest)
        items: dict[str, Item] = {}
        for url, soup in listings:
            for it in self.items_from_listing(url, soup):
                key = it.url.rstrip("/")
                if key in items:
                    if len(it.context) > len(items[key].context):
                        items[key].context = it.context
                    continue
                items[key] = it
        todo = list(items.values())[: self.max_items]
        log.info("  %s: 목록 %d개, 항목 %d개", ed.id, len(listings), len(todo))
        with ThreadPoolExecutor(self.workers) as ex:
            done = list(ex.map(self.expand, todo))

        out = []
        for it in done:
            body = " ".join([it.title, it.context, *it.texts])
            hits = self.m.keyword_hits(body)
            if not hits or not year_ok(body, ed) or other_year_url(it.site or it.url, ed.year):
                continue
            links = platform_links(" ".join(it.hrefs))
            if not self.m.is_challenge(it.title + " " + it.context[:300], body + " " + " ".join(links)):
                continue
            out.append((it, Challenge(
                conf=ed.name, conf_key=ed.key, year=ed.year,
                title=it.title or it.url, url=it.site or it.url, detail_url=it.url,
                keywords=hits, platforms=links, snippet=self.m.snippet(body), source="crawl",
            )))
        # 기간 추출은 매칭된 항목만 (추가 페이지 요청이 생기므로)
        with ThreadPoolExecutor(self.workers) as ex:
            wins = list(ex.map(lambda p: self.window(p[0], ed), out))
        for (_, c), w in zip(out, wins):
            c.start = w.start.isoformat() if w.start else ""
            c.end = w.end.isoformat() if w.end else ""
            c.date_source = w.source
            c.end_strong = w.end_strong
        return [c for _, c in out]
