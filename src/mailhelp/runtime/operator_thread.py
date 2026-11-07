"""Telegram input and queued web commands beside the mail loop (Planung 3.6, Schritt 0.5).

The thread serves the dialog as soon as input arrives, so a web action no longer waits
for a whole mail batch with its language-model calls. The dialog itself is serialized
by its lock; see docs/Entkopplung-Web-und-Abruf.md.
"""
from __future__ import annotations

from collections.abc import Callable
from threading import Event, Thread


class OperatorThread(Thread):
    def __init__(self, serve: Callable[[], bool], wait: Callable[[float], bool], wake: Callable[[], None],
                 retry_seconds: float, idle_seconds: float):
        super().__init__(name="mailhelp-operator", daemon=True)
        # serve() handles pending input and reports whether Telegram answered normally;
        # wait() returns early when input or a web command arrives.
        self.serve, self.wait, self.wake = serve, wait, wake
        self.retry_seconds, self.idle_seconds = retry_seconds, idle_seconds
        self.stop_event = Event()
        # Set after every pass; the mail loop waits on it for a relevance decision.
        self.served = Event()

    def run(self) -> None:
        try:
            while not self.stop_event.is_set():
                succeeded = self.serve()
                self.served.set()
                if self.stop_event.is_set():
                    break
                if succeeded:
                    self.wait(min(self.idle_seconds, 0.1))
                else:
                    self.stop_event.wait(self.retry_seconds)
        finally:
            self.served.set()

    def stop(self) -> None:
        self.stop_event.set()
        self.wake()
        self.served.set()
