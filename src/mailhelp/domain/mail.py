"""Fachmodelle für den Kontext vollständige Mailzustände."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID
import re

from pydantic import AnyHttpUrl, Field, field_validator, model_validator

from ._base import CalendarDate, StrictModel
from .duplicate import DuplicateDecision, MailImapIdentity
from .extraction import ActionRoute, EventExtraction, ExtractionCountConflict, Summary, TaskExtraction
from .processing import (ProcessingError, ProcessingSteps, ProposalNotification,
                         ValidationIssue, WriteAttemptReference)
from .proposal import Proposal
from .relevance import Relevance, RelevanceDialog, RelevanceDialogStatus


class DisplayHeaders(StrictModel):
    """Sanitized, bounded headers retained for user-facing notifications."""

    sender: str = Field(max_length=500)
    subject: str = Field(max_length=500)


class MailState(StrictModel):
    schema_version: Literal[9] = 9
    id: str = Field(pattern=r"^[a-f0-9]{24}$")
    imap: MailImapIdentity
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    config_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    steps: ProcessingSteps = Field(default_factory=ProcessingSteps)
    mail: dict[str, Any] | None = None
    display_headers: DisplayHeaders | None = None
    relevance: Relevance | None = None
    summary: Summary | None = None
    action_route: ActionRoute | None = None
    action_router_call_id: str | None = Field(default=None, min_length=1, max_length=500)
    task_extraction: TaskExtraction | None = None
    event_extraction: EventExtraction | None = None
    extraction_count_conflicts: list[ExtractionCountConflict] = Field(default_factory=list)
    normalized_proposals: list[Proposal] = Field(default_factory=list)
    proposals: list[Proposal] = Field(default_factory=list)
    proposal_notifications: list[ProposalNotification] = Field(default_factory=list)
    llm_call_ids: list[str] = Field(default_factory=list)
    validation_errors: list[ValidationIssue] = Field(default_factory=list)
    write_attempts: list[WriteAttemptReference] = Field(default_factory=list)
    awaiting_relevance: bool = False
    relevance_dialog: RelevanceDialog | None = None
    error: ProcessingError | None = None
    deferred_until: datetime | None = None
    duplicate: DuplicateDecision | None = None

    @model_validator(mode="after")
    def consistent_relevance_dialog(self) -> "MailState":
        """Keep a dialog bound to this mail and its explicit waiting state."""
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("Zeitstempel müssen eine Zeitzone enthalten")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at darf nicht vor created_at liegen")
        write_keys = [(item.proposal_id, item.proposal_version, item.service) for item in self.write_attempts]
        if len(write_keys) != len(set(write_keys)):
            raise ValueError("Schreibversuche dürfen nicht doppelt referenziert werden")
        if any(item.mail_id != self.id for item in self.write_attempts):
            raise ValueError("Schreibversuche müssen zur Mail gehören")
        conflict_keys = [(item.category, item.router_call_id, item.extractor_call_id)
                         for item in self.extraction_count_conflicts]
        if len(conflict_keys) != len(set(conflict_keys)):
            raise ValueError("Zählerkonflikte dürfen nicht doppelt vorkommen")
        notification_keys = [(item.proposal_id, item.proposal_version)
                             for item in self.proposal_notifications]
        if len(notification_keys) != len(set(notification_keys)):
            raise ValueError("Vorschlagsmeldungen dürfen nicht doppelt vorkommen")
        proposal_keys = {(item.id, item.version) for item in self.proposals}
        if any(key not in proposal_keys for key in notification_keys):
            raise ValueError("Vorschlagsmeldungen müssen zu einer Vorschlagsversion gehören")
        if self.relevance_dialog is None:
            if self.awaiting_relevance:
                raise ValueError("Wartende Relevanz benötigt einen Dialog")
            return self
        if self.relevance_dialog.mail_id != self.id:
            raise ValueError("Relevanzdialog gehört nicht zu dieser Mail")
        is_open = self.relevance_dialog.status == RelevanceDialogStatus.OPEN
        if self.awaiting_relevance != is_open:
            raise ValueError("Dialogstatus und wartender Relevanzzustand widersprechen sich")
        return self
