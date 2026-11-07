"""Per-command lock acquisition times, scoped to the executing thread/context."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from contextvars import ContextVar
from time import perf_counter
from typing import Any

_WAITS: ContextVar[dict[str, float] | None] = ContextVar("command_lock_waits", default=None)


@contextmanager
def measure_lock_waits() -> Iterator[dict[str, float]]:
    waits = {"dialog_lock_wait_ms": 0.0, "store_lock_wait_ms": 0.0}
    token = _WAITS.set(waits)
    try:
        yield waits
    finally:
        _WAITS.reset(token)


@contextmanager
def measured_lock(lock: AbstractContextManager[Any], kind: str) -> Iterator[None]:
    started = perf_counter()
    with lock:
        waited = (perf_counter() - started) * 1000
        waits = _WAITS.get()
        if waits is not None:
            waits[f"{kind}_lock_wait_ms"] += waited
        yield
