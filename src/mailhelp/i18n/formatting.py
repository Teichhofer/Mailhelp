"""7.5.2: dates, times, numbers and durations in the active language.

German stays exactly as before ("07.01.2027", "14:30 Uhr", "1.234"); English uses the short month
name and the 24-hour clock ("Jan 7, 2027", "14:30", "1,234"), so no time needs AM/PM to be clear.
"""
from __future__ import annotations

from datetime import date, datetime, time

from . import Locale, current

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def day(value: date) -> str:
    if current() == Locale.EN:
        return f"{MONTHS[value.month - 1]} {value.day}, {value.year}"
    return f"{value:%d.%m.%Y}"


def clock(value: time | datetime) -> str:
    """The time of day without suffix; ``clock_suffix`` adds " Uhr" in German."""
    return f"{value:%H:%M}"


def clock_suffix() -> str:
    return "" if current() == Locale.EN else " Uhr"


def day_time(value: datetime) -> str:
    """``07.01.2027, 14:30 Uhr`` / ``Jan 7, 2027, 14:30``."""
    return f"{day(value)}, {clock(value)}{clock_suffix()}"


def number(value: int) -> str:
    grouped = f"{value:,}"
    return grouped if current() == Locale.EN else grouped.replace(",", ".")


def decimal(value: float, digits: int) -> str:
    grouped = f"{value:,.{digits}f}"
    if current() == Locale.EN:
        return grouped
    return grouped.replace(",", " ").replace(".", ",").replace(" ", ".")
