"""Durable, version-authorized write execution and uncertain-result reconciliation."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx

from ..adapter import PermanentError, UncertainWriteError
from ..models import Proposal, ProposalStatus
from .contracts import ExternalWriter, PreparedWrite, TargetWriter, proposal_is_writable


def execute_confirmed(proposal: Proposal, writer: ExternalWriter, persist: Callable[[Proposal], None],
                      test_mode: bool = False) -> tuple[Proposal, dict[str, Any]]:
    if not proposal_is_writable(proposal):
        raise ValueError("Nur neue, sichere und eigene Vorschläge oder ausdrücklich bestätigte "
                         "Ersatz-Neuanlagen dürfen extern angelegt werden")
    if proposal.status == ProposalStatus.SIMULATED:
        return proposal, {"simulation": True}
    if (proposal.status not in {ProposalStatus.CONFIRMED, ProposalStatus.WRITING, ProposalStatus.UNCERTAIN}
            or proposal.open_questions):
        raise ValueError("Schreiben erfordert vollständige, bestätigte Vorschlagsversion")
    if isinstance(writer, TargetWriter) and proposal.target != writer.target:
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
    found = writer.reconcile(key)
    if found is not None:
        created = _with_external_result(proposal, found)
        persist(created)
        return created, found
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
    created = _with_external_result(writing, result)
    persist(created)
    return created, result


def _with_external_result(proposal: Proposal, result: dict[str, Any]) -> Proposal:
    external_id = result.get("id")
    if external_id is None or isinstance(external_id, bool) or not str(external_id):
        raise ValueError("Externe Integration: benötigter Schlüsselpfad id fehlt")
    link = result.get("url") or result.get("html_url") or result.get("htmlLink")
    return proposal.model_copy(update={
        "status": ProposalStatus.CREATED,
        "external_id": str(external_id) if external_id is not None else None,
        "external_link": str(link) if link is not None else None,
    })

