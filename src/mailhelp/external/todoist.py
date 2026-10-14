"""Todoist task payloads, pagination and idempotency lookup."""
from __future__ import annotations

from datetime import datetime
from functools import partial
from typing import Any

from pydantic import ValidationError

from ..models import Proposal, ProposalKind
from .contracts import PreparedWrite, TodoistTaskListResponse, TodoistTaskResponse, validation_path
from .transport import HttpTransport


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
        return PreparedWrite(lambda: self._create_prepared(proposal, key, url, body))

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

