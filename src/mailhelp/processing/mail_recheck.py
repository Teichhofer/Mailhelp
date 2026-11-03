"""Deliberate re-check of a mail that was filed as irrelevant (Planung 3.6, Schritte 0.2 und 0.3).

The mail state is reset durably to an unprocessed mail of the current configuration.
The regular resumption of unfinished states then fetches the mail again from the
server, because retention may have removed its content and images, and runs the whole
pipeline. A restart in between therefore needs no special recovery.
"""
from __future__ import annotations

import re
from enum import StrEnum
from typing import TYPE_CHECKING

from .. import state_names
from ..models import MailState

if TYPE_CHECKING:
    from ..storage import JsonStore
    from .orchestrator import Orchestrator

_MAIL_ID = re.compile(r"[a-f0-9]{24}")


class RecheckOutcome(StrEnum):
    QUEUED = "queued"
    ALREADY_PENDING = "already_pending"
    NOT_FOUND = "not_found"
    NOT_IRRELEVANT = "not_irrelevant"
    # The request named an analysis round that has since changed.
    STALE = "stale"


def filed_as_irrelevant(state: MailState) -> bool:
    """Completed after a relevance check that skipped everything else and proposed nothing.

    The relevance result itself may already be removed by retention, so the steps decide.
    """
    steps = state.steps
    return (steps.completion == "completed" and steps.relevance == "completed" and steps.summary == "skipped"
            and not state.proposals)


def _load(store: JsonStore, mail_id: str) -> MailState | None:
    state = store.load_model(state_names.mail(mail_id), MailState) if _MAIL_ID.fullmatch(mail_id) else None
    return state if isinstance(state, MailState) else None


def recheck_round(store: JsonStore, mail_id: str) -> int | None:
    """The analysis round a re-check of *mail_id* must name, or ``None`` if it is not offered."""
    state = _load(store, mail_id)
    return state.analysis_round if state is not None and filed_as_irrelevant(state) else None


def request_recheck(orchestrator: Orchestrator, mail_id: str, expected_round: int | None = None) -> RecheckOutcome:
    """Queue *mail_id* for a fresh analysis; repeating the request changes nothing.

    With *expected_round*, only that analysis round may be reset (web version check).
    """
    state = _load(orchestrator.store, mail_id)
    if state is None:
        return RecheckOutcome.NOT_FOUND
    if expected_round is not None and expected_round != state.analysis_round:
        return RecheckOutcome.STALE
    if state.steps.completion == "pending":
        return RecheckOutcome.ALREADY_PENDING
    if not filed_as_irrelevant(state):
        return RecheckOutcome.NOT_IRRELEVANT
    # Identity and the duplicate decision stay; every analysis result is recomputed.
    fresh = MailState(id=state.id, imap=state.imap, created_at=state.created_at,
                      config_fingerprint=orchestrator.fingerprint_for(state.imap.account_id),
                      analysis_round=state.analysis_round + 1, display_headers=state.display_headers,
                      duplicate=state.duplicate, llm_call_ids=state.llm_call_ids)
    orchestrator.remember_topics(fresh)
    orchestrator.save(state_names.mail(state.id), fresh)
    orchestrator.logger.event("INFO", "orchestrator", "recheck_requested", mail_id=state.id,
                              round=fresh.analysis_round,
                              configuration_changed=fresh.config_fingerprint != state.config_fingerprint)
    return RecheckOutcome.QUEUED
