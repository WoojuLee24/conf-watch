"""네트워크 없이 도는 단위 테스트."""
import datetime as dt

from bs4 import BeautifulSoup

from confwatch.deadlines import parse_ccf_yaml, parse_deadline, parse_start, upcoming_deadlines
from confwatch.match import Matcher
from confwatch.sources.crawl import Crawler, other_year_url, year_ok
from confwatch.deadlines import Edition

CFG = {"keywords": ["vision-language navigation", "VLA", "re:\\bnavigation\\b"],
       "challenge_terms": ["challenge", "competition", "leaderboard"]}


def test_deadline_timezones():
    assert parse_deadline("2025-11-13 23:59:59", "UTC-12").isoformat() == "2025-11-14T11:59:59+00:00"
    assert parse_deadline("2026-09-25 23:59:59", "AoE").isoformat() == "2026-09-26T11:59:59+00:00"
    assert parse_deadline("2026-05-07 11:59:00", "UTC+0").isoformat() == "2026-05-07T11:59:00+00:00"
    assert parse_deadline("TBD", "AoE") is None


def test_parse_start():
    assert parse_start("June 5-7, 2026", 2026) == dt.date(2026, 6, 5)
    assert parse_start("September 27 - October 1, 2026", 2026) == dt.date(2026, 9, 27)
    assert parse_start("December 8-10 (Sydney), December 9-11 (Atlanta and Paris), 2026", 2026) == dt.date(2026, 12, 8)


def test_ccf_yaml_and_upcoming():
    y = """
- title: CVPR
  confs:
    - year: 2027
      link: https://cvpr.thecvf.com/Conferences/2027
      timeline:
        - abstract_deadline: '2026-11-10 23:59:59'
          deadline: '2026-11-16 23:59:59'
      timezone: UTC-12
      date: June 20-25, 2027
      place: Seattle
"""
    eds = parse_ccf_yaml("cvpr", "CVPR", y)
    assert eds[0].id == "cvpr2027" and len(eds[0].deadlines) == 2
    now = dt.datetime(2026, 11, 12, tzinfo=dt.timezone.utc)
    up = upcoming_deadlines(eds, now, 30)
    assert [d.kind for _, d in up] == ["deadline"]       # 초록 마감은 이미 지남


def test_keywords():
    m = Matcher.from_config(CFG)
    assert m.keyword_hits("Vision Language Navigation challenge") == ["vision-language navigation", r"\bnavigation\b"]
    assert m.keyword_hits("VLA models") == ["VLA"]
    assert m.keyword_hits("VLAD descriptors") == []      # 단어 경계
    assert Matcher.from_config({"keywords": []}).keyword_hits("anything") == ["*"]


def test_is_challenge():
    m = Matcher.from_config(CFG)
    assert m.is_challenge("The Earth Rover Challenge", "")
    assert m.is_challenge("Mobile AI workshop and associated challenges", "")
    assert not m.is_challenge("25 years of Aerial Robotics: Challenges and Opportunities", "")
    assert not m.is_challenge("Workshop on X", "we discuss open challenges in robotics")
    assert m.is_challenge("Workshop on X", "Submit at https://eval.ai/web/challenges/challenge-page/1/overview")
    assert m.is_challenge("Workshop on X", "Challenge Timeline: registration opens March 1")


def ed(key="icra", name="ICRA", year=2027):
    return Edition(key, name, year, "", "", "", None)


def test_year_filters():
    assert not year_ok("ICRA 2025 Workshop on Robot Software", ed())          # 지난해 내용 재탕
    assert year_ok("Workshop at ICRA 2027, Vienna", ed())
    assert year_ok("held with ICRA'27", ed())
    assert other_year_url("https://cs.gmu.edu/BARN_Challenge/BARN_Challenge2025.html", 2027)
    assert other_year_url("https://nips.cc/Conferences/2018/CompetitionTrack", 2026)
    assert not other_year_url("https://earth-rover-challenge.github.io/", 2026)


def test_items_from_json_listing():
    raw = ('<script>var D=[{"kind":"competition","title":"The Earth Rover Challenge",'
           '"websiteUrl":"https://earth-rover-challenge.github.io/"},'
           '{"kind":"exhibitor","title":"Some Company","website":"https://company.example.com/"}]</script>')
    items = Crawler.items_from_json("https://2026.ieee-iros.org/program/competitions/", raw)
    assert [i.url for i in items] == ["https://earth-rover-challenge.github.io/"]
    assert items[0].title == "The Earth Rover Challenge"


def test_listing_virtual_items():
    html = ('<div class="card"><a href="/virtual/2025/workshop/123">Embodied AI Workshop</a> '
            'Navigation challenges in Habitat</div><a href="https://twitter.com/x">t</a>')
    c = Crawler(None, Matcher.from_config(CFG))
    items = c.items_from_listing("https://cvpr.thecvf.com/virtual/2025/events/workshop", BeautifulSoup(html, "lxml"))
    assert [i.url for i in items] == ["https://cvpr.thecvf.com/virtual/2025/workshop/123"]
