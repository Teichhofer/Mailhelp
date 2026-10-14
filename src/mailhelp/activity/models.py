"""Stored models of an activity report (schema version 1)."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from ..domain._base import StrictModel

_TEXT = r"^[^\x00-\x08\x0b-\x1f\x7f]*$"
_CLOCK = r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$"
REPORT_ID = r"^[a-f0-9]{32}$"
# Excluded by default: they hold drafts, junk and deleted mail, not activities.
EXCLUDED_ROLES = frozenset({"trash", "junk", "drafts"})


class ReportDefinition(StrictModel):
    """What the user asked for; fixed once the report has started."""

    title: str = Field(min_length=1, max_length=120, pattern=_TEXT)
    topic: str = Field(min_length=10, max_length=2000, pattern=_TEXT)
    since: date
    until: date
    folders: list[str] = Field(min_length=1, max_length=50)
    # The configured mailbox the folders belong to (3.1); reports before 3.1 read mailbox 1.
    mailbox: int = Field(default=1, ge=1, le=99)
    include_sent: bool = True
    skip_automated: bool = False

    @model_validator(mode="after")
    def bounded_period(self) -> ReportDefinition:
        if self.since > self.until:
            raise ValueError("Der Zeitraum beginnt nach seinem Ende")
        if (self.until - self.since).days > 3 * 366:
            raise ValueError("Der Zeitraum darf höchstens drei Jahre umfassen")
        if len(set(self.folders)) != len(self.folders):
            raise ValueError("Jeder Ordner darf nur einmal vorkommen")
        return self


class ReportStatus(StrEnum):
    COUNTING = "counting"      # listing mail identities, no content read
    READY = "ready"            # waits for the explicit, paid start
    RUNNING = "running"
    PAUSED = "paused"
    DONE = "done"
    CANCELLED = "cancelled"
    FAILED = "failed"


ACTIVE = frozenset({ReportStatus.COUNTING, ReportStatus.RUNNING})


class FolderProgress(StrictModel):
    """The mail of one folder within the period, processed in UID order."""

    folder: str = Field(min_length=1, max_length=500)
    sent: bool = False
    uidvalidity: int | None = None
    uids: list[int] = Field(default_factory=list)
    done: int = Field(default=0, ge=0)


class ReportCounters(StrictModel):
    listed: int = 0
    read: int = 0
    skipped_sender: int = 0
    skipped_other: int = 0
    duplicates: int = 0
    evaluated: int = 0
    relevant: int = 0
    events: int = 0
    llm_calls: int = 0
    failed: int = 0


class ReportEvent(StrictModel):
    """One dated activity; user corrections are kept apart from the model's values."""

    id: str = Field(pattern=r"^e[0-9]{1,3}$")
    title: str = Field(min_length=1, max_length=200, pattern=_TEXT)
    day: date
    start_time: str | None = Field(default=None, pattern=_CLOCK)
    end_time: str | None = Field(default=None, pattern=_CLOCK)
    location: str | None = Field(default=None, max_length=300, pattern=_TEXT)
    evidence: str = Field(default="", max_length=500)
    cancelled: bool = False
    out_of_range: bool = False
    excluded: bool = False
    manual: bool = False
    edited: bool = False


class ReportMail(StrictModel):
    key: str = Field(min_length=1, max_length=600)
    folder: str
    uid: int
    message_id: str = ""
    received_at: datetime
    sender: str = Field(default="", max_length=500)
    subject: str = Field(default="", max_length=500)
    text: str = ""
    attachments: list[str] = Field(default_factory=list)
    skipped: Literal["sender", "automated", "size", "suspicious", "duplicate", "unreadable"] | None = None
    relevant: bool | None = None
    confidence: Literal["high", "medium", "low"] | None = None
    reason: str = Field(default="", max_length=500)
    relevance_call_id: str | None = None
    events_call_id: str | None = None
    events_extracted: bool = False
    events: list[ReportEvent] = Field(default_factory=list)
    # The user's verdict overrides the model's in views and export.
    user_relevant: bool | None = None
    text_removed: bool = False
    # An unusable model answer is recorded, never retried automatically (cost).
    failed_step: Literal["relevance", "events"] | None = None
    accounted: bool = False
    cached_input: bool = False

    @property
    def counts_as_relevant(self) -> bool:
        return self.user_relevant if self.user_relevant is not None else bool(self.relevant)


class ActivityReport(StrictModel):
    schema_version: Literal[1] = 1
    id: str = Field(pattern=REPORT_ID)
    version: int = Field(default=1, ge=1)
    definition: ReportDefinition
    status: ReportStatus = ReportStatus.COUNTING
    message: str = Field(default="", max_length=500)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    # Creation order for reports with the same created_at (coarse Windows clock);
    # 0 for reports written before 2.3.1.
    sequence: int = Field(default=0, ge=0)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    blocked_addresses: list[str] = Field(default_factory=list)
    blocked_domains: list[str] = Field(default_factory=list)
    folders: list[FolderProgress] = Field(default_factory=list)
    counters: ReportCounters = Field(default_factory=ReportCounters)
    # Mails the user marked relevant after a negative verdict; their dates are extracted next.
    pending_extractions: list[str] = Field(default_factory=list)
    operations: dict[str, str] = Field(default_factory=dict)
    counting_failures: int = 0
    authorized_actor: str | None = None
    repetitions: dict[str, str] = Field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(len(item.uids) for item in self.folders)

    @property
    def processed(self) -> int:
        return sum(item.done for item in self.folders)

    def in_range(self, day: date) -> bool:
        """Announced dates may follow the period; older ones may be reported late."""
        return (self.definition.since - timedelta(days=30) <= day
                <= self.definition.until + timedelta(days=365))


__all__ = ["ACTIVE", "EXCLUDED_ROLES", "REPORT_ID", "ActivityReport", "FolderProgress", "ReportCounters",
           "ReportDefinition", "ReportEvent", "ReportMail", "ReportStatus"]
