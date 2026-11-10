"""5.2 (V1): the contract that separates a write result from its verification.

A successful write response, an id or a cached match is no proof that the entry
exists with the confirmed facts. A proposal with a known write result therefore
stays ``VERIFYING`` until a fresh, independent read at the original target proves
it; only then does it become ``CREATED``. Verification only reads: it never writes,
repairs, changes or deletes an entry, and it never allows a second write.

The record ``write-verification-<operation>.json`` keeps what verification and a
restart need: the identity of the write, the bound target, the write receipt, the
expected facts with their fingerprint, the check state and the last comparison.
Before the write the same record is saved as a *write intent* (pending, without a
receipt and without a check time): it keeps the prepared expected facts, so an entry
found again after an unclear write is compared with what was really sent.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from ._base import StrictModel
from .proposal import ProposalStatus

Operation = Literal["create", "update", "append", "cancel", "duplicate"]


class VerificationState(StrEnum):
    PENDING = "pending"
    VERIFIED = "verified"
    NOT_FOUND = "not_found"
    MISMATCH = "mismatch"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"
    LEGACY_UNVERIFIED = "legacy_unverified"
    SIMULATED = "simulated"


# States after which no further automatic read follows; "Erneut prüfen" may start one.
FINAL = {VerificationState.VERIFIED, VerificationState.NOT_FOUND, VerificationState.MISMATCH,
         VerificationState.UNAVAILABLE, VerificationState.UNSUPPORTED,
         VerificationState.LEGACY_UNVERIFIED, VerificationState.SIMULATED}

# Proposal states in which an entry may already exist at the target; none of them
# allows another write, and duplicate checks treat them as written.
WRITTEN = {ProposalStatus.WRITING, ProposalStatus.UNCERTAIN, ProposalStatus.VERIFYING, ProposalStatus.CREATED}

# Allowed transitions of the write states. VERIFYING never goes back to a state that
# could start a write; a failed verification keeps VERIFYING with its final check state.
TRANSITIONS: dict[ProposalStatus, frozenset[ProposalStatus]] = {
    ProposalStatus.CONFIRMED: frozenset({ProposalStatus.WRITING, ProposalStatus.SIMULATED, ProposalStatus.FAILED}),
    ProposalStatus.WRITING: frozenset({ProposalStatus.VERIFYING, ProposalStatus.UNCERTAIN, ProposalStatus.FAILED}),
    ProposalStatus.UNCERTAIN: frozenset({ProposalStatus.VERIFYING, ProposalStatus.UNCERTAIN}),
    ProposalStatus.VERIFYING: frozenset({ProposalStatus.VERIFYING, ProposalStatus.CREATED}),
    ProposalStatus.CREATED: frozenset({ProposalStatus.CREATED}),
}


def allowed(old: ProposalStatus, new: ProposalStatus) -> bool:
    """Whether a write state may change from *old* to *new*; other states are not governed here."""
    return old not in TRANSITIONS or new in TRANSITIONS[old]


def fingerprint(expected: dict[str, Any]) -> str:
    """A stable fingerprint of the expected facts, independent of key order."""
    return hashlib.sha256(json.dumps(expected, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


def operation_id(mail_id: str, proposal_id: str, version: int, operation: Operation) -> str:
    return hashlib.sha256(f"{mail_id}:{proposal_id}:v{version}:{operation}".encode()).hexdigest()[:32]


class TargetBinding(StrictModel):
    """The target the write was authorized for; verification never follows another one."""

    profile: int = Field(ge=1)
    provider: str = Field(min_length=1, max_length=30)
    # A stable account binding (never an alias such as "primary" or "default" alone).
    account: str = Field(min_length=1, max_length=200)
    # Calendar, project or list id, or the checked CalDAV collection.
    container: str = Field(min_length=1, max_length=2000)


class WriteReceipt(StrictModel):
    external_id: str = Field(min_length=1, max_length=500)
    written_at: datetime
    revision: str | None = Field(default=None, max_length=500)
    result: Literal["created", "found_by_key", "updated", "appended", "cancelled", "existing"]


class FieldDifference(StrictModel):
    """A bounded expected/actual pair for display; never a full provider response."""

    expected: str | None = Field(default=None, max_length=500)
    actual: str | None = Field(default=None, max_length=500)


class WriteVerification(StrictModel):
    schema_version: Literal[1] = 1
    id: str = Field(pattern=r"^[a-f0-9]{32}$")
    mail_id: str = Field(pattern=r"^[a-f0-9]{24}$")
    proposal_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    proposal_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=200)
    operation: Operation
    target: TargetBinding
    receipt: WriteReceipt | None = None
    expected: dict[str, Any]
    expected_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    state: VerificationState = VerificationState.PENDING
    attempts: int = Field(default=0, ge=0)
    checked_at: datetime | None = None
    next_check_at: datetime | None = None
    deadline_at: datetime
    last_error: str | None = Field(default=None, pattern=r"^[a-z0-9_]{1,60}$")
    differences: dict[str, FieldDifference] = Field(default_factory=dict, max_length=30)
    # The check state last reported to the user; a report is never sent twice.
    notified: VerificationState | None = None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def consistent(self) -> WriteVerification:
        stamps = (self.deadline_at, self.created_at, self.updated_at, self.checked_at, self.next_check_at)
        if any(value is not None and value.tzinfo is None for value in stamps):
            raise ValueError("Zeitstempel müssen eine Zeitzone enthalten")
        if self.id != operation_id(self.mail_id, self.proposal_id, self.proposal_version, self.operation):
            raise ValueError("Die Prüfkennung gehört zu genau einer Vorschlagsversion und Operation")
        if self.expected_fingerprint != fingerprint(self.expected):
            raise ValueError("Der Sollstand passt nicht zu seinem Fingerabdruck")
        live = self.state not in {VerificationState.LEGACY_UNVERIFIED, VerificationState.SIMULATED}
        if live and self.receipt is None and not self.is_intent:
            raise ValueError("Eine Nachprüfung braucht einen Schreibbeleg mit externer ID")
        if self.receipt is not None and (self.state == VerificationState.PENDING) != (self.next_check_at is not None):
            raise ValueError("Genau eine ausstehende Prüfung hat einen nächsten Prüfzeitpunkt")
        if self.state == VerificationState.VERIFIED and (self.checked_at is None or self.differences):
            raise ValueError("Eine bestandene Prüfung hat einen Prüfzeitpunkt und keine Abweichung")
        if (self.state == VerificationState.MISMATCH) != bool(self.differences):
            raise ValueError("Genau eine Abweichung nennt die abweichenden Felder")
        return self

    @property
    def is_intent(self) -> bool:
        """Saved before the write: pending, no receipt and no check time yet."""
        return self.state == VerificationState.PENDING and self.receipt is None and self.next_check_at is None
