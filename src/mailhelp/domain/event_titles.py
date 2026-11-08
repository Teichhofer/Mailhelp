"""Deterministic title comparison for finding an existing calendar event (Planung 4.6, 17.1).

Only a prefilter: whether a calendar entry is the same appointment is decided by the
calendar matcher (when configured) or by an exact title. German compounds are common
("Gemeinderatssitzung" for "Sitzung des Gemeinderats"), so a significant word of one
title may also be contained in the other.
"""
from __future__ import annotations

import re
import unicodedata

# Words that name no appointment on their own.
_STOP = frozenset({
    "der", "die", "das", "den", "dem", "des", "ein", "eine", "einer", "eines", "und", "oder",
    "mit", "für", "von", "vom", "zum", "zur", "im", "am", "an", "auf", "in", "bei", "nach",
    "termin", "termine", "treffen", "neu", "neuer", "neue", "geändert", "verschoben",
    "abgesagt", "absage", "änderung", "verschiebung", "einladung", "uhr", "the", "and"})
MIN_WORD = 4


def normalized(title: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", title).casefold().split())


def significant_words(title: str) -> frozenset[str]:
    """Words of at least four letters that are no stop word; digits and dates are dropped."""
    words = re.findall(r"[^\W\d_]+", normalized(title))
    return frozenset(word for word in words if len(word) >= MIN_WORD and word not in _STOP)


def titles_related(query: str, summary: str) -> bool:
    """True if a significant word of either title occurs in the other title."""
    left, right = significant_words(query), significant_words(summary)
    if not left or not right:
        return False
    text_left, text_right = normalized(query), normalized(summary)
    return any(word in text_right for word in left) or any(word in text_left for word in right)


__all__ = ["normalized", "significant_words", "titles_related"]
