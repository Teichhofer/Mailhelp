"""8.7: the versioned valuation revisions of an instance and the meter that binds them to attempts.

Revisions are only ever appended, by the operator at the host (``--set-valuation``); a change applies
to attempts that begin afterwards and never re-values recorded usage. Without a first revision no
usage is recorded at all: example values are never assumed.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from threading import RLock
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..persistence.storage import atomic_replace
from .ledger import Purpose, UsageLedger
from .points import Valuation, current

USAGE_DIRECTORY = "usage"  # inside the state directory of the instance
FILE = "valuations.json"
LEDGER = "attempts.jsonl"
# Server-side purpose of the calls made in this context; a customer request can never set it.
PURPOSE: ContextVar[Purpose] = ContextVar("usage_purpose", default=Purpose.CUSTOMER)
# 8.7.4: the feature a call belongs to, recorded as stage prefix ("learning.relevance"). A learning
# run uses the same steps as mail processing; only the prefix tells its usage apart.
SCOPES = frozenset({"learning"})
SCOPE: ContextVar[str | None] = ContextVar("usage_scope", default=None)


class ValuationError(ValueError):
    """The valuation file cannot be read or the requested revision is not valid."""


class _File(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    revisions: list[Valuation] = Field(default_factory=list)


class Valuations:
    """``valuations.json`` in the usage directory; re-read when the operator changed it."""

    def __init__(self, directory: Path) -> None:
        self.path = directory / FILE
        self._lock = RLock()
        self._seen: tuple[int, int] | None = None
        self._revisions: list[Valuation] = []

    def revisions(self) -> list[Valuation]:
        with self._lock:
            try:
                status = self.path.stat()
            except FileNotFoundError:
                self._seen, self._revisions = None, []
                return []
            if (status.st_mtime_ns, status.st_size) != self._seen:
                try:
                    data = _File.model_validate(json.loads(self.path.read_text(encoding="utf-8")))
                except (ValueError, ValidationError) as exc:
                    raise ValuationError("Bewertungsstände sind nicht lesbar") from exc
                self._revisions, self._seen = data.revisions, (status.st_mtime_ns, status.st_size)
            return list(self._revisions)

    def add(self, usd_per_eur: Decimal, markup_percent: Decimal, actor: str, at: datetime) -> Valuation:
        """Append a revision valid from ``at``; earlier revisions stay unchanged."""
        with self._lock:
            revisions = self.revisions()
            if revisions and at <= max(item.valid_from for item in revisions):
                raise ValuationError("Ein neuer Bewertungsstand muss nach dem letzten beginnen")
            try:
                item = Valuation(revision=len(revisions) + 1, usd_per_eur=usd_per_eur,
                                 markup_percent=markup_percent, valid_from=at, actor=actor)
            except ValidationError as exc:
                raise ValuationError("Kurs muss positiv und Aufschlag mindestens 0 sein, beide endlich") from exc
            content = _File(revisions=[*revisions, item]).model_dump_json(indent=2) + "\n"
            atomic_replace(self.path, content)
            # Readable for the service group only; on Windows this only keeps the file writable.
            os.chmod(self.path, 0o640)
            return item


class UsageMeter:
    """What a provider client calls around each attempt; records nothing without a valuation."""

    def __init__(self, directory: Path, clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self.valuations = Valuations(directory)
        self.ledger = UsageLedger(directory / LEDGER, clock)
        self.clock = clock

    def begin(self, attempt: str, stage: str, mail_id: str | None = None) -> bool:
        valuation = current(self.valuations.revisions(), self.clock())
        if valuation is None:
            return False
        stage = stage if re.fullmatch(r"[a-z0-9_-]{1,48}", stage) else "other"
        scope = SCOPE.get()
        stage = f"{scope}.{stage}" if scope is not None else stage
        self.ledger.begin(attempt, stage, PURPOSE.get(), valuation, mail_id)
        return True

    def settle(self, attempt: str, raw_cost: object, provider_id: str | None = None) -> None:
        self.ledger.settle(attempt, raw_cost, provider_id)


@contextmanager
def operator_purpose() -> Iterator[None]:
    """Calls in this block are operator maintenance and do not count as customer usage."""
    token = PURPOSE.set(Purpose.OPERATOR)
    try:
        yield
    finally:
        PURPOSE.reset(token)


@contextmanager
def usage_scope(scope: str) -> Iterator[None]:
    """Calls in this block are recorded as part of ``scope`` (one of :data:`SCOPES`)."""
    if scope not in SCOPES:
        raise ValueError("Unbekannter Verbrauchsbereich")
    token = SCOPE.set(scope)
    try:
        yield
    finally:
        SCOPE.reset(token)


__all__ = ["FILE", "LEDGER", "PURPOSE", "SCOPE", "SCOPES", "USAGE_DIRECTORY", "UsageMeter", "ValuationError",
           "Valuations", "operator_purpose", "usage_scope"]
