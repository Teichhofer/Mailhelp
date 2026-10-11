"""Process-bound graceful stop handshake; never replayed after a restart."""
from __future__ import annotations

import secrets
from threading import RLock
from typing import Callable


class Lifecycle:
    def __init__(self, stop: Callable[[], None], authorize: Callable[[str], bool]):
        self.process = secrets.token_hex(16)
        self.stop, self.authorize = stop, authorize
        self.state = "running"
        self._key = None
        self._lock = RLock()

    def request(self, process: str, key: str, actor: str) -> Callable[[], None]:
        with self._lock:
            if process != self.process or not self.authorize(actor):
                raise ValueError("Veraltete oder nicht autorisierte Stopanforderung")
            if len(key) != 32 or any(c not in "0123456789abcdef" for c in key):
                raise ValueError("Ungültige Stopanforderung")
            if self._key is not None and self._key != key:
                raise ValueError("Beenden wurde bereits angefordert")
            self._key, self.state = key, "stop_requested"

        def after_response():
            with self._lock:
                if self.state == "stopping":
                    return
                if not self.authorize(actor):
                    self.state, self._key = "running", None
                    return
                self.state = "stopping"
                self.stop()
        return after_response
