"""Shared formatting helpers for web and review representations."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


def format_datetime_local(value: datetime, zone: str | ZoneInfo) -> str:
    """Format a datetime in the given timezone as DD.MM.YYYY, HH:MM Uhr."""
    tz = ZoneInfo(zone) if isinstance(zone, str) else zone
    return value.astimezone(tz).strftime("%d.%m.%Y, %H:%M Uhr")

