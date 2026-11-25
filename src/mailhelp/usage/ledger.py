"""8.7: the durable usage ledger – one readable JSONL line per event, append-only.

Every provider attempt is written *before* its request is sent (``begun``, with the valuation it is
bound to) and gets at most one result (``settled``). Repeated results, duplicate events and restarts
therefore count an attempt at most once; an attempt without a result stays visibly unclear and no
cost is invented for it. The ledger holds no mail text, prompt or key, and rotating diagnostic logs
are never its source.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from threading import RLock
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError

from .points import CostStatus, Valuation, points, reported_cost, total

ATTEMPT = r"^[A-Za-z0-9:_-]{1,120}$"


class UsageCorrupt(RuntimeError):
    """A line other than an interrupted last one cannot be read; nothing is guessed."""


class Purpose(StrEnum):
    CUSTOMER = "customer"  # everything done for the customer, retries and fallbacks included
    OPERATOR = "operator"  # operator tests and maintenance; set by the server, never chosen by a customer


class _Line(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1
    attempt: str = Field(pattern=ATTEMPT)
    at: AwareDatetime


class Begun(_Line):
    type: Literal["begun"] = "begun"
    stage: str = Field(pattern=r"^[a-z0-9_.-]{1,64}$")
    purpose: Purpose
    valuation: Valuation
    mail_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{24}$")


class Settled(_Line):
    type: Literal["settled"] = "settled"
    status: CostStatus
    cost_usd: Decimal | None = None
    points: Decimal | None = None
    provider_id: str | None = Field(default=None, max_length=200)


@dataclass
class Attempt:
    begun: Begun
    settled: Settled | None = None

    @property
    def points(self) -> Decimal | None:
        """Known points, or None while the cost is missing, invalid or not yet reported."""
        return self.settled.points if self.settled is not None else None

    @property
    def unclear(self) -> bool:
        """No result yet, or a result whose cost cannot be valued."""
        return self.settled is None or self.settled.status in {CostStatus.MISSING, CostStatus.INVALID}


@dataclass(frozen=True)
class Summary:
    """Known points of a period plus the number of attempts that cannot be valued (yet)."""

    points: Decimal
    counted: int
    unclear: int
    by_stage: dict[str, Decimal] = field(default_factory=dict)
    by_day: dict[date, Decimal] = field(default_factory=dict)

    @property
    def complete(self) -> bool:
        return self.unclear == 0


class UsageLedger:
    """Append-only attempts of one instance in ``path`` (JSONL)."""

    def __init__(self, path: Path, clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self.path, self.clock = path, clock
        self._lock = RLock()
        self._attempts: dict[str, Attempt] = {}
        self._read()

    def _read(self) -> None:
        try:
            data = self.path.read_bytes()
        except FileNotFoundError:
            return
        if data and not data.endswith(b"\n"):
            # An append interrupted by a crash: the fragment is kept beside the ledger for tracing and
            # removed from it, so the attempt it described stays unclear and later lines stay readable.
            cut = data.rfind(b"\n") + 1
            with self.path.with_name(self.path.name + ".torn").open("ab") as stream:
                stream.write(data[cut:] + b"\n")
            with self.path.open("r+b") as stream:
                stream.truncate(cut)
                os.fsync(stream.fileno())
            data = data[:cut]
        for number, line in enumerate(data.decode("utf-8").split("\n")):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
                item: Begun | Settled = (Begun if raw.get("type") == "begun" else Settled).model_validate(raw)
            except (ValueError, ValidationError, AttributeError) as exc:
                raise UsageCorrupt(f"Verbrauchsbestand Zeile {number + 1} ist nicht lesbar") from exc
            self._apply(item)

    def _apply(self, item: Begun | Settled) -> bool:
        if isinstance(item, Begun):
            if item.attempt in self._attempts:
                return False
            self._attempts[item.attempt] = Attempt(item)
            return True
        attempt = self._attempts.get(item.attempt)
        if attempt is None or attempt.settled is not None:
            return False  # an unknown attempt or a repeated result
        attempt.settled = item
        return True

    def _append(self, item: Begun | Settled) -> None:
        line = json.dumps(item.model_dump(mode="json"), ensure_ascii=False, sort_keys=True) + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("ab") as stream:
            stream.write(line.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())

    def begin(self, attempt: str, stage: str, purpose: Purpose, valuation: Valuation,
              mail_id: str | None = None) -> None:
        """Bind the attempt to its valuation, durably, before the provider is called."""
        if mail_id is not None and not re.fullmatch(r"[a-f0-9]{24}", mail_id):
            mail_id = None
        item = Begun(attempt=attempt, at=self.clock(), stage=stage, purpose=purpose, valuation=valuation,
                     mail_id=mail_id)
        with self._lock:
            if attempt not in self._attempts:
                self._append(item)
                self._apply(item)

    def settle(self, attempt: str, raw_cost: object, provider_id: str | None = None) -> None:
        """Record the result once; a repeated delivery of the same result changes nothing."""
        with self._lock:
            known = self._attempts.get(attempt)
            if known is None or known.settled is not None:
                return
            status, cost = reported_cost(raw_cost)
            value = points(cost, known.begun.valuation) if cost is not None else None
            item = Settled(attempt=attempt, at=self.clock(), status=status, cost_usd=cost, points=value,
                           provider_id=provider_id if isinstance(provider_id, str) else None)
            self._append(item)
            self._apply(item)

    def not_sent(self, attempt: str) -> None:
        """The connection was refused: nothing reached the provider, so nothing is used or unclear."""
        with self._lock:
            known = self._attempts.get(attempt)
            if known is None or known.settled is not None:
                return
            item = Settled(attempt=attempt, at=self.clock(), status=CostStatus.NOT_SENT)
            self._append(item)
            self._apply(item)

    def attempts(self) -> list[Attempt]:
        """In the order they began."""
        with self._lock:
            return list(self._attempts.values())

    def started_at(self) -> datetime | None:
        """When recording began: the first attempt ever written."""
        items = self.attempts()
        return items[0].begun.at if items else None


def summarize(attempts: list[Attempt], start: datetime, end: datetime, timezone: ZoneInfo,
              purpose: Purpose | None = Purpose.CUSTOMER) -> Summary:
    """Attempts that *began* in [start, end); each belongs to exactly one local day."""
    chosen = [item for item in attempts if start <= item.begun.at < end
              and (purpose is None or item.begun.purpose is purpose)]
    known = [item for item in chosen if item.points is not None]
    by_stage: dict[str, list[Decimal]] = {}
    by_day: dict[date, list[Decimal]] = {}
    for item in known:
        assert item.points is not None
        by_stage.setdefault(item.begun.stage, []).append(item.points)
        by_day.setdefault(item.begun.at.astimezone(timezone).date(), []).append(item.points)
    return Summary(total([item.points for item in known if item.points is not None]), len(chosen),
                   sum(item.unclear for item in chosen), {key: total(value) for key, value in sorted(by_stage.items())},
                   {key: total(value) for key, value in sorted(by_day.items())})


__all__ = ["Attempt", "Begun", "Purpose", "Settled", "Summary", "UsageCorrupt", "UsageLedger", "summarize"]
