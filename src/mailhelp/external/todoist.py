"""Todoist task payloads, pagination and idempotency lookup."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any
from urllib.parse import quote

from pydantic import ValidationError

from ..models import Proposal, ProposalKind
from .contracts import (
    IntegrationModel,
    PreparedWrite,
    TodoistTaskListResponse,
    TodoistTaskResponse,
    validation_path,
)
from .transport import HttpTransport
from .verification import EntryRead, task_facts

# A task completed before its check is looked up among recently completed ones (5.2).
COMPLETED_WINDOW = timedelta(days=14)
COMPLETED_PAGES = 10


class TodoistTaskRead(IntegrationModel):
    """One task as read for verification; unknown fields are ignored."""

    id: str | int
    content: str = ""
    description: str = ""
    project_id: str | int
    due: dict[str, Any] | None = None
    checked: bool = False
    is_completed: bool = False
    is_deleted: bool = False
    url: str | None = None


class TodoistCompletedPage(IntegrationModel):
    items: list[dict[str, Any]]
    next_cursor: str | None = None


class TodoistUser(IntegrationModel):
    id: str | int


def _due_value(due: dict[str, Any] | None) -> str | None:
    """API v1 keeps a time point in ``date``; older answers used ``datetime``."""
    if due is None:
        return None
    value = due.get("datetime") or due.get("date")
    return None if value is None else str(value)


def _now() -> datetime:
    return datetime.now(UTC)


class TodoistOperations(HttpTransport):
    def _reconcile_todoist(self, key: str) -> dict[str, Any] | None:
        cursor = None
        seen_cursors: set[str] = set()
        while True:
            params = {"project_id": self.target}
            if cursor is not None:
                params["cursor"] = cursor
            response = self.policy.run(partial(self._get, "/tasks", params))
            try: page = TodoistTaskListResponse.model_validate(response.json())
            except (ValueError, ValidationError) as exc:
                raise ValueError(f"Todoist tasks: ungültige Antwort am Schlüsselpfad {validation_path(exc)}") from exc
            found = next((item for item in page.results if f"[{key}]" in item.description), None)
            if found is not None:
                return found.model_dump()
            cursor = page.next_cursor
            if cursor is None:
                return None
            if not cursor or cursor in seen_cursors:
                raise ValueError("Todoist tasks: ungültige Antwort am Schlüsselpfad next_cursor")
            seen_cursors.add(cursor)

    def _prepare_todoist(self, proposal: Proposal, key: str) -> PreparedWrite:
        if proposal.kind != ProposalKind.TASK: raise ValueError("Todoist akzeptiert nur Aufgaben")
        url, body = "/tasks", {"content": proposal.title,
                               "description": f"{proposal.description}\n\n[{key}]".strip(),
                               "project_id": self.target}
        if isinstance(proposal.due, datetime):
            body["due_datetime"] = proposal.due.isoformat()
        elif proposal.due is not None:
            body["due_date"] = proposal.due.isoformat()
        return PreparedWrite(lambda: self._create_prepared(proposal, key, url, body),
                             expected=self._todoist_expected(proposal, key))

    def _todoist_expected(self, proposal: Proposal, key: str) -> dict[str, Any] | None:
        if proposal.kind != ProposalKind.TASK:
            return None
        return task_facts(proposal.title, f"{proposal.description}\n\n[{key}]".strip(), proposal.due, self.target)

    def _todoist_account(self) -> str:
        response = self._get("/user", {})
        try: return str(TodoistUser.model_validate(response.json()).id)
        except (ValueError, ValidationError) as exc:
            raise ValueError(f"Todoist user: ungültige Antwort am Schlüsselpfad {validation_path(exc)}") from exc

    def _read_todoist(self, external_id: str) -> EntryRead | None:
        """A fresh read by id; a 404 counts only while the bound project is reachable."""
        url = f"/tasks/{quote(external_id, safe='')}"
        self.logger.event("DEBUG", self.service, "http_request", method="GET", url=url)
        response = self.client.get(url, headers=self._auth_headers())
        if response.status_code == 404:
            self.check_access()
            return self._completed_todoist(external_id)
        self._raise_for_status(response)
        try: task = TodoistTaskRead.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise ValueError(f"Todoist task: ungültige Antwort am Schlüsselpfad {validation_path(exc)}") from exc
        return None if task.is_deleted else self._task_read(task)

    def _task_read(self, task: TodoistTaskRead) -> EntryRead:
        facts = {**task_facts(task.content, task.description, None, str(task.project_id)),
                 "due": _due_value(task.due)}
        return EntryRead(facts, link=task.url, completed=task.checked or task.is_completed)

    def _completed_todoist(self, external_id: str) -> EntryRead | None:
        """Done is not missing: look for the task among recently completed ones of the project."""
        now = _now()
        params: dict[str, Any] = {"project_id": self.target, "since": (now - COMPLETED_WINDOW).isoformat(),
                                  "until": (now + timedelta(minutes=1)).isoformat()}
        for _page in range(COMPLETED_PAGES):
            response = self._get("/tasks/completed/by_completion_date", params)
            try:
                page = TodoistCompletedPage.model_validate(response.json())
                match = next((item for item in page.items if str(item.get("id")) == external_id), None)
                task = None if match is None else TodoistTaskRead.model_validate({**match, "checked": True})
            except (ValueError, ValidationError) as exc:
                raise ValueError("Todoist completed tasks: ungültige Antwort am Schlüsselpfad "
                                 f"{validation_path(exc)}") from exc
            if task is not None:
                return None if task.is_deleted else self._task_read(task)
            if not page.next_cursor:
                return None
            params["cursor"] = page.next_cursor
        return None

    def fetch_active_tasks(self, *, strict: bool = False) -> list[TodoistTaskResponse]:
        """Fetch active tasks in configured project with caching and graceful fallback."""
        if self.service != "todoist":
            return []
        cache_key = (self.service, self.target, "tasks")
        cached = None if strict else self._get_cached(cache_key)
        if cached is not None:
            return cached

        tasks: list[TodoistTaskResponse] = []
        cursor = None
        seen_cursors: set[str] = set()
        try:
            while True:
                params = {"project_id": self.target}
                if cursor is not None:
                    params["cursor"] = cursor
                response = self.policy.run(partial(self._get, "/tasks", params))
                page = TodoistTaskListResponse.model_validate(response.json())
                tasks.extend(page.results)
                cursor = page.next_cursor
                if cursor is None or cursor in seen_cursors:
                    break
                seen_cursors.add(cursor)
            self._set_cached(cache_key, tasks)
            return tasks
        except Exception as exc:
            if strict:
                raise
            self.logger.event("WARNING", self.service, "fetch_tasks_failed", error=str(exc))
            return []

