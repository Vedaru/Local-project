"""Utilities for mixed Chinese/English lexical matching in memory retrieval."""

from __future__ import annotations

import re

_WORD_PATTERN = re.compile(r"[a-zA-Z0-9_]+")
_CJK_PATTERN = re.compile(r"[\u4e00-\u9fff]+")


def tokenize_for_search(text: str) -> set[str]:
    """Tokenize query text for robust substring matching.

    For Latin text, split by word boundaries.
    For Chinese text, generate bi-grams to improve matching without spaces.
    """
    normalized = (text or "").strip().lower()
    if not normalized:
        return set()

    tokens: set[str] = set()

    for word in _WORD_PATTERN.findall(normalized):
        if word:
            tokens.add(word)

    for chunk in _CJK_PATTERN.findall(normalized):
        if not chunk:
            continue
        if len(chunk) == 1:
            tokens.add(chunk)
            continue

        # Keep phrase token and add bi-grams for fuzzy Chinese matching.
        tokens.add(chunk)
        for idx in range(len(chunk) - 1):
            tokens.add(chunk[idx : idx + 2])

    return {token for token in tokens if token}
