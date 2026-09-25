"""Fachmodelle für den Kontext Verarbeitung und Dialogzustand."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID
import re

from pydantic import AnyHttpUrl, Field, field_validator, model_validator

from ._base import CalendarDate, StrictModel


class TelegramDialogState(StrictModel):
    schema_version: Literal[1] = 1
    mail_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{24}$")
    proposal_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,64}$")
    version: int | None = Field(default=None, ge=1)
    retry_required: bool = False
    question: str | None = Field(default=None, min_length=1, max_length=4000)
    normalized_answer: str | None = Field(default=None, min_length=1, max_length=4000)

    @model_validator(mode="after")
    def complete_reference(self) -> "TelegramDialogState":
        if len({self.mail_id is None, self.proposal_id is None, self.version is None}) != 1:
            raise ValueError("mail_id, proposal_id und version müssen gemeinsam gesetzt sein")
        retry_values = self.question is not None and self.normalized_answer is not None
        if self.retry_required != retry_values or (self.retry_required and self.mail_id is None):
            raise ValueError("Ein Revisions-Retry benötigt Referenz, Frage und normalisierte Antwort")
        return self


class QuestionStatus(StrEnum):
    OPEN = "open"
    ANSWERED = "answered"


class AnswerStatus(StrEnum):
    PENDING = "pending"
    VALID = "valid"
    INVALID = "invalid"


class ProposalRevisionStatus(StrEnum):
    PENDING = "pending"
    RETRY_REQUIRED = "retry_required"
    COMPLETED = "completed"
    PAUSED = "paused"


class ProposalClarificationState(StrictModel):
    """Durable trust boundary between a Telegram answer and proposal revision."""

    schema_version: Literal[4] = 4
    mail_id: str = Field(pattern=r"^[a-f0-9]{24}$")
    proposal_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    version: int = Field(ge=1)
    question: str = Field(min_length=1, max_length=4000)
    question_status: QuestionStatus = QuestionStatus.OPEN
    answer_status: AnswerStatus = AnswerStatus.PENDING
    authorized_answer: str | None = Field(default=None, min_length=1, max_length=4000)
    interpretation_status: ProposalRevisionStatus = ProposalRevisionStatus.PENDING
    interpretation_attempts: int = Field(default=0, ge=0)
    next_interpretation_at: datetime | None = None
    normalized_answer: str | None = Field(default=None, min_length=1, max_length=4000)
    proposal_revision_status: ProposalRevisionStatus = ProposalRevisionStatus.PENDING
    revision_attempts: int = Field(default=0, ge=0)
    next_revision_at: datetime | None = None

    @model_validator(mode="after")
    def consistent_answer(self) -> "ProposalClarificationState":
        answered = self.question_status == QuestionStatus.ANSWERED
        valid = self.answer_status == AnswerStatus.VALID
        if answered != valid or valid != (self.normalized_answer is not None):
            raise ValueError("Nur eine valide normalisierte Antwort darf eine Frage beantworten")
        if self.answer_status == AnswerStatus.PENDING and self.interpretation_attempts:
            if self.authorized_answer is None:
                raise ValueError("Interpretationsversuche benötigen die autorisierte Antwort")
        if self.interpretation_status != ProposalRevisionStatus.PENDING and self.authorized_answer is None:
            raise ValueError("Ein Interpretationsstatus benötigt die autorisierte Antwort")
        if self.next_interpretation_at is not None and self.authorized_answer is None:
            raise ValueError("Ein Interpretationszeitpunkt benötigt die autorisierte Antwort")
        if not answered and self.proposal_revision_status != ProposalRevisionStatus.PENDING:
            raise ValueError("Eine offene Frage darf keine Revision besitzen")
        for label, value in (("Interpretationsversuch", self.next_interpretation_at),
                             ("Revisionsversuch", self.next_revision_at)):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError(f"Der nächste {label} benötigt einen UTC-Offset")
        return self


class ProcessingSteps(StrictModel):
    preparation: Literal["pending", "completed", "skipped"] = "pending"
    relevance: Literal["pending", "completed", "skipped"] = "pending"
    summary: Literal["pending", "completed", "skipped"] = "pending"
    summary_notification: Literal["pending", "sending", "completed", "skipped"] = "pending"
    action_detection: Literal["pending", "completed", "failed", "skipped"] = "pending"
    action_router: Literal["pending", "completed", "failed", "skipped"] = "pending"
    task_extraction: Literal["pending", "completed", "failed", "skipped"] = "pending"
    event_extraction: Literal["pending", "completed", "failed", "skipped"] = "pending"
    normalization: Literal["pending", "completed", "failed", "skipped"] = "pending"
    proposal_building: Literal["pending", "completed", "failed", "skipped"] = "pending"
    proposal_notification: Literal["pending", "sending", "completed", "skipped"] = "pending"
    completion: Literal["pending", "completed", "skipped"] = "pending"


class ProcessingStage(StrEnum):
    PREPARATION = "preparation"
    RELEVANCE = "relevance"
    SUMMARY = "summary"
    SUMMARY_NOTIFICATION = "summary_notification"
    ACTION_DETECTION = "action_detection"
    ACTION_ROUTER = "action_router"
    TASK_EXTRACTION = "task_extraction"
    EVENT_EXTRACTION = "event_extraction"
    NORMALIZATION = "normalization"
    PROPOSAL_BUILDING = "proposal_building"
    PROPOSAL_NOTIFICATION = "proposal_notification"
    COMPLETION = "completion"


class ProcessingErrorCode(StrEnum):
    MIME_LIMIT_EXCEEDED = "mime_limit_exceeded"
    LLM_SCHEMA_VALIDATION_EXHAUSTED = "llm_schema_validation_exhausted"
    PROVIDER_RESPONSE_INVALID = "provider_response_invalid"
    INVALID_JSON = "invalid_json"
    SCHEMA_VALIDATION_FAILED = "schema_validation_failed"
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

    mail_id: str = Field(pattern=r"^[a-f0-9]{24}$")
    proposal_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    proposal_version: int = Field(ge=1)
    service: Literal["todoist", "google_calendar"]
    idempotency_key: str = Field(min_length=1, max_length=200)


class ProposalNotification(StrictModel):
    """Durable Telegram delivery state for one immutable proposal version."""

    proposal_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    proposal_version: int = Field(ge=1)
    status: Literal["pending", "sending", "completed"] = "pending"
