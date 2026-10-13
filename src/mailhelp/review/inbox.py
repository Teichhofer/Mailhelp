"""Durable command queue from the web server to the main thread.

Web server threads never change review state themselves.  They submit a
command here and answer the browser at once; the main thread executes queued
commands in arrival order (before each mail, while idle and while waiting for
a relevance decision) and stores a short result without mail content.

* The same idempotency key never has a second effect: the stored entry and,
  once finished, its result are returned again.
* An entry is marked ``running`` before it is executed.  After a crash such an
  entry is reconciled against the current state, never executed blindly again.
* Finished entries are removed after a retention period.

Telegram updates keep their own ``telegram-inbox``: they carry Telegram
offsets and acknowledgements that web commands do not have.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from threading import Lock
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..configuration import AdminCommand
from ..storage import JsonStore
from .commands import ReviewCommand
from .results import REJECTED_STATUSES, ResultStatus, ReviewResult

COMMAND_INBOX = "command-inbox"
RETENTION = timedelta(days=1)
MAX_QUEUED = 50


class CommandStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    REJECTED = "rejected"
    FAILED = "failed"


FINISHED = frozenset({CommandStatus.DONE, CommandStatus.REJECTED, CommandStatus.FAILED})


def _finished_status(result: ReviewResult) -> CommandStatus:
    return (CommandStatus.FAILED if result.status == ResultStatus.FAILED
            else CommandStatus.REJECTED if result.status in REJECTED_STATUSES else CommandStatus.DONE)


class CommandEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-f0-9]{32}$")
    command: ReviewCommand | AdminCommand
    received_at: datetime
    status: CommandStatus = CommandStatus.QUEUED
    result: ReviewResult | None = None
    finished_at: datetime | None = None


class CommandInboxState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    entries: list[CommandEntry] = Field(default_factory=list)


class CommandConflict(ValueError):
    """The idempotency key was already used for a different command."""


class CommandInboxFull(RuntimeError):
    """Too many commands are waiting; the main thread is busy or stopped."""


def _now() -> datetime:
    return datetime.now(UTC)


class CommandInbox:
    """Thread-safe, durable and ordered queue of review commands."""

    def __init__(self, store: JsonStore, wake: Callable[[], None] | None = None,
                 clock: Callable[[], datetime] = _now):
        self.store, self.wake, self.clock = store, wake, clock
        self._lock = Lock()

    def _load(self) -> CommandInboxState:
        state = self.store.load_model(COMMAND_INBOX, CommandInboxState, CommandInboxState())
        assert isinstance(state, CommandInboxState)
        return state

    def _save(self, state: CommandInboxState) -> None:
        value = state.model_dump(mode="json")
        for entry, record in zip(state.entries, value["entries"], strict=False):
            if isinstance(entry.command, ReviewCommand) and entry.command.patch is not None:
                record["command"]["patch"] = entry.command.patch.model_dump(mode="json", exclude_unset=True)
        self.store.save(COMMAND_INBOX, value)

    def submit(self, command: ReviewCommand | AdminCommand) -> tuple[CommandEntry, bool]:
        """Queue *command*; returns the entry and whether it is new."""
        return self._submit(command, None)

    def record_completed(self, command: ReviewCommand, result: ReviewResult) -> CommandEntry:
        """Record an already executed Telegram command; never enqueue it for execution."""
        entry, _ = self._submit(command, result)
        return entry

    def _submit(self, command: ReviewCommand | AdminCommand,
                result: ReviewResult | None) -> tuple[CommandEntry, bool]:
        with self._lock:
            state = self._load()
            existing = next((entry for entry in state.entries
                             if entry.command.idempotency_key == command.idempotency_key), None)
            if existing is not None:
                if existing.command != command:
                    raise CommandConflict("Idempotenzschlüssel gehört zu einem anderen Befehl")
                return existing, False
            if result is None and sum(entry.status == CommandStatus.QUEUED for entry in state.entries) >= MAX_QUEUED:
                raise CommandInboxFull("Zu viele wartende Befehle")
            entry = CommandEntry(id=secrets.token_hex(16), command=command,
                                 received_at=self.clock())
            if result is not None:
                entry.result, entry.finished_at = result, self.clock()
                entry.status = _finished_status(result)
            state.entries.append(entry)
            self._save(state)
        if self.wake is not None and result is None:
            self.wake()
        return entry, True

    def get(self, entry_id: str) -> CommandEntry | None:
        with self._lock:
            return next((entry for entry in self._load().entries if entry.id == entry_id), None)

    def queued(self) -> list[CommandEntry]:
        with self._lock:
            return [entry for entry in self._load().entries if entry.status == CommandStatus.QUEUED]

    def counts(self) -> dict[CommandStatus, int]:
        """Entries per status; finished ones are kept for one day."""
        result: dict[CommandStatus, int] = {}
        for entry in self._entries():
            result[entry.status] = result.get(entry.status, 0) + 1
        return result

    def start(self, entry_id: str) -> None:
        """Mark the entry running; persisted before the command has any effect."""
        self._update(entry_id, status=CommandStatus.RUNNING)

    def finish(self, entry_id: str, result: ReviewResult) -> None:
        status = _finished_status(result)
        self._update(entry_id, status=status, result=result, finished_at=self.clock())

    def recover(self, reconcile: Callable[[ReviewCommand | AdminCommand], ReviewResult]) -> int:
        """Reconcile entries interrupted while running; returns their number."""
        interrupted = [entry for entry in self._entries() if entry.status == CommandStatus.RUNNING]
        for entry in interrupted:
            self.finish(entry.id, reconcile(entry.command))
        return len(interrupted)

    def _entries(self) -> list[CommandEntry]:
        with self._lock:
            return list(self._load().entries)

    def _update(self, entry_id: str, **changes: object) -> None:
        with self._lock:
            state = self._load()
            cutoff = self.clock() - RETENTION
            # Finished entries are kept for a day so a repeated request still
            # receives its result, then they are removed.
            state.entries = [entry for entry in state.entries
                             if entry.finished_at is None or entry.finished_at >= cutoff]
            for index, entry in enumerate(state.entries):
                if entry.id == entry_id:
                    state.entries[index] = entry.model_copy(update=changes)
            self._save(state)


__all__ = ["COMMAND_INBOX", "CommandConflict", "CommandEntry", "CommandInbox",
           "CommandInboxFull", "CommandInboxState", "CommandStatus", "FINISHED",
           "MAX_QUEUED", "RETENTION"]
