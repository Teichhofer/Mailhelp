"""Idempotente Adapter für Todoist und Google Kalender."""
from __future__ import annotations
from typing import Any, Callable, Protocol
import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from .models import Proposal, ProposalKind, ProposalStatus


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
    except (httpx.TimeoutException, httpx.TransportError):
        uncertain = writing.model_copy(update={"status": ProposalStatus.UNCERTAIN})
        persist(uncertain)
        return uncertain, {}
    except httpx.HTTPStatusError:
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
    def __init__(self, service: str, token: str, target: str, timeout: float = 30, transport: httpx.BaseTransport | None = None):
        if service not in {"todoist", "google_calendar"}: raise ValueError("Unbekannter Dienst")
        base = "https://api.todoist.com/rest/v2" if service == "todoist" else "https://www.googleapis.com/calendar/v3"
        self.service, self.target, self.client = service, target, httpx.Client(base_url=base, headers={"Authorization": f"Bearer {token}"}, timeout=timeout, transport=transport)

    def reconcile(self, key: str) -> dict[str, Any] | None:
        if self.service == "todoist":
            response = self.client.get("/tasks", params={"project_id": self.target}); response.raise_for_status()
            items = self._validate_list(response, TodoistTaskResponse, "Todoist tasks")
            found = next((item for item in items if key in item.description), None)
            return found.model_dump() if found else None
        response = self.client.get(f"/calendars/{self.target}/events", params={"privateExtendedProperty": f"mailhelp_key={key}"}); response.raise_for_status()
        try: items = CalendarListResponse.model_validate(response.json()).items
        except (ValueError, ValidationError) as exc: raise ValueError(f"Google Calendar events: ungültige Antwort am Schlüsselpfad {_path(exc)}") from exc
        return items[0].model_dump() if items else None

    def create(self, proposal: Proposal, key: str) -> dict[str, Any]:
        if self.service == "todoist":
            if proposal.kind != ProposalKind.TASK: raise ValueError("Todoist akzeptiert nur Aufgaben")
            url, body = "/tasks", {"content": proposal.title, "description": f"{proposal.description}\n\n[{key}]".strip(), "project_id": self.target}
            if proposal.due: body["due_datetime"] = proposal.due.isoformat()
        else:
            if proposal.kind != ProposalKind.EVENT: raise ValueError("Kalender akzeptiert nur Termine")
            url, body = f"/calendars/{self.target}/events", {"summary": proposal.title, "description": proposal.description, "start": {"dateTime": proposal.start.isoformat()}, "end": {"dateTime": proposal.end.isoformat()}, "extendedProperties": {"private": {"mailhelp_key": key}}}
        response = self.client.post(url, json=body, headers={"X-Request-Id": key}); response.raise_for_status()
        model = TodoistTaskResponse if self.service == "todoist" else CalendarEventResponse
        try: result = model.model_validate(response.json())
        except (ValueError, ValidationError) as exc: raise ValueError(f"{self.service}: ungültige Antwort am Schlüsselpfad {_path(exc)}") from exc
        return result.model_dump()

    @staticmethod
    def _validate_list(response: httpx.Response, model: type[IntegrationModel], operation: str) -> list[IntegrationModel]:
        try:
            value = response.json()
            if not isinstance(value, list): raise ValueError("Antwort ist keine Liste")
            return [model.model_validate(item) for item in value]
        except (ValueError, ValidationError) as exc: raise ValueError(f"{operation}: ungültige Antwort am Schlüsselpfad {_path(exc)}") from exc

    def close(self) -> None: self.client.close()


def _path(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return ", ".join(".".join(str(value) for value in item["loc"]) or "<root>" for item in exc.errors(include_input=False))
    return "<json>"
