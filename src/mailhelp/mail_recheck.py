"""Deliberate re-check of a mail that was filed as irrelevant (Planung 3.6, Schritt 0.2).

The mail state is reset durably to an unprocessed mail of the current configuration.
The regular resumption of unfinished states then fetches the mail again from the
server, because retention may have removed its content and images, and runs the whole
pipeline. A restart in between therefore needs no special recovery.
"""
from __future__ import annotations

import re
from enum import StrEnum
from typing import TYPE_CHECKING

from . import state_names
from .models import MailState

if TYPE_CHECKING:
    from .orchestrator import Orchestrator

_MAIL_ID = re.compile(r"[a-f0-9]{24}")


class RecheckOutcome(StrEnum):
    QUEUED = "queued"
    ALREADY_PENDING = "already_pending"
    NOT_FOUND = "not_found"
    NOT_IRRELEVANT = "not_irrelevant"


def filed_as_irrelevant(state: MailState) -> bool:
    """Completed after a relevance check that skipped everything else and proposed nothing.

    The relevance result itself may already be removed by retention, so the steps decide.
    """
    steps = state.steps
    return (steps.completion == "completed" and steps.relevance == "completed" and steps.summary == "skipped"
            and not state.proposals)


def request_recheck(orchestrator: Orchestrator, mail_id: str) -> RecheckOutcome:
    """Queue *mail_id* for a fresh analysis; repeating the request changes nothing."""
    state = (orchestrator.store.load_model(state_names.mail(mail_id), MailState)
             if _MAIL_ID.fullmatch(mail_id) else None)
    if not isinstance(state, MailState):
        return RecheckOutcome.NOT_FOUND
    if state.steps.completion == "pending":
        return RecheckOutcome.ALREADY_PENDING
    if not filed_as_irrelevant(state):
        return RecheckOutcome.NOT_IRRELEVANT
    # Identity and the duplicate decision stay; every analysis result is recomputed.
    fresh = MailState(id=state.id, imap=state.imap, created_at=state.created_at,
                      config_fingerprint=orchestrator.fingerprint_for(state.imap.account_id),
                      display_headers=state.display_headers, duplicate=state.duplicate,
                      llm_call_ids=state.llm_call_ids)
    orchestrator.remember_topics(fresh)
    orchestrator.save(state_names.mail(state.id), fresh)
    orchestrator.logger.event("INFO", "orchestrator", "recheck_requested", mail_id=state.id,
                              configuration_changed=fresh.config_fingerprint != state.config_fingerprint)
    return RecheckOutcome.QUEUED
