"""Per-report limits around each actual provider call, including repairs."""
from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Event
from typing import TYPE_CHECKING, Any

from ..analysis import Completer
from ..openrouter import RateLimitExceeded
from .models import ReportStatus

if TYPE_CHECKING:
    from .service import ActivityService


class ReportPaused(Exception):
    """The report cannot authorize another model call right now."""


class BudgetedCompleter:
    def __init__(self, client: Completer):
        self.client = client
        self.guard: ContextVar[Callable[[], None]] = ContextVar("activity_guard", default=lambda: None)

    @contextmanager
    def limited(self, guard: Callable[[], None]) -> Iterator[None]:
        token = self.guard.set(guard)
        try:
            yield
        finally:
            self.guard.reset(token)

    def complete(self, *args: Any, **kwargs: Any) -> tuple[str, Any]:
        self.guard.get()()
        return self.client.complete(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        """Keep provider metrics and schema-validation reporting on the real client."""
        return getattr(self.client, name)


class ReportCalls:
    """A report's share of the per-minute budget and its hard limit, checked before every provider call."""

    def __init__(self, service: ActivityService, client: BudgetedCompleter, stop_event: Event,
                 settings: Callable[[], Any], per_minute: Callable[[], int], clock: Callable[[], float]):
        self.service, self.client, self.stop_event = service, client, stop_event
        # Read on every call: changed settings apply to the next model call.
        self.settings, self.per_minute, self.clock = settings, per_minute, clock
        self._calls: list[float] = []

    def wait_for_share(self) -> None:
        """Use at most the configured share of the per-minute budget."""
        share = self.settings().activity_report.max_share_of_llm_budget
        allowed = max(1, int(self.per_minute() * share))
        while True:
            now = self.clock()
            self._calls = [stamp for stamp in self._calls if now - stamp < 60]
            if len(self._calls) < allowed or self.stop_event.is_set():
                self._calls.append(now)
                return
            self.stop_event.wait(min(5.0, 60 - (now - self._calls[0])))

    def _reserve(self, report_id: str) -> None:
        """Count one provider call against the report, or pause it with the reason."""
        self.wait_for_share()
        with self.service.lock:
            current = self.service.store.load(report_id)
            if current is None or current.status in {ReportStatus.PAUSED, ReportStatus.CANCELLED}:
                raise ReportPaused()
            if self.stop_event.is_set() or not self.service.authorized(current):
                current.status = ReportStatus.PAUSED
                current.message = "Angehalten. Bitte mit gültiger Sitzung fortsetzen."
                self.service.store.save(current)
                raise ReportPaused()
            limit = self.settings().activity_report.max_llm_calls
            if current.counters.llm_calls >= limit:
                current.status = ReportStatus.PAUSED
                current.message = f"Höchstzahl von {limit} KI-Aufrufen erreicht."
                self.service.store.save(current)
                raise ReportPaused()
            current.counters.llm_calls += 1
            self.service.store.save(current)

    def call(self, call: Callable[[], Any], report_id: str | None = None) -> Any:
        """Wait for the report's budget share; the shared budget defers, it never fails a mail."""
        while True:
            if report_id is None:
                self.wait_for_share()
            try:
                def reserve() -> None:
                    if report_id is not None:
                        self._reserve(report_id)
                with self.client.limited(reserve):
                    return call()
            except RateLimitExceeded as exc:
                self.stop_event.wait(max(1.0, min(60.0, exc.next_allowed_at - time.time())))
                if self.stop_event.is_set():
                    raise
