"""7.2: Google Tasks as a task target (Planung 7.2, 4).

Google Tasks keeps the day a task is planned for, never a time: ``due`` carries only the
date. Mailhelp therefore writes the confirmed day (in the configured zone) and keeps an
exact deadline readable in the notes. The operation key travels in the notes as
``[mailhelp:…]``; it is the only way to find an unclear write again. A missing key after an
unclear request is not proof that nothing was written, so a reconciliation that cannot read
the whole list, or finds the key twice, stays unclear instead of permitting a new write.
Removing a task is not offered: the API has no condition that protects a deletion against a
change made after the last read.
"""
from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import date, datetime
from functools import partial
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx
from pydantic import Field, ValidationError

from ..domain.proposal import Proposal, ProposalKind
from ..llm.adapter import RetryPolicy, uncertain_write
from ..logging import EventLogger, NullLogger
from .contracts import (
    AccessTokenProvider,
    AuthenticationError,
    ExternalUncertain,
    IntegrationModel,
    PreparedWrite,
    TargetAccessError,
    TodoistTaskResponse,
    validation_path,
)
from .provider import ProviderWriter
from .verification import EntryRead, task_facts

API = "https://tasks.googleapis.com/tasks/v1"
SCOPE = "https://www.googleapis.com/auth/tasks"
# Google's limits; a proposal (title ≤ 500, description ≤ 4000) stays below them with the deadline
# line and the key, so nothing is ever cut (pinned by a test).
TITLE_LIMIT, NOTES_LIMIT = 1024, 8192
# 100 pages of 100 tasks; a longer list is reported as incomplete instead of read forever.
MAX_PAGES = 100
DUE_NOTE = "Google Tasks übernimmt das Datum; die genaue Frist steht im Text."


class GoogleTask(IntegrationModel):
    id: str = Field(min_length=1)
    title: str = ""
    notes: str = ""
    status: str = "needsAction"
    due: str | None = None
    deleted: bool = False
    webViewLink: str | None = None


def _link(value: str | None) -> str | None:
    """Only a Google https link is shown; anything else in an answer is dropped."""
    if value and re.fullmatch(r"https://([a-z0-9-]+\.)*google\.com/[^\s<>\"']*", value):
        return value
    return None


class GoogleTaskList(IntegrationModel):
    id: str = Field(min_length=1)


def _reason(response: httpx.Response) -> str:
    """The structured reason of a Google error; never the message text."""
    try:
        body = response.json()
        errors = body["error"].get("errors") or [{}]
        details = body["error"].get("details") or [{}]
        return str(errors[0].get("reason") or details[0].get("reason") or "")
    except (ValueError, KeyError, TypeError, AttributeError, IndexError):
        return ""


class GoogleTasks(ProviderWriter):
    """Tasks in one Google Tasks list; ``@default`` is the account's first list."""

    service, label, role = "google_tasks", "Google Tasks", "tasks"
    supports_remove = False

    def __init__(self, token: AccessTokenProvider, target: str, timeout: float = 30,
                 transport: httpx.BaseTransport | None = None, policy: RetryPolicy | None = None,
                 logger: EventLogger | None = None, timezone: str = "Europe/Berlin") -> None:
        self.token, self.target, self.zone = token, target, ZoneInfo(timezone)
        self.client = httpx.Client(base_url=API, timeout=timeout, transport=transport, follow_redirects=False)
        self.policy = policy or RetryPolicy(0, 0, 0, lambda _delay: False)
        self.logger = logger or NullLogger()
        self._read_cache: dict[tuple[Any, ...], tuple[float, Any]] = {}

    def close(self) -> None:
        self.client.close()

    def _send(self, method: str, url: str, *, body: dict[str, Any] | None = None,
              params: dict[str, str] | None = None, key: str | None = None,
              allowed: frozenset[int] = frozenset()) -> httpx.Response:
        self.logger.event("DEBUG", self.service, "http_request", method=method, url=url, call_id=key)
        response = self.client.request(method, url, json=body, params=params,
                                       headers={"Authorization": f"Bearer {self.token.access_token()}"})
        if response.status_code in allowed:
            return response
        if response.status_code == 401:
            self.token.invalidate()
            self.logger.event("ERROR", self.service, "authentication_failed", status=401)
            raise AuthenticationError(f"{self.label}: Google hat den Zugriff abgelehnt; erneut anmelden")
        if response.status_code in {403, 404}:
            reason = _reason(response)
            self.logger.event("ERROR", self.service, "target_access_failed", status=response.status_code,
                              reason=reason)
            if reason in {"accessNotConfigured", "SERVICE_DISABLED"}:
                raise TargetAccessError(f"{self.label}: Die Google Tasks API ist im Google-Projekt nicht "
                                        "aktiviert", "api_disabled")
            if response.status_code == 403 and reason in {"insufficientPermissions", "ACCESS_TOKEN_SCOPE_INSUFFICIENT"}:
                raise TargetAccessError(f"{self.label}: Die Anmeldung erlaubt keine Aufgaben; mit "
                                        "Google-Tasks-Recht erneut anmelden", "forbidden")
            raise TargetAccessError(f"{self.label}: Liste nicht gefunden oder Berechtigung fehlt",
                                    "forbidden" if response.status_code == 403 else "not_found")
        response.raise_for_status()
        return response

    def _json(self, response: httpx.Response) -> dict[str, Any]:
        try:
            value = response.json()
        except ValueError as exc:
            raise ValueError(f"{self.label}: ungültige Antwort am Schlüsselpfad <json>") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{self.label}: ungültige Antwort am Schlüsselpfad <root>")
        return value

    def _task(self, item: Any) -> GoogleTask:
        try:
            return GoogleTask.model_validate(item)
        except ValidationError as exc:
            raise ValueError(f"{self.label}: ungültige Antwort am Schlüsselpfad {validation_path(exc)}") from exc

    def _list(self) -> str:
        return quote(self.target, safe="@")

    def _tasks_url(self) -> str:
        return f"/lists/{self._list()}/tasks"

    def _pages(self, params: dict[str, str]) -> Iterator[GoogleTask]:
        """Every task of the bound list; a list longer than ``MAX_PAGES`` pages is incomplete."""
        token: str | None = None
        seen: set[str] = set()
        for _page in range(MAX_PAGES):
            query = {**params, "maxResults": "100", **({"pageToken": token} if token else {})}
            page = self._json(self.policy.run(partial(self._send, "GET", self._tasks_url(), params=query)))
            items, token = page.get("items", []), page.get("nextPageToken")
            if not isinstance(items, list) or (token is not None and (not isinstance(token, str) or token in seen)):
                raise ValueError(f"{self.label}: ungültige Antwort am Schlüsselpfad nextPageToken")
            yield from map(self._task, items)
            if token is None:
                return
            seen.add(token)
        raise ExternalUncertain(f"{self.label}: Liste zu lang, um sie vollständig zu lesen")

    def check_access(self) -> None:
        self.policy.run(lambda: self._send("GET", f"/users/@me/lists/{self._list()}"))

    def account_binding(self) -> str:
        """The list's own id; for ``@default`` that is the account's list, never the alias."""
        try:
            return GoogleTaskList.model_validate(
                self._json(self._send("GET", f"/users/@me/lists/{self._list()}"))).id
        except ValidationError as exc:
            raise ValueError(f"{self.label}: ungültige Antwort am Schlüsselpfad {validation_path(exc)}") from exc

    def reconcile(self, key: str) -> dict[str, Any] | None:
        """The task carrying *key*, also when completed, hidden or deleted since; two are a conflict."""
        self.logger.event("INFO", self.service, "reconcile_started", call_id=key)
        found = [task for task in self._pages({"showCompleted": "true", "showHidden": "true", "showDeleted": "true"})
                 if f"[{key}]" in task.notes]
        if len(found) > 1:
            self.logger.event("ERROR", self.service, "reconcile_conflict", call_id=key, matches=len(found))
            raise ExternalUncertain(f"{self.label}: Vorgang mehrfach gefunden; bitte beim Anbieter prüfen")
        return None if not found else {"id": found[0].id, "htmlLink": _link(found[0].webViewLink)}

    def _day(self, due: date | datetime | None) -> date | None:
        """The confirmed day in the configured zone; a time zone change never moves it."""
        return due.astimezone(self.zone).date() if isinstance(due, datetime) else due

    def notes(self, proposal: Proposal, key: str) -> str:
        lines = [proposal.description.strip()]
        if isinstance(proposal.due, datetime):
            moment = proposal.due.astimezone(self.zone)
            lines.append(f"Frist: {moment:%d.%m.%Y, %H:%M} Uhr ({self.zone.key})")
        return "\n\n".join([*filter(None, lines), f"[{key}]"])

    def _prepare(self, proposal: Proposal, key: str) -> PreparedWrite:
        if proposal.kind != ProposalKind.TASK:
            raise ValueError(f"{self.label} akzeptiert nur Aufgaben")
        payload: dict[str, Any] = {"title": proposal.title, "notes": self.notes(proposal, key),
                                   "status": "needsAction"}
        day = self._day(proposal.due)
        if day is not None:
            payload["due"] = f"{day.isoformat()}T00:00:00.000Z"
        url = self._tasks_url()

        def create() -> dict[str, Any]:
            task = self._task(self._json(uncertain_write(lambda: self._send("POST", url, body=payload, key=key))))
            return {"id": task.id, "htmlLink": _link(task.webViewLink)}
        return PreparedWrite(lambda: self._logged(proposal, key, create), expected=self.expected_facts(proposal, key))

    def expected_facts(self, proposal: Proposal, key: str) -> dict[str, Any] | None:
        if proposal.kind != ProposalKind.TASK:
            return None
        return task_facts(proposal.title, self.notes(proposal, key), self._day(proposal.due), self.target)

    def read_entry(self, external_id: str) -> EntryRead | None:
        """The task read freshly in the bound list; completed still exists, deleted does not."""
        response = self._send("GET", f"{self._tasks_url()}/{quote(external_id, safe='')}",
                              allowed=frozenset({404, 410}))
        if response.status_code in {404, 410}:
            self.check_access()
            return None
        task = self._task(self._json(response))
        if task.deleted:
            return None
        facts = task_facts(task.title, task.notes, None, self.target)
        return EntryRead({**facts, "due": None if not task.due else task.due[:10]}, link=_link(task.webViewLink),
                         completed=task.status == "completed")

    def fetch_active_tasks(self, *, strict: bool = False) -> list[TodoistTaskResponse]:
        """Open tasks for the duplicate check; a failed read is never an empty list when *strict*."""
        cache_key = (self.service, self.target, "tasks")
        cached = None if strict else self._get_cached(cache_key)
        if cached is not None:
            return cached
        try:
            tasks = [TodoistTaskResponse(id=task.id, content=task.title[:500], description=task.notes[:4000],
                                         url=_link(task.webViewLink))
                     for task in self._pages({"showCompleted": "false"})]
        except Exception as exc:
            self.logger.event("WARNING", self.service, "fetch_tasks_failed", error=str(exc))
            if strict:
                raise
            return []
        self._set_cached(cache_key, tasks)
        return tasks
