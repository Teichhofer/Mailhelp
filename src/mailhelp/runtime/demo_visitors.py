"""7.1 (D3): one private copy of the demo dataset per visitor session.

The area of a visitor is found only through the server-side session; no path, cookie value or form
field can name it. A start order is idempotent: the same key returns the same area, so a double click
or a repeated request never copies the mails twice.
"""
from __future__ import annotations

import hashlib
import shutil
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from ..persistence.storage import JsonStore
from .demo_dataset import install

VISITORS = "demo-visitors"
MAX_VISITORS = 50


class DemoLimitReached(RuntimeError):
    """Every demo area is in use; nothing of another visitor is removed to make room."""


class VisitorEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    area: str = Field(pattern=r"^[0-9a-f]{32}$")
    created_at: float


class VisitorState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = 1
    # Keyed by the SHA-256 of the session id; the id itself is never stored here.
    visitors: dict[str, VisitorEntry] = Field(default_factory=dict)
    # Start keys and the session hash they belong to.
    starts: dict[str, str] = Field(default_factory=dict)


def _hash(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()


class DemoVisitors:
    def __init__(self, store: JsonStore, root: Path, dataset: Path, *, max_visitors: int = MAX_VISITORS,
                 clock: Callable[[], float] = time.time) -> None:
        self.store, self.root, self.dataset = store, root, dataset
        self.max_visitors, self.clock = max_visitors, clock

    def _state(self) -> VisitorState:
        state = self.store.load_model(VISITORS, VisitorState, VisitorState())
        assert isinstance(state, VisitorState)
        return state

    def area(self, session_id: str) -> Path | None:
        """The store directory of this session's demo, or None before the start."""
        entry = self._state().visitors.get(_hash(session_id))
        path = self.root / entry.area if entry is not None else None
        return path if path is not None and path.is_dir() else None

    def full(self) -> bool:
        """Whether a new visitor would exceed the limit; a running start checks again under the lock."""
        return len(self._state().visitors) >= self.max_visitors

    def start(self, session_id: str, key: str) -> Path:
        owner = _hash(session_id)
        with self.store.locked():
            state = self._state()
            if key in state.starts and state.starts[key] != owner:
                raise ValueError("Dieser Startauftrag gehört zu einer anderen Sitzung.")
            entry = state.visitors.get(owner)
            if entry is not None and (self.root / entry.area).is_dir():
                return self.root / entry.area
            if entry is None and len(state.visitors) >= self.max_visitors:
                raise DemoLimitReached("Gerade sind alle Demo-Plätze belegt. Bitte später erneut versuchen.")
            area = uuid.uuid4().hex
            install(self.dataset, self.root / area)
            state.visitors[owner] = VisitorEntry(area=area, created_at=self.clock())
            state.starts[key] = owner
            self.store.save(VISITORS, state.model_dump(mode="json"))
            return self.root / area

    def reset(self, session_id: str, key: str) -> Path:
        """Replace only this session's area with a fresh copy of the dataset."""
        owner = _hash(session_id)
        with self.store.locked():
            state = self._state()
            entry = state.visitors.pop(owner, None)
            state.starts = {start: holder for start, holder in state.starts.items() if holder != owner}
            self.store.save(VISITORS, state.model_dump(mode="json"))
        if entry is not None:
            shutil.rmtree(self.root / entry.area, ignore_errors=True)
        return self.start(session_id, key)

    def cleanup(self, active_sessions: set[str]) -> int:
        """Remove areas of ended sessions and copies left by an interrupted start; returns the count."""
        alive = {_hash(session_id) for session_id in active_sessions}
        with self.store.locked():
            state = self._state()
            ended = [owner for owner in state.visitors if owner not in alive]
            for owner in ended:
                del state.visitors[owner]
            state.starts = {key: owner for key, owner in state.starts.items() if owner in state.visitors}
            self.store.save(VISITORS, state.model_dump(mode="json"))
            kept = {entry.area for entry in state.visitors.values()}
        removed = 0
        if self.root.is_dir():
            for path in self.root.iterdir():
                if path.name not in kept:
                    shutil.rmtree(path, ignore_errors=True)
                    removed += 1
        return removed
