"""Idempotente Adapter für Todoist und Google Kalender."""
from __future__ import annotations
from typing import Any, Callable, Protocol
import time, traceback
import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from .models import Proposal, ProposalKind, ProposalStatus
from .adapter import PermanentError, RetryPolicy, UncertainWriteError, uncertain_write
from .logging import EventLogger, NullLogger


class IntegrationModel(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)


class TodoistTaskResponse(IntegrationModel):
    id: str | int
    description: str = ""
    url: str | None = None


class CalendarEventResponse(IntegrationModel):
    id: str = Field(min_length=1)
    htmlLink: str | None = None


class CalendarListResponse(IntegrationModel):
    items: list[CalendarEventResponse]


class ExternalWriter(Protocol):
    def reconcile(self, key: str) -> dict[str, Any] | None: ...
    def create(self, proposal: Proposal, key: str) -> dict[str, Any]: ...


def execute_confirmed(proposal: Proposal, writer: ExternalWriter, persist: Callable[[Proposal], None], test_mode: bool = False) -> tuple[Proposal, dict[str, Any]]:
    if proposal.status not in {ProposalStatus.CONFIRMED, ProposalStatus.WRITING, ProposalStatus.UNCERTAIN} or proposal.open_questions: raise ValueError("Schreiben erfordert vollständige, bestätigte Vorschlagsversion")
    if test_mode:
        persist(proposal)
        return proposal, {"simulation": True}
    key = f"mailhelp:{proposal.id}:v{proposal.version}"
    found = writer.reconcile(key)
    if found is not None:
        created = _with_external_result(proposal, found)
        persist(created)
        return created, found
    # A restart while an API request was in flight must never blindly repeat it.
    if proposal.status == ProposalStatus.WRITING:
        uncertain = proposal.model_copy(update={"status": ProposalStatus.UNCERTAIN})
        persist(uncertain)
        return uncertain, {}
    writing = proposal.model_copy(update={"status": ProposalStatus.WRITING})
    persist(writing)
    try: result = writer.create(writing, key)
    except (UncertainWriteError, httpx.TimeoutException, httpx.TransportError):
        uncertain = writing.model_copy(update={"status": ProposalStatus.UNCERTAIN})
        persist(uncertain)
        return uncertain, {}
    except (PermanentError, httpx.HTTPStatusError):
        failed = writing.model_copy(update={"status": ProposalStatus.FAILED})
        persist(failed)
        return failed, {}
    created = _with_external_result(writing, result)
    persist(created)
    return created, result


def _with_external_result(proposal: Proposal, result: dict[str, Any]) -> Proposal:
    external_id = result.get("id")
    if external_id is None or isinstance(external_id, bool) or not str(external_id):
        raise ValueError("Externe Integration: benötigter Schlüsselpfad id fehlt")
    link = result.get("url") or result.get("html_url") or result.get("htmlLink")
    return proposal.model_copy(update={
        "status": ProposalStatus.CREATED,
        "external_id": str(external_id) if external_id is not None else None,
        "external_link": str(link) if link is not None else None,
    })


class HttpWriter:
    def __init__(self, service: str, token: str, target: str, timeout: float = 30, transport: httpx.BaseTransport | None = None, policy: RetryPolicy | None = None, logger: EventLogger | None = None):
        if service not in {"todoist", "google_calendar"}: raise ValueError("Unbekannter Dienst")
        base = "https://api.todoist.com/rest/v2" if service == "todoist" else "https://www.googleapis.com/calendar/v3"
        self.service, self.target, self.client = service, target, httpx.Client(base_url=base, headers={"Authorization": f"Bearer {token}"}, timeout=timeout, transport=transport)
        self.policy = policy or RetryPolicy(0, 0, 0, lambda _delay: False)
        self.logger = logger or NullLogger()

    def reconcile(self, key: str) -> dict[str, Any] | None:
        self.logger.event("INFO", self.service, "reconcile_started", call_id=key)
        if self.service == "todoist":
            response = self.policy.run(lambda: self._get("/tasks", {"project_id": self.target}))
            items = self._validate_list(response, TodoistTaskResponse, "Todoist tasks")
            found = next((item for item in items if key in item.description), None)
            return found.model_dump() if found else None
        response = self.policy.run(lambda: self._get(f"/calendars/{self.target}/events", {"privateExtendedProperty": f"mailhelp_key={key}"}))
        try: items = CalendarListResponse.model_validate(response.json()).items
        except (ValueError, ValidationError) as exc: raise ValueError(f"Google Calendar events: ungültige Antwort am Schlüsselpfad {_path(exc)}") from exc
        return items[0].model_dump() if items else None

    def create(self, proposal: Proposal, key: str) -> dict[str, Any]:
        self.logger.event("INFO", self.service, "create_started", call_id=key, mail_id=proposal.source_mail_id, proposal_id=proposal.id)
        if self.service == "todoist":
            if proposal.kind != ProposalKind.TASK: raise ValueError("Todoist akzeptiert nur Aufgaben")
            url, body = "/tasks", {"content": proposal.title, "description": f"{proposal.description}\n\n[{key}]".strip(), "project_id": self.target}
            if proposal.due: body["due_datetime"] = proposal.due.isoformat()
        else:
            if proposal.kind != ProposalKind.EVENT: raise ValueError("Kalender akzeptiert nur Termine")
            url, body = f"/calendars/{self.target}/events", {"summary": proposal.title, "description": proposal.description, "start": {"dateTime": proposal.start.isoformat()}, "end": {"dateTime": proposal.end.isoformat()}, "extendedProperties": {"private": {"mailhelp_key": key}}}
        started = time.perf_counter()
        try:
            response = uncertain_write(lambda: self._post(url, body, key))
        except Exception as exc:
            self.logger.event("ERROR", self.service, "create_failed", call_id=key, mail_id=proposal.source_mail_id,
                              proposal_id=proposal.id, error=exc, stacktrace=traceback.format_exc(), duration_ms=round((time.perf_counter()-started)*1000, 3))
            raise
        model = TodoistTaskResponse if self.service == "todoist" else CalendarEventResponse
        try: result = model.model_validate(response.json())
        except (ValueError, ValidationError) as exc: raise ValueError(f"{self.service}: ungültige Antwort am Schlüsselpfad {_path(exc)}") from exc
        self.logger.event("INFO", self.service, "create_completed", call_id=key, mail_id=proposal.source_mail_id,
                          proposal_id=proposal.id, duration_ms=round((time.perf_counter()-started)*1000, 3), status=response.status_code)
        return result.model_dump()

    @staticmethod
    def _validate_list(response: httpx.Response, model: type[IntegrationModel], operation: str) -> list[IntegrationModel]:
        try:
            value = response.json()
            if not isinstance(value, list): raise ValueError("Antwort ist keine Liste")
            return [model.model_validate(item) for item in value]
        except (ValueError, ValidationError) as exc: raise ValueError(f"{operation}: ungültige Antwort am Schlüsselpfad {_path(exc)}") from exc

    def close(self) -> None: self.client.close()

    def _get(self, url: str, params: dict[str, Any]) -> httpx.Response:
        self.logger.event("DEBUG", self.service, "http_request", method="GET", url=url)
        response = self.client.get(url, params=params); response.raise_for_status(); return response

    def _post(self, url: str, body: dict[str, Any], key: str) -> httpx.Response:
        self.logger.event("DEBUG", self.service, "http_request", method="POST", url=url, call_id=key)
        response = self.client.post(url, json=body, headers={"X-Request-Id": key}); response.raise_for_status(); return response


def _path(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return ", ".join(".".join(str(value) for value in item["loc"]) or "<root>" for item in exc.errors(include_input=False))
    return "<json>"
