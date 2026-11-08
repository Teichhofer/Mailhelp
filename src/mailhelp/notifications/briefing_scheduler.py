"""Local-time briefing slots with durable identities, retry dates and restart checkpoints."""
from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from threading import Lock
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from ..config import Settings
from ..storage import StateStore

STATE = "briefing_state"
Outcome = Literal["saved", "simulated", "skipped_empty", "uncertain", "failed"]
DONE = {"saved", "simulated", "skipped_empty"}


class BriefingRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    label: str
    mailbox: int
    scheduled_at: datetime
    window_start: datetime
    status: Literal["pending", "saved", "simulated", "skipped_empty", "uncertain", "failed"] = "pending"
    attempts: int = 0
    retry_at: datetime | None = None
    error: str | None = None
    account: str | None = None
    snapshot: dict[str, str] | None = None
    draft: dict = Field(default_factory=dict)


class BriefingState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    latest_day: date | None = None
    last_briefing_at: datetime | None = None
    runs: dict[str, BriefingRun] = Field(default_factory=dict)


def target_mailbox(settings: Settings) -> int:
    enabled = settings.imap.enabled_mailboxes()
    choice = settings.briefings.mailbox
    if choice == "default":
        return enabled[0].id
    if choice not in {box.id for box in enabled}:
        raise ValueError("Briefing-Postfach nicht mehr aktiv")
    return choice


class BriefingScheduler:
    """Ticked by the existing background thread; no network I/O under the store lock."""

    def __init__(self, store: StateStore, settings: Callable[[], Settings],
                 deliver: Callable[[BriefingRun, Callable[[], None]], Outcome],
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC),
                 report: Callable[[str, str], None] = lambda identity, status: None):
        self.store, self.settings, self.deliver = store, settings, deliver
        self.clock, self.report = clock, report
        self._lock = Lock()

    def _save(self, state: BriefingState) -> None:
        with self.store.locked():
            self.store.save(STATE, state.model_dump(mode="json"))

    def tick(self) -> None:
        if not self._lock.acquire(blocking=False):
            return
        try:
            self._tick()
        finally:
            self._lock.release()

    def _tick(self) -> None:
        cfg = self.settings()
        if not cfg.briefings.enabled:
            return
        now = self.clock()
        if now.tzinfo is None:
            raise ValueError("Briefing-Zeitpunkt benötigt eine Zeitzone")
        zone = ZoneInfo(cfg.timezone)
        local = now.astimezone(zone)
        state = self.store.load_model(STATE, BriefingState, BriefingState())
        if state.latest_day is not None and local.date() < state.latest_day:
            return  # A backwards clock never creates new runs on an already passed day.
        state.latest_day = local.date()
        mailbox = target_mailbox(cfg)
        for label in cfg.briefings.times:
            scheduled = datetime.combine(local.date(), time.fromisoformat(label), zone).astimezone(UTC)
            if scheduled > now:
                continue
            # The local date/time identity deliberately excludes target and timezone: changing
            # either setting never creates a second draft of an already handled slot.
            identity = hashlib.sha256(f"{local.date()}T{label}".encode()).hexdigest()[:24]
            if identity not in state.runs:
                start = state.last_briefing_at or datetime.combine(local.date(), time.min, zone).astimezone(UTC)
                state.runs[identity] = BriefingRun(id=identity, label=label, mailbox=mailbox,
                                                  scheduled_at=scheduled, window_start=min(start, scheduled))
        self._save(state)
        for run in sorted(state.runs.values(), key=lambda entry: entry.scheduled_at):
            if (run.status in DONE or run.scheduled_at > now or run.label not in cfg.briefings.times
                    or run.retry_at is not None and run.retry_at > now):
                continue
            self._attempt(state, run, now)

    def _attempt(self, state: BriefingState, run: BriefingRun, now: datetime) -> None:
        if run.attempts == 0 and state.last_briefing_at is not None:
            run.window_start = min(state.last_briefing_at, run.scheduled_at)
        run.status, run.retry_at, run.error = "pending", None, None
        run.attempts += 1
        self._save(state)
        try:
            result = self.deliver(run, lambda: self._save(state))
            if result not in {*DONE, "uncertain", "failed"}:
                raise ValueError("Unbekanntes Briefing-Ergebnis")
            run.status = result
        except Exception as exc:
            run.status = "uncertain" if run.draft.get("status") == "uncertain" else "failed"
            run.error = type(exc).__name__
        if run.status in DONE:
            if state.last_briefing_at is None or run.scheduled_at > state.last_briefing_at:
                state.last_briefing_at = run.scheduled_at
            run.snapshot = None  # Successful checkpoints contain no copied mail content.
        else:
            run.retry_at = now + timedelta(seconds=60)
        self._save(state)
        self.report(run.id, run.status)
