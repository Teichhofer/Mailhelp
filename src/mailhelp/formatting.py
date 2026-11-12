"""Shared formatting helpers for web and review representations."""
from __future__ import annotations

import math
from datetime import datetime
from zoneinfo import ZoneInfo


def format_datetime_local(value: datetime, zone: str | ZoneInfo) -> str:
    """Format a datetime in the given timezone as DD.MM.YYYY, HH:MM Uhr."""
    tz = ZoneInfo(zone) if isinstance(zone, str) else zone
    return value.astimezone(tz).strftime("%d.%m.%Y, %H:%M Uhr")



def _decimal(value: float, digits: int) -> str:
    return f"{value:,.{digits}f}".replace(",", " ").replace(".", ",").replace(" ", ".")


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
        return f"{minutes} Min." + (f" {rest} s" if rest else "")
    if round(seconds / 60) < 1440:
        hours, minutes = divmod(round(seconds / 60), 60)
        return f"{hours} Std." + (f" {minutes} Min." if minutes else "")
    days, hours = divmod(round(seconds / 3600), 24)
    return f"{days} {'Tag' if days == 1 else 'Tage'}" + (f" {hours} Std." if hours else "")
