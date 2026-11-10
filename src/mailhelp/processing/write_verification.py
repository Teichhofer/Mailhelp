"""5.2: durable write receipts and the read-only verification of written entries.

Order of a verified write (Planung 5.2, 3.2):

1. ``intent`` saves the prepared expected facts and the bound target before the write;
2. ``begin`` saves the write receipt *before* the first read and moves the proposal to
   ``VERIFYING``;
3. ``check`` performs at most one fresh read when it is due, outside every state lock,
   and records the outcome; only a passed check turns the proposal into ``CREATED``,
   and only for the very version and external id that were written.

Nothing here ever writes to a provider: a failed or exhausted check keeps the entry
unverified and never leads to a second write.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx

from .. import state_names
from ..config import WriteVerificationSettings
from ..domain.verification import (
    FINAL,
    TargetBinding,
    VerificationState,
    WriteReceipt,
    WriteVerification,
    fingerprint,
    operation_id,
)
from ..external.contracts import TargetWriter
from ..external.roles import provider_key
from ..external.verification import EntryReader, How, compare
from ..llm.adapter import PermanentError, RetryableError
from ..logging import EventLogger, NullLogger
from ..models import Proposal, ProposalStatus
from ..storage import JsonStore

# A read that may succeed later; every other failure ends the automatic checks.
NOT_VISIBLE = "not_visible"


def idempotency_key(proposal: Proposal) -> str:
    return f"mailhelp:{proposal.source_mail_id}:{proposal.id}:v{proposal.version}"


def _read_error(error: Exception) -> tuple[str, bool]:
    """A structured code and whether a later read may succeed; never the provider's text."""
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        if status == 429:
            return "rate_limited", True
        return ("provider_unavailable", True) if status >= 500 else ("provider_refused", False)
    if isinstance(error, (httpx.TimeoutException, httpx.TransportError, RetryableError)):
        return "provider_unavailable", True
    if isinstance(error, PermanentError):
        return "access_denied", False
    if isinstance(error, ValueError):
        return "invalid_response", False
    raise error


class WriteVerifications:
    def __init__(self, store: JsonStore, settings: WriteVerificationSettings | None = None,
                 now: Callable[[], datetime] = lambda: datetime.now(UTC), logger: EventLogger | None = None):
        self.store, self.settings = store, settings or WriteVerificationSettings()
        self.now, self.logger = now, logger or NullLogger()

    def load(self, proposal: Proposal) -> WriteVerification | None:
        name = state_names.write_verification(
            operation_id(proposal.source_mail_id, proposal.id, proposal.version, "create"))
        return self.store.load_model(name, WriteVerification)

    def _save(self, record: WriteVerification) -> WriteVerification:
        record = WriteVerification.model_validate(record.model_dump())
        self.store.save(state_names.write_verification(record.id), record.model_dump(mode="json"))
        return record

    def _binding(self, proposal: Proposal, reader: EntryReader) -> TargetBinding:
        return TargetBinding(profile=proposal.target_profile, provider=provider_key(cast(TargetWriter, reader)),
                             account=reader.account_binding(), container=proposal.target)

    def intent(self, proposal: Proposal, reader: EntryReader, expected: dict[str, Any]) -> None:
        """Save the expected facts before the write; a known receipt is never replaced."""
        existing = self.load(proposal)
        if existing is not None and existing.receipt is not None:
            return
        now = self.now()
        self._save(WriteVerification(
            id=operation_id(proposal.source_mail_id, proposal.id, proposal.version, "create"),
            mail_id=proposal.source_mail_id, proposal_id=proposal.id, proposal_version=proposal.version,
            idempotency_key=idempotency_key(proposal), operation="create",
            target=self._binding(proposal, reader), expected=expected, expected_fingerprint=fingerprint(expected),
            deadline_at=now + timedelta(seconds=self.settings.max_elapsed_seconds), created_at=now, updated_at=now))

    def begin(self, proposal: Proposal, result: dict[str, Any], how: How,
              reader: EntryReader) -> Proposal | None:
        """Save the receipt and return the ``VERIFYING`` proposal; ``None`` if nothing can be compared."""
        record = self._receipt(proposal, str(result["id"]), how, reader)
        if record is None:
            return None
        assert record.receipt is not None
        link = result.get("url") or result.get("html_url") or result.get("htmlLink")
        return proposal.model_copy(update={
            "status": ProposalStatus.VERIFYING, "external_id": record.receipt.external_id,
            "external_link": str(link) if link is not None else proposal.external_link})

    def _receipt(self, proposal: Proposal, external_id: str, how: How,
                 reader: EntryReader) -> WriteVerification | None:
        existing = self.load(proposal)
        if existing is not None and existing.receipt is not None:
            return existing  # a restart after the receipt: the same entry, the same check
        if existing is None and how == "found_by_key":
            # Found without a saved intent (another operation, or written before 5.2): the
            # facts it was written with are unknown, so a comparison would be guesswork.
            return None
        expected = existing.expected if existing is not None else reader.expected_facts(
            proposal, idempotency_key(proposal))
        if expected is None:
            return None
        now = self.now()
        target = existing.target if existing is not None else self._binding(proposal, reader)
        return self._save(WriteVerification(
            id=operation_id(proposal.source_mail_id, proposal.id, proposal.version, "create"),
            mail_id=proposal.source_mail_id, proposal_id=proposal.id, proposal_version=proposal.version,
            idempotency_key=idempotency_key(proposal), operation="create", target=target,
            receipt=WriteReceipt(external_id=external_id, written_at=now, result=how),
            expected=expected, expected_fingerprint=fingerprint(expected), next_check_at=now,
            deadline_at=now + timedelta(seconds=self.settings.max_elapsed_seconds), created_at=now, updated_at=now))

    def check(self, proposal: Proposal, reader: EntryReader,
              persist: Callable[[Proposal], None]) -> tuple[Proposal, WriteVerification | None]:
        """At most one due read; returns the (possibly created) proposal and the check state."""
        record = self.load(proposal)
        if record is None or record.receipt is None:
            assert proposal.external_id is not None  # a VERIFYING proposal always has one
            record = self._receipt(proposal, proposal.external_id, "existing", reader)
            if record is None:
                return proposal, None
        if record.state == VerificationState.VERIFIED:
            return self._apply(proposal, record, persist), record
        if record.state in FINAL:
            return proposal, record
        assert record.next_check_at is not None  # a pending check with a receipt is always scheduled
        if record.next_check_at > self.now():
            return proposal, record
        record = self._save(self._attempt(record, reader))
        self.logger.event("INFO", "verification", "write_checked", mail_id=record.mail_id,
                          proposal_id=record.proposal_id, version=record.proposal_version,
                          attempt=record.attempts, state=record.state.value, error=record.last_error,
                          fields=sorted(record.differences))
        if record.state == VerificationState.VERIFIED:
            return self._apply(proposal, record, persist), record
        return proposal, record

    def _attempt(self, record: WriteVerification, reader: EntryReader) -> WriteVerification:
        assert record.receipt is not None
        now, attempts = self.now(), record.attempts + 1
        base: dict[str, Any] = {"attempts": attempts, "checked_at": now, "updated_at": now,
                                "next_check_at": None, "last_error": None, "differences": {}}
        if getattr(reader, "target", record.target.container) != record.target.container:
            return record.model_copy(update={**base, "state": VerificationState.UNAVAILABLE,
                                              "last_error": "target_changed"})
        try:
            if reader.account_binding() != record.target.account:
                return record.model_copy(update={**base, "state": VerificationState.UNAVAILABLE,
                                                  "last_error": "account_changed"})
            found = reader.read_entry(record.receipt.external_id)
        except Exception as error:
            code, transient = _read_error(error)
        else:
            if found is not None:
                differences = compare(record.expected, found.facts)
                state = VerificationState.MISMATCH if differences else VerificationState.VERIFIED
                return record.model_copy(update={**base, "state": state, "differences": differences})
            code, transient = NOT_VISIBLE, True
        delays = self.settings.retry_delays_seconds
        due = now + timedelta(seconds=delays[attempts - 1]) if attempts <= len(delays) else None
        if transient and due is not None and due <= record.deadline_at:
            return record.model_copy(update={**base, "state": VerificationState.PENDING, "next_check_at": due,
                                              "last_error": code})
        final = VerificationState.NOT_FOUND if code == NOT_VISIBLE else VerificationState.UNAVAILABLE
        return record.model_copy(update={**base, "state": final, "last_error": code})

    def _apply(self, proposal: Proposal, record: WriteVerification,
               persist: Callable[[Proposal], None]) -> Proposal:
        """CREATED only for the written version and entry; a newer version stays as it is."""
        assert record.receipt is not None
        with self.store.locked():
            current = self.store.load_model(state_names.proposal(record.mail_id, record.proposal_id), Proposal)
            if (current is None or current.status != ProposalStatus.VERIFYING
                    or current.version != record.proposal_version
                    or current.external_id != record.receipt.external_id):
                return proposal if current is None else current
            created = current.model_copy(update={"status": ProposalStatus.CREATED})
            persist(created)
        return created

    def mark_notified(self, record: WriteVerification) -> None:
        with self.store.locked():
            current = self.store.load_model(state_names.write_verification(record.id), WriteVerification)
            if current is not None and current.state == record.state:
                self._save(current.model_copy(update={"notified": current.state}))
