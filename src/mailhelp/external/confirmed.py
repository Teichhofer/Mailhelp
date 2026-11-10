"""Durable, version-authorized write execution and uncertain-result reconciliation."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx

from ..llm.adapter import PermanentError, UncertainWriteError
from ..models import Proposal, ProposalStatus
from .calendar import CalendarOperations
from .contracts import ExternalWriter, PreparedWrite, TargetWriter, proposal_is_writable
from .roles import provider_key
from .verification import EntryReader, How, VerificationPort

# The receipt of each write operation (5.2); a found entry is "found_by_key".
RECEIPTS: dict[str, How] = {"create": "created", "update": "updated", "append": "appended",
                            "cancel": "cancelled", "duplicate": "existing"}


def execute_confirmed(proposal: Proposal, writer: ExternalWriter, persist: Callable[[Proposal], None],
                      test_mode: bool = False, *, authorize: Callable[[], bool] | None = None,
                      verification: VerificationPort | None = None,
                      ) -> tuple[Proposal, dict[str, Any]]:
    """Write a confirmed version at most once.

    With *verification* and a writer that can read its entries (5.2), a write answer or
    an entry found by its key leads to ``VERIFYING`` with a durable receipt, never
    directly to ``CREATED``; the caller then checks the entry by a fresh read.
    """
    if not proposal_is_writable(proposal):
        raise ValueError("Nur neue, sichere und eigene Vorschläge oder ausdrücklich bestätigte "
                         "Ersatz-Neuanlagen dürfen extern angelegt werden")
    if proposal.status == ProposalStatus.SIMULATED:
        return proposal, {"simulation": True}
    if proposal.status == ProposalStatus.VERIFYING:
        # 5.2: the entry is written; only a read may follow, never a second write.
        return proposal, {"verifying": True}
    if (proposal.status not in {ProposalStatus.CONFIRMED, ProposalStatus.WRITING, ProposalStatus.UNCERTAIN}
            or proposal.open_questions):
        raise ValueError("Schreiben erfordert vollständige, bestätigte Vorschlagsversion")
    if isinstance(writer, TargetWriter) and (proposal.target_profile != getattr(writer, "target_profile", 1)
            or proposal.target != writer.target or
            proposal.target_provider and proposal.target_provider != provider_key(writer)):
        # Even reconciliation must not search a newly configured target for an
        # action authorized against a different project/calendar.
        return proposal, {"target_mismatch": True}
    # A dry run must never contact either target, even for reconciliation.
    if test_mode:
        simulated = proposal.model_copy(update={
            "status": ProposalStatus.SIMULATED,
            "external_id": None,
            "external_link": None,
        })
        persist(simulated)
        return simulated, {"simulation": True}
    key = f"mailhelp:{proposal.source_mail_id}:{proposal.id}:v{proposal.version}"
    checker = (verification, writer) if verification is not None and isinstance(writer, EntryReader) else None
    found = _found(proposal, writer, key)
    if found is not None:
        return _written(proposal, found, "found_by_key", checker, persist)
    # A request which may already have reached the external service must never
    # be repeated automatically.  Later reconciliations may still prove that
    # it succeeded.
    if proposal.status in {ProposalStatus.WRITING, ProposalStatus.UNCERTAIN}:
        uncertain = proposal.model_copy(update={"status": ProposalStatus.UNCERTAIN})
        persist(uncertain)
        return uncertain, {}
    # Only this transition is allowed to initiate a new external write.  A
    # future operator retry therefore needs its own explicit state transition
    # back to CONFIRMED rather than falling through from UNCERTAIN.
    writing = proposal.model_copy(update={"status": ProposalStatus.WRITING})
    # All reads, LLM comparisons and payload validation precede the durable
    # write boundary. A preflight failure leaves the authorization CONFIRMED.
    prepared = (writer.prepare(proposal, key) if isinstance(writer, TargetWriter)
                else PreparedWrite(lambda: writer.create(writing, key)))
    # Preparation can involve slow external reads. Check again at the write boundary,
    # including when the confirmed record was resumed in a fresh process.
    if authorize is not None and not authorize():
        return proposal, {"authorization_invalid": True}
    if prepared.expected is None:
        checker = None  # an operation without expected facts cannot be compared
    if checker is not None:
        # The write intent with its expected facts is durable before the write (5.2, 3.2).
        assert prepared.expected is not None
        checker[0].intent(proposal, checker[1], prepared.expected, prepared.kind)
    if prepared.requires_write:
        persist(writing)
    try: result = prepared.operation()
    except (UncertainWriteError, httpx.TimeoutException, httpx.TransportError):
        uncertain = writing.model_copy(update={"status": ProposalStatus.UNCERTAIN})
        persist(uncertain)
        return uncertain, {}
    except (PermanentError, httpx.HTTPStatusError):
        failed = writing.model_copy(update={"status": ProposalStatus.FAILED})
        persist(failed)
        return failed, {}
    return _finish(writing, result, prepared, checker, verification, persist)


def _finish(writing: Proposal, result: dict[str, Any], prepared: PreparedWrite,
            checker: tuple[VerificationPort, EntryReader] | None, verification: VerificationPort | None,
            persist: Callable[[Proposal], None]) -> tuple[Proposal, dict[str, Any]]:
    how: How = "existing" if result.get("operation") == "already_cancelled" else RECEIPTS[prepared.kind]
    written = _written(writing, result, how, checker, persist)
    if verification is not None and result.get("operation") == "calendar_file":
        verification.unsupported(written[0])
    return written


def _found(proposal: Proposal, writer: ExternalWriter, key: str) -> dict[str, Any] | None:
    found = writer.reconcile(key)
    if (found is None and proposal.is_cancellation and proposal.target_event_id is not None
            and proposal.status in {ProposalStatus.WRITING, ProposalStatus.UNCERTAIN}
            and isinstance(writer, CalendarOperations)
            and writer.existing_event(proposal.target_event_id) is None):
        # 4.6, 17.6: a cancelled entry no longer carries a findable key, so an unclear
        # cancellation is matched by its target: gone or cancelled means it succeeded.
        found = {"id": proposal.target_event_id, "operation": "event_cancelled"}
    return found


def _written(proposal: Proposal, result: dict[str, Any], how: How,
             checker: tuple[VerificationPort, EntryReader] | None,
             persist: Callable[[Proposal], None]) -> tuple[Proposal, dict[str, Any]]:
    """A known write result: ``VERIFYING`` with a durable receipt, or ``CREATED`` without a check."""
    _external_id(result)
    if checker is not None:
        verifying = checker[0].begin(proposal, result, how, checker[1])
        if verifying is not None:
            persist(verifying)
            return verifying, {**result, "verifying": True}
    created = _with_external_result(proposal, result)
    persist(created)
    return created, result


def _external_id(result: dict[str, Any]) -> str:
    external_id = result.get("id")
    if external_id is None or isinstance(external_id, bool) or not str(external_id):
        raise ValueError("Externe Integration: benötigter Schlüsselpfad id fehlt")
    return str(external_id)


def _with_external_result(proposal: Proposal, result: dict[str, Any]) -> Proposal:
    external_id = _external_id(result)
    link = result.get("url") or result.get("html_url") or result.get("htmlLink")
    return proposal.model_copy(update={
        "status": ProposalStatus.CREATED,
        "external_id": external_id,
        "external_link": str(link) if link is not None else None,
    })

