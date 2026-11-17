"""Shared formatting helpers for web and review representations."""
from __future__ import annotations

import math
from datetime import datetime
from zoneinfo import ZoneInfo

from .i18n import tr
from .i18n.formatting import day_time, decimal


def format_datetime_local(value: datetime, zone: str | ZoneInfo) -> str:
    """Format a datetime in the given timezone as DD.MM.YYYY, HH:MM Uhr (7.5: or Jan 7, 2027, 14:30)."""
    tz = ZoneInfo(zone) if isinstance(zone, str) else zone
    return day_time(value.astimezone(tz))



def _decimal(value: float, digits: int) -> str:
    return decimal(value, digits)


def duration_text(seconds: float, *, precise: bool = False) -> str:
    """A duration in the largest fitting unit (5.9): s, Min. and s, Std. and Min., Tage and Std.

    The value is rounded to the precision of a unit before the unit is chosen, so 59.96 s reads
    "1 Min." and never "60,0 s".
    """
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError("Eine Dauer muss endlich und nicht negativ sein")
    digits = 2 if precise else 1
    if round(seconds, digits) < 60:
        return f"{_decimal(seconds, digits)} s"
    if round(seconds) < 3600:
        minutes, rest = divmod(round(seconds), 60)
        return tr("{n} Min.", n=minutes) + (f" {rest} s" if rest else "")
    if round(seconds / 60) < 1440:
        hours, minutes = divmod(round(seconds / 60), 60)
        return tr("{n} Std.", n=hours) + (" " + tr("{n} Min.", n=minutes) if minutes else "")
    days, hours = divmod(round(seconds / 3600), 24)
    return (tr("{n} Tag", n=days) if days == 1 else tr("{n} Tage", n=days)) + (
        " " + tr("{n} Std.", n=hours) if hours else "")
