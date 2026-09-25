"""Fachmodelle für den Kontext Run- und Queue-Zustand."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID
import re

from pydantic import AnyHttpUrl, Field, field_validator, model_validator

from ._base import CalendarDate, StrictModel


class MailRunEntryStatus(StrEnum):
    DISCOVERED = "discovered"
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    WAITING_FOR_USER = "waiting_for_user"
    FAILED = "failed"
    SKIPPED = "skipped"


class MailRunEntry(StrictModel):
    """One immutable IMAP identity and its durable processing state."""

    account_id: str = Field(min_length=1)
    folder: str = Field(min_length=1)
    uidvalidity: int = Field(ge=1)
    uid: int = Field(ge=1)
    status: MailRunEntryStatus = MailRunEntryStatus.DISCOVERED
    analysis_terminal: Literal[
        "completed", "irrelevant", "duplicate", "failed", "skipped"
    ] | None = None
    user_action_open: bool = False
    # Stable classification only; exception text (which could contain server
    # or credential material) is deliberately not persisted.
    failure_code: Literal["imap_read_exhausted", "processing_failed"] | None = None

    @property
    def key(self) -> str:
        return f"{self.account_id}\0{self.folder}\0{self.uidvalidity}\0{self.uid}"

    @model_validator(mode="after")
    def consistent_terminal_state(self) -> "MailRunEntry":
        terminal = self.status in {
            MailRunEntryStatus.COMPLETED, MailRunEntryStatus.WAITING_FOR_USER,
            MailRunEntryStatus.FAILED, MailRunEntryStatus.SKIPPED,
        }
        if terminal != (self.analysis_terminal is not None):
            raise ValueError("Terminaler Analysezustand und Eintragszustand widersprechen sich")
        if self.user_action_open != (self.status == MailRunEntryStatus.WAITING_FOR_USER):
            raise ValueError("Eine offene Benutzeraktion benötigt waiting_for_user")
        if self.failure_code is not None and self.status != MailRunEntryStatus.FAILED:
            raise ValueError("Ein Fehlermerkmal benötigt failed")
        return self


class MailRunCounters(StrictModel):
    discovered: int = Field(default=0, ge=0)
    queued: int = Field(default=0, ge=0)
    processing: int = Field(default=0, ge=0)
    completed: int = Field(default=0, ge=0)
    waiting_for_user: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    skipped: int = Field(default=0, ge=0)


class MailRunState(StrictModel):
    """Versioned, completely materialised queue for one bounded mail run."""

    schema_version: Literal[1] = 1
    run_id: UUID
    max_mails: int | None = Field(default=None, ge=1)
    created_at: datetime
    entries: list[MailRunEntry]
    counters: MailRunCounters

    @property
    def run_complete(self) -> bool:
        """Report whether analysis reached a terminal state for the fixed queue."""
        return all(entry.analysis_terminal is not None for entry in self.entries)

    @model_validator(mode="after")
    def consistent_queue(self) -> "MailRunState":
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("Run-Erstellungszeit benötigt einen UTC-Offset")
        keys = [entry.key for entry in self.entries]
        if len(keys) != len(set(keys)):
            raise ValueError("Ein Run darf keine doppelten IMAP-Identitäten enthalten")
        expected = {status.value: 0 for status in MailRunEntryStatus}
        for entry in self.entries:
            expected[entry.status.value] += 1
        if self.counters.model_dump() != expected:
            raise ValueError("Aggregierte Run-Zähler stimmen nicht mit den Einträgen überein")
        return self


class ImapCheckpoint(StrictModel):
    schema_version: Literal[1] = 1
    uidvalidity: int | None = Field(default=None, ge=1)
    # ``uid`` remains as a human-friendly high-water mark and for backwards
    # compatibility.  Correctness is provided by the completed ranges: a high
    # UID must never imply that lower UIDs have also been handled.
    uid: int = Field(default=0, ge=0)
    start_uid: int | None = Field(default=None, ge=0)
    completed_uid_ranges: list[tuple[int, int]] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_completed_uid_ranges(self) -> "ImapCheckpoint":
        previous_end = self.start_uid or 0
        for start, end in self.completed_uid_ranges:
            if start > end or start <= previous_end:
                raise ValueError("UID-Bereiche müssen geordnet, getrennt und oberhalb der Start-UID liegen")
            previous_end = end
        return self


class TelegramOffset(StrictModel):
    schema_version: Literal[1] = 1
    offset: int = Field(default=0, ge=0)
