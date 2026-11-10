"""5.2: the provider-neutral read contract and the deterministic comparison of a written entry.

A reader loads one entry by its external id, freshly from the bound target, and
returns its facts normalised to the same keys the expected facts use. The
comparison is deterministic: no LLM decides whether a title or a due date fits.

Allowed normalisations (and only these):

* text: line endings unified to ``\\n``, surrounding whitespace removed; an empty and a
  missing location or description are the same;
* time points: compared as instants, so ``Z`` and ``+01:00`` may denote the same time;
  a floating time without zone is compared with the wall time that was sent;
* dates stay dates: a date never equals a time point, an all-day entry never a timed one.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal, Protocol, runtime_checkable

from ..domain.verification import FieldDifference, Operation
from ..models import Proposal

TEMPORAL = ("due", "start", "end")
# How the written entry became known: by the write answer, found by its key, or already there.
How = Literal["created", "found_by_key", "updated", "appended", "cancelled", "existing"]


@dataclass(frozen=True)
class EntryRead:
    """The facts of one freshly read entry; never a full provider response."""

    facts: dict[str, Any]
    link: str | None = None
    # A task that is already done still exists; done is not missing (Planung 5.2, 5).
    completed: bool = False


@runtime_checkable
class EntryReader(Protocol):
    """A writer whose entries can be verified by a fresh read at the bound target."""

    def account_binding(self) -> str:
        """A stable identity of the authenticated account, never an alias such as ``primary``."""

    def expected_facts(self, proposal: Proposal, key: str) -> dict[str, Any] | None:
        """The facts a plain new entry is written with; ``None`` for other operations."""

    def read_entry(self, external_id: str) -> EntryRead | None:
        """The entry as it is now; ``None`` if it is not (or no longer) visible at the target."""


class VerificationPort(Protocol):
    """The durable receipts of a write; implemented by ``processing.write_verification``."""

    def intent(self, proposal: Proposal, reader: EntryReader, expected: dict[str, Any],
               operation: Operation = "create") -> None:
        """Save the expected facts of the coming write; a known receipt is never replaced."""

    def unsupported(self, proposal: Proposal) -> None:
        """Record a delivered calendar file whose import cannot be checked."""

    def begin(self, proposal: Proposal, result: dict[str, Any], how: How, reader: EntryReader) -> Proposal | None:
        """Save the receipt and return the ``VERIFYING`` proposal; ``None`` if nothing can be compared."""


def _iso(value: date | datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def task_facts(title: str, description: str, due: date | datetime | None, container: str) -> dict[str, Any]:
    return {"kind": "task", "title": title, "description": description, "due": _iso(due),
            "container": container}


def event_facts(title: str, description: str, start: date | datetime | None, end: date | datetime | None,
                all_day: bool, location: str | None, container: str) -> dict[str, Any]:
    return {"kind": "event", "title": title, "description": description, "start": _iso(start),
            "end": _iso(end), "all_day": all_day, "location": location, "container": container}


def _text(value: Any) -> str:
    return "" if value is None else str(value).replace("\r\n", "\n").replace("\r", "\n").strip()


def _temporal(value: Any) -> date | datetime | None:
    if value is None:
        return None
    text = str(value)
    if "T" not in text:
        return date.fromisoformat(text)
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _same_time(expected: Any, actual: Any) -> bool:
    try:
        want, have = _temporal(expected), _temporal(actual)
    except ValueError:
        return False
    if want is None or have is None or isinstance(want, datetime) != isinstance(have, datetime):
        return want is None and have is None
    if isinstance(want, datetime) and isinstance(have, datetime):
        if have.tzinfo is None:
            # A floating time: the wall time that was sent decides.
            return want.replace(tzinfo=None) == have
    return want == have


def _shown(value: Any) -> str | None:
    return None if value is None else str(value)[:500]


def compare(expected: dict[str, Any], actual: dict[str, Any]) -> dict[str, FieldDifference]:
    """The fields in which the read entry differs from the expected facts."""
    differences: dict[str, FieldDifference] = {}
    for name, want in expected.items():
        have = actual.get(name)
        if name in TEMPORAL:
            same = _same_time(want, have)
        elif isinstance(want, bool):
            same = want is have
        else:
            same = _text(want) == _text(have)
        if not same:
            differences[name] = FieldDifference(expected=_shown(want), actual=_shown(have))
    return differences
