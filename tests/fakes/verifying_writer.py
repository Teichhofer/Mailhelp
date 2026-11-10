"""A simulated task provider whose entries can be written once and read back (5.2, V2).

Synthetic data only; no network. Each read follows an optional script: ``"entry"``
returns the stored entry, ``None`` an invisible one, a dict overrides read facts and
an exception is raised as the provider's read error.
"""
from __future__ import annotations

from typing import Any

import httpx

from mailhelp.external.contracts import PreparedWrite, TargetWriter
from mailhelp.external.verification import EntryRead, task_facts
from mailhelp.llm.adapter import UncertainWriteError


class SimulatedProvider:
    def __init__(self) -> None:
        self.entries: dict[str, dict[str, Any]] = {}
        self.by_key: dict[str, dict[str, Any]] = {}
        self.writes: list[str] = []
        self.reads: list[str] = []


class VerifyingWriter(TargetWriter):
    service, role, label = "todoist", "tasks", "Simulierte Aufgabenliste"

    def __init__(self, provider: SimulatedProvider, *, target: str = "Inbox", account: str = "konto-1",
                 script: list[Any] | None = None, unclear_write: bool = False, plain: bool = True):
        self.provider, self.target, self.account = provider, target, account
        self.script, self.unclear_write, self.plain = list(script or []), unclear_write, plain
        self.on_read = lambda: None

    def check_access(self) -> None:
        return None

    def close(self) -> None:
        return None

    def reconcile(self, key: str) -> dict[str, Any] | None:
        return self.provider.by_key.get(key)

    def account_binding(self) -> str:
        return self.account

    def expected_facts(self, proposal, key: str) -> dict[str, Any] | None:
        if not self.plain:
            return None
        return task_facts(proposal.title, f"{proposal.description}\n\n[{key}]".strip(), proposal.due, self.target)

    def prepare(self, proposal, key: str) -> PreparedWrite:
        expected = self.expected_facts(proposal, key)
        return PreparedWrite(lambda: self._write(key, expected, proposal), expected=expected)

    def _write(self, key: str, expected: dict[str, Any] | None, proposal) -> dict[str, Any]:
        external_id = f"t{len(self.provider.writes) + 1}"
        self.provider.writes.append(key)
        self.provider.entries[external_id] = dict(expected or {"title": proposal.title})
        self.provider.by_key[key] = {"id": external_id, "url": f"https://aufgaben.example.invalid/{external_id}"}
        if self.unclear_write:
            raise UncertainWriteError("Verbindung nach dem Schreiben abgebrochen")
        return dict(self.provider.by_key[key])

    def read_entry(self, external_id: str) -> EntryRead | None:
        self.provider.reads.append(external_id)
        self.on_read()
        outcome = self.script.pop(0) if self.script else "entry"
        if isinstance(outcome, Exception):
            raise outcome
        stored = self.provider.entries.get(external_id)
        if outcome is None or stored is None:
            return None
        return EntryRead({**stored, **(outcome if isinstance(outcome, dict) else {})})


def provider_reads(request, posted: dict[str, Any]):
    """Answer the 5.2 reads of the real HTTP adapters from what was actually posted; else ``None``.

    The account binding (Todoist ``/user``, Google calendar resource) and the fresh read of the
    written entry by id; a Todoist answer carries the due object like the real service.
    """
    path = request.url.path
    if request.method != "GET":
        return None
    if path == "/api/v1/user":
        return httpx.Response(200, json={"id": "synthetic-user"})
    if path.startswith("/calendar/v3/calendars/") and path.count("/") == 4:
        return httpx.Response(200, json={"id": "owner@example.test"})
    written = posted.get("id")
    if written is not None and path == f"/api/v1/tasks/{written}":
        due = posted.get("due_date") or posted.get("due_datetime")
        return httpx.Response(200, json={**posted, "due": None if due is None else {"date": due}})
    if written is not None and path.endswith(f"/events/{written}"):
        return httpx.Response(200, json=posted)
    return None
