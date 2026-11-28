"""8.9.3 (Planung 8.9 AP3): weekdays the source itself names for a calendar day.

A model may shorten "Dienstag, den 19.11.2026" to "19.11.2026"; the weekday of the source must not be lost on
the way. The application, not the model, finds the passages: only the current part of the mail and its
attachments count. A quoted older mail ("--- Ursprüngliche Nachricht ---", "Am … schrieb …:", "> …") and the
mail headers are left out, and only passages naming the same day are compared, so another row of a table never
contradicts it.
"""
from __future__ import annotations

import re
from datetime import date

from .german_dates import MONTH_PATTERN, MONTHS, WEEKDAY_OR_ABBREVIATION_PATTERN, weekday_contradicts

# The first line of a quoted older message ends the current part.
_QUOTE = re.compile(r"(?im)^[ \t]*(?:-{2,}[ \t]*(?:ursprüngliche|urspruengliche|original)\b.*"
                    r"|am .+ schrieb .+:|on .+ wrote:|von:[ \t].+)$")
_QUOTED_LINE = re.compile(r"(?m)^[ \t]*>.*$")
_PASSAGE = re.compile(
    rf"(?i)(?<![\w.])({WEEKDAY_OR_ABBREVIATION_PATTERN})\.?,?\s+(?:den\s+)?(\d{{1,2}})\."
    rf"(?:(\d{{1,2}})\.(\d{{4}})?|\s*({MONTH_PATTERN})(?:\s+(\d{{4}}))?)(?![\d.]*\d)")


def current_part(text: str) -> str:
    """The text above the first quoted older message, without quoted lines."""
    found = _QUOTE.search(text)
    return _QUOTED_LINE.sub("", text[:found.start()] if found else text)


def date_source(text: str, attachments: list[str]) -> str:
    """The passages whose weekdays count: the current part of the mail text and every attachment text."""
    return "\n".join([current_part(text), *attachments])


def _named_day(match: re.Match[str], year: int) -> date | None:
    month = int(match[3]) if match[3] else MONTHS[match[5].casefold()]
    written = match[4] or match[6]
    try:
        return date(int(written) if written else year, month, int(match[2]))
    except ValueError:
        return None


def weekday_conflict(day: date, source: str) -> str | None:
    """The first passage of *source* that names *day* with a different weekday, else None."""
    for match in _PASSAGE.finditer(source):
        if _named_day(match, day.year) == day and weekday_contradicts(day, match[1]):
            return " ".join(match[0].split())
    return None


__all__ = ["current_part", "date_source", "weekday_conflict"]
