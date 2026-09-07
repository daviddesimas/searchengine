from __future__ import annotations

import re

TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has",
    "he", "in", "is", "it", "its", "of", "on", "or", "that", "the", "to",
    "was", "were", "will", "with", "this", "you", "your", "we", "they",
}


def tokenize(text: str) -> list[str]:
    tokens = [m.group(0).lower() for m in TOKEN_RE.finditer(text or "")]
    return [t for t in tokens if len(t) > 1 and t not in STOPWORDS]
