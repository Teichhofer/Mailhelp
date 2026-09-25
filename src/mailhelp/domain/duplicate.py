"""Fachmodelle für den Kontext Duplikaterkennung."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID
import re

from pydantic import AnyHttpUrl, Field, field_validator, model_validator

from ._base import CalendarDate, StrictModel


class MailImapIdentity(StrictModel):
    account_id: str = Field(pattern=r"^[a-f0-9]{24}$")
    folder: str = Field(min_length=1)
    uidvalidity: int = Field(ge=1)
    uid: int = Field(ge=1)


class DuplicateIndexEntry(StrictModel):
    """Minimal, content-free identity material retained for duplicate checks."""

    mail_id: str = Field(pattern=r"^[a-f0-9]{24}$")
    imap: MailImapIdentity
    message_ids: list[Annotated[str, Field(
        max_length=998, pattern=r"^<[^<>@\s]+@[^<>@\s]+>$"
    )]] = Field(default_factory=list, max_length=20)
    content_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def unique_message_ids(self) -> "DuplicateIndexEntry":
        if len(self.message_ids) != len(set(self.message_ids)):
            raise ValueError("Normalisierte Message-IDs dürfen nicht doppelt vorkommen")
        return self


class DuplicateIndex(StrictModel):
    schema_version: Literal[1] = 1
    entries: list[DuplicateIndexEntry] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_technical_identity(self) -> "DuplicateIndex":
        identities = [(entry.imap.account_id, entry.imap.folder, entry.imap.uidvalidity, entry.imap.uid)
                      for entry in self.entries]
        if len(identities) != len(set(identities)):
            raise ValueError("Technische IMAP-Identitäten dürfen nicht doppelt vorkommen")
        return self


class DuplicateDecision(StrictModel):
    outcome: Literal["new", "duplicate", "ambiguous"]
    reason: Literal["no_match", "same_message", "missing_message_id", "multiple_message_ids",
                    "message_id_reused", "fingerprint_collision", "candidate_incomplete"]
    previous_mail_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{24}$")

    @model_validator(mode="after")
    def reference_matches_outcome(self) -> "DuplicateDecision":
        if (self.outcome == "new") == (self.previous_mail_id is not None):
            raise ValueError("Nur Treffer benötigen einen früheren Mailbezug")
        return self
