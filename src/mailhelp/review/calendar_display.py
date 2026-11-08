"""How changes against the calendar and candidate entries are described (Planung 4.6, 17.4).

Shared by the web cards and Telegram so both channels name the same before/after values.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from ..domain.proposal import CalendarCandidate

ARROW = " → "


def candidate_label(candidate: CalendarCandidate, configured_timezone: str | None) -> str:
    """„Titel“ am 04.12.2026 18:00 Uhr; an all-day entry without a time."""
    start = candidate.start
    when = (f"{start.astimezone(ZoneInfo(configured_timezone or 'UTC')):%d.%m.%Y %H:%M} Uhr"
            if isinstance(start, datetime) else f"{start:%d.%m.%Y}")
    return f"„{candidate.title or 'ohne Titel'}“ am {when}"


def change_parts(change: str) -> tuple[str, str, str] | None:
    """``("Beginn", old, new)`` from "Beginn 04.12.2026 18:00 Uhr → 11.12.2026 18:00 Uhr"."""
    label, _, rest = change.partition(" ")
    old, arrow, new = rest.partition(ARROW)
    if not arrow or not label or not old or not new:
        return None
    return label, old, new


__all__ = ["candidate_label", "change_parts"]
