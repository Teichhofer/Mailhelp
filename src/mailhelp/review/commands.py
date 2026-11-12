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
    ALREADY_DONE = "already_done"
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
    # A mail filed as irrelevant is analysed again; version is its analysis round (3.6.2).
    RECHECK_MAIL = "recheck_mail"
    SERIES_ANSWER = "series_answer"
    SERIES_CONFIRM = "series_confirm"
    # 4.6: pick one of the calendar entries a change or cancellation may refer to.
    CHOOSE_EVENT = "choose_calendar_event"
    # 5.2: read a written entry again; never writes.
    VERIFY_ENTRY = "verify_entry"
    # 5.9.3: take one value of a field conflict; a new version, never a write.
    CHOOSE_VARIANT = "choose_conflict_variant"


# Commands on a whole mail instead of one proposal.
MAIL_KINDS = frozenset({CommandKind.RELEVANCE, CommandKind.RECHECK_MAIL})
PROPOSAL_KINDS = frozenset(set(CommandKind) - MAIL_KINDS)


class SeriesMember(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    proposal_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    version: int = Field(ge=1)


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
    members: tuple[SeriesMember, ...] = Field(default=(), max_length=100)
    endpoint: Literal["start", "end"] = "start"
    # Position in the displayed version's calendar_candidates; the version binds it.
    candidate: int | None = Field(default=None, ge=0, le=9)
    # 5.9.3: Proposal.field_conflicts[].id and one of its variants, bound by the version.
    conflict_id: str | None = Field(default=None, pattern=r"^[a-z_]{1,20}-[0-9]{1,6}$")
    variant: Literal["a", "b", "c"] | None = None

    @model_validator(mode="after")
    def candidate_only_for_a_choice(self) -> ReviewCommand:
        if (self.kind == CommandKind.CHOOSE_EVENT) != (self.candidate is not None):
            raise ValueError("Nur die Terminauswahl enthält einen Kandidaten")
        choice = self.kind == CommandKind.CHOOSE_VARIANT
        if choice != (self.conflict_id is not None) or choice != (self.variant is not None):
            raise ValueError("Nur die Auswahl eines Werts nennt Widerspruch und Variante")
        return self

    @model_validator(mode="after")
    def complete(self) -> ReviewCommand:
        if self.endpoint == "end" and self.kind != CommandKind.SERIES_ANSWER:
            raise ValueError("Ein gemeinsames Ende gehört nur zu einer Serienantwort")
        if self.kind in {CommandKind.SERIES_ANSWER, CommandKind.SERIES_CONFIRM}:
            if not self.members or len({item.proposal_id for item in self.members}) != len(self.members):
                raise ValueError("Serie benötigt eine eindeutige Liste angezeigter Vorschlagsversionen")
            if (self.proposal_id, self.version) != (self.members[0].proposal_id, self.members[0].version):
                raise ValueError("Serienbefehl muss an den ersten angezeigten Eintrag gebunden sein")
        elif self.members:
            raise ValueError("Nur Serienbefehle enthalten eine Versionsliste")
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
        answering = self.kind in {CommandKind.ANSWER, CommandKind.SERIES_ANSWER}
        if answering != (self.text is not None and bool(self.text.strip())):
            raise ValueError("Nur eine Antwort enthält einen nicht leeren Text")
        if (self.kind == CommandKind.RELEVANCE) != (self.decision is not None):
            raise ValueError("Nur eine Relevanzentscheidung enthält eine Entscheidung")
        return self


__all__ = ["MAIL_KINDS", "CommandKind", "CommandSource", "PROPOSAL_KINDS", "ReviewCommand"]
