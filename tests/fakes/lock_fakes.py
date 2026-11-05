"""Reproduce lock-order inversions between the store lock and a component lock."""
from __future__ import annotations

from collections.abc import Callable
from threading import Event, Thread, current_thread
from typing import Any

from mailhelp.storage import JsonStore


class ProbedStore(JsonStore):
    """Signals when the contending thread reaches a read of the store."""

    def __init__(self, directory) -> None:
        super().__init__(directory)
        self.contender: Thread | None = None
        self.reading = Event()

    def _probe(self) -> None:
        if current_thread() is self.contender:
            self.reading.set()

    def load(self, name: str, default: Any = None) -> Any:
        self._probe()
        return super().load(name, default)

    def load_model(self, name, model, default=None):
        self._probe()
        return super().load_model(name, model, default)


def finishes_while_store_lock_held(store: ProbedStore, contender: Callable[[], object],
                                   holder: Callable[[], object], timeout: float = 5) -> bool:
    """Run *contender* while another thread holds the store lock and then calls *holder*.

    This is the order of the deadlock of 4.0.0: the notification thread held the store
    lock and asked a component, a web thread held that component's own lock and waited
    for the store lock. With one lock order both calls finish.
    """
    done = Event()
    thread = Thread(target=contender, daemon=True)
    store.contender = thread

    def hold() -> None:
        with store.locked():
            thread.start()
            # With its own lock the contender now holds it and waits for the store.
            store.reading.wait(timeout=0.5)
            holder()
        done.set()

    Thread(target=hold, daemon=True).start()
    finished = done.wait(timeout)
    thread.join(timeout)
    return finished and not thread.is_alive()
