"""Channel-neutral review commands.

Every command names its source, the authorized person, the exact proposal
version it refers to and an idempotency key.  A channel adapter (Telegram or
the web) only translates its input into such a command.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..domain.proposal_sources import ProposalReference
from .editing import ProposalEditPatch


class CommandSource(StrEnum):
    TELEGRAM = "telegram"
    WEB = "web"


class CommandKind(StrEnum):
    CONFIRM = "confirm"
    CONFIRM_DUPLICATE = "confirm_duplicate"
    REJECT = "reject"
    START_CLARIFICATION = "clarify"
    ANSWER = "answer"
    CANCEL_CLARIFICATION = "cancel"
    RELEVANCE = "relevance"
    EDIT = "edit_fields"
    MERGE = "merge_proposals"
    SEPARATE = "separate_proposals"
    RESTORE = "restore_proposal"
    DEFAULTS = "reapply_defaults"
    RECHECK = "recheck_proposal"
    RETARGET = "retarget_proposal"


PROPOSAL_KINDS = frozenset(set(CommandKind) - {CommandKind.RELEVANCE})


class ReviewCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: CommandKind
    source: CommandSource
    # "telegram:<user>:<chat>" or "web:<session id>"; set by the channel adapter.
    actor: str = Field(min_length=1, max_length=200)
    mail_id: str = Field(pattern=r"^[a-f0-9]{24}$")
    proposal_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,64}$")
    version: int = Field(ge=1)
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")
    text: str | None = Field(default=None, min_length=1, max_length=4000)
    decision: Literal["relevant", "irrelevant"] | None = None
    # Telegram update offset that makes a replayed relevance answer detectable.
    replay_offset: int | None = Field(default=None, ge=1)
    patch: ProposalEditPatch | None = None
    target_ref: ProposalReference | None = None
    target_version: int | None = Field(default=None, ge=1)
    proposal_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    target_profile: int | None = Field(default=None, ge=1, le=99)

    @model_validator(mode="after")
    def complete(self) -> ReviewCommand:
        if self.kind in {CommandKind.MERGE, CommandKind.SEPARATE}:
            if self.target_ref is None or self.target_version is None:
                raise ValueError("Zusammenführung benötigt die Zielversion")
        elif self.target_ref is not None or self.target_version is not None:
            raise ValueError("Nur Zusammenführung enthält ein Ziel")
        if (self.kind in {CommandKind.RESTORE, CommandKind.DEFAULTS, CommandKind.RETARGET}) != (
            self.proposal_hash is not None
        ):
            raise ValueError("Wiederherstellung und Dauerannahme benötigen den geprüften Hash")
        if (self.kind == CommandKind.RETARGET) != (self.target_profile is not None):
            raise ValueError("Zielwechsel benötigt die gewählte Profilnummer")
        if (self.kind == CommandKind.EDIT) != (self.patch is not None):
            raise ValueError("Nur strukturierte Bearbeitung enthält Felder")
        if (self.kind in PROPOSAL_KINDS) != (self.proposal_id is not None):
            raise ValueError("Nur Vorschlagsbefehle benötigen eine Vorschlags-ID")
        if (self.kind == CommandKind.ANSWER) != (self.text is not None and bool(self.text.strip())):
            raise ValueError("Nur eine Antwort enthält einen nicht leeren Text")
        if (self.kind == CommandKind.RELEVANCE) != (self.decision is not None):
            raise ValueError("Nur eine Relevanzentscheidung enthält eine Entscheidung")
        return self


__all__ = ["CommandKind", "CommandSource", "PROPOSAL_KINDS", "ReviewCommand"]
