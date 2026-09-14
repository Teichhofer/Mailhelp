"""Idempotente Adapter für Todoist und Google Kalender."""
from __future__ import annotations
from typing import Any, Callable, Protocol
import httpx
from .models import Proposal, ProposalKind, ProposalStatus


class ExternalWriter(Protocol):
    def reconcile(self, key: str) -> dict[str, Any] | None: ...
    def create(self, proposal: Proposal, key: str) -> dict[str, Any]: ...


def execute_confirmed(proposal: Proposal, writer: ExternalWriter, persist: Callable[[Proposal], None], test_mode: bool = False) -> tuple[Proposal, dict[str, Any]]:
    if proposal.status != ProposalStatus.CONFIRMED or proposal.open_questions: raise ValueError("Schreiben erfordert vollständige, bestätigte Vorschlagsversion")
    if test_mode:
        persist(proposal)
        return proposal, {"simulation": True}
    key = f"mailhelp:{proposal.id}:v{proposal.version}"
    found = writer.reconcile(key)
    if found is not None:
        created = proposal.model_copy(update={"status": ProposalStatus.CREATED})
        persist(created)
        return created, found
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
    created = writing.model_copy(update={"status": ProposalStatus.CREATED})
    persist(created)
    return created, result


class HttpWriter:
    def __init__(self, service: str, token: str, target: str, timeout: float = 30, transport: httpx.BaseTransport | None = None):
        if service not in {"todoist", "google_calendar"}: raise ValueError("Unbekannter Dienst")
        base = "https://api.todoist.com/rest/v2" if service == "todoist" else "https://www.googleapis.com/calendar/v3"
        self.service, self.target, self.client = service, target, httpx.Client(base_url=base, headers={"Authorization": f"Bearer {token}"}, timeout=timeout, transport=transport)

    def reconcile(self, key: str) -> dict[str, Any] | None:
        if self.service == "todoist":
            response = self.client.get("/tasks", params={"project_id": self.target}); response.raise_for_status(); items = response.json()
            return next((item for item in items if key in item.get("description", "")), None)
        response = self.client.get(f"/calendars/{self.target}/events", params={"privateExtendedProperty": f"mailhelp_key={key}"}); response.raise_for_status()
        items = response.json().get("items", [])
        return items[0] if items else None

    def create(self, proposal: Proposal, key: str) -> dict[str, Any]:
        if self.service == "todoist":
            if proposal.kind != ProposalKind.TASK: raise ValueError("Todoist akzeptiert nur Aufgaben")
            url, body = "/tasks", {"content": proposal.title, "description": f"{proposal.description}\n\n[{key}]".strip(), "project_id": self.target}
            if proposal.due: body["due_datetime"] = proposal.due.isoformat()
        else:
            if proposal.kind != ProposalKind.EVENT: raise ValueError("Kalender akzeptiert nur Termine")
            url, body = f"/calendars/{self.target}/events", {"summary": proposal.title, "description": proposal.description, "start": {"dateTime": proposal.start.isoformat()}, "end": {"dateTime": proposal.end.isoformat()}, "extendedProperties": {"private": {"mailhelp_key": key}}}
        response = self.client.post(url, json=body, headers={"X-Request-Id": key}); response.raise_for_status(); return response.json()

    def close(self) -> None: self.client.close()
