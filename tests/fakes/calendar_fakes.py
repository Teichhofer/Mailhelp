"""Simulated calendars for the 4.6 change and cancellation flow (synthetic data only)."""
from __future__ import annotations

import json
from datetime import datetime

import httpx

from mailhelp.proposals.integrations import HttpWriter


def _moment(raw: dict[str, str]) -> datetime:
    value = raw.get("dateTime") or f"{raw['date']}T00:00:00+00:00"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class FakeGoogleCalendar:
    """Google Calendar events by id: list with window and key filter, get, patch.

    Like Google, a cancelled event disappears from lists but stays readable by id.
    ``fail`` maps ``(method, "list" | "get" | "patch")`` to a forced answer.
    """

    def __init__(self, *events: dict):
        self.events = {item["id"]: dict(item) for item in events}
        self.requests: list[httpx.Request] = []
        self.patches: list[tuple[str, dict]] = []
        self.fail: dict[tuple[str, str], httpx.Response] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        event_id = path.split("/events/", 1)[1] if "/events/" in path else None
        kind = "list" if event_id is None else ("patch" if request.method == "PATCH" else "get")
        if (request.method, kind) in self.fail:
            return self.fail[(request.method, kind)]
        if kind == "list":
            return httpx.Response(200, json={"items": self._listed(request.url.params)})
        if event_id not in self.events:
            return httpx.Response(410 if kind == "get" else 404, json={"error": {"errors": []}})
        if kind == "patch":
            body = json.loads(request.content)
            self.patches.append((event_id, body))
            self.events[event_id] = {**self.events[event_id], **body}
        return httpx.Response(200, json=self.events[event_id])

    def _listed(self, params: httpx.QueryParams) -> list[dict]:
        listed = [item for item in self.events.values() if item.get("status") != "cancelled"]
        key = params.get("privateExtendedProperty")
        if key is not None:
            wanted = key.split("=", 1)[1]
            return [item for item in listed
                    if item.get("extendedProperties", {}).get("private", {}).get("mailhelp_key") == wanted]
        low, high = datetime.fromisoformat(params["timeMin"]), datetime.fromisoformat(params["timeMax"])
        return [item for item in listed if _moment(item["end"]) > low and _moment(item["start"]) < high]


def google_writer(calendar: FakeGoogleCalendar, matcher=None, target: str = "calendar-1") -> HttpWriter:
    """``calendar-1`` is the calendar the proposal builder fakes bind proposals to."""
    return HttpWriter(service="google_calendar", token="tok", target=target, calendar_timezone="Europe/Berlin",
                      transport=httpx.MockTransport(calendar), calendar_matcher=matcher)


def timed(event_id: str, summary: str, start: str, end: str, **extra) -> dict:
    """A timed Google event; ``start``/``end`` are ISO instants with offset."""
    return {"id": event_id, "summary": summary, "start": {"dateTime": start}, "end": {"dateTime": end},
            "htmlLink": f"https://calendar.example.test/{event_id}", **extra}


def vevent(uid: str, summary: str, start: str, end: str) -> bytes:
    """A CalDAV resource; ``start``/``end`` in UTC basic format, e.g. 20261204T180000Z."""
    return (f"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Synthetisch//DE\r\nBEGIN:VEVENT\r\nUID:{uid}\r\n"
            f"SUMMARY:{summary}\r\nDTSTART:{start}\r\nDTEND:{end}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n").encode()
