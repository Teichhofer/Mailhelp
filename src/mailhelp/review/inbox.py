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
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from statistics import median
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

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
    timings: dict[str, float] = Field(default_factory=dict)
    acknowledged: bool = False


def command_payload(command: ReviewCommand | AdminCommand) -> dict[str, Any]:
    """Preserve the distinction between omitted edit fields and explicit deletion."""
    value = command.model_dump(mode="json")
    if isinstance(command, ReviewCommand) and command.patch is not None:
        value["patch"] = command.patch.model_dump(mode="json", exclude_unset=True)
    return value


def entry_payload(entry: CommandEntry) -> dict[str, Any]:
    value = entry.model_dump(mode="json")
    value["command"] = command_payload(entry.command)
    return value


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
        # Serialized with the store's own re-entrant lock, never a second one: the
        # notification thread reads the inbox while holding the store lock, and a web
        # page holding a separate inbox lock and waiting for the store deadlocked with it.
        self.store, self.wake, self.clock = store, wake, clock
        from .incoming import IncomingCommands
        self.changed: Callable[[], None] | None = None
        self._snapshot: tuple[CommandEntry, ...] = ()
        self.accepted: deque[tuple[str, float, bool]] = deque(maxlen=20)
        self._accept_events: deque[tuple[str, float, bool]] = deque()
        with store.locked():
            store.observe(COMMAND_INBOX, self._publish)
            self._load()  # Validate persisted state before publishing the original patch fields.
            self._publish(store.load(COMMAND_INBOX, {}))
            self.incoming = IncomingCommands(store.directory, lambda: MAX_QUEUED, clock)
            self.incoming.initialize(list(self._snapshot))

    def _publish(self, value: Any) -> None:
        self._snapshot = ()
        try:
            self._snapshot = tuple(CommandInboxState.model_validate(value or {}).entries)
        except ValidationError:
            pass  # Invalid authoritative state is rejected by _load before execution.

    def refresh(self) -> None:
        if self.changed is not None:
            self.changed()

    def drain(self) -> None:
        """Only the operator imports receipts; deletion follows the queue commit."""
        self.incoming.repair()
        for record in self.incoming.records():
            if record.entry.id in {entry.id for entry in self._snapshot}:
                current = next(entry for entry in self._snapshot if entry.id == record.entry.id)
                if record.entry != current:
                    self.incoming.publish(current)
                self.incoming.remove_incoming(record)
                continue
            imported, _ = self._submit(record.entry.command, None, original=record.entry)
            self.incoming.publish(imported)
            self.incoming.remove_incoming(record)
        self.refresh()

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
        if command.source.value == "web":
            existing = self.existing(command)
            if existing is not None:
                return existing, False
            return self.incoming.accept(command)
        return self._submit(command, None)

    def existing(self, command: ReviewCommand | AdminCommand) -> CommandEntry | None:
        for entry in self._snapshot:
            if entry.command.idempotency_key == command.idempotency_key:
                if command_payload(entry.command) != command_payload(command):
                    raise CommandConflict("Idempotenzschlüssel gehört zu einem anderen Befehl")
                return self.incoming.decorate(entry)
        return self.incoming.existing(command)

    def record_completed(self, command: ReviewCommand, result: ReviewResult) -> CommandEntry:
        """Record an already executed Telegram command; never enqueue it for execution."""
        entry, _ = self._submit(command, result)
        return entry

    def _submit(self, command: ReviewCommand | AdminCommand,
                result: ReviewResult | None, *, original: CommandEntry | None = None) -> tuple[CommandEntry, bool]:
        with self.store.locked():
            state = self._load()
            existing = next((entry for entry in state.entries
                             if entry.command.idempotency_key == command.idempotency_key), None)
            if existing is not None:
                if command_payload(existing.command) != command_payload(command):
                    raise CommandConflict("Idempotenzschlüssel gehört zu einem anderen Befehl")
                return existing, False
            if result is None and sum(entry.status == CommandStatus.QUEUED for entry in state.entries) >= MAX_QUEUED:
                raise CommandInboxFull("Zu viele wartende Befehle")
            entry = original or CommandEntry(id=secrets.token_hex(16), command=command,
                                            received_at=self.clock())
            if result is not None:
                entry.result, entry.finished_at = result, self.clock()
                entry.status = _finished_status(result)
            state.entries.append(entry)
            self._save(state)
        if self.wake is not None and result is None and original is None:
            self.wake()
        return entry, True

    def get(self, entry_id: str) -> CommandEntry | None:
        entry = next((entry for entry in self._snapshot if entry.id == entry_id), None)
        if entry is not None:
            return self.incoming.decorate(entry)
        record = self.incoming.receipt(entry_id)
        return self.incoming.decorate(record.entry) if record else None

    def queued(self) -> list[CommandEntry]:
        return [entry for entry in self._entries() if entry.status == CommandStatus.QUEUED]

    def counts(self) -> dict[CommandStatus, int]:
        """Entries per status; finished ones are kept for one day."""
        result: dict[CommandStatus, int] = {}
        for entry in self._entries():
            result[entry.status] = result.get(entry.status, 0) + 1
        return result

    def start(self, entry_id: str) -> None:
        """Mark the entry running; persisted before the command has any effect."""
        self.drain()
        self._update(entry_id, status=CommandStatus.RUNNING)

    def finish(self, entry_id: str, result: ReviewResult, *, timings: dict[str, float] | None = None) -> None:
        status = _finished_status(result)
        entry = self.get(entry_id)
        self._update(entry_id, status=status, result=result, finished_at=self.clock(),
                     timings={**(entry.timings if entry else {}), **(timings or {})})

    def note_acceptance(self, entry: CommandEntry, elapsed_ms: float, new: bool) -> None:
        sample = (entry.id, round(elapsed_ms, 3), not new)
        self.accepted.append(sample)
        self._accept_events.append(sample)

    def take_acceptances(self) -> list[tuple[str, float, bool]]:
        events = []
        while self._accept_events:
            events.append(self._accept_events.popleft())
        return events

    def acceptance_latencies(self) -> dict[str, float]:
        samples = [elapsed for _, elapsed, _ in self.accepted]
        return ({"count": len(samples), "median_ms": median(samples), "max_ms": max(samples)}
                if samples else {})

    def latencies(self) -> dict[str, float]:
        """Last 20 measured Web commands; exclude legacy/unmeasured entries."""
        samples = [entry.timings["queue_wait_ms"] for entry in self._entries()
                   if entry.command.source.value == "web" and "queue_wait_ms" in entry.timings][-20:]
        return ({"count": len(samples), "median_ms": median(samples), "max_ms": max(samples)}
                if samples else {})

    def recover(self, reconcile: Callable[[ReviewCommand | AdminCommand], ReviewResult],
                resume: Callable[[ReviewCommand | AdminCommand], ReviewResult] | None = None) -> int:
        """Reconcile entries interrupted while running; returns their number."""
        interrupted = [entry for entry in self._entries() if entry.status == CommandStatus.RUNNING]
        for entry in interrupted:
            recover = resume if resume is not None and self.incoming.receipt(entry.id) is not None else reconcile
            self.finish(entry.id, recover(entry.command))
        return len(interrupted)

    def _entries(self) -> list[CommandEntry]:
        entries = {entry.id: self.incoming.decorate(entry) for entry in self._snapshot}
        for record in self.incoming.records(quarantine=False):
            entries.setdefault(record.entry.id, self.incoming.decorate(record.entry))
        return sorted(entries.values(), key=lambda entry: (entry.received_at, entry.id))

    def _update(self, entry_id: str, **changes: object) -> None:
        from .incoming import requires_ack
        if not any(entry.id == entry_id for entry in self._snapshot):
            self.drain()
        with self.store.locked():
            state = self._load()
            cutoff = self.clock() - RETENTION
            # Finished entries are kept for a day so a repeated request still
            # receives its result, then they are removed.
            removed = [entry for entry in state.entries if entry.finished_at is not None
                       and entry.finished_at < cutoff and not requires_ack(self.incoming.decorate(entry))]
            state.entries = [entry for entry in state.entries if entry not in removed]
            for index, entry in enumerate(state.entries):
                if entry.id == entry_id:
                    state.entries[index] = entry.model_copy(update=changes)
            self.refresh()
            self._save(state)
            for entry in removed:
                self.incoming.forget(entry)
        updated = self.get(entry_id)
        if updated is not None:
            self.incoming.publish(updated)


__all__ = ["COMMAND_INBOX", "CommandConflict", "CommandEntry", "CommandInbox",
           "CommandInboxFull", "CommandInboxState", "CommandStatus", "FINISHED",
           "MAX_QUEUED", "RETENTION"]
