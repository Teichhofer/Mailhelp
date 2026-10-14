"""Microsoft 365 via Microsoft Graph: Outlook calendar and Microsoft To Do.

Microsoft issues a new refresh token with every renewal.  The newest one is kept
in ``microsoft-token.json`` next to ``.env`` (outside the state directory, so
``mailhelp --clear`` keeps the sign-in); ``MICROSOFT_REFRESH_TOKEN`` only seeds
the first renewal.  ``mailhelp --microsoft-login`` signs in with a device code.
"""
from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from functools import partial
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import Field, ValidationError

from ..adapter import RETRYABLE_STATUS, RetryPolicy, uncertain_write
from ..logging import EventLogger, NullLogger
from ..models import Proposal, ProposalKind
from ..storage import atomic_replace
from .calendar import CalendarOperations
from .contracts import (
    AccessTokenProvider,
    AuthenticationError,
    CalendarAccessError,
    CalendarOverlapEvent,
    ExternalUnavailable,
    IntegrationModel,
    OAuthTokenError,
    PreparedWrite,
    TodoistTaskResponse,
    validation_path,
)
from .provider import ProviderWriter

GRAPH = "https://graph.microsoft.com/v1.0"
LOGIN = "https://login.microsoftonline.com"
SCOPES = "offline_access Calendars.ReadWrite Tasks.ReadWrite"
# Named MAPI property that carries the idempotency key on every Outlook event.
KEY_PROPERTY = "String {6b1c9a0e-4f43-4c9a-9d55-6d61696c6865} Name mailhelpKey"
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"


class MicrosoftTokenResponse(IntegrationModel):
    access_token: str = Field(min_length=1)
    expires_in: int = Field(gt=0)
    token_type: str
    refresh_token: str | None = None


class DeviceCodeResponse(IntegrationModel):
    device_code: str = Field(min_length=1)
    user_code: str = Field(min_length=1, max_length=50)
    verification_uri: str = Field(pattern=r"^https://")
    expires_in: int = Field(gt=0, le=3600)
    interval: int = Field(default=5, ge=1, le=60)


class TokenFile:
    """The newest Microsoft refresh token as readable JSON, readable only by the owner."""

    def __init__(self, path: Path):
        self.path = path

    def load(self) -> str | None:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8")).get("refresh_token")
        except (OSError, ValueError, AttributeError):
            return None
        return value if isinstance(value, str) and value else None

    def save(self, token: str) -> None:
        atomic_replace(self.path, json.dumps({"schema_version": 1, "refresh_token": token,
                                              "updated_at": datetime.now(UTC).isoformat()}, indent=2) + "\n")
        os.chmod(self.path, 0o600)


class MicrosoftTokenProvider(AccessTokenProvider):
    """Short-lived access tokens in memory; rotated refresh tokens persisted at once."""

    def __init__(self, client_id: str, client_secret: str, seed: str, tenant: str, tokens: TokenFile,
                 timeout: float = 30, transport: httpx.BaseTransport | None = None,
                 clock: Callable[[], float] = time.time, logger: EventLogger | None = None):
        self._client_id, self._client_secret, self._seed, self._tokens = client_id, client_secret, seed, tokens
        self._clock = clock
        self._token: str | None = None
        self._expires_at = 0.0
        self._client = httpx.Client(base_url=f"{LOGIN}/{tenant}/oauth2/v2.0", timeout=timeout, transport=transport)
        self._logger = logger or NullLogger()

    def _form(self, **values: str) -> dict[str, str]:
        form = {"client_id": self._client_id, "scope": SCOPES, **values}
        if self._client_secret:
            form["client_secret"] = self._client_secret
        return form

    def access_token(self) -> str:
        if self._token is not None and self._clock() < self._expires_at - 60:
            return self._token
        refresh = self._tokens.load() or self._seed
        if not refresh:
            raise OAuthTokenError("Microsoft: keine Anmeldung vorhanden. 'mailhelp --microsoft-login' ausführen.")
        self._logger.event("INFO", "microsoft_oauth", "token_refresh_started")
        response = self._client.post("/token", data=self._form(grant_type="refresh_token", refresh_token=refresh))
        if response.status_code in RETRYABLE_STATUS:
            raise ExternalUnavailable("Microsoft-Anmeldedienst vorübergehend nicht erreichbar")
        try:
            response.raise_for_status()
            value = MicrosoftTokenResponse.model_validate(response.json())
            if value.token_type.lower() != "bearer":
                raise ValueError("unerwarteter Token-Typ")
        except (httpx.HTTPStatusError, ValueError, ValidationError):
            self._logger.event("ERROR", "microsoft_oauth", "token_refresh_denied", status=response.status_code)
            raise OAuthTokenError("Microsoft-Anmeldung abgelehnt oder abgelaufen. "
                                  "'mailhelp --microsoft-login' erneut ausführen.") from None
        if value.refresh_token:
            self._tokens.save(value.refresh_token)
        self._token, self._expires_at = value.access_token, self._clock() + value.expires_in
        self._logger.event("INFO", "microsoft_oauth", "token_credentials_accepted", expires_in=value.expires_in,
                           rotated=bool(value.refresh_token))
        return self._token

    def invalidate(self) -> None:
        self._token, self._expires_at = None, 0.0

    def device_login(self, show: Callable[[str], None], sleep: Callable[[float], None] = time.sleep,
                     clock: Callable[[], float] = time.monotonic) -> None:
        """Sign in with a device code; only the user code and address are shown, never tokens."""
        response = self._client.post("/devicecode", data={"client_id": self._client_id, "scope": SCOPES})
        try:
            response.raise_for_status()
            device = DeviceCodeResponse.model_validate(response.json())
        except (httpx.HTTPStatusError, ValueError, ValidationError):
            raise OAuthTokenError("Microsoft: Gerätecode-Anmeldung nicht möglich (Client-ID und "
                                  "'Öffentliche Clientflows zulassen' prüfen)") from None
        show(f"Öffne {device.verification_uri} und gib den Code {device.user_code} ein.")
        interval, deadline = device.interval, clock() + device.expires_in
        while clock() < deadline:
            sleep(interval)
            answer = self._client.post("/token", data=self._form(grant_type=DEVICE_GRANT,
                                                                 device_code=device.device_code))
            if answer.status_code == 200:
                try:
                    value = MicrosoftTokenResponse.model_validate(answer.json())
                except (ValueError, ValidationError):
                    break
                if not value.refresh_token:
                    break
                self._tokens.save(value.refresh_token)
                self.invalidate()
                show("Microsoft-Anmeldung gespeichert.")
                return
            error = _error_code(answer)
            if error == "authorization_pending":
                continue
            if error == "slow_down":
                interval += 5
                continue
            break
        raise OAuthTokenError("Microsoft-Anmeldung nicht abgeschlossen (abgelehnt oder abgelaufen)")

    def close(self) -> None:
        self._client.close()


def _error_code(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except ValueError:
        return None
    return body.get("error") if isinstance(body, dict) and isinstance(body.get("error"), str) else None


class GraphEvent(IntegrationModel):
    id: str = Field(min_length=1)
    subject: str | None = ""
    body: dict[str, Any] | None = None
    location: dict[str, Any] | None = None
    start: dict[str, str]
    end: dict[str, str]
    isAllDay: bool = False
    isCancelled: bool = False
    webLink: str | None = None


class GraphTask(IntegrationModel):
    id: str = Field(min_length=1)
    title: str = ""
    body: dict[str, Any] | None = None
    status: str = "notStarted"
    linkedResources: list[dict[str, Any]] = Field(default_factory=list)


class GraphResource:
    """Authenticated Graph requests with Mailhelp's error classification."""

    service: str
    label: str
    logger: EventLogger
    policy: RetryPolicy

    def __init__(self, token: AccessTokenProvider, target: str, timeout: float = 30,
                 transport: httpx.BaseTransport | None = None, policy: RetryPolicy | None = None,
                 logger: EventLogger | None = None):
        self.token, self.target = token, target
        self.client = httpx.Client(base_url=GRAPH, timeout=timeout, transport=transport, follow_redirects=False)
        self.policy = policy or RetryPolicy(0, 0, 0, lambda _delay: False)
        self.logger = logger or NullLogger()
        self._read_cache: dict[tuple[Any, ...], tuple[float, Any]] = {}

    def close(self) -> None:
        self.client.close()

    def _send(self, method: str, url: str, *, body: dict[str, Any] | None = None,
              params: dict[str, str] | None = None, key: str | None = None) -> httpx.Response:
        self.logger.event("DEBUG", self.service, "http_request", method=method, url=url.split("?")[0],
                          call_id=key)
        headers = {"Authorization": f"Bearer {self.token.access_token()}",
                   "Prefer": 'outlook.timezone="UTC", outlook.body-content-type="text"'}
        response = self.client.request(method, url, json=body, params=params, headers=headers)
        if response.status_code == 401:
            self.token.invalidate()
            self.logger.event("ERROR", self.service, "authentication_failed", status=401)
            raise AuthenticationError(f"{self.label}: Microsoft hat den Zugriffstoken abgelehnt")
        if response.status_code in {403, 404}:
            self.logger.event("ERROR", self.service, "target_access_failed", status=response.status_code)
            raise CalendarAccessError(f"{self.label}: Ziel nicht gefunden oder Berechtigung fehlt")
        response.raise_for_status()
        return response

    def _pages(self, url: str, params: dict[str, str] | None = None) -> Iterator[dict[str, Any]]:
        """Every item of a paged collection; nextLinks must stay on Microsoft Graph."""
        seen: set[str] = set()
        while True:
            response = self.policy.run(partial(self._send, "GET", url, params=params))
            try:
                page = response.json()
                items, following = page["value"], page.get("@odata.nextLink")
                if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
                    raise ValueError("value")
                if following is not None and (not isinstance(following, str) or not following.startswith(GRAPH + "/")
                                              or following in seen):
                    raise ValueError("@odata.nextLink")
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                raise ValueError(f"{self.label}: ungültige Antwort am Schlüsselpfad {exc}") from exc
            yield from items
            if following is None:
                return
            seen.add(following)
            url, params = following, None


def _graph_time(value: dict[str, str]) -> tuple[dict[str, str], bool]:
    """A neutral boundary as Graph dateTimeTimeZone (UTC) and whether it is a whole day."""
    if "dateTime" in value:
        moment = datetime.fromisoformat(value["dateTime"]).astimezone(UTC)
        return {"dateTime": moment.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": "UTC"}, False
    return {"dateTime": f"{date.fromisoformat(value['date'])}T00:00:00", "timeZone": "UTC"}, True


def _neutral_time(value: dict[str, str], all_day: bool) -> dict[str, str]:
    """Graph answers in UTC (Prefer header); whole days become ``{"date": …}``."""
    if all_day:
        return {"date": value["dateTime"][:10]}
    moment = datetime.fromisoformat(value["dateTime"][:19]).replace(tzinfo=UTC)
    return {"dateTime": moment.isoformat()}


class OutlookCalendar(GraphResource, ProviderWriter, CalendarOperations):
    """Events in an Outlook / Microsoft 365 calendar."""

    service, label, role = "outlook_calendar", "Outlook-Kalender", "calendar"

    def __init__(self, token: AccessTokenProvider, target: str, timeout: float = 30,
                 transport: httpx.BaseTransport | None = None, policy: RetryPolicy | None = None,
                 logger: EventLogger | None = None, calendar_timezone: str = "UTC", calendar_matcher: Any = None):
        super().__init__(token, target, timeout, transport, policy, logger)
        self.calendar_timezone = calendar_timezone
        self.calendar_matcher = calendar_matcher

    @property
    def _base(self) -> str:
        return "/me/calendar" if self.target == "default" else f"/me/calendars/{quote(self.target, safe='')}"

    def check_access(self) -> None:
        self.policy.run(lambda: self._send("GET", self._base))

    def reconcile(self, key: str) -> dict[str, Any] | None:
        self.logger.event("INFO", self.service, "reconcile_started", call_id=key)
        value = key.replace("'", "''")
        query = {"$filter": f"singleValueExtendedProperties/Any(ep: ep/id eq '{KEY_PROPERTY}' "
                            f"and ep/value eq '{value}')", "$select": "id,webLink"}
        for item in self._pages(f"{self._base}/events", query):
            return self._result(item)
        return None

    def _result(self, item: dict[str, Any]) -> dict[str, Any]:
        try:
            event = GraphEvent.model_validate({"start": {}, "end": {}, **item})
        except ValidationError as exc:
            raise ValueError(f"{self.label}: ungültige Antwort am Schlüsselpfad {validation_path(exc)}") from exc
        link = event.webLink if event.webLink and event.webLink.startswith("https://") else None
        return {"id": event.id, "htmlLink": link}

    def _prepare(self, proposal: Proposal, key: str) -> PreparedWrite:
        return self._prepare_calendar(proposal, key)

    def _graph_body(self, body: dict[str, Any], key: str) -> dict[str, Any]:
        result: dict[str, Any] = {"singleValueExtendedProperties": [{"id": KEY_PROPERTY, "value": key}]}
        if "summary" in body:
            result["subject"] = body["summary"]
        if body.get("description"):
            result["body"] = {"contentType": "text", "content": body["description"]}
        if body.get("location"):
            result["location"] = {"displayName": body["location"]}
        for name in ("start", "end"):
            if name in body:
                result[name], all_day = _graph_time(body[name])
                result["isAllDay"] = all_day
        return result

    def _insert_calendar_event(self, proposal: Proposal, key: str, body: dict[str, Any]) -> dict[str, Any]:
        payload = {**self._graph_body(body, key), "transactionId": key[:255]}
        return self._logged(proposal, key, lambda: self._result(uncertain_write(
            lambda: self._send("POST", f"{self._base}/events", body=payload, key=key)).json()))

    def _update_calendar_event(self, existing_id: str, body: dict[str, Any], key: str, proposal: Proposal,
                               time_changes: list[str] | None = None) -> dict[str, Any]:
        url = f"{self._base}/events/{quote(existing_id, safe='')}"

        def change() -> dict[str, Any]:
            if body.get("status") == "cancelled":
                # Graph lets only the organizer "cancel"; deleting works for every own event.
                uncertain_write(lambda: self._send("DELETE", url, key=key))
                return {"id": existing_id, "operation": "duplicate_updated", "time_changes": time_changes or []}
            answer = uncertain_write(lambda: self._send("PATCH", url, body=self._graph_body(body, key), key=key))
            return {**self._result(answer.json()), "operation": "duplicate_updated",
                    "time_changes": time_changes or []}

        return self._logged(proposal, key, change, "duplicate_updated")

    def _calendar_candidates(self, time_min: str, time_max: str) -> Iterator[CalendarOverlapEvent]:
        params = {"startDateTime": time_min, "endDateTime": time_max, "$top": "50",
                  "$select": "id,subject,body,location,start,end,isAllDay,isCancelled,webLink"}
        for item in self._pages(f"{self._base}/calendarView", params):
            try:
                event = GraphEvent.model_validate(item)
                if event.isCancelled:
                    continue
                yield CalendarOverlapEvent.model_validate({
                    "id": event.id, "summary": (event.subject or "")[:500],
                    "description": str((event.body or {}).get("content") or "")[:4000],
                    "location": str((event.location or {}).get("displayName") or "")[:1000] or None,
                    "htmlLink": event.webLink if (event.webLink or "").startswith("https://") else None,
                    "start": _neutral_time(event.start, event.isAllDay),
                    "end": _neutral_time(event.end, event.isAllDay)})
            except (ValidationError, ValueError, KeyError) as exc:
                raise ValueError(f"{self.label}: ungültige Antwort am Schlüsselpfad {exc}") from None

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


class MicrosoftTodo(GraphResource, ProviderWriter):
    """Tasks in a Microsoft To Do list; ``default`` is the built-in list „Aufgaben“."""

    service, label, role = "microsoft_todo", "Microsoft To Do", "tasks"
    _list_id: str | None = None

    def _list(self) -> str:
        if self.target != "default":
            return self.target
        if self._list_id is None:
            for item in self._pages("/me/todo/lists"):
                if item.get("wellknownListName") == "defaultList" and isinstance(item.get("id"), str):
                    self._list_id = item["id"]
                    break
            else:
                raise CalendarAccessError(f"{self.label}: Standardliste nicht gefunden")
        return self._list_id

    def _tasks(self) -> str:
        return f"/me/todo/lists/{quote(self._list(), safe='')}/tasks"

    def check_access(self) -> None:
        self.policy.run(lambda: self._send("GET", f"/me/todo/lists/{quote(self._list(), safe='')}"))

    def _task(self, item: dict[str, Any]) -> GraphTask:
        try:
            return GraphTask.model_validate(item)
        except ValidationError as exc:
            raise ValueError(f"{self.label}: ungültige Antwort am Schlüsselpfad {validation_path(exc)}") from exc

    def reconcile(self, key: str) -> dict[str, Any] | None:
        self.logger.event("INFO", self.service, "reconcile_started", call_id=key)
        for item in self._pages(self._tasks(), {"$expand": "linkedResources", "$top": "100"}):
            task = self._task(item)
            text = str((task.body or {}).get("content") or "")
            if f"[{key}]" in text or any(link.get("externalId") == key for link in task.linkedResources):
                return {"id": task.id}
        return None

    def _prepare(self, proposal: Proposal, key: str) -> PreparedWrite:
        if proposal.kind != ProposalKind.TASK:
            raise ValueError(f"{self.label} akzeptiert nur Aufgaben")
        payload: dict[str, Any] = {
            "title": proposal.title,
            "body": {"contentType": "text", "content": f"{proposal.description}\n\n[{key}]".strip()},
            "linkedResources": [{"applicationName": "Mailhelp", "displayName": "Mailhelp", "externalId": key}]}
        if isinstance(proposal.due, datetime):
            payload["dueDateTime"] = {"dateTime": proposal.due.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
                                      "timeZone": "UTC"}
        elif proposal.due is not None:
            payload["dueDateTime"] = {"dateTime": f"{proposal.due}T00:00:00", "timeZone": "UTC"}
        tasks = self._tasks()
        return PreparedWrite(lambda: self._logged(proposal, key, lambda: {"id": self._task(uncertain_write(
            lambda: self._send("POST", tasks, body=payload, key=key)).json()).id}))

    def fetch_active_tasks(self, *, strict: bool = False) -> list[TodoistTaskResponse]:
        cache_key = (self.service, self.target, "tasks")
        cached = None if strict else self._get_cached(cache_key)
        if cached is not None:
            return cached
        try:
            tasks = [TodoistTaskResponse(id=task.id, content=task.title[:500],
                                         description=str((task.body or {}).get("content") or "")[:4000])
                     for task in map(self._task, self._pages(self._tasks(), {"$filter": "status ne 'completed'",
                                                                             "$top": "100"}))]
        except Exception as exc:
            self.logger.event("WARNING", self.service, "fetch_tasks_failed", error=str(exc))
            if strict:
                raise
            return []
        self._set_cached(cache_key, tasks)
        return tasks
