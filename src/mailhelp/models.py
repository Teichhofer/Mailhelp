"""Vertrauensgrenze und feste Schemata der Fachlogik."""
from __future__ import annotations

from datetime import datetime
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


class MailImapIdentity(StrictModel):
    folder: str = Field(min_length=1)
    uidvalidity: int = Field(ge=1)
    uid: int = Field(ge=1)


class MailState(StrictModel):
    schema_version: Literal[2] = 2
    id: str = Field(pattern=r"^[a-f0-9]{24}$")
    imap: MailImapIdentity
    steps: ProcessingSteps = Field(default_factory=ProcessingSteps)
    mail: dict[str, Any] | None = None
    relevance: Relevance | None = None
    summary: Summary | None = None
    proposals: list[Proposal] = Field(default_factory=list)
    llm_call_ids: list[str] = Field(default_factory=list)
    awaiting_relevance: bool = False
    error: dict[str, str] | None = None
