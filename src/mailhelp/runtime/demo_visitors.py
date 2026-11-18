"""7.1 (D3): one private copy of the demo dataset per visitor session.

The area of a visitor is found only through the server-side session; no path, cookie value or form
field can name it. A start order is idempotent: the same key returns the same area, so a double click
or a repeated request never copies the mails twice.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from ..i18n import Locale
from ..persistence.storage import JsonStore
from .demo_dataset import DATASETS, DemoDatasetError, install, packaged

VISITORS = "demo-visitors"
MAX_VISITORS = 50


class DemoLimitReached(RuntimeError):
    """Every demo area is in use; nothing of another visitor is removed to make room."""


class VisitorEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    area: str = Field(pattern=r"^[0-9a-f]{32}$")
    created_at: float
    dataset_locale: Locale = Locale.DE
    dataset_id: str = "standard-v1"
    dataset_revision: str = "unknown"
    generation: int = Field(default=1, ge=1)
    reference_time: str = "2026-11-16T09:00:00+01:00"
    timezone: str = "Europe/Berlin"


class StartOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")
    owner: str
    operation: str
    locale: Locale
    area: str


class VisitorState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = 2
    # Keyed by the SHA-256 of the session id; the id itself is never stored here.
    visitors: dict[str, VisitorEntry] = Field(default_factory=dict)
    # Start keys and the session hash they belong to.
    starts: dict[str, str] = Field(default_factory=dict)
    orders: dict[str, StartOrder] = Field(default_factory=dict)


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
        if state.schema_version == 1:
            with self.store.locked():
                raw = self.store.load(VISITORS)
                if raw["schema_version"] == 1:
                    self.store.save("demo-visitors-v1-backup", raw)
                    state.schema_version = 2
                    self.store.save(VISITORS, state.model_dump(mode="json"))
                else:
                    state = VisitorState.model_validate(raw)
        return state

    def area(self, session_id: str) -> Path | None:
        """The store directory of this session's demo, or None before the start."""
        entry = self._state().visitors.get(_hash(session_id))
        path = self.root / entry.area if entry is not None else None
        return path if path is not None and path.is_dir() else None

    def entry(self, session_id: str) -> VisitorEntry | None:
        return self._state().visitors.get(_hash(session_id))

    def full(self) -> bool:
        """Whether a new visitor would exceed the limit; a running start checks again under the lock."""
        return len(self._state().visitors) >= self.max_visitors

    def start(self, session_id: str, key: str, locale: Locale = Locale.DE) -> Path:
        return self._replace(session_id, key, locale, "start")

    def _replace(self, session_id: str, key: str, locale: Locale, operation: str, *,
                 generation: int | None = None, retain_old: bool = False) -> Path:
        owner = _hash(session_id)
        with self.store.locked():
            state = self._state()
            if key in state.starts and state.starts[key] != owner:
                raise ValueError("Dieser Startauftrag gehört zu einer anderen Sitzung.")
            order = state.orders.get(key)
            entry = state.visitors.get(owner)
            if order is not None:
                if (order.owner, order.operation, order.locale) != (owner, operation, locale):
                    raise ValueError("Dieser Auftrag hat einen anderen Inhalt oder gehört zu einer anderen Sitzung.")
                if entry is not None and entry.area != order.area:
                    raise ValueError("Dieser Auftrag gehört zu einer älteren Demo-Generation.")
                if (self.root / order.area).is_dir():
                    return self.root / order.area
            if generation is not None and (entry is None or entry.generation != generation):
                raise ValueError("Die Demo wurde inzwischen neu gestartet. Bitte die Seite neu laden.")
            if operation == "start" and entry is not None and (self.root / entry.area).is_dir():
                state.starts[key] = owner
                state.orders[key] = StartOrder(owner=owner, operation=operation, locale=locale, area=entry.area)
                self.store.save(VISITORS, state.model_dump(mode="json"))
                return self.root / entry.area
            if entry is None and len(state.visitors) >= self.max_visitors:
                raise DemoLimitReached("Gerade sind alle Demo-Plätze belegt. Bitte später erneut versuchen.")
            area = uuid.uuid4().hex
            source = self.dataset if locale == Locale.DE else packaged(locale)
            target = self.root / area
            manifest = install(source, target)
            snapshot = target / ".demo"
            snapshot.mkdir()
            answers = (source / "answers.json").read_bytes()
            if hashlib.sha256(answers).hexdigest() != manifest.answers:
                raise DemoDatasetError("Die vorbereiteten Antworten wurden während der Installation verändert.")
            (snapshot / "answers.json").write_bytes(answers)
            (snapshot / "manifest.json").write_text(json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False),
                                                     encoding="utf-8")
            revision = hashlib.sha256((snapshot / "manifest.json").read_bytes()).hexdigest()
            state.visitors[owner] = VisitorEntry(
                area=area, created_at=entry.created_at if entry is not None else self.clock(),
                dataset_locale=locale, dataset_id=DATASETS[locale], dataset_revision=revision,
                generation=entry.generation + 1 if entry is not None else 1,
                reference_time=manifest.reference_time, timezone=manifest.timezone)
            state.starts[key] = owner
            state.orders[key] = StartOrder(owner=owner, operation=operation, locale=locale, area=area)
            state.schema_version = 2
            self.store.save(VISITORS, state.model_dump(mode="json"))
        if entry is not None and not retain_old:
            shutil.rmtree(self.root / entry.area, ignore_errors=True)
        return target

    def reset(self, session_id: str, key: str, locale: Locale = Locale.DE, *,
              generation: int | None = None, retain_old: bool = False) -> Path:
        """Replace only this session's area with a fresh copy of the dataset."""
        return self._replace(session_id, key, locale, "reset", generation=generation, retain_old=retain_old)

    def cleanup(self, active_sessions: set[str]) -> int:
        """Remove areas of ended sessions and copies left by an interrupted start; returns the count."""
        alive = {_hash(session_id) for session_id in active_sessions}
        with self.store.locked():
            state = self._state()
            ended = [owner for owner in state.visitors if owner not in alive]
            for owner in ended:
                del state.visitors[owner]
            state.starts = {key: owner for key, owner in state.starts.items() if owner in state.visitors}
            state.orders = {key: order for key, order in state.orders.items() if order.owner in state.visitors}
            self.store.save(VISITORS, state.model_dump(mode="json"))
            kept = {entry.area for entry in state.visitors.values()}
            removed = 0
            if self.root.is_dir():
                for path in self.root.iterdir():
                    if path.name not in kept:
                        shutil.rmtree(path, ignore_errors=True)
                        removed += 1
        return removed
