"""Deterministic temporal normalization of validated action extractions.

Supported date formats are exactly ``YYYY-MM-DD`` and ``DD.MM.YYYY``.
Supported time formats are exactly ``HH:MM`` and ``HH:MM:SS`` (24-hour
clock).  Relative or otherwise free-form values are deliberately retained as
unresolved input; this module never guesses a date, time, duration, or offset.

The prepared mail context is accepted only when ``date_context_status`` is
``valid``, both timestamps are offset-aware and no more than seven days apart,
and ``user_timezone`` names an available IANA zone.  The header timestamp is a
reference instant only; it is not used to turn relative language into a date.
The user zone supplies the zone for explicitly extracted local clock times.

Responsibility remains an independent fact on every result.  In particular, a
resolved temporal value with ``responsibility == "unclear"`` is not by itself
an action that may be offered for confirmation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from enum import StrEnum
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .models import ExtractedEvent, ExtractedTask


class NormalizationReason(StrEnum):
    MISSING_DATE = "missing_date"
    MISSING_TIME = "missing_time"
    MISSING_END_TIME = "missing_end_time"
    UNSUPPORTED_DATE = "unsupported_date_format"
    UNSUPPORTED_TIME = "unsupported_time_format"
    INVALID_DATE = "invalid_date"
    INVALID_TIME = "invalid_time"
    INVALID_CONTEXT = "invalid_mail_date_context"
    CONFLICTING_CONTEXT = "conflicting_mail_date_context"
    MISSING_TIMEZONE = "missing_timezone_context"
    UNKNOWN_TIMEZONE = "unknown_timezone"
    AMBIGUOUS_LOCAL_TIME = "ambiguous_local_time"
    NONEXISTENT_LOCAL_TIME = "nonexistent_local_time"
    END_NOT_AFTER_START = "end_not_after_start"


@dataclass(frozen=True)
class MailDateContext:
    date_context_status: str
    date_header_parsed: str | None
    imap_received_at: str | None
    user_timezone: str | None


@dataclass(frozen=True)
class TemporalValue:
    start: date | datetime
    end: date | datetime
    all_day: bool


@dataclass(frozen=True)
class NormalizationResult:
    """Exactly one of ``value`` and ``reason`` is populated."""

    value: TemporalValue | date | datetime | None
    reason: NormalizationReason | None
    raw_value: str | None
    question: str | None
    responsibility: str

    @property
    def resolved(self) -> bool:
        return self.value is not None

    @property
    def confirmation_ready(self) -> bool:
        """Temporal completeness does not override unclear responsibility."""
        return self.resolved and self.responsibility != "unclear"


_DATE_ISO = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_DATE_DE = re.compile(r"\d{2}\.\d{2}\.\d{4}\Z")
_TIME = re.compile(r"\d{2}:\d{2}(?::\d{2})?\Z")


def _failure(reason: NormalizationReason, raw: str | None, responsibility: str,
             question: str) -> NormalizationResult:
    return NormalizationResult(None, reason, raw, question, responsibility)


def _parse_date(raw: str | None, responsibility: str) -> date | NormalizationResult:
    if raw is None:
        return _failure(NormalizationReason.MISSING_DATE, raw, responsibility,
                        "Welches Datum ist gemeint?")
    fmt = "%Y-%m-%d" if _DATE_ISO.fullmatch(raw) else "%d.%m.%Y" if _DATE_DE.fullmatch(raw) else None
    if fmt is None:
        return _failure(NormalizationReason.UNSUPPORTED_DATE, raw, responsibility,
                        f"Welches konkrete Datum ist mit „{raw}“ gemeint?")
    try:
        return datetime.strptime(raw, fmt).date()
    except ValueError:
        return _failure(NormalizationReason.INVALID_DATE, raw, responsibility,
                        "Bitte ein gültiges Kalenderdatum angeben.")


def _parse_time(raw: str, responsibility: str) -> time | NormalizationResult:
    if not _TIME.fullmatch(raw):
        return _failure(NormalizationReason.UNSUPPORTED_TIME, raw, responsibility,
                        "Bitte die Uhrzeit als HH:MM oder HH:MM:SS angeben.")
    try:
        return time.fromisoformat(raw)
    except ValueError:
        return _failure(NormalizationReason.INVALID_TIME, raw, responsibility,
                        "Bitte eine gültige Uhrzeit angeben.")


def _aware_timestamp(raw: str | None) -> datetime | None:
    if raw is None:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _context_zone(context: MailDateContext, responsibility: str) -> ZoneInfo | NormalizationResult:
    if context.date_context_status == "conflicting":
        return _failure(NormalizationReason.CONFLICTING_CONTEXT, None, responsibility,
                        "Welcher Mail-Datumskontext soll verwendet werden?")
    if context.date_context_status != "valid":
        return _failure(NormalizationReason.INVALID_CONTEXT, None, responsibility,
                        "Welcher Mail-Datumskontext soll verwendet werden?")
    header, received = _aware_timestamp(context.date_header_parsed), _aware_timestamp(context.imap_received_at)
    if header is None or received is None:
        return _failure(NormalizationReason.INVALID_CONTEXT, None, responsibility,
                        "Welcher Mail-Datumskontext soll verwendet werden?")
    if abs((header.astimezone(timezone.utc) - received.astimezone(timezone.utc)).total_seconds()) > 7 * 86400:
        return _failure(NormalizationReason.CONFLICTING_CONTEXT, None, responsibility,
                        "Welcher Mail-Datumskontext soll verwendet werden?")
    if not context.user_timezone:
        return _failure(NormalizationReason.MISSING_TIMEZONE, None, responsibility,
                        "Welche Zeitzone soll verwendet werden?")
    try:
        return ZoneInfo(context.user_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        return _failure(NormalizationReason.UNKNOWN_TIMEZONE, context.user_timezone, responsibility,
                        "Welche gültige IANA-Zeitzone soll verwendet werden?")


def _localize(day: date, clock: time, zone: ZoneInfo, responsibility: str) -> datetime | NormalizationResult:
    naive = datetime.combine(day, clock)
    candidates: list[datetime] = []
    for fold in (0, 1):
        candidate = naive.replace(tzinfo=zone, fold=fold)
        if candidate.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) == naive:
            if not candidates or candidate.utcoffset() != candidates[0].utcoffset():
                candidates.append(candidate)
    if not candidates:
        return _failure(NormalizationReason.NONEXISTENT_LOCAL_TIME, clock.isoformat(), responsibility,
                        "Diese Ortszeit existiert wegen der Zeitumstellung nicht; welche Uhrzeit ist gemeint?")
    if len(candidates) > 1:
        return _failure(NormalizationReason.AMBIGUOUS_LOCAL_TIME, clock.isoformat(), responsibility,
                        "Welcher UTC-Offset gilt für diese doppelte Ortszeit?")
    return candidates[0]


def normalize_event(event: ExtractedEvent, context: MailDateContext) -> NormalizationResult:
    """Normalize an event without making a responsibility decision."""
    responsibility = event.responsibility
    day = _parse_date(event.date_text, responsibility)
    if isinstance(day, NormalizationResult):
        return day
    zone = _context_zone(context, responsibility)
    if isinstance(zone, NormalizationResult):
        return zone
    if event.time_text is None:
        if event.end_time_text is not None:
            return _failure(NormalizationReason.MISSING_TIME, event.end_time_text, responsibility,
                            "Welche Beginnzeit gehört zur Endzeit?")
        return NormalizationResult(TemporalValue(day, day + timedelta(days=1), True), None,
                                   event.date_text, None, responsibility)
    if event.end_time_text is None:
        return _failure(NormalizationReason.MISSING_END_TIME, event.time_text, responsibility,
                        "Wann endet der Termin?")
    start_clock = _parse_time(event.time_text, responsibility)
    if isinstance(start_clock, NormalizationResult):
        return start_clock
    end_clock = _parse_time(event.end_time_text, responsibility)
    if isinstance(end_clock, NormalizationResult):
        return end_clock
    start = _localize(day, start_clock, zone, responsibility)
    if isinstance(start, NormalizationResult):
        return start
    end = _localize(day, end_clock, zone, responsibility)
    if isinstance(end, NormalizationResult):
        return end
    if end <= start:
        return _failure(NormalizationReason.END_NOT_AFTER_START,
                        f"{event.time_text}–{event.end_time_text}", responsibility,
                        "Liegt das Ende an einem anderen Tag oder ist eine Uhrzeit falsch?")
    return NormalizationResult(TemporalValue(start, end, False), None,
                               f"{event.date_text} {event.time_text}–{event.end_time_text}", None,
                               responsibility)


def normalize_task_due(task: ExtractedTask, context: MailDateContext) -> NormalizationResult:
    """Normalize the supported date-only task deadline form."""
    responsibility = task.responsibility
    if task.due_text is None:
        return _failure(NormalizationReason.MISSING_DATE, None, responsibility,
                        "Soll die Aufgabe eine Fälligkeit haben?")
    parsed = _parse_date(task.due_text, responsibility)
    if isinstance(parsed, NormalizationResult):
        return parsed
    checked = _context_zone(context, responsibility)
    if isinstance(checked, NormalizationResult):
        return checked
    return NormalizationResult(parsed, None, task.due_text, None, responsibility)
