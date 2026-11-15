"""German calendar words shared by every deterministic date parser (Planung 3.3, pillar 6).

Only vocabulary and small checks live here.  Each parser keeps its own accepted
formats on purpose: extracted mail dates are strict (``TT.MM.JJJJ``), Telegram
answers may confirm a known date with a two-digit year.
"""
from __future__ import annotations

import re
from datetime import date

# Regex alternation of the month names, including the transliteration "maerz".
MONTH_PATTERN = (r"januar|februar|märz|maerz|april|mai|juni|juli|august|"
                 r"september|oktober|november|dezember")
MONTHS = {name: number for number, names in enumerate(((), ("januar",), ("februar",),
          ("märz", "maerz"), ("april",), ("mai",), ("juni",), ("juli",), ("august",),
          ("september",), ("oktober",), ("november",), ("dezember",))) for name in names}
WEEKDAY_PATTERN = r"montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag"
# Full names and their two-letter abbreviations, each name before its abbreviation.
WEEKDAY_OR_ABBREVIATION_PATTERN = (r"montag|mo|dienstag|di|mittwoch|mi|donnerstag|do|freitag|fr|"
                                   r"samstag|sa|sonntag|so")
WEEKDAYS = {name: number for number, name in enumerate(WEEKDAY_PATTERN.split("|"))}
WEEKDAYS.update({name: number for number, name in enumerate(("mo", "di", "mi", "do", "fr", "sa", "so"))})
_YEAR = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")


def explicit_years(text: str) -> set[str]:
    """Four-digit years (1900–2099) written in *text*."""
    return set(_YEAR.findall(text))


def weekday_contradicts(day: date, weekday: str | None) -> bool:
    """A stated weekday that does not fall on *day*; no weekday never contradicts."""
    return weekday is not None and day.weekday() != WEEKDAYS[weekday.casefold()]


__all__ = ["MONTHS", "MONTH_PATTERN", "WEEKDAYS", "WEEKDAY_OR_ABBREVIATION_PATTERN", "WEEKDAY_PATTERN",
           "explicit_years", "weekday_contradicts"]
