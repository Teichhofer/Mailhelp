"""Install activated connections only between mail cycles, never during processing."""
from __future__ import annotations

from abc import ABC, abstractmethod
from threading import Lock


class PendingConnections(ABC):
    area = ""

    def __init__(self, app, resources):
        self.app, self.resources = app, resources
        self.lock = Lock()
        self.pending = None

    def request(self, settings, secrets):
        with self.lock:
            self.pending = settings, secrets

    def apply_pending(self) -> None:
        with self.lock:
            pending, self.pending = self.pending, None
        if pending is None:
            return
        try:
            self._apply(pending)
        except Exception:
            with self.lock:
                if self.pending is None:
                    self.pending = pending
            self.app.logger.event("ERROR", self.area, "activation_failed")

    @abstractmethod
    def _apply(self, pending):
        """Build the new adapters and install them; on failure nothing is installed."""

    def close(self):
        self.resources.close()


__all__ = ["PendingConnections"]
