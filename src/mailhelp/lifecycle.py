"""Process-bound graceful stop handshake; never replayed after a restart.

States: ``running`` → ``stop_requested`` (accepted, answer still being sent) →
``stopping`` (application.stop() called) → ``stopped`` (run loop has finished).
A signal (SIGINT/SIGTERM) uses the same ``application.stop`` and ends in
``stopped`` as well.  Every transition is logged with the process identifier.
"""
from __future__ import annotations

import secrets
from collections.abc import Callable
from threading import RLock


class Lifecycle:
    def __init__(self, stop: Callable[[], None], authorize: Callable[[str], bool],
                 log: Callable[[str, str], None] = lambda state, process: None):
        self.process = secrets.token_hex(16)
        self.stop, self.authorize, self.log = stop, authorize, log
        self.state = "running"
        self._key: str | None = None
        self._lock = RLock()

    def _set(self, state: str) -> None:
        self.state = state
        self.log(state, self.process)

    def request(self, process: str, key: str, actor: str) -> Callable[[], None]:
        with self._lock:
            if process != self.process or not self.authorize(actor):
                raise ValueError("Veraltete oder nicht autorisierte Stopanforderung")
            if len(key) != 32 or any(c not in "0123456789abcdef" for c in key):
                raise ValueError("Ungültige Stopanforderung")
            if self._key is not None and self._key != key:
                raise ValueError("Beenden wurde bereits angefordert")
            self._key = key
            self._set("stop_requested")

        def after_response() -> None:
            with self._lock:
                if self.state != "stop_requested":
                    return
                if not self.authorize(actor):
                    self._key = None
                    self._set("running")
                    return
                self._set("stopping")
                self.stop()
        return after_response

    def finished(self) -> None:
        """The run loop has ended (after a web stop or a signal)."""
        with self._lock:
            if self.state != "stopped":
                self._set("stopped")
