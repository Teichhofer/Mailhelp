"""Vertrauensgrenze und feste Schemata der Fachlogik."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ImapCheckpoint(StrictModel):
    schema_version: Literal[1] = 1
    uidvalidity: int | None = Field(default=None, ge=1)
    uid: int = Field(default=0, ge=0)


class TelegramOffset(StrictModel):
    schema_version: Literal[1] = 1
    offset: int = Field(default=0, ge=0)


class TelegramDialogState(StrictModel):
    schema_version: Literal[1] = 1
    proposal_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,64}$")
    version: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def complete_reference(self) -> "TelegramDialogState":
        if (self.proposal_id is None) != (self.version is None):
            raise ValueError("proposal_id und version müssen gemeinsam gesetzt sein")
        return self


class Relevance(StrictModel):
    decision: Literal["relevant", "irrelevant", "unclear"]
    topic_ids: list[str] = Field(default_factory=list)
    reason: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def consistent_topics(self) -> "Relevance":
        if self.decision == "irrelevant" and self.topic_ids:
            raise ValueError("Irrelevante Nachrichten dürfen keine Themen enthalten")
        if len(self.topic_ids) != len(set(self.topic_ids)):
            raise ValueError("Themen-IDs dürfen nicht doppelt vorkommen")
        return self


class RelevanceDialogStatus(StrEnum):
    OPEN = "open"
    DECIDED = "decided"


class RelevanceDialog(StrictModel):
    schema_version: Literal[1] = 1
    mail_id: str = Field(pattern=r"^[a-f0-9]{24}$")
    version: int = Field(default=1, ge=1)
    status: RelevanceDialogStatus = RelevanceDialogStatus.OPEN
    decision: Literal["relevant", "irrelevant"] | None = None
    telegram_offset: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def consistent_decision(self) -> "RelevanceDialog":
        decided = self.status == RelevanceDialogStatus.DECIDED
        has_complete_decision = self.decision is not None and self.telegram_offset is not None
        has_partial_decision = (self.decision is None) != (self.telegram_offset is None)
        if has_partial_decision or decided != has_complete_decision:
            raise ValueError("Entscheidung und Telegram-Offset müssen gemeinsam gesetzt sein")
        return self


class Summary(StrictModel):
    sentences: list[str] = Field(min_length=2, max_length=4)
    deadlines: list[str] = Field(default_factory=list)


class ProposalKind(StrEnum):
    TASK = "task"
    EVENT = "event"


class ProposalStatus(StrEnum):
    NEEDS_CLARIFICATION = "needs_clarification"
    PENDING_CONFIRMATION = "pending_confirmation"
    CONFIRMED = "confirmed"
    WRITING = "writing"
    CREATED = "created"
    REJECTED = "rejected"
    FAILED = "failed"
    UNCERTAIN = "uncertain"


class Proposal(StrictModel):
    schema_version: Literal[1] = 1
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    version: int = Field(ge=1)
    kind: ProposalKind
    title: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=4000)
    evidence: str = Field(min_length=1, max_length=2000)
    source_mail_id: str = Field(min_length=1, max_length=64)
    open_questions: list[str] = Field(default_factory=list)
    due: datetime | None = None
    start: datetime | None = None
    end: datetime | None = None
    all_day: bool = False
    location: str | None = Field(default=None, max_length=1000)
    target: str = Field(min_length=1, max_length=500)
    status: ProposalStatus = ProposalStatus.PENDING_CONFIRMATION
    external_id: str | None = Field(default=None, max_length=500)
    external_link: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def complete_event(self) -> "Proposal":
        if self.kind == ProposalKind.EVENT and not self.open_questions and (self.start is None or self.end is None):
            raise ValueError("Ein vollständiger Termin benötigt Beginn und Ende")
        if self.end is not None and self.start is not None and self.end <= self.start:
            raise ValueError("Terminende muss nach dem Beginn liegen")
        if self.kind == ProposalKind.TASK and (self.start is not None or self.end is not None or self.all_day):
            raise ValueError("Aufgaben dürfen keine Kalenderzeit enthalten")
        return self


class Actions(StrictModel):
    proposals: list[Proposal] = Field(default_factory=list, max_length=20)


class ProcessingSteps(StrictModel):
    preparation: Literal["pending", "completed", "skipped"] = "pending"
    relevance: Literal["pending", "completed", "skipped"] = "pending"
    summary: Literal["pending", "completed", "skipped"] = "pending"
    action_detection: Literal["pending", "completed", "skipped"] = "pending"
    notification: Literal["pending", "completed", "skipped"] = "pending"
    completion: Literal["pending", "completed", "skipped"] = "pending"


class ProcessingStage(StrEnum):
    PREPARATION = "preparation"
    RELEVANCE = "relevance"
    SUMMARY = "summary"
    ACTION_DETECTION = "action_detection"
    NOTIFICATION = "notification"
    COMPLETION = "completion"


class ProcessingErrorCode(StrEnum):
    MIME_LIMIT_EXCEEDED = "mime_limit_exceeded"
    LLM_SCHEMA_VALIDATION_EXHAUSTED = "llm_schema_validation_exhausted"
    PERMANENT_ADAPTER_ERROR = "permanent_adapter_error"
    LLM_RATE_LIMITED = "llm_rate_limited"
    INTERNAL_ERROR = "internal_error"


class ProcessingError(StrictModel):
    """Persistierbarer Fehler ohne Inhalte oder technische Ausnahmeinformationen."""

    code: ProcessingErrorCode
    stage: ProcessingStage
    occurred_at: datetime
    retryable: bool | None = None
    notification_marked_at: datetime | None = None


class ValidationIssue(StrictModel):
    """Content-free, durable description of a rejected validation boundary."""

    stage: ProcessingStage
    code: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9_]+$")
    path: list[str | int] = Field(default_factory=list, max_length=20)
    occurred_at: datetime


class WriteAttemptReference(StrictModel):
    """Stable reference from a mail to a separately persisted write generation."""

    proposal_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    proposal_version: int = Field(ge=1)
    service: Literal["todoist", "google_calendar"]
    idempotency_key: str = Field(min_length=1, max_length=200)


class MailImapIdentity(StrictModel):
    folder: str = Field(min_length=1)
    uidvalidity: int = Field(ge=1)
    uid: int = Field(ge=1)


class MailState(StrictModel):
    schema_version: Literal[4] = 4
    id: str = Field(pattern=r"^[a-f0-9]{24}$")
    imap: MailImapIdentity
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    config_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    steps: ProcessingSteps = Field(default_factory=ProcessingSteps)
    mail: dict[str, Any] | None = None
    relevance: Relevance | None = None
    summary: Summary | None = None
    proposals: list[Proposal] = Field(default_factory=list)
    llm_call_ids: list[str] = Field(default_factory=list)
    validation_errors: list[ValidationIssue] = Field(default_factory=list)
    write_attempts: list[WriteAttemptReference] = Field(default_factory=list)
    awaiting_relevance: bool = False
    relevance_dialog: RelevanceDialog | None = None
    error: ProcessingError | None = None
    deferred_until: datetime | None = None

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
