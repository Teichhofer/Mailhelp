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
    # 5.1.5: the web session that started the job ended before it ran.
    SESSION_ENDED = "session_ended"


ACTIVE = {ReanalysisStatus.QUEUED, ReanalysisStatus.RUNNING}


def adoption_pending(job: ReanalysisJob) -> bool:
    """A requested adoption that the background service has not yet run or refused."""
    return job.adoption_round is not None and job.adopted_at is None and job.adoption_error is None
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
    # 5.1.5: the web session that started the job; checked again before it runs.
    actor: str | None = Field(default=None, pattern=r"^web:.+$", max_length=200)
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
    # 5.1.3: when the checked result was adopted into the mail; adopted at most once.
    adopted_at: datetime | None = None
    # 5.1.5: an adoption requested on the web, run by the background service with the shown
    # round and versions; a refusal keeps its reason for the page.
    adoption_round: int | None = Field(default=None, ge=1)
    adoption_versions: dict[str, int] | None = None
    adoption_actor: str | None = Field(default=None, pattern=r"^web:.+$", max_length=200)
    adoption_error: str | None = Field(default=None, pattern=r"^[a-z_]{1,40}$")
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
        requested = (self.adoption_round, self.adoption_versions, self.adoption_actor)
        if any(value is not None for value in requested) and None in requested:
            raise ValueError("Eine Übernahmeanfrage nennt Runde, Versionen und Sitzung")
        if self.adoption_round is not None and self.status != ReanalysisStatus.COMPLETED:
            raise ValueError("Nur ein abgeschlossener Auftrag kann übernommen werden")
        if self.adopted_at is not None and self.status != ReanalysisStatus.COMPLETED:
            raise ValueError("Nur ein abgeschlossener Auftrag kann übernommen sein")
        if self.llm_calls > self.max_llm_calls:
            raise ValueError("Mehr Modellaufrufe als das Budget des Auftrags erlaubt")
        if any(item.source_mail_id != self.mail_id for item in self.proposals):
            raise ValueError("Vorschläge einer Nachanalyse gehören zu ihrer Mail")
        return self
