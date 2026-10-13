"""Deterministischer RFC-5545 iCalendar-Parser für Termineinladungen."""
from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .domain.extraction import ParsedCalendarEvent

MAX_CALENDAR_BYTES = 1_000_000

_VIDEO_LINK_PATTERN = re.compile(
    r"https://(?:meet\.google\.com/[a-z0-9-]+|[a-z0-9.-]*zoom\.us/j/\d+|teams\.microsoft\.com/l/meetup-join/[^\s\"'>]+)",
    re.IGNORECASE,
)


def _unfold_ical(text: str) -> list[str]:
    """Unfold lines split by CRLF or LF followed by space or tab (RFC 5545 Sec 3.1)."""
    # Normalize CRLF and CR to LF
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    # Unfold lines: newline followed by space or tab is removed
    unfolded = re.sub(r"\n[ \t]", "", normalized)
    return [line.strip() for line in unfolded.split("\n") if line.strip()]


_ESCAPE = re.compile(r"\\([nN,;\\])")


def _unescape_text(value: str) -> str:
    """Unescape RFC 5545 escaped characters: \\n, \\N, \\,, \\;, \\\\.

    One pass from left to right: an escaped backslash is consumed before the
    character after it can form a new escape (``C:\\\\new`` stays ``C:\\new``).
    """
    result = _ESCAPE.sub(lambda match: "\n" if match.group(1) in "nN" else match.group(1), value)
    return result.strip()


def _parse_ical_datetime(raw_val: str, params: dict[str, str], default_timezone: str = "UTC") -> tuple[date | datetime, bool]:
    """Parse an iCalendar DATE or DATE-TIME value into date or timezone-aware datetime."""
    val = raw_val.strip()
    is_date_value = params.get("VALUE", "").upper() == "DATE" or (len(val) == 8 and val.isdigit())
    if is_date_value:
        year = int(val[:4])
        month = int(val[4:6])
        day = int(val[6:8])
        return date(year, month, day), True

    # DATE-TIME: YYYYMMDDTHHMMSS or YYYYMMDDTHHMMSSZ
    clean_val = val.replace("-", "").replace(":", "")
    if "T" not in clean_val:
        raise ValueError(f"Ungültiges iCalendar-Zeitformat: {raw_val}")

    date_part, time_part = clean_val.split("T", 1)
    year = int(date_part[:4])
    month = int(date_part[4:6])
    day = int(date_part[6:8])

    is_utc = time_part.endswith("Z")
    time_digits = time_part[:-1] if is_utc else time_part
    hour = int(time_digits[:2])
    minute = int(time_digits[2:4])
    second = int(time_digits[4:6]) if len(time_digits) >= 6 else 0

    if is_utc:
        tz = UTC
    elif "TZID" in params:
        tz_name = params["TZID"].strip("'\"")
        try:
            tz = ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, ValueError):
            tz = ZoneInfo(default_timezone)
    else:
        try:
            tz = ZoneInfo(default_timezone)
        except (ZoneInfoNotFoundError, ValueError):
            tz = UTC

    dt = datetime(year, month, day, hour, minute, second, tzinfo=tz)
    return dt, False


def _extract_video_link(location: str, description: str, raw_props: dict[str, str]) -> str | None:
    """Extract conference link from location, description, or custom X-props."""
    candidates = [
        raw_props.get("X-GOOGLE-CONFERENCE", ""),
        raw_props.get("URL", ""),
        location,
        description,
    ]
    for candidate in candidates:
        if candidate:
            match = _VIDEO_LINK_PATTERN.search(candidate)
            if match:
                return match.group(0)
    return None


def parse_icalendar(content: str | bytes, default_timezone: str = "UTC") -> list[ParsedCalendarEvent]:
    """Parse VEVENT components from RFC 5545 iCalendar data with bounds checking."""
    if isinstance(content, bytes):
        if len(content) > MAX_CALENDAR_BYTES:
            raise ValueError(f"Kalenderdatei überschreitet das Limit von {MAX_CALENDAR_BYTES} Bytes")
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            text = content.decode("latin-1", errors="replace")
    else:
        if len(content.encode("utf-8")) > MAX_CALENDAR_BYTES:
            raise ValueError(f"Kalenderdatei überschreitet das Limit von {MAX_CALENDAR_BYTES} Bytes")
        text = content

    lines = _unfold_ical(text)
    events: list[ParsedCalendarEvent] = []

    in_vevent = False
    current_props: dict[str, tuple[str, dict[str, str]]] = {}
    current_raw: dict[str, str] = {}

    for line in lines:
        if line == "BEGIN:VEVENT":
            in_vevent = True
            current_props = {}
            current_raw = {}
            continue
        if line == "END:VEVENT":
            if in_vevent:
                event = _build_event(current_props, current_raw, default_timezone)
                if event is not None:
                    events.append(event)
            in_vevent = False
            continue

        if not in_vevent:
            continue

        if ":" not in line:
            continue

        name_params, value = line.split(":", 1)
        name_parts = name_params.split(";")
        prop_name = name_parts[0].upper()
        params: dict[str, str] = {}
        for param in name_parts[1:]:
            if "=" in param:
                p_key, p_val = param.split("=", 1)
                params[p_key.upper()] = p_val

        current_props[prop_name] = (value, params)
        current_raw[prop_name] = value

    return events


def _build_event(
    props: dict[str, tuple[str, dict[str, str]]],
    raw_props: dict[str, str],
    default_timezone: str,
) -> ParsedCalendarEvent | None:
    if "DTSTART" not in props:
        return None

    try:
        dtstart_val, dtstart_params = props["DTSTART"]
        start, all_day = _parse_ical_datetime(dtstart_val, dtstart_params, default_timezone)

        if "DTEND" in props:
            dtend_val, dtend_params = props["DTEND"]
            end, _ = _parse_ical_datetime(dtend_val, dtend_params, default_timezone)
        else:
            end = start

        # If all-day date: ensure end >= start
        if isinstance(start, date) and not isinstance(start, datetime) and isinstance(end, datetime):
            end = end.date()

        summary_val = _unescape_text(props.get("SUMMARY", ("Unbenannter Termin", {}))[0])
        if not summary_val:
            summary_val = "Unbenannter Termin"

        desc_val = _unescape_text(props.get("DESCRIPTION", ("", {}))[0])
        location_val = _unescape_text(props.get("LOCATION", ("", {}))[0]) or None

        uid_val = props.get("UID", (None, {}))[0]
        if uid_val:
            uid_val = uid_val.strip()

        seq_raw = props.get("SEQUENCE", ("0", {}))[0]
        try:
            sequence = int(seq_raw)
        except ValueError:
            sequence = 0

        status_raw = props.get("STATUS", ("CONFIRMED", {}))[0].upper().strip()
        status: Any = status_raw if status_raw in {"CONFIRMED", "TENTATIVE", "CANCELLED"} else "CONFIRMED"

        video_link = _extract_video_link(location_val or "", desc_val, raw_props)

        return ParsedCalendarEvent(
            uid=uid_val,
            sequence=sequence,
            summary=summary_val[:500],
            description=desc_val[:4000],
            start=start,
            end=end,
            all_day=all_day,
            location=location_val[:1000] if location_val else None,
            video_link=video_link,
            status=status,
        )
    except Exception:
        return None

