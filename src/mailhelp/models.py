"""Vertrauensgrenze und feste Schemata der Fachlogik."""
from __future__ import annotations

from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Annotated, Any, Literal
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


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


class TelegramDialogState(StrictModel):
    schema_version: Literal[1] = 1
    mail_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{24}$")
    proposal_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,64}$")
    version: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def complete_reference(self) -> "TelegramDialogState":
        if len({self.mail_id is None, self.proposal_id is None, self.version is None}) != 1:
            raise ValueError("mail_id, proposal_id und version müssen gemeinsam gesetzt sein")
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


class RelevanceDialogStatus(StrEnum):
    OPEN = "open"
    DECIDED = "decided"


class RelevanceDialog(StrictModel):
    schema_version: Literal[1] = 1
    mail_id: str = Field(pattern=r"^[a-f0-9]{24}$")
    version: int = Field(default=1, ge=1)
    status: RelevanceDialogStatus = RelevanceDialogStatus.OPEN
    decision: Literal["relevant", "irrelevant"] | None = None
    telegram_offset: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def consistent_decision(self) -> "RelevanceDialog":
        decided = self.status == RelevanceDialogStatus.DECIDED
        has_complete_decision = self.decision is not None and self.telegram_offset is not None
        has_partial_decision = (self.decision is None) != (self.telegram_offset is None)
        if has_partial_decision or decided != has_complete_decision:
            raise ValueError("Entscheidung und Telegram-Offset müssen gemeinsam gesetzt sein")
        return self


class Summary(StrictModel):
    sentences: list[str] = Field(min_length=2, max_length=4)
    deadlines: list[str] = Field(default_factory=list)


class ActionRoute(StrictModel):
    """Bounded action classification before detailed extraction.

    For ``unclear`` the counters are merely the number of possible task/event
    candidates seen by the router.  They may independently be zero; no action
    is extracted until the ambiguity has been resolved by a person.
    """

    action_state: Literal["none", "task", "event", "task_and_event", "unclear"]
    task_count: int = Field(ge=0, le=20)
    event_count: int = Field(ge=0, le=20)
    reason: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def consistent_counts(self) -> "ActionRoute":
        expected = {
            "none": self.task_count == 0 and self.event_count == 0,
            "task": self.task_count > 0 and self.event_count == 0,
            "event": self.task_count == 0 and self.event_count > 0,
            "task_and_event": self.task_count > 0 and self.event_count > 0,
            "unclear": True,
        }
        if not expected[self.action_state]:
            raise ValueError("Aktionszustand und Zähler widersprechen sich")
        return self


class ExtractedTask(StrictModel):
    """Unnormalised task facts copied from an untrusted message."""

    title: str = Field(min_length=1, max_length=500)
    description: str = Field(max_length=4000)
    evidence: str = Field(min_length=1, max_length=2000)
    responsibility: Literal["user", "other", "unclear"]
    certainty: Literal["certain", "uncertain", "contradictory"]
    classification: Literal["new", "non_binding", "already_completed", "change", "cancellation", "recurring", "unsupported"]
    due_text: str | None = Field(default=None, min_length=1, max_length=500)


class TaskExtraction(StrictModel):
    schema_version: Literal[1] = 1
    tasks: list[ExtractedTask] = Field(default_factory=list, max_length=20)


class ExtractedEvent(StrictModel):
    """Unnormalised event facts; missing facts remain explicitly absent."""

    title: str = Field(min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=4000)
    evidence: str = Field(min_length=1, max_length=2000)
    date_text: str | None = Field(default=None, min_length=1, max_length=500)
    time_text: str | None = Field(default=None, min_length=1, max_length=500)
    end_time_text: str | None = Field(default=None, min_length=1, max_length=500)
    location: str | None = Field(default=None, min_length=1, max_length=1000)
    video_link: AnyHttpUrl | None = Field(default=None, max_length=2000)
    responsibility: Literal["user", "other", "unclear"]
    certainty: Literal["certain", "uncertain", "contradictory"]
    classification: Literal["new", "non_binding", "already_completed", "change", "cancellation", "recurring", "unsupported"]


class EventExtraction(StrictModel):
    schema_version: Literal[1] = 1
    events: list[ExtractedEvent] = Field(default_factory=list, max_length=20)


class ProposalKind(StrEnum):
    TASK = "task"
    EVENT = "event"


class ProposalResponsibility(StrEnum):
    USER = "user"
    OTHER = "other"
    UNCLEAR = "unclear"


class ProposalCertainty(StrEnum):
    CERTAIN = "certain"
    UNCERTAIN = "uncertain"
    CONTRADICTORY = "contradictory"


class ProposalClassification(StrEnum):
    NEW = "new"
    NON_BINDING = "non_binding"
    ALREADY_COMPLETED = "already_completed"
    CHANGE = "change"
    CANCELLATION = "cancellation"
    RECURRING = "recurring"
    UNSUPPORTED = "unsupported"


class ProposalStatus(StrEnum):
    NEEDS_CLARIFICATION = "needs_clarification"
    PENDING_CONFIRMATION = "pending_confirmation"
    CONFIRMED = "confirmed"
    WRITING = "writing"
    CREATED = "created"
    SIMULATED = "simulated"
    REJECTED = "rejected"
    FAILED = "failed"
    UNCERTAIN = "uncertain"


class Proposal(StrictModel):
    schema_version: Literal[2] = 2
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    version: int = Field(ge=1)
    kind: ProposalKind
    responsibility: ProposalResponsibility
    certainty: ProposalCertainty
    classification: ProposalClassification
    title: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=4000)
    evidence: str = Field(min_length=1, max_length=2000)
    source_mail_id: str = Field(min_length=1, max_length=64)
    open_questions: list[str] = Field(default_factory=list)
    # A date-only deadline and an instant are deliberately represented by the
    # same, strictly checked union.  Keeping ``date`` in the model prevents a
    # deadline such as ``2026-10-01`` from silently becoming midnight.
    due: date | datetime | None = None
    start: date | datetime | None = None
    end: date | datetime | None = None
    all_day: bool = False
    location: str | None = Field(default=None, max_length=1000)
    video_link: AnyHttpUrl | None = Field(default=None, max_length=2000)
    target: str = Field(min_length=1, max_length=500)
    status: ProposalStatus = ProposalStatus.PENDING_CONFIRMATION
    external_id: str | None = Field(default=None, max_length=500)
    external_link: str | None = Field(default=None, max_length=2000)
    uncertain_notified: bool = False
    simulation_notified: bool = False

    @model_validator(mode="after")
    def validate_consistency(self) -> "Proposal":
        if self.status == ProposalStatus.SIMULATED and (self.external_id is not None or self.external_link is not None):
            raise ValueError("Ein simulierter Vorschlag darf kein externes Ergebnis enthalten")
        if self.simulation_notified and self.status != ProposalStatus.SIMULATED:
            raise ValueError("Eine Simulation darf nur im simulierten Zustand als gemeldet markiert werden")
        ready = (self.classification == ProposalClassification.NEW and
                 self.responsibility == ProposalResponsibility.USER and
                 self.certainty == ProposalCertainty.CERTAIN and not self.open_questions)
        if self.status == ProposalStatus.PENDING_CONFIRMATION and not ready:
            raise ValueError("Nur vollständige neue Vorschläge dürfen bestätigt werden")
        if self.kind == ProposalKind.TASK and (self.start is not None or self.end is not None or self.all_day):
            raise ValueError("Aufgaben dürfen keine Kalenderzeit enthalten")
        if self.kind == ProposalKind.TASK and isinstance(self.due, datetime) and (
                self.due.tzinfo is None or self.due.utcoffset() is None):
            raise ValueError("Zeitgebundene Aufgabenfristen benötigen einen eindeutigen UTC-Offset")
        if self.kind == ProposalKind.EVENT and self.due is not None:
            raise ValueError("Termine dürfen keine Aufgabenfrist enthalten")
        if self.kind != ProposalKind.EVENT:
            return self
        if not self.open_questions and (self.start is None or self.end is None):
            raise ValueError("Ein vollständiger Termin benötigt Beginn und Ende")
        values = (self.start, self.end)
        if self.all_day:
            if any(isinstance(value, datetime) for value in values if value is not None):
                raise ValueError("Ganztägige Termine benötigen reine Datumswerte")
        else:
            if any(not isinstance(value, datetime) for value in values if value is not None):
                raise ValueError("Zeitgebundene Termine benötigen Datums- und Zeitwerte")
            if any(value.tzinfo is None or value.utcoffset() is None for value in values if isinstance(value, datetime)):
                raise ValueError("Zeitgebundene Termine benötigen einen eindeutigen UTC-Offset")
        if self.end is not None and self.start is not None and self.end <= self.start:
            raise ValueError("Terminende muss nach dem Beginn liegen")
        return self


class Actions(StrictModel):
    proposals: list[Proposal] = Field(default_factory=list, max_length=20)


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


class DisplayHeaders(StrictModel):
    """Sanitized, bounded headers retained for user-facing notifications."""

    sender: str = Field(max_length=500)
    subject: str = Field(max_length=500)


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


class ProposalNotification(StrictModel):
    """Durable Telegram delivery state for one immutable proposal version."""

    proposal_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    proposal_version: int = Field(ge=1)
    status: Literal["pending", "sending", "completed"] = "pending"


class MailState(StrictModel):
    schema_version: Literal[9] = 9
    id: str = Field(pattern=r"^[a-f0-9]{24}$")
    imap: MailImapIdentity
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    config_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    steps: ProcessingSteps = Field(default_factory=ProcessingSteps)
    mail: dict[str, Any] | None = None
    display_headers: DisplayHeaders | None = None
    relevance: Relevance | None = None
    summary: Summary | None = None
    action_route: ActionRoute | None = None
    task_extraction: TaskExtraction | None = None
    event_extraction: EventExtraction | None = None
    normalized_proposals: list[Proposal] = Field(default_factory=list)
    proposals: list[Proposal] = Field(default_factory=list)
    proposal_notifications: list[ProposalNotification] = Field(default_factory=list)
    llm_call_ids: list[str] = Field(default_factory=list)
    validation_errors: list[ValidationIssue] = Field(default_factory=list)
    write_attempts: list[WriteAttemptReference] = Field(default_factory=list)
    awaiting_relevance: bool = False
    relevance_dialog: RelevanceDialog | None = None
    error: ProcessingError | None = None
    deferred_until: datetime | None = None
    duplicate: DuplicateDecision | None = None

    @model_validator(mode="after")
    def consistent_relevance_dialog(self) -> "MailState":
        """Keep a dialog bound to this mail and its explicit waiting state."""
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("Zeitstempel müssen eine Zeitzone enthalten")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at darf nicht vor created_at liegen")
        write_keys = [(item.proposal_id, item.proposal_version, item.service) for item in self.write_attempts]
        if len(write_keys) != len(set(write_keys)):
            raise ValueError("Schreibversuche dürfen nicht doppelt referenziert werden")
        if any(item.mail_id != self.id for item in self.write_attempts):
            raise ValueError("Schreibversuche müssen zur Mail gehören")
        notification_keys = [(item.proposal_id, item.proposal_version)
                             for item in self.proposal_notifications]
        if len(notification_keys) != len(set(notification_keys)):
            raise ValueError("Vorschlagsmeldungen dürfen nicht doppelt vorkommen")
        proposal_keys = {(item.id, item.version) for item in self.proposals}
        if any(key not in proposal_keys for key in notification_keys):
            raise ValueError("Vorschlagsmeldungen müssen zu einer Vorschlagsversion gehören")
        if self.relevance_dialog is None:
            if self.awaiting_relevance:
                raise ValueError("Wartende Relevanz benötigt einen Dialog")
            return self
        if self.relevance_dialog.mail_id != self.id:
            raise ValueError("Relevanzdialog gehört nicht zu dieser Mail")
        is_open = self.relevance_dialog.status == RelevanceDialogStatus.OPEN
        if self.awaiting_relevance != is_open:
            raise ValueError("Dialogstatus und wartender Relevanzzustand widersprechen sich")
        return self
