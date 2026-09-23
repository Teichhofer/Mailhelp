"""Deterministic temporal normalization of validated action extractions.

Supported dates also include German month names with an optional weekday and
``den``; times may carry the German ``Uhr`` suffix. Relative or otherwise free-form values are deliberately retained as
unresolved input; this module never guesses a date, time, duration, or offset.

The prepared mail context is accepted only when ``date_context_status`` is
``valid``, both timestamps are offset-aware and no more than seven days apart,
and ``user_timezone`` names an available IANA zone.  The header timestamp is a
reference instant only; it is not used to turn relative language into a date.
An explicitly extracted ``UTC±HH:MM`` offset supplies a fixed-offset timezone
for local clock times.  Only when it is absent does the user zone supply the
timezone.

Responsibility remains an independent fact on every result.  In particular, a
resolved temporal value with ``responsibility == "unclear"`` is not by itself
an action that may be offered for confirmation.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from enum import StrEnum
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .models import ExtractedEvent, ExtractedTask, TemporalFact, TimeRequirement


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
    known_date: date | None = None
    known_start: datetime | None = None
    temporal_fact: TemporalFact | None = None

    @property
    def resolved(self) -> bool:
        return self.value is not None

    @property
    def confirmation_ready(self) -> bool:
        """Temporal completeness does not override unclear responsibility."""
        return self.resolved and self.responsibility != "unclear"


_DATE_ISO = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_DATE_DE = re.compile(
    r"(?i)(?:(montag|mo|dienstag|di|mittwoch|mi|donnerstag|do|freitag|fr|"
    r"samstag|sa|sonntag|so)(?:,\s*|\s+))?(\d{2})\.(\d{2})\.(\d{4})\Z")
_DATE_YEARLESS = re.compile(
    r"(?i)(\d{1,2})\.?\s+(januar|februar|märz|maerz|april|mai|juni|juli|august|"
    r"september|oktober|november|dezember)\Z")
_DATE_NAMED = re.compile(
    r"(?i)(?:(montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag),?\s+)?"
    r"(?:den\s+)?(\d{1,2})\.?\s+(januar|februar|märz|maerz|april|mai|juni|juli|august|"
    r"september|oktober|november|dezember)\s+(\d{4})\Z")
_TIME = re.compile(r"(\d{1,2}):(\d{2})(?::(\d{2}))?(?:\s+Uhr)?\Z", re.IGNORECASE)


def _failure(reason: NormalizationReason, raw: str | None, responsibility: str,
             question: str) -> NormalizationResult:
    return NormalizationResult(None, reason, raw, question, responsibility)


_MONTHS = {name: number for number, names in enumerate(((), ("januar",), ("februar",),
    ("märz", "maerz"), ("april",), ("mai",), ("juni",), ("juli",), ("august",),
    ("september",), ("oktober",), ("november",), ("dezember",))) for name in names}
_WEEKDAYS = {name: number for number, name in enumerate(
    ("montag", "dienstag", "mittwoch", "donnerstag", "freitag", "samstag", "sonntag"))}
_WEEKDAYS.update({name: number for number, name in enumerate(
    ("mo", "di", "mi", "do", "fr", "sa", "so"))})


def _parse_date(raw: str | None, responsibility: str, context: MailDateContext | None = None,
                evidence: str = "") -> tuple[date, TemporalFact] | NormalizationResult:
    if raw is None:
        return _failure(NormalizationReason.MISSING_DATE, raw, responsibility,
                        "Welches Datum ist gemeint?")
    numeric = _DATE_DE.fullmatch(raw)
    fmt = "%Y-%m-%d" if _DATE_ISO.fullmatch(raw) else "%d.%m.%Y" if numeric else None
    if fmt is None:
        named = _DATE_NAMED.fullmatch(raw.strip())
        if named is not None:
            try:
                candidate = date(int(named.group(4)), _MONTHS[named.group(3).casefold()],
                                 int(named.group(2)))
            except ValueError:
                return _failure(NormalizationReason.INVALID_DATE, raw, responsibility,
                                "Bitte ein gültiges Kalenderdatum angeben.")
            if named.group(1) is not None and candidate.weekday() != _WEEKDAYS[named.group(1).casefold()]:
                return _failure(NormalizationReason.INVALID_DATE, raw, responsibility,
                                "Wochentag und Kalenderdatum widersprechen sich.")
            return candidate, TemporalFact(raw_text=raw, normalized_date=candidate,
                                           year_source="explicit_mail", status="resolved")
        match = _DATE_YEARLESS.fullmatch(raw.strip())
        if match is not None and context is not None:
            checked = _context_zone(context, responsibility)
            if isinstance(checked, NormalizationResult):
                return replace(checked, raw_value=raw,
                               temporal_fact=TemporalFact(raw_text=raw, status="unresolved"))
            header = _aware_timestamp(context.date_header_parsed)
            assert header is not None
            local_day = header.astimezone(checked).date()
            years = set(re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", evidence))
            if len(years) > 1:
                return replace(_failure(NormalizationReason.CONFLICTING_CONTEXT, raw, responsibility,
                               "Welche der widersprüchlichen Jahreszahlen gilt?"),
                               temporal_fact=TemporalFact(raw_text=raw, status="conflicting"))
            year = int(next(iter(years))) if years else local_day.year
            source = "explicit_mail" if years else "mail_context"
            try:
                candidate = date(year, _MONTHS[match.group(2).casefold()], int(match.group(1)))
                if not years and candidate < local_day:
                    candidate = candidate.replace(year=year + 1)
            except ValueError:
                return _failure(NormalizationReason.INVALID_DATE, raw, responsibility,
                                "Bitte ein gültiges Kalenderdatum angeben.")
            return candidate, TemporalFact(raw_text=raw, normalized_date=candidate,
                                           year_source=source, status="resolved")
        return _failure(NormalizationReason.UNSUPPORTED_DATE, raw, responsibility,
                        f"Welches konkrete Datum ist mit „{raw}“ gemeint?")
    try:
        if numeric is None:
            parsed = datetime.strptime(raw, fmt).date()
        else:
            parsed = date(int(numeric.group(4)), int(numeric.group(3)), int(numeric.group(2)))
            if (numeric.group(1) is not None
                    and parsed.weekday() != _WEEKDAYS[numeric.group(1).casefold()]):
                return _failure(NormalizationReason.INVALID_DATE, raw, responsibility,
                                "Wochentag und Kalenderdatum widersprechen sich.")
        years = set(re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", f"{raw} {evidence}"))
        if len(years) > 1:
            return replace(_failure(NormalizationReason.CONFLICTING_CONTEXT, raw, responsibility,
                           "Welche der widersprüchlichen Jahreszahlen gilt?"),
                           temporal_fact=TemporalFact(raw_text=raw, status="conflicting"))
        return parsed, TemporalFact(raw_text=raw, normalized_date=parsed,
                                    year_source="explicit_mail", status="resolved")
    except ValueError:
        return _failure(NormalizationReason.INVALID_DATE, raw, responsibility,
                        "Bitte ein gültiges Kalenderdatum angeben.")


def _parse_time(raw: str, responsibility: str) -> time | NormalizationResult:
    match = _TIME.fullmatch(raw.strip())
    if match is None:
        return _failure(NormalizationReason.UNSUPPORTED_TIME, raw, responsibility,
                        "Bitte die Uhrzeit als HH:MM oder HH:MM:SS angeben.")
    try:
        return time(int(match.group(1)), int(match.group(2)), int(match.group(3) or 0))
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


def _explicit_offset(raw: str) -> timezone:
    """Convert the already schema-validated UTC offset into a fixed timezone."""
    sign = 1 if raw[3] == "+" else -1
    return timezone(sign * timedelta(hours=int(raw[4:6]), minutes=int(raw[7:9])))


def normalize_event(event: ExtractedEvent, context: MailDateContext) -> NormalizationResult:
    """Normalize an event without making a responsibility decision."""
    responsibility = event.responsibility
    parsed_day = _parse_date(event.date_text, responsibility, context, event.evidence)
    if isinstance(parsed_day, NormalizationResult):
        if parsed_day.temporal_fact is None:
            return replace(parsed_day, temporal_fact=TemporalFact(
                raw_text=event.date_text,
                status=("conflicting" if parsed_day.reason == NormalizationReason.CONFLICTING_CONTEXT
                        else "unresolved")))
        return parsed_day
    day, fact = parsed_day
    if event.time_requirement == TimeRequirement.ALL_DAY:
        if event.time_text is not None or event.end_time_text is not None:
            return replace(_failure(NormalizationReason.INVALID_TIME,
                           event.time_text or event.end_time_text, responsibility,
                           "Ein ausdrücklich ganztägiger Termin darf keine Uhrzeit enthalten."),
                           temporal_fact=fact)
        checked = _context_zone(context, responsibility)
        if isinstance(checked, NormalizationResult):
            return replace(checked, temporal_fact=fact)
        return NormalizationResult(TemporalValue(day, day + timedelta(days=1), True), None,
                                   event.date_text, None, responsibility, temporal_fact=fact)
    if event.time_text is None:
        if event.end_time_text is not None:
            result = _failure(NormalizationReason.MISSING_TIME, event.end_time_text, responsibility,
                              "Wann beginnt der Termin?")
        else:
            result = _failure(NormalizationReason.MISSING_TIME, event.date_text, responsibility,
                              "Wann beginnt der Termin?")
        return replace(result, known_date=day, temporal_fact=fact)
    zone = (_explicit_offset(event.timezone_offset_text)
            if event.timezone_offset_text is not None
            else _context_zone(context, responsibility))
    if isinstance(zone, NormalizationResult):
        return replace(zone, temporal_fact=fact)
    start_clock = _parse_time(event.time_text, responsibility)
    if isinstance(start_clock, NormalizationResult):
        return replace(start_clock, temporal_fact=fact)
    start = (datetime.combine(day, start_clock, zone)
             if isinstance(zone, timezone) else _localize(day, start_clock, zone, responsibility))
    if isinstance(start, NormalizationResult):
        return replace(start, temporal_fact=fact)
    if event.end_time_text is None:
        result = _failure(NormalizationReason.MISSING_END_TIME, event.time_text, responsibility,
                          "Wann endet der Termin?")
        return replace(result, known_date=day, known_start=start, temporal_fact=fact)
    end_clock = _parse_time(event.end_time_text, responsibility)
    if isinstance(end_clock, NormalizationResult):
        return replace(end_clock, temporal_fact=fact)
    end = (datetime.combine(day, end_clock, zone)
           if isinstance(zone, timezone) else _localize(day, end_clock, zone, responsibility))
    if isinstance(end, NormalizationResult):
        return replace(end, temporal_fact=fact)
    if end <= start:
        return replace(_failure(NormalizationReason.END_NOT_AFTER_START,
                       f"{event.time_text}–{event.end_time_text}", responsibility,
                       "Liegt das Ende an einem anderen Tag oder ist eine Uhrzeit falsch?"),
                       temporal_fact=fact)
    return NormalizationResult(TemporalValue(start, end, False), None,
                               f"{event.date_text} {event.time_text}–{event.end_time_text}", None,
                               responsibility, temporal_fact=fact)


def normalize_task_due(task: ExtractedTask, context: MailDateContext) -> NormalizationResult:
    """Normalize the supported date-only task deadline form."""
    responsibility = task.responsibility
    if task.due_text is None:
        return _failure(NormalizationReason.MISSING_DATE, None, responsibility,
                        "Soll die Aufgabe eine Fälligkeit haben?")
    parsed = _parse_date(task.due_text, responsibility, context, task.evidence)
    if isinstance(parsed, NormalizationResult):
        return parsed
    parsed, fact = parsed
    checked = _context_zone(context, responsibility)
    if isinstance(checked, NormalizationResult):
        return replace(checked, temporal_fact=fact)
    return NormalizationResult(parsed, None, task.due_text, None, responsibility,
                               temporal_fact=fact)
