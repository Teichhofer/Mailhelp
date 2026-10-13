"""Per-report limits around each actual provider call, including repairs."""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from ..analysis import Completer


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
