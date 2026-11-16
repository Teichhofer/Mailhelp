"""Install activated connections only between mail cycles, never during processing."""
from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import ExitStack
from threading import Lock
from typing import Any

from ..config import Secrets, Settings

Pending = tuple[Settings, Secrets]


class PendingConnections(ABC):
    area = ""

    # app is the running Application; lower layers do not know its class.
    def __init__(self, app: Any, resources: ExitStack) -> None:
        self.app, self.resources = app, resources
        self.lock = Lock()
        self.pending: Pending | None = None

    def request(self, settings: Settings, secrets: Secrets) -> None:
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
    def _apply(self, pending: Pending) -> None:
        """Build the new adapters and install them; on failure nothing is installed."""

    def close(self) -> None:
        self.resources.close()


__all__ = ["PendingConnections"]
