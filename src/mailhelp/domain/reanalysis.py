"""5.1 (R3): a deliberate re-analysis of one mail as a durable, readable job.

A job is bound to the mail's original mailbox identity and to the analysis round
it started from. Each paid step stores its result before the next one begins, so
a restart continues without repeating finished model calls. The job never changes
the mail state: its proposals are candidates for a checked adoption (5.1.3).
"""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from ._base import StrictModel
from .duplicate import MailImapIdentity
from .extraction import ActionRoute, EventExtraction, TaskExtraction
from .proposal import Proposal


class ReanalysisStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ReanalysisError(StrEnum):
    MAIL_MISSING = "mail_missing"
    UIDVALIDITY_CHANGED = "uidvalidity_changed"
    MAILBOX_UNAVAILABLE = "mailbox_unavailable"
    BUDGET_EXHAUSTED = "budget_exhausted"
    MODEL_FAILED = "model_failed"
    STALE_ROUND = "stale_round"


ACTIVE = {ReanalysisStatus.QUEUED, ReanalysisStatus.RUNNING}
FINISHED = {ReanalysisStatus.COMPLETED, ReanalysisStatus.FAILED, ReanalysisStatus.CANCELLED}

# The steps in order; "route" to "events" are the paid model calls. Reading the mail
# is no stage: its content is never copied into the job and is read again after a restart.
Stage = Literal["route", "tasks", "events", "build", "done"]


class ReanalysisJob(StrictModel):
    schema_version: Literal[1] = 1
    id: str = Field(pattern=r"^[a-f0-9]{32}$")
    mail_id: str = Field(pattern=r"^[a-f0-9]{24}$")
    # The analysis round of the mail when the job started; a newer round makes it stale.
    source_round: int = Field(ge=1)
    config_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    imap: MailImapIdentity
    # The user's short note for this analysis; untrusted input, never a write approval.
    hint: str | None = Field(default=None, min_length=1, max_length=500)
    key_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    status: ReanalysisStatus = ReanalysisStatus.QUEUED
    stage: Stage = "route"
    attempts: int = Field(default=0, ge=0)
    max_attempts: int = Field(ge=1)
    max_llm_calls: int = Field(ge=1)
    llm_calls: int = Field(default=0, ge=0)
    call_ids: list[str] = Field(default_factory=list, max_length=50)
    action_route: ActionRoute | None = None
    task_extraction: TaskExtraction | None = None
    event_extraction: EventExtraction | None = None
    proposals: list[Proposal] = Field(default_factory=list, max_length=40)
    error: ReanalysisError | None = None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def consistent(self) -> ReanalysisJob:
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("Zeitstempel müssen eine Zeitzone enthalten")
        if (self.status == ReanalysisStatus.FAILED) != (self.error is not None):
            raise ValueError("Genau ein fehlgeschlagener Auftrag nennt einen Fehler")
        if self.status == ReanalysisStatus.COMPLETED and self.stage != "done":
            raise ValueError("Ein abgeschlossener Auftrag hat alle Schritte durchlaufen")
        if self.llm_calls > self.max_llm_calls:
            raise ValueError("Mehr Modellaufrufe als das Budget des Auftrags erlaubt")
        if any(item.source_mail_id != self.mail_id for item in self.proposals):
            raise ValueError("Vorschläge einer Nachanalyse gehören zu ihrer Mail")
        return self
