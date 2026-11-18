"""The readable state file of the central OAuth service with compare-and-swap writes."""
from __future__ import annotations

import json
import os
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path

from pydantic import ValidationError

from .models import AuthState

_NAME = "auth-state.json"


class StateConflict(RuntimeError):
    """The state changed since it was read; the caller reads again instead of overwriting."""


class StateDamaged(RuntimeError):
    """The state file cannot be read; nothing is guessed or reset silently."""


class StateFile:
    def __init__(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / _NAME
        self._lock = threading.RLock()

    def read(self) -> AuthState:
        if not self.path.exists():
            return AuthState()
        try:
            return AuthState.model_validate(json.loads(self.path.read_text(encoding="utf-8")))
        except (ValueError, ValidationError):
            raise StateDamaged("Zustand des Anmeldedienstes ist beschädigt") from None

    def write(self, state: AuthState, expected_revision: int) -> AuthState:
        """Store *state* as the next revision, only if nobody wrote since *expected_revision*."""
        with self._lock:
            if self.read().revision != expected_revision:
                raise StateConflict("Zustand inzwischen geändert")
            stored = state.model_copy(update={"revision": expected_revision + 1})
            descriptor, temporary = tempfile.mkstemp(dir=self.path.parent, prefix=f".{_NAME}.")
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    stream.write(stored.model_dump_json(indent=1) + "\n")
                os.replace(temporary, self.path)
            except BaseException:
                Path(temporary).unlink(missing_ok=True)
                raise
            return stored

    def update(self, change: Callable[[AuthState], AuthState]) -> AuthState:
        """Read, change and write under the lock of this process."""
        with self._lock:
            current = self.read()
            return self.write(change(current), current.revision)


__all__ = ["StateConflict", "StateDamaged", "StateFile"]
