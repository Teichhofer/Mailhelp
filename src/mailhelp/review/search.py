"""Full-text matching for the mail archive: tolerant of case, umlaut spelling and accents.

``fold`` maps text to a comparable form ("Größe" and "groesse" become equal).
``excerpt`` finds a term again in the original text so the page can show where
it matched; positions are tracked character by character for that purpose.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# Per-field and per-mail limits keep the in-memory index bounded.
FIELD_LIMIT = 100_000
MAIL_LIMIT = 200_000
CONTEXT = 60
# Joins folded fields so that no term can match across two of them.
SEPARATOR = "\x1f"
_UMLAUTS = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "æ": "ae", "œ": "oe", "ø": "oe"}


def _fold_char(char: str) -> str:
    folded = "".join(_UMLAUTS.get(item, item) for item in char.casefold())
    return "".join(item for item in unicodedata.normalize("NFKD", folded) if not unicodedata.combining(item))


def fold(text: str) -> str:
    """Comparable form: NFKC, case-folded, umlauts spelt out, accents removed, whitespace collapsed."""
    folded = "".join(_fold_char(char) for char in unicodedata.normalize("NFKC", text))
    return " ".join(folded.split())


def _fold_positions(text: str) -> tuple[str, list[int]]:
    """Like ``fold`` (without collapsing whitespace), with the source index of every folded character."""
    out: list[str] = []
    positions: list[int] = []
    for index, char in enumerate(text):
        for item in _fold_char(char):
            out.append(" " if item.isspace() else item)
            positions.append(index)
    return "".join(out), positions


def terms(query: str) -> list[str]:
    """Words and "quoted phrases" of a query, folded; every one must occur."""
    found = (fold(phrase or word.strip('"')) for phrase, word in re.findall(r'"([^"]+)"|(\S+)', query))
    return [term for term in found if term]


@dataclass(frozen=True)
class Hit:
    """Where a search matched and the text around it (unescaped; the page escapes it)."""

    where: str
    before: str
    match: str
    after: str


def excerpt(fields: list[tuple[str, str]], wanted: list[str]) -> Hit | None:
    """The first field containing the first term, with up to 60 characters of context."""
    if not wanted:
        return None
    for label, text in fields:
        shown = unicodedata.normalize("NFKC", " ".join(text.split()))
        folded, positions = _fold_positions(shown)
        start = folded.find(wanted[0])
        if start < 0:
            continue
        first, last = positions[start], positions[start + len(wanted[0]) - 1] + 1
        before = shown[max(0, first - CONTEXT):first]
        after = shown[last:last + CONTEXT]
        return Hit(label, ("…" if first > CONTEXT else "") + before, shown[first:last],
                   after + ("…" if last + CONTEXT < len(shown) else ""))
    return None


def bounded(fields: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Fields cut to the per-field and per-mail limits, empty fields dropped."""
    result, used = [], 0
    for label, text in fields:
        piece = text[:min(FIELD_LIMIT, MAIL_LIMIT - used)]
        if piece.strip():
            result.append((label, piece))
            used += len(piece)
    return result
