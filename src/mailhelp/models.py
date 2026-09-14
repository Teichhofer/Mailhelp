"""Vertrauensgrenze und feste Schemata der Fachlogik."""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Relevance(StrictModel):
    decision: Literal["relevant", "irrelevant", "unclear"]
    topic_ids: list[str] = Field(default_factory=list)
    reason: str = Field(min_length=1, max_length=1000)


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
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    version: int = Field(ge=1)
    kind: ProposalKind
    title: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=4000)
    evidence: str = Field(min_length=1, max_length=2000)
    open_questions: list[str] = Field(default_factory=list)
    due: datetime | None = None
    start: datetime | None = None
    end: datetime | None = None
    all_day: bool = False
    location: str | None = Field(default=None, max_length=1000)
    status: ProposalStatus = ProposalStatus.PENDING_CONFIRMATION

    @model_validator(mode="after")
    def complete_event(self) -> "Proposal":
        if self.kind == ProposalKind.EVENT and not self.open_questions and (self.start is None or self.end is None):
            raise ValueError("Ein vollständiger Termin benötigt Beginn und Ende")
        if self.end is not None and self.start is not None and self.end <= self.start:
            raise ValueError("Terminende muss nach dem Beginn liegen")
        return self


class Actions(StrictModel):
    proposals: list[Proposal] = Field(default_factory=list, max_length=20)
