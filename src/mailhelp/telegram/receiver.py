"""Responsive Telegram input: a receiver thread with a durable inbox.

Mail analysis can take minutes.  Polling Telegram only between analysis
cycles left button presses unanswered for that long, so Telegram showed a
spinner and the bot looked dead.  The receiver thread long-polls Telegram
continuously, acknowledges every button press immediately and stores each
update in the durable inbox *before* the next ``getUpdates`` call confirms it
to Telegram, so a crash cannot lose input.

The receiver never touches mail, proposal or dialog state.  The main thread
remains the only one that processes updates (between mails and while idle),
which keeps every write to the state files single-threaded.
"""
from __future__ import annotations

import time
from threading import Event, Lock, Thread
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from ..logging import EventLogger
from ..storage import JsonStore

INBOX = "telegram-inbox"
ACKNOWLEDGEMENT = "Eingegangen – wird bearbeitet …"


class InboxEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    update: dict[str, Any]
    # The receiver already stopped Telegram's loading indicator.
    acknowledged: bool = False
    # Failed processing attempts and the earliest next attempt (Unix time).
    attempts: int = Field(default=0, ge=0)
    not_before: float | None = None

    def ready(self, now: float) -> bool:
        return self.not_before is None or self.not_before <= now

    @property
    def update_id(self) -> int:
        return self.update["update_id"]


class InboxState(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[1] = 1
    entries: list[InboxEntry] = Field(default_factory=list)


def update_id(raw: Any) -> int | None:
    """The integer update id of a raw update, or None if it has none."""
    value = raw.get("update_id") if isinstance(raw, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


class TelegramInbox:
    """Durable, ordered and thread-safe queue of received Telegram updates."""

    def __init__(self, store: JsonStore):
        self.store = store
        self._lock = Lock()
        self._arrived = Event()

    def _load(self) -> InboxState:
        state = self.store.load_model(INBOX, InboxState, InboxState())
        assert isinstance(state, InboxState)
        return state

    def add(self, updates: list[dict[str, Any]], acknowledged: set[int]) -> None:
        """Persist new updates in update order; already stored ids are ignored."""
        with self._lock:
            state = self._load()
            known = {entry.update_id for entry in state.entries}
            for raw in updates:
                identifier = update_id(raw)
                if identifier is not None and identifier not in known:
                    known.add(identifier)
                    state.entries.append(InboxEntry(update=raw, acknowledged=identifier in acknowledged))
            state.entries.sort(key=lambda entry: entry.update_id)
            self.store.save(INBOX, state.model_dump(mode="json"))
        self._arrived.set()

    def pending(self) -> list[InboxEntry]:
        with self._lock:
            return list(self._load().entries)

    def remove(self, identifier: int) -> None:
        with self._lock:
            state = self._load()
            state.entries = [entry for entry in state.entries if entry.update_id != identifier]
            self.store.save(INBOX, state.model_dump(mode="json"))

    def record_failure(self, identifier: int, retry_seconds: float) -> int:
        """Count a failed attempt and delay the next one; returns the attempt count."""
        with self._lock:
            state = self._load()
            attempts = 0
            for entry in state.entries:
                if entry.update_id == identifier:
                    entry.attempts += 1
                    attempts = entry.attempts
                    entry.not_before = time.time() + retry_seconds * attempts
            self.store.save(INBOX, state.model_dump(mode="json"))
            return attempts

    def next_offset(self) -> int:
        """Telegram offset that confirms every stored update."""
        entries = self.pending()
        return entries[-1].update_id + 1 if entries else 0

    def wait(self, timeout: float) -> bool:
        """Wait until updates arrive (or wake() is called); True if woken."""
        woken = self._arrived.wait(timeout)
        # Cleared before the caller reads pending(): an update stored after
        # this point sets the event again and is picked up by the next wait.
        self._arrived.clear()
        return woken

    def wake(self) -> None:
        self._arrived.set()


class _UpdateSource(Protocol):
    def poll(self, offset: int, timeout: int | None = None) -> list[dict[str, Any]]: ...
    def answer_callback(self, callback_id: str, text: str) -> None: ...


class TelegramReceiver(Thread):
    """Long-poll Telegram, acknowledge button presses and fill the inbox."""

    def __init__(self, telegram: _UpdateSource, inbox: TelegramInbox, offset: int,
                 logger: EventLogger, error_backoff_seconds: float):
        # Daemon: a long-poll in flight must not keep a stopping process alive.
        super().__init__(name="telegram-receiver", daemon=True)
        self.telegram, self.inbox, self.offset = telegram, inbox, offset
        self.logger, self.stop_event = logger, Event()
        self.error_backoff_seconds = error_backoff_seconds

    def stop(self) -> None:
        """Stop after the current long-poll and wake a main thread waiting on the inbox."""
        self.stop_event.set()
        self.inbox.wake()

    def run(self) -> None:
        self.logger.event("INFO", "telegram", "receiver_started", offset=self.offset)
        while not self.stop_event.is_set():
            if not self.receive_once():
                self.stop_event.wait(self.error_backoff_seconds)
        self.logger.event("INFO", "telegram", "receiver_stopped", offset=self.offset)

    def receive_once(self) -> bool:
        """One long-poll; returns False after an error that warrants a backoff."""
        try:
            updates = self.telegram.poll(self.offset)
        except Exception as exc:
            if not self.stop_event.is_set():
                self.logger.event("ERROR", "telegram", "receiver_poll_failed",
                                  error_class=type(exc).__name__)
            return False
        valid = [raw for raw in updates if update_id(raw) is not None]
        if len(valid) != len(updates):
            self.logger.event("WARNING", "telegram", "receiver_invalid_update",
                              count=len(updates) - len(valid), reason="missing_update_id")
        if not valid:
            return True
        acknowledged = {identifier for raw in valid
                        if (identifier := self._acknowledge(raw)) is not None}
        try:
            self.inbox.add(valid, acknowledged)
        except Exception as exc:
            # Keep the offset: Telegram redelivers these updates next time.
            self.logger.event("ERROR", "telegram", "receiver_inbox_failed",
                              error_class=type(exc).__name__)
            return False
        self.offset = max(self.offset, max(update_id(raw) for raw in valid) + 1)  # type: ignore[type-var]
        self.logger.event("INFO", "telegram", "receiver_updates_stored",
                          count=len(valid), acknowledged=len(acknowledged), next_offset=self.offset)
        return True

    def _acknowledge(self, raw: dict[str, Any]) -> int | None:
        """Stop the loading indicator at once; the action follows from the inbox."""
        callback = raw.get("callback_query")
        callback_id = callback.get("id") if isinstance(callback, dict) else None
        if not isinstance(callback_id, str):
            return None
        try:
            self.telegram.answer_callback(callback_id, ACKNOWLEDGEMENT)
        except Exception as exc:
            self.logger.event("WARNING", "telegram", "receiver_acknowledgement_failed",
                              error_class=type(exc).__name__)
            return None
        return update_id(raw)


__all__ = ["ACKNOWLEDGEMENT", "INBOX", "InboxEntry", "InboxState", "TelegramInbox",
           "TelegramReceiver", "update_id"]
