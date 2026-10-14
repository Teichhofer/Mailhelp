"""iCalendar resources for CalDAV: create, read and change VEVENT and VTODO components.

Provider answers are untrusted: parsing is bounded, tolerant of unknown
properties and never evaluates anything but the properties Mailhelp needs.
Unknown properties of an existing event survive an update unchanged.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from ..calendar_parser import _parse_ical_datetime, _unescape_text, _unfold_ical
from .ical import _fold_ical_line, _ical_datetime, _ical_text

MAX_RESOURCE_BYTES = 1_000_000
PRODID = "-//Mailhelp//CalDAV//DE"
# Properties Mailhelp writes; an update replaces them and keeps every other line.
MANAGED = frozenset({"SUMMARY", "DESCRIPTION", "LOCATION", "DTSTART", "DTEND", "DURATION", "STATUS",
                     "X-MAILHELP-KEY", "SEQUENCE", "DTSTAMP", "LAST-MODIFIED"})


def resource_uid(key: str) -> str:
    """Deterministic UID (and resource name): the same proposal version always maps to one resource."""
    return "mailhelp-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


@dataclass
class Property:
    name: str
    params: dict[str, str]
    value: str

    def line(self) -> str:
        params = "".join(f";{key}={value}" for key, value in self.params.items())
        return f"{self.name}{params}:{self.value}"


@dataclass
class Component:
    name: str
    properties: list[Property] = field(default_factory=list)
    children: list[Component] = field(default_factory=list)

    def get(self, name: str) -> Property | None:
        return next((item for item in self.properties if item.name == name), None)

    def text(self, name: str) -> str:
        found = self.get(name)
        return _unescape_text(found.value) if found is not None else ""

    def lines(self) -> list[str]:
        return [f"BEGIN:{self.name}", *(item.line() for item in self.properties),
                *(line for child in self.children for line in child.lines()), f"END:{self.name}"]


def parse_calendar(content: str | bytes) -> Component:
    """The VCALENDAR object of one resource; raises ValueError for anything else."""
    if isinstance(content, bytes):
        if len(content) > MAX_RESOURCE_BYTES:
            raise ValueError("iCalendar-Ressource ist zu groß")
        content = content.decode("utf-8", errors="replace")
    elif len(content) > MAX_RESOURCE_BYTES:
        raise ValueError("iCalendar-Ressource ist zu groß")
    stack: list[Component] = []
    root: Component | None = None
    for line in _unfold_ical(content):
        name_params, separator, value = line.partition(":")
        if not separator:
            continue
        name, *raw_params = name_params.split(";")
        name = name.upper()
        if name == "BEGIN":
            component = Component(value.strip().upper())
            if stack:
                stack[-1].children.append(component)
            elif root is None:
                root = component
            else:
                raise ValueError("Mehr als ein Kalenderobjekt")
            stack.append(component)
        elif name == "END":
            if not stack or stack[-1].name != value.strip().upper():
                raise ValueError("Unausgeglichene iCalendar-Komponenten")
            stack.pop()
        elif stack:
            params = dict(param.split("=", 1) for param in raw_params if "=" in param)
            stack[-1].properties.append(Property(name, {key.upper(): val for key, val in params.items()}, value))
    if root is None or root.name != "VCALENDAR" or stack:
        raise ValueError("Keine vollständige VCALENDAR-Ressource")
    return root


def serialize(calendar: Component) -> bytes:
    return ("\r\n".join(_fold_ical_line(line) for line in calendar.lines()) + "\r\n").encode("utf-8")


def _stamp() -> str:
    return _ical_datetime(datetime.now(UTC))


def _time_property(name: str, value: dict[str, str]) -> Property:
    """A Google-style ``{"dateTime": …}`` or ``{"date": …}`` boundary as DTSTART/DTEND/DUE."""
    if "dateTime" in value:
        return Property(name, {}, _ical_datetime(datetime.fromisoformat(value["dateTime"])))
    return Property(name, {"VALUE": "DATE"}, f"{date.fromisoformat(value['date']):%Y%m%d}")


def _calendar(child: Component) -> Component:
    return Component("VCALENDAR", [Property("VERSION", {}, "2.0"), Property("PRODID", {}, PRODID)], [child])


def event_resource(uid: str, body: dict[str, Any], key: str) -> bytes:
    """A new VEVENT from the provider-neutral event body (Google field names)."""
    event = Component("VEVENT", [Property("UID", {}, uid), Property("DTSTAMP", {}, _stamp()),
                                 Property("SEQUENCE", {}, "0")])
    _apply(event, body, key)
    return serialize(_calendar(event))


def todo_resource(uid: str, title: str, description: str, due: date | datetime | None, key: str) -> bytes:
    """A new open VTODO; *description* already carries the Mailhelp marker."""
    todo = Component("VTODO", [Property("UID", {}, uid), Property("DTSTAMP", {}, _stamp()),
                               Property("SUMMARY", {}, _ical_text(title)),
                               Property("STATUS", {}, "NEEDS-ACTION"),
                               Property("X-MAILHELP-KEY", {}, _ical_text(key)),
                               Property("DESCRIPTION", {}, _ical_text(description))])
    if isinstance(due, datetime):
        todo.properties.append(Property("DUE", {}, _ical_datetime(due)))
    elif due is not None:
        todo.properties.append(Property("DUE", {"VALUE": "DATE"}, f"{due:%Y%m%d}"))
    return serialize(_calendar(todo))


def _apply(event: Component, body: dict[str, Any], key: str) -> None:
    """Replace the managed properties named in *body*; everything else stays."""
    replaced: list[Property] = []
    if "summary" in body:
        replaced.append(Property("SUMMARY", {}, _ical_text(body["summary"])))
    if body.get("description"):
        replaced.append(Property("DESCRIPTION", {}, _ical_text(body["description"])))
    if body.get("location"):
        replaced.append(Property("LOCATION", {}, _ical_text(body["location"])))
    if "start" in body:
        replaced.append(_time_property("DTSTART", body["start"]))
    if "end" in body:
        replaced.append(_time_property("DTEND", body["end"]))
    if body.get("status") == "cancelled":
        replaced.append(Property("STATUS", {}, "CANCELLED"))
    replaced.append(Property("X-MAILHELP-KEY", {}, _ical_text(key)))
    names = {item.name for item in replaced}
    if "DTEND" in names:
        names.add("DURATION")
    event.properties = [item for item in event.properties if item.name not in names] + replaced


def master(calendar: Component, kind: str) -> Component:
    """The single, non-recurring component of a resource; recurring series are not changed."""
    found = [child for child in calendar.children if child.name == kind]
    if len(found) != 1 or found[0].get("RRULE") is not None or found[0].get("RECURRENCE-ID") is not None:
        raise ValueError("Wiederkehrende oder mehrteilige Termine werden nicht verändert")
    return found[0]


def updated_event(content: bytes, body: dict[str, Any], key: str) -> bytes:
    """The existing event with Mailhelp's confirmed changes and a higher SEQUENCE."""
    calendar = parse_calendar(content)
    event = master(calendar, "VEVENT")
    sequence = event.get("SEQUENCE")
    number = int(sequence.value) + 1 if sequence is not None and sequence.value.strip().isdigit() else 1
    _apply(event, body, key)
    event.properties = [item for item in event.properties
                        if item.name not in {"SEQUENCE", "DTSTAMP", "LAST-MODIFIED"}]
    event.properties += [Property("SEQUENCE", {}, str(number)), Property("DTSTAMP", {}, _stamp())]
    return serialize(calendar)


def boundary(prop: Property | None, zone: str) -> dict[str, str] | None:
    """A DTSTART/DTEND/DUE value in the neutral ``{"dateTime"|"date": …}`` form."""
    if prop is None:
        return None
    value, all_day = _parse_ical_datetime(prop.value, prop.params, zone)
    return {"date": value.isoformat()} if all_day else {"dateTime": value.isoformat()}


def event_summary(calendar: Component, zone: str) -> dict[str, Any] | None:
    """Fields of a single event for duplicate checks; None for series or incomplete events."""
    try:
        event = master(calendar, "VEVENT")
        start = boundary(event.get("DTSTART"), zone)
        end = boundary(event.get("DTEND"), zone) or start
    except ValueError:
        return None
    if start is None or end is None:
        return None
    return {"summary": event.text("SUMMARY")[:500], "description": event.text("DESCRIPTION")[:4000],
            "location": event.text("LOCATION")[:1000] or None, "start": start, "end": end,
            "cancelled": event.text("STATUS").upper() == "CANCELLED"}


def open_todo(calendar: Component) -> dict[str, str] | None:
    """Title and text of an open task; None when completed, cancelled or not a task."""
    todo = next((child for child in calendar.children if child.name == "VTODO"), None)
    if todo is None or todo.text("STATUS").upper() in {"COMPLETED", "CANCELLED"} or todo.get("COMPLETED"):
        return None
    return {"content": todo.text("SUMMARY")[:500], "description": todo.text("DESCRIPTION")[:4000],
            "key": todo.text("X-MAILHELP-KEY")}


