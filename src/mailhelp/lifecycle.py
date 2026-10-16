"""Process-bound graceful stop/restart handshake; never replayed after a restart.

States: ``running`` → ``stop_requested`` (accepted, answer still being sent) →
``stopping`` (application.stop() called) → ``stopped`` (run loop has finished).
A signal (SIGINT/SIGTERM) uses the same ``application.stop`` and ends in
``stopped`` as well.  Every transition is logged with the process identifier.
A confirmed restart uses ``restart_requested`` → ``restarting`` → ``stopped``;
the CLI replaces the process only after the run and its resource context finish.
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
        self.restart_requested = False
        self._key: str | None = None
        self._restart_action = False
        self._lock = RLock()

    def _set(self, state: str) -> None:
        self.state = state
        self.log(state, self.process)

    def request(self, process: str, key: str, actor: str, *, restart: bool = False) -> Callable[[], None]:
        with self._lock:
            if process != self.process or not self.authorize(actor):
                raise ValueError("Veraltete oder nicht autorisierte Stopanforderung")
            if len(key) != 32 or any(c not in "0123456789abcdef" for c in key):
                raise ValueError("Ungültige Stopanforderung")
            if self._key is not None and (self._key != key or self._restart_action != restart):
                raise ValueError("Beenden wurde bereits angefordert")
            if self._key is None:
                self._key, self._restart_action = key, restart
                self._set("restart_requested" if restart else "stop_requested")

        def after_response() -> None:
            with self._lock:
                if (self.state != ("restart_requested" if restart else "stop_requested")
                        or self._key != key):
                    return
                if not self.authorize(actor):
                    self._key = None
                    self._set("running")
                    return
                self.restart_requested = restart
                self._set("restarting" if restart else "stopping")
                self.stop()
        return after_response

    def finished(self) -> None:
        """The run loop has ended (after a web stop or a signal)."""
        with self._lock:
            if self.state != "stopped":
                self._set("stopped")
