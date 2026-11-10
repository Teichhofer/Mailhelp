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
from email.utils import parsedate_to_datetime
from threading import Lock
from typing import Any, cast, get_args

import httpx

from .. import state_names
from ..config import WriteVerificationSettings
from ..domain.verification import (
    FINAL,
    FieldDifference,
    Operation,
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
# A cancelled entry may still be visible for a moment; only a lasting one is a deviation.
STILL_ACTIVE = "still_active"
OPERATIONS: tuple[Operation, ...] = get_args(Operation)
# A provider's wait hint is honoured up to an hour; beyond the deadline the check ends unverified.
MAX_RETRY_AFTER = 3600.0


def idempotency_key(proposal: Proposal) -> str:
    return f"mailhelp:{proposal.source_mail_id}:{proposal.id}:v{proposal.version}"


def retry_after(error: Exception, now: datetime) -> float:
    """Seconds a provider asked to wait (``Retry-After`` as seconds or HTTP date); 0 without a hint."""
    if not isinstance(error, httpx.HTTPStatusError):
        return 0.0
    value = error.response.headers.get("Retry-After", "").strip()
    if value.isdigit():
        return min(float(value), MAX_RETRY_AFTER)
    try:
        moment = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return 0.0
    if moment.tzinfo is None:
        return 0.0
    return min(max((moment - now).total_seconds(), 0.0), MAX_RETRY_AFTER)


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
        # At most one running check per operation, even if a reload or a second caller asks again.
        self._guard, self._active = Lock(), set[str]()

    def load(self, proposal: Proposal) -> WriteVerification | None:
        """The record of this version's single write operation, whichever it is."""
        for operation in OPERATIONS:
            name = state_names.write_verification(
                operation_id(proposal.source_mail_id, proposal.id, proposal.version, operation))
            record = self.store.load_model(name, WriteVerification)
            if record is not None:
                return record
        return None

    def _save(self, record: WriteVerification) -> WriteVerification:
        record = WriteVerification.model_validate(record.model_dump())
        self.store.save(state_names.write_verification(record.id), record.model_dump(mode="json"))
        return record

    def _binding(self, proposal: Proposal, reader: EntryReader) -> TargetBinding:
        return TargetBinding(profile=proposal.target_profile, provider=provider_key(cast(TargetWriter, reader)),
                             account=reader.account_binding(), container=proposal.target)

    def intent(self, proposal: Proposal, reader: EntryReader, expected: dict[str, Any],
               operation: Operation = "create") -> None:
        """Save the expected facts before the write; a known receipt is never replaced."""
        existing = self.load(proposal)
        if existing is not None and existing.receipt is not None:
            return
        if existing is not None and existing.operation != operation:
            # The preparation now chose another operation (e.g. a duplicate appeared): one record only.
            self.store.delete(state_names.write_verification(existing.id))
        now = self.now()
        self._save(WriteVerification(
            id=operation_id(proposal.source_mail_id, proposal.id, proposal.version, operation),
            mail_id=proposal.source_mail_id, proposal_id=proposal.id, proposal_version=proposal.version,
            idempotency_key=idempotency_key(proposal), operation=operation,
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
        operation: Operation = existing.operation if existing is not None else "create"
        return self._save(WriteVerification(
            id=operation_id(proposal.source_mail_id, proposal.id, proposal.version, operation),
            mail_id=proposal.source_mail_id, proposal_id=proposal.id, proposal_version=proposal.version,
            idempotency_key=idempotency_key(proposal), operation=operation, target=target,
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
        with self._guard:
            if record.id in self._active:
                return proposal, record
            self._active.add(record.id)
        try:
            # The read runs outside every state lock; only the result is saved under it.
            record = self._save(self._attempt(record, reader))
        finally:
            with self._guard:
                self._active.discard(record.id)
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
            wait = retry_after(error, now)
        else:
            wait = 0.0
            if record.operation == "cancel":
                # A cancellation is proven by the entry no longer being active at the bound target.
                if found is None:
                    return record.model_copy(update={**base, "state": VerificationState.VERIFIED})
                code, transient = STILL_ACTIVE, True
            elif found is not None:
                differences = compare(record.expected, found.facts)
                state = VerificationState.MISMATCH if differences else VerificationState.VERIFIED
                return record.model_copy(update={**base, "state": state, "differences": differences})
            else:
                code, transient = NOT_VISIBLE, True
        delays = self.settings.retry_delays_seconds
        due = (now + timedelta(seconds=max(delays[attempts - 1], wait))) if attempts <= len(delays) else None
        if transient and due is not None and due <= record.deadline_at:
            return record.model_copy(update={**base, "state": VerificationState.PENDING, "next_check_at": due,
                                              "last_error": code})
        if code == STILL_ACTIVE:
            return record.model_copy(update={**base, "state": VerificationState.MISMATCH, "last_error": code,
                                              "differences": {"status": FieldDifference(
                                                  expected="abgesagt", actual="weiterhin aktiv")}})
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

    def unsupported(self, proposal: Proposal) -> None:
        """5.2: a calendar file was delivered; whether it was imported cannot be checked."""
        assert proposal.external_id is not None
        now, expected = self.now(), {"kind": "event", "title": proposal.title}
        self._save(WriteVerification(
            id=operation_id(proposal.source_mail_id, proposal.id, proposal.version, "create"),
            mail_id=proposal.source_mail_id, proposal_id=proposal.id, proposal_version=proposal.version,
            idempotency_key=idempotency_key(proposal), operation="create",
            target=TargetBinding(profile=proposal.target_profile, provider="calendar_file", account="telegram",
                                 container=proposal.target),
            receipt=WriteReceipt(external_id=proposal.external_id, written_at=now, result="created"),
            expected=expected, expected_fingerprint=fingerprint(expected), state=VerificationState.UNSUPPORTED,
            deadline_at=now, created_at=now, updated_at=now))

    def mark_notified(self, record: WriteVerification) -> None:
        with self.store.locked():
            current = self.store.load_model(state_names.write_verification(record.id), WriteVerification)
            if current is not None and current.state == record.state:
                self._save(current.model_copy(update={"notified": current.state}))
