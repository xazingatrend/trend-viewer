"""Deterministic keyword normalization and matching helpers."""

import re
import unicodedata


STOPWORDS = frozenset(
    {
        # Korean particles and generic trend-feed vocabulary.
        "에서",
        "으로",
        "하고",
        "과의",
        "오늘",
        "이번",
        "현재",
        "최근",
        "실시간",
        "영상",
        "쇼츠",
        "공식",
        "발표",
        "뉴스",
        "소식",
        "추천",
        "정리",
        "모음",
        "화제",
        "인기",
        "트렌드",
        "새로운",
        "신작",
        "공개",
        "최초",
        "단독",
        "관련",
        "정보",
        "리뷰",
        "반응",
        "이유",
        "방법",
        "결과",
        "업데이트",
        "콘텐츠",
        "채널",
        "라이브",
        "다시보기",
        # English generic words.
        "the",
        "and",
        "for",
        "with",
        "this",
        "that",
        "are",
        "was",
        "were",
        "has",
        "have",
        "had",
        "his",
        "her",
        "its",
        "our",
        "your",
        "you",
        "not",
        "but",
        "all",
        "any",
        "can",
        "will",
        "just",
        "out",
        "one",
        "two",
        "three",
        "four",
        "five",
        "six",
        "seven",
        "eight",
        "nine",
        "ten",
        "hundred",
        "thousand",
        "million",
        "first",
        "second",
        "third",
        "get",
        "got",
        "like",
        "more",
        "most",
        "off",
        "on",
        "in",
        "to",
        "of",
        "at",
        "by",
        "as",
        "is",
        "it",
        "be",
        "we",
        "an",
        "or",
        "if",
        "so",
        "up",
        "no",
        "do",
        "my",
        "me",
        "us",
        "he",
        "she",
        "they",
        "them",
        "than",
        "then",
        "there",
        "here",
        "been",
        "being",
        "does",
        "did",
        "who",
        "which",
        "while",
        "because",
        "very",
        "really",
        "make",
        "made",
        "day",
        "week",
        "year",
        "from",
        "into",
        "about",
        "after",
        "before",
        "over",
        "under",
        "video",
        "videos",
        "official",
        "news",
        "update",
        "updates",
        "latest",
        "today",
        "now",
        "new",
        "live",
        "review",
        "reviews",
        "trend",
        "trending",
        "viral",
        "shorts",
        "short",
        "watch",
        "why",
        "how",
        "what",
        "when",
        "where",
        "best",
        "top",
        # Japanese generic words.
        "今日",
        "今回",
        "現在",
        "最近",
        "動画",
        "公式",
        "発表",
        "ニュース",
        "おすすめ",
        "まとめ",
        "話題",
        "人気",
        "最新",
        "新作",
        "公開",
        "関連",
        "情報",
        "レビュー",
    }
)

_HANGUL_RE = re.compile(r"^[\uac00-\ud7a3]+$")
_TOKEN_RE = re.compile(
    r"(?<![a-z0-9])[a-z0-9]{2,}(?![a-z0-9])"
    r"|[\uac00-\ud7a3]{2,}"
    r"|[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]{2,}"
)


def normalize(text):
    """Return an NFKC, case-folded, punctuation-collapsed string."""
    normalized = unicodedata.normalize("NFKC", str(text or "")).casefold()
    normalized = re.sub(r"[^\w\s]", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def tokens(text):
    """Extract significant ASCII, Hangul, Kana, and Han token runs."""
    normalized = normalize(text)
    return [token for token in _TOKEN_RE.findall(normalized) if token not in STOPWORDS]


def matches(anchor, text):
    """Return whether *text* contains the complete script-aware anchor."""
    normalized_anchor = normalize(anchor)
    normalized_text = normalize(text)
    if not normalized_anchor or not normalized_text:
        return False

    compact_anchor = normalized_anchor.replace(" ", "")
    compact_text = normalized_text.replace(" ", "")
    pure_hangul = bool(_HANGUL_RE.fullmatch(compact_anchor))
    compact_threshold = 3 if pure_hangul else 4
    if len(compact_anchor) >= compact_threshold and compact_anchor in compact_text:
        return True

    anchor_tokens = tokens(normalized_anchor)
    if not anchor_tokens:
        return False
    text_tokens = tokens(normalized_text)
    text_token_set = set(text_tokens)

    for anchor_token in anchor_tokens:
        if _HANGUL_RE.fullmatch(anchor_token):
            if anchor_token in text_token_set:
                continue
            if len(anchor_token) >= 3 and any(
                text_token.startswith(anchor_token) for text_token in text_tokens
            ):
                continue
            return False
        if anchor_token not in text_token_set:
            return False
    return True
