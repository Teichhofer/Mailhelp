"""CalDAV calendars (VEVENT) and task lists (VTODO): Nextcloud, iCloud, mailbox.org, Radicale, …

Every proposal version maps to exactly one resource ``<uid>.ics`` whose name is
derived from the idempotency key.  ``PUT`` with ``If-None-Match: *`` therefore
can never create a second copy, and reconciliation is a plain ``GET``.
"""
from __future__ import annotations

import xml.etree.ElementTree as ElementTree
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from ..adapter import PermanentError, RetryPolicy, uncertain_write
from ..logging import EventLogger, NullLogger
from ..models import Proposal, ProposalKind
from .calendar import CalendarOperations
from .contracts import (
    AuthenticationError,
    CalendarAccessError,
    CalendarOverlapEvent,
    PreparedWrite,
    TodoistTaskResponse,
)
from .ical import _ical_datetime
from .icalendar_data import (
    event_resource,
    event_summary,
    open_todo,
    parse_calendar,
    resource_uid,
    todo_resource,
    updated_event,
)
from .provider import ProviderWriter

DAV, CALDAV = "DAV:", "urn:ietf:params:xml:ns:caldav"
MAX_XML_BYTES = 5_000_000
PROPFIND = (b'<?xml version="1.0" encoding="utf-8"?><d:propfind xmlns:d="DAV:" '
            b'xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop><d:resourcetype/>'
            b'<c:supported-calendar-component-set/></d:prop></d:propfind>')


def _query(component: str, time_range: tuple[str, str] | None = None) -> bytes:
    window = f'<c:time-range start="{time_range[0]}" end="{time_range[1]}"/>' if time_range else ""
    return (f'<?xml version="1.0" encoding="utf-8"?><c:calendar-query xmlns:d="DAV:" '
            f'xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop><d:getetag/><c:calendar-data/></d:prop>'
            f'<c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="{component}">{window}'
            f'</c:comp-filter></c:comp-filter></c:filter></c:calendar-query>').encode()


def _xml(content: bytes) -> ElementTree.Element:
    """Parse an untrusted multistatus answer; DTDs (and thus entities) are refused."""
    if len(content) > MAX_XML_BYTES or b"<!DOCTYPE" in content.upper() or b"<!ENTITY" in content.upper():
        raise ValueError("CalDAV: unzulässige XML-Antwort")
    try:
        return ElementTree.fromstring(content)
    except ElementTree.ParseError as exc:
        raise ValueError("CalDAV: ungültige XML-Antwort") from exc


class DavResource:
    """HTTP access to one CalDAV collection with Basic authentication (app password)."""

    service: str
    label: str
    component: str
    logger: EventLogger
    policy: RetryPolicy

    def __init__(self, collection: str, username: str, password: str, timeout: float = 30,
                 transport: httpx.BaseTransport | None = None, policy: RetryPolicy | None = None,
                 logger: EventLogger | None = None):
        self.collection = collection if collection.endswith("/") else collection + "/"
        self.target = collection
        self.client = httpx.Client(timeout=timeout, transport=transport, auth=(username, password),
                                   follow_redirects=False)
        self.policy = policy or RetryPolicy(0, 0, 0, lambda _delay: False)
        self.logger = logger or NullLogger()
        self._read_cache: dict[tuple[Any, ...], tuple[float, Any]] = {}

    def close(self) -> None:
        self.client.close()

    def _send(self, method: str, url: str, *, content: bytes | None = None, headers: dict[str, str] | None = None,
              allowed: frozenset[int] = frozenset()) -> httpx.Response:
        self.logger.event("DEBUG", self.service, "http_request", method=method, url=urlsplit(url).path)
        response = self.client.request(method, url, content=content, headers=headers or {})
        if response.status_code in allowed:
            return response
        if response.status_code == 401:
            self.logger.event("ERROR", self.service, "authentication_failed", status=401)
            raise AuthenticationError(f"{self.label}: Anmeldung abgelehnt (Benutzername oder App-Passwort prüfen)")
        if response.status_code in {403, 404, 405}:
            self.logger.event("ERROR", self.service, "target_access_failed", status=response.status_code)
            raise CalendarAccessError(f"{self.label}: Sammlung nicht erreichbar oder keine Berechtigung")
        response.raise_for_status()
        return response

    def _resource(self, key: str) -> str:
        return self.collection + resource_uid(key) + ".ics"

    def _member(self, href: str) -> str:
        """Absolute address of a resource the server named; only members of the collection."""
        url = urljoin(self.collection, href)
        if not url.startswith(self.collection) or url == self.collection or ".." in urlsplit(url).path:
            raise ValueError("CalDAV: Ressource außerhalb der konfigurierten Sammlung")
        return url

    def check_access(self) -> None:
        """PROPFIND on the collection: a calendar collection that accepts this component."""
        response = self.policy.run(lambda: self._send(
            "PROPFIND", self.collection, content=PROPFIND,
            headers={"Depth": "0", "Content-Type": "application/xml; charset=utf-8"}))
        root = _xml(response.content)
        if root.find(f".//{{{DAV}}}resourcetype/{{{CALDAV}}}calendar") is None:
            raise CalendarAccessError(f"{self.label}: Die Adresse ist keine CalDAV-Kalendersammlung")
        supported = [item.get("name", "").upper() for item in root.iter(f"{{{CALDAV}}}comp")]
        if supported and self.component not in supported:
            raise CalendarAccessError(self._unsupported())

    def _unsupported(self) -> str:
        return f"{self.label}: Die Sammlung nimmt keine {self.component}-Einträge an"

    def reconcile(self, key: str) -> dict[str, Any] | None:
        self.logger.event("INFO", self.service, "reconcile_started", call_id=key)
        url = self._resource(key)
        response = self.policy.run(lambda: self._send("GET", url, allowed=frozenset({404})))
        if response.status_code == 404:
            return None
        parse_calendar(response.content)
        return {"id": url}

    def _put_new(self, key: str, content: bytes) -> dict[str, Any]:
        """Create the resource once; an existing one is this very proposal version."""
        url = self._resource(key)
        response = uncertain_write(lambda: self._send(
            "PUT", url, content=content, allowed=frozenset({412}),
            headers={"If-None-Match": "*", "Content-Type": "text/calendar; charset=utf-8"}))
        return {"id": url, "operation": "already_present"} if response.status_code == 412 else {"id": url}

    def _report(self, body: bytes) -> Iterator[tuple[str, bytes]]:
        """(address, calendar data) of every resource a calendar-query returns."""
        response = self.policy.run(lambda: self._send(
            "REPORT", self.collection, content=body,
            headers={"Depth": "1", "Content-Type": "application/xml; charset=utf-8"}))
        for item in _xml(response.content).iter(f"{{{DAV}}}response"):
            href, data = item.find(f"{{{DAV}}}href"), item.find(f".//{{{CALDAV}}}calendar-data")
            if href is None or not href.text or data is None or not data.text:
                continue
            yield self._member(href.text.strip()), data.text.encode("utf-8")


class CalDavCalendar(DavResource, ProviderWriter, CalendarOperations):
    """Events in a CalDAV calendar, with the same duplicate, change and cancellation flow as Google."""

    service, label, component, role = "caldav_calendar", "CalDAV-Kalender", "VEVENT", "calendar"

    def __init__(self, collection: str, username: str, password: str, timeout: float = 30,
                 transport: httpx.BaseTransport | None = None, policy: RetryPolicy | None = None,
                 logger: EventLogger | None = None, calendar_timezone: str = "UTC",
                 calendar_matcher: Any = None):
        super().__init__(collection, username, password, timeout, transport, policy, logger)
        self.calendar_timezone = calendar_timezone
        self.calendar_matcher = calendar_matcher

    def _prepare(self, proposal: Proposal, key: str) -> PreparedWrite:
        return self._prepare_calendar(proposal, key)

    def _insert_calendar_event(self, proposal: Proposal, key: str, body: dict[str, Any]) -> dict[str, Any]:
        content = event_resource(resource_uid(key), body, key)
        return self._logged(proposal, key, lambda: self._put_new(key, content))

    def _update_calendar_event(self, existing_id: str, body: dict[str, Any], key: str, proposal: Proposal,
                               time_changes: list[str] | None = None) -> dict[str, Any]:
        url = self._member(existing_id)

        def change() -> dict[str, Any]:
            current = self.policy.run(lambda: self._send("GET", url))
            etag = current.headers.get("ETag")
            if not etag:
                raise PermanentError(f"{self.label}: Server liefert kein ETag; Änderung nicht sicher möglich")
            try:
                content = updated_event(current.content, body, key)
            except ValueError as exc:
                raise PermanentError(f"{self.label}: Termin lässt sich nicht sicher ändern ({exc})") from exc
            response = uncertain_write(lambda: self._send(
                "PUT", url, content=content, allowed=frozenset({412}),
                headers={"If-Match": etag, "Content-Type": "text/calendar; charset=utf-8"}))
            if response.status_code == 412:
                raise PermanentError(f"{self.label}: Termin wurde zwischenzeitlich geändert; bitte erneut prüfen")
            return {"id": url, "operation": "duplicate_updated", "time_changes": time_changes or []}

        return self._logged(proposal, key, change, "duplicate_updated")

    def _calendar_candidates(self, time_min: str, time_max: str) -> Iterator[CalendarOverlapEvent]:
        window = (_ical_datetime(datetime.fromisoformat(time_min)), _ical_datetime(datetime.fromisoformat(time_max)))
        for url, data in self._report(_query("VEVENT", window)):
            fields = event_summary(parse_calendar(data), self.calendar_timezone or "UTC")
            if fields is None or fields.pop("cancelled"):
                continue
            yield CalendarOverlapEvent.model_validate({"id": url, **fields})

    def fetch_events_in_window(self, start: datetime | date, end: datetime | date, *,
                               strict: bool = False) -> list[CalendarOverlapEvent]:
        def moment(value: datetime | date) -> str:
            if not isinstance(value, datetime):
                value = datetime.combine(value, datetime.min.time(), UTC)
            return value.isoformat()

        cache_key = (self.service, self.target, moment(start), moment(end))
        cached = None if strict else self._get_cached(cache_key)
        if cached is not None:
            return cached
        try:
            events = list(self._calendar_candidates(moment(start), moment(end)))
        except Exception as exc:
            if strict:
                raise
            self.logger.event("WARNING", self.service, "fetch_events_failed", error=str(exc))
            return []
        self._set_cached(cache_key, events)
        return events


class CalDavTasks(DavResource, ProviderWriter):
    """Open tasks (VTODO) in a CalDAV task list; also Apple Erinnerungen via iCloud."""

    service, label, component, role = "caldav_tasks", "CalDAV-Aufgaben", "VTODO", "tasks"

    def _prepare(self, proposal: Proposal, key: str) -> PreparedWrite:
        if proposal.kind != ProposalKind.TASK:
            raise ValueError(f"{self.label} akzeptiert nur Aufgaben")
        content = todo_resource(resource_uid(key), proposal.title,
                                f"{proposal.description}\n\n[{key}]".strip(), proposal.due, key)
        return PreparedWrite(lambda: self._logged(proposal, key, lambda: self._put_new(key, content)))

    def fetch_active_tasks(self, *, strict: bool = False) -> list[TodoistTaskResponse]:
        cache_key = (self.service, self.target, "tasks")
        cached = None if strict else self._get_cached(cache_key)
        if cached is not None:
            return cached
        try:
            tasks = []
            for url, data in self._report(_query("VTODO")):
                fields = open_todo(parse_calendar(data))
                if fields is not None:
                    tasks.append(TodoistTaskResponse(id=url, content=fields["content"],
                                                     description=fields["description"]))
        except Exception as exc:
            self.logger.event("WARNING", self.service, "fetch_tasks_failed", error=str(exc))
            if strict:
                raise
            return []
        self._set_cached(cache_key, tasks)
        return tasks


class AppleReminders(CalDavTasks):
    """iCloud reminders through CalDAV; lists upgraded to the new iCloud reminders are not reachable."""

    service, label = "apple_reminders", "Apple Erinnerungen"

    def check_access(self) -> None:
        try:
            super().check_access()
        except CalendarAccessError as exc:
            raise CalendarAccessError(self._unsupported()) from exc

    def _unsupported(self) -> str:
        return ("Apple Erinnerungen: Diese Liste ist über CalDAV nicht erreichbar. Auf die neuen "
                "iCloud-Erinnerungen aktualisierte Listen bietet Apple nicht mehr über CalDAV an.")

