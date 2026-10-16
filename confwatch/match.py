"""검색어 / challenge 판별."""
from __future__ import annotations

import re
from dataclasses import dataclass

# challenge 가 실제로 열린다는 강한 신호: 평가 플랫폼 링크
PLATFORM_RE = re.compile(
    r"https?://(?:www\.)?(eval\.ai|codalab\.lisn\.upsaclay\.fr|codalab\.org|competitions\.codalab\.org|"
    r"codabench\.org|www\.codabench\.org|kaggle\.com|aicrowd\.com|huggingface\.co/spaces|"
    r"robotics-challenge|tianchi\.aliyun\.com)[^\s\"'<>)]*", re.I)

TITLE_RE = re.compile(r"\bchallenge\b|\bcompetitions?\b|\b(?:and|&)\s+(?:associated\s+)?challenges\b|\bchallenges\s+(?:and|&)\s+workshop", re.I)
GENERIC_RE = re.compile(r"challenges?\s+(?:and|&)\s+(?:opportunit|future|direction|solution|lesson|perspective)"
                        r"|(?:open|key|grand|new|emerging)\s+challenges?\b|challenges?\s+(?:in|of|for)\s", re.I)
# 실제 대회 운영을 뜻하는 표현
BODY_RE = re.compile(
    r"\b(?:challenge|competition)\s+(?:track|tracks|results?|winners?|rules|timeline|registration|submissions?|"
    r"phases?|leaderboard|prizes?|participants?|dataset|baseline|award|deadline|website|page|server)\b"
    r"|\b(?:participate|participants|register|submit)\s+(?:in|to|for)\s+(?:the|our)\s+(?:\w+\s+){0,3}(?:challenge|competition)"
    r"|\b(?:challenge|competition)\s+(?:is|will be)\s+(?:held|hosted|organized|open)"
    r"|\bchallenge\s+component\b|\bour\s+(?:[\w-]+\s+){0,3}(?:challenge|competition)\b", re.I)


def compile_keywords(keywords: list[str]) -> list[tuple[str, re.Pattern]]:
    out = []
    for k in keywords or []:
        k = str(k)
        if k.startswith("re:"):
            out.append((k[3:], re.compile(k[3:], re.I)))
        else:
            # 단어 경계 + 하이픈/공백 차이 무시 (vision-language == vision language)
            parts = [re.escape(p) for p in re.split(r"[\s\-]+", k.strip()) if p]
            out.append((k, re.compile(r"(?<![\w])" + r"[\s\-]+".join(parts) + r"(?![\w])", re.I)))
    return out


@dataclass
class Matcher:
    keywords: list[tuple[str, re.Pattern]]
    terms: list[str]

    @classmethod
    def from_config(cls, cfg: dict) -> "Matcher":
        return cls(compile_keywords(cfg.get("keywords") or []),
                   [t.lower() for t in cfg.get("challenge_terms") or ["challenge", "competition", "leaderboard"]])

    def keyword_hits(self, text: str) -> list[str]:
        if not self.keywords:
            return ["*"]
        return [name for name, rx in self.keywords if rx.search(text)]

    def is_challenge(self, title: str, body: str) -> bool:
        """challenge/competition 이 실제로 열리는지.

        - 제목: 'XYZ Challenge', 'Competition', 'Workshop and Challenges' (일반 표현
          'Challenges and Opportunities', 'Open Challenges in' 은 제외)
        - 본문: 평가 플랫폼 링크, leaderboard, 'Challenge Track/Results/Submission' 류 표현
        """
        if TITLE_RE.search(title) and not GENERIC_RE.search(title):
            return True
        if any(t in title.lower() for t in self.terms if t not in ("challenge", "competition", "leaderboard")):
            return True
        if PLATFORM_RE.search(body):
            return True
        if "leaderboard" in self.terms and re.search(r"\bleaderboards?\b", body, re.I):
            return True
        return len(BODY_RE.findall(body)) >= 1

    def snippet(self, text: str, width: int = 160) -> str:
        for _, rx in self.keywords:
            m = rx.search(text)
            if m:
                a, b = max(0, m.start() - width), min(len(text), m.end() + width)
                return ("…" if a else "") + text[a:b].strip() + ("…" if b < len(text) else "")
        return text[: width * 2].strip()


def platform_links(text: str) -> list[str]:
    seen, out = set(), []
    for m in PLATFORM_RE.finditer(text):
        u = m.group(0).rstrip(".,;")
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out[:5]
