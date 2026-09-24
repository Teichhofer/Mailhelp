"""Vertrauensgrenze und feste Schemata der Fachlogik."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from enum import StrEnum
from uuid import UUID
from typing import Annotated, Any, Literal
import re
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator, model_validator

CalendarDate = date


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


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


class IrrelevantSenders(StrictModel):
    """Durable, human-readable sender prefilter learned from rejected topics."""

    schema_version: Literal[1] = 1
    addresses: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_entries(self) -> "IrrelevantSenders":
        address_pattern = re.compile(r"^[^@\s<>]+@[^@\s<>]+$")
        domain_pattern = re.compile(
            r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
            r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
        )
        if (self.addresses != sorted(set(self.addresses))
                or any(address != address.casefold() or not address_pattern.fullmatch(address)
                       for address in self.addresses)):
            raise ValueError("Absenderadressen müssen gültig, kleingeschrieben und eindeutig sein")
        if (self.domains != sorted(set(self.domains))
                or any(domain != domain.casefold() or not domain_pattern.fullmatch(domain)
                       for domain in self.domains)):
            raise ValueError("Absenderdomains müssen gültig, kleingeschrieben und eindeutig sein")
        return self


class TelegramDialogState(StrictModel):
    schema_version: Literal[1] = 1
    mail_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{24}$")
    proposal_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,64}$")
    version: int | None = Field(default=None, ge=1)
    retry_required: bool = False
    question: str | None = Field(default=None, min_length=1, max_length=4000)
    normalized_answer: str | None = Field(default=None, min_length=1, max_length=4000)

    @model_validator(mode="after")
    def complete_reference(self) -> "TelegramDialogState":
        if len({self.mail_id is None, self.proposal_id is None, self.version is None}) != 1:
            raise ValueError("mail_id, proposal_id und version müssen gemeinsam gesetzt sein")
        retry_values = self.question is not None and self.normalized_answer is not None
        if self.retry_required != retry_values or (self.retry_required and self.mail_id is None):
            raise ValueError("Ein Revisions-Retry benötigt Referenz, Frage und normalisierte Antwort")
        return self


class QuestionStatus(StrEnum):
    OPEN = "open"
    ANSWERED = "answered"


class AnswerStatus(StrEnum):
    PENDING = "pending"
    VALID = "valid"
    INVALID = "invalid"


class ProposalRevisionStatus(StrEnum):
    PENDING = "pending"
    RETRY_REQUIRED = "retry_required"
    COMPLETED = "completed"
    PAUSED = "paused"


class ProposalClarificationState(StrictModel):
    """Durable trust boundary between a Telegram answer and proposal revision."""

    schema_version: Literal[4] = 4
    mail_id: str = Field(pattern=r"^[a-f0-9]{24}$")
    proposal_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    version: int = Field(ge=1)
    question: str = Field(min_length=1, max_length=4000)
    question_status: QuestionStatus = QuestionStatus.OPEN
    answer_status: AnswerStatus = AnswerStatus.PENDING
    authorized_answer: str | None = Field(default=None, min_length=1, max_length=4000)
    interpretation_status: ProposalRevisionStatus = ProposalRevisionStatus.PENDING
    interpretation_attempts: int = Field(default=0, ge=0)
    next_interpretation_at: datetime | None = None
    normalized_answer: str | None = Field(default=None, min_length=1, max_length=4000)
    proposal_revision_status: ProposalRevisionStatus = ProposalRevisionStatus.PENDING
    revision_attempts: int = Field(default=0, ge=0)
    next_revision_at: datetime | None = None

    @model_validator(mode="after")
    def consistent_answer(self) -> "ProposalClarificationState":
        answered = self.question_status == QuestionStatus.ANSWERED
        valid = self.answer_status == AnswerStatus.VALID
        if answered != valid or valid != (self.normalized_answer is not None):
            raise ValueError("Nur eine valide normalisierte Antwort darf eine Frage beantworten")
        if self.answer_status == AnswerStatus.PENDING and self.interpretation_attempts:
            if self.authorized_answer is None:
                raise ValueError("Interpretationsversuche benötigen die autorisierte Antwort")
        if self.interpretation_status != ProposalRevisionStatus.PENDING and self.authorized_answer is None:
            raise ValueError("Ein Interpretationsstatus benötigt die autorisierte Antwort")
        if self.next_interpretation_at is not None and self.authorized_answer is None:
            raise ValueError("Ein Interpretationszeitpunkt benötigt die autorisierte Antwort")
        if not answered and self.proposal_revision_status != ProposalRevisionStatus.PENDING:
            raise ValueError("Eine offene Frage darf keine Revision besitzen")
        for label, value in (("Interpretationsversuch", self.next_interpretation_at),
                             ("Revisionsversuch", self.next_revision_at)):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError(f"Der nächste {label} benötigt einen UTC-Offset")
        return self


class Relevance(StrictModel):
    decision: Literal["relevant", "irrelevant", "unclear"]
    # Deliberately no default: OpenRouter derives its structured-output schema
    # from this model, so every provider response must contain the field even
    # when the correct value is an empty list.
    topic_ids: list[str]
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
    sentences: list[str] = Field(min_length=1, max_length=2)
    deadlines: list[str] = Field(default_factory=list)


class TelegramAnswerInterpretation(StrictModel):
    """Bounded result of comparing a Telegram reply with its open question."""

    usable: bool
    normalized_answer: str | None = Field(default=None, min_length=1, max_length=4000)
    reason: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def answer_matches_decision(self) -> "TelegramAnswerInterpretation":
        if self.usable != (self.normalized_answer is not None):
            raise ValueError("Nur eine verwendbare Antwort darf einen normalisierten Wert enthalten")
        return self


class TelegramClarification(StrictModel):
    """Safe, concrete follow-up rendered for an insufficient Telegram reply."""

    message: str = Field(min_length=1, max_length=4000)


class CalendarDuplicateDecision(StrictModel):
    """Bounded LLM verdict for one time-overlapping calendar entry."""

    same_event: bool
    missing_fields: list[Literal["description", "location", "video_link"]] = Field(
        default_factory=list, max_length=3
    )
    reason: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def fields_require_same_event(self) -> "CalendarDuplicateDecision":
        if not self.same_event and self.missing_fields:
            raise ValueError("Fehlende Felder sind nur beim gleichen Termin zulässig")
        if len(self.missing_fields) != len(set(self.missing_fields)):
            raise ValueError("Fehlende Felder dürfen nicht doppelt vorkommen")
        return self


class LearnedCategory(StrictModel):
    """One deliberately non-authoritative category proposed by an LLM."""

    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=1000)
    examples: list[str] = Field(default_factory=list, max_length=20)


class MailClassification(StrictModel):
    categories: list[LearnedCategory] = Field(min_length=1, max_length=20)


class AbstractCategories(StrictModel):
    categories: list[LearnedCategory] = Field(default_factory=list, max_length=50)


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


class TimeRequirement(StrEnum):
    """Explicit mail evidence about whether an event needs clock times."""

    ALL_DAY = "all_day"
    TIMED = "timed"
    REQUIRED_UNKNOWN = "required_unknown"


class TemporalResolutionStatus(StrEnum):
    """Application-owned resolution state for an extracted date expression."""

    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    CONFLICTING = "conflicting"


class YearSource(StrEnum):
    """Why a normalized date has the year that it has."""

    EXPLICIT_MAIL = "explicit_mail"
    MAIL_CONTEXT = "mail_context"
    TELEGRAM = "telegram"
    UNKNOWN = "unknown"


class TemporalFact(StrictModel):
    """Structured date fact created at the raw-extraction trust boundary."""

    raw_text: str | None = Field(default=None, max_length=500)
    normalized_date: CalendarDate | None = None
    year_source: YearSource = YearSource.UNKNOWN
    status: TemporalResolutionStatus

    @model_validator(mode="after")
    def consistent_resolution(self) -> "TemporalFact":
        if (self.status == TemporalResolutionStatus.RESOLVED) != (self.normalized_date is not None):
            raise ValueError("Nur ein aufgelöster Zeitfakt darf ein normalisiertes Datum enthalten")
        if self.normalized_date is None and self.year_source != YearSource.UNKNOWN:
            raise ValueError("Ein ungelöster Zeitfakt darf keine Jahresherkunft behaupten")
        return self


class ExtractedEvent(StrictModel):
    """Unnormalised event facts; missing facts remain explicitly absent."""

    title: str = Field(min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=4000)
    evidence: str = Field(min_length=1, max_length=2000)
    date_text: str | None = Field(default=None, min_length=1, max_length=500)
    time_text: str | None = Field(default=None, min_length=1, max_length=500)
    end_time_text: str | None = Field(default=None, min_length=1, max_length=500)
    timezone_offset_text: str | None = None
    time_requirement: TimeRequirement
    location: str | None = Field(default=None, min_length=1, max_length=1000)
    video_link: AnyHttpUrl | None = Field(default=None, max_length=2000)
    responsibility: Literal["user", "other", "unclear"]
    certainty: Literal["certain", "uncertain", "contradictory"]
    classification: Literal["new", "non_binding", "already_completed", "change", "cancellation", "recurring", "unsupported"]

    @field_validator("timezone_offset_text")
    @classmethod
    def explicit_timezone_offset(cls, value: str | None) -> str | None:
        """Accept only an explicit, bounded UTC offset copied from the mail."""
        if value is None:
            return None
        match = re.fullmatch(r"UTC([+-])(\d{2}):(\d{2})", value)
        if match is None:
            raise ValueError("Zeitzonen-Offset muss exakt UTC±HH:MM entsprechen")
        hours, minutes = int(match.group(2)), int(match.group(3))
        if minutes > 59 or hours > 14 or (hours == 14 and minutes != 0):
            raise ValueError("Zeitzonen-Offset muss im Bereich UTC-14:00 bis UTC+14:00 liegen")
        return value


class EventExtraction(StrictModel):
    schema_version: Literal[1] = 1
    events: list[ExtractedEvent] = Field(default_factory=list, max_length=20)


class ExtractionCountConflict(StrictModel):
    """Durable evidence that a router count disagreed with an extraction."""

    schema_version: Literal[1] = 1
    category: Literal["task", "event"]
    expected_count: int = Field(ge=0, le=20)
    actual_count: int = Field(ge=0, le=20)
    router_call_id: str = Field(min_length=1, max_length=500)
    extractor_call_id: str = Field(min_length=1, max_length=500)
    notification_marked_at: datetime | None = None

    @model_validator(mode="after")
    def validates_real_conflict(self) -> "ExtractionCountConflict":
        if self.expected_count == self.actual_count:
            raise ValueError("Ein Zählerkonflikt benötigt unterschiedliche Werte")
        if (self.notification_marked_at is not None
                and (self.notification_marked_at.tzinfo is None
                     or self.notification_marked_at.utcoffset() is None)):
            raise ValueError("Der Benachrichtigungszeitpunkt benötigt einen UTC-Offset")
        return self


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


class KnownTemporalFacts(StrictModel):
    """Valid temporal facts retained while an event interval is incomplete."""

    date: CalendarDate | None = None
    start: datetime | None = None

    @model_validator(mode="after")
    def validate_facts(self) -> "KnownTemporalFacts":
        if self.start is not None and (self.start.tzinfo is None or self.start.utcoffset() is None):
            raise ValueError("Eine bekannte Beginnzeit benötigt einen eindeutigen UTC-Offset")
        if self.date is None and self.start is None:
            raise ValueError("Mindestens ein bekannter Zeitfakt ist erforderlich")
        if self.date is not None and self.start is not None and self.start.date() != self.date:
            raise ValueError("Bekanntes Datum und bekannte Beginnzeit müssen zusammenpassen")
        return self


class ActionLedgerEntry(StrictModel):
    """Human-readable record of an action successfully created externally."""

    action_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    mail_id: str = Field(pattern=r"^[a-f0-9]{24}$")
    proposal_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    proposal_version: int = Field(ge=1)
    kind: ProposalKind
    title: str = Field(min_length=1, max_length=500)
    target: str = Field(min_length=1, max_length=500)
    external_id: str | None = Field(default=None, max_length=500)
    external_link: str | None = Field(default=None, max_length=2000)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ActionLedger(StrictModel):
    """Durable, validated bookkeeping for completed calendar/task writes."""

    schema_version: Literal[1] = 1
    entries: list[ActionLedgerEntry] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_proposal_versions(self) -> "ActionLedger":
        keys = [(item.mail_id, item.proposal_id, item.proposal_version) for item in self.entries]
        if len(keys) != len(set(keys)):
            raise ValueError("Angelegte Aktionen dürfen nicht doppelt verbucht werden")
        return self


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
    known_temporal_facts: KnownTemporalFacts | None = None
    temporal_fact: TemporalFact | None = None
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
        if self.kind != ProposalKind.EVENT and self.known_temporal_facts is not None:
            raise ValueError("Nur Termine dürfen bekannte Zeitfakten enthalten")
        if self.kind != ProposalKind.EVENT:
            return self
        if not self.open_questions and (self.start is None or self.end is None):
            raise ValueError("Ein vollständiger Termin benötigt Beginn und Ende")
        if self.known_temporal_facts is not None and (self.start is not None or self.end is not None):
            raise ValueError("Unvollständige Zeitfakten dürfen nicht mit Terminintervallen gemischt werden")
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


class ProposalRevisionChanges(StrictModel):
    """Closed set of business fields which an LLM may change in a revision."""

    responsibility: ProposalResponsibility | None = None
    certainty: ProposalCertainty | None = None
    classification: ProposalClassification | None = None
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=4000)
    due: date | datetime | None = None
    start: date | datetime | None = None
    end: date | datetime | None = None
    # An application-owned date fact may be supplied by the bounded Telegram
    # parser.  It is translated into ``known_temporal_facts`` below and is not
    # copied blindly onto Proposal.
    temporal_date: CalendarDate | None = None
    all_day: bool | None = None
    location: str | None = Field(default=None, max_length=1000)
    video_link: AnyHttpUrl | None = Field(default=None, max_length=2000)
    target: str | None = Field(default=None, min_length=1, max_length=500)


class ProposalRevisionDelta(StrictModel):
    """Minimal LLM output: the answered question and explicitly changed fields."""

    answered_question: str = Field(min_length=1, max_length=4000)
    changes: ProposalRevisionChanges


def _required_revision_questions(proposal: Proposal) -> list[str]:
    """Derive invariant clarification questions from the revised business facts."""
    questions: list[str] = []
    if proposal.kind == ProposalKind.EVENT:
        known_start = (proposal.known_temporal_facts.start
                       if proposal.known_temporal_facts is not None else None)
        if proposal.start is None and known_start is None:
            questions.append("Wann beginnt der Termin?")
        if proposal.end is None:
            questions.append("Wann endet der Termin?")
    if proposal.responsibility != ProposalResponsibility.USER:
        questions.append("Ist die Nutzerin oder der Nutzer für diesen Eintrag zuständig?")
    if proposal.certainty == ProposalCertainty.UNCERTAIN:
        questions.append("Ist die extrahierte Information sicher belegt?")
    elif proposal.certainty == ProposalCertainty.CONTRADICTORY:
        questions.append("Wie soll der Widerspruch in den Angaben aufgelöst werden?")
    classification = {
        ProposalClassification.NON_BINDING: "Soll der nicht bindende Hinweis dennoch als neuer Eintrag angelegt werden?",
        ProposalClassification.ALREADY_COMPLETED: "Der Eintrag ist bereits abgeschlossen und nicht direkt ausführbar.",
        ProposalClassification.CHANGE: "Welcher bestehende Eintrag soll geändert werden?",
        ProposalClassification.CANCELLATION: "Welcher bestehende Eintrag soll storniert werden?",
        ProposalClassification.RECURRING: "Wiederkehrende Einträge werden nicht automatisch angelegt.",
        ProposalClassification.UNSUPPORTED: "Diese Art von Eintrag wird nicht unterstützt.",
    }.get(proposal.classification)
    if classification:
        questions.append(classification)
    return questions


def apply_proposal_revision(previous: Proposal, delta: ProposalRevisionDelta) -> Proposal:
    """Apply a validated delta locally; identity, lifecycle and version stay authoritative."""
    if delta.answered_question not in previous.open_questions:
        raise ValueError("Die beantwortete Frage ist im Vorschlag nicht offen")
    changes = delta.changes.model_dump(exclude_unset=True)
    temporal_date = changes.pop("temporal_date", None)
    resolved_day = (previous.temporal_fact.normalized_date
                    if previous.temporal_fact is not None else None)
    known = previous.known_temporal_facts
    if known is not None and known.date is not None:
        resolved_day = known.date
    if temporal_date is not None:
        if resolved_day is not None and temporal_date != resolved_day:
            raise ValueError(
                f"temporal_date widerspricht dem validierten Datum {resolved_day.isoformat()}")
        resolved_day = temporal_date
        if known is None and previous.temporal_fact is None and previous.start is None:
            known = KnownTemporalFacts(date=temporal_date)
            changes["known_temporal_facts"] = known
    for field in ("due", "start"):
        value = changes.get(field)
        value_day = value.date() if isinstance(value, datetime) else value
        if resolved_day is not None and value is not None and value_day != resolved_day:
            raise ValueError(
                f"{field} widerspricht dem validierten Datum {resolved_day.isoformat()}")
    end = changes.get("end")
    if resolved_day is not None and end is not None:
        end_day = end.date() if isinstance(end, datetime) else end
        allowed_end_days = {resolved_day}
        if not previous.all_day and isinstance(end, datetime):
            allowed_end_days.add(resolved_day + timedelta(days=1))
        if end_day not in allowed_end_days:
            raise ValueError(
                f"end widerspricht dem validierten Datum {resolved_day.isoformat()}")

    confirmed_start = (known.start if known is not None else previous.start)
    if "start" in changes and confirmed_start is not None and changes["start"] != confirmed_start:
        raise ValueError("Ein bestätigter Terminbeginn darf nicht verändert werden")

    # Incomplete event intervals retain their application-owned facts separately.
    # This avoids mixing a half interval with ``known_temporal_facts`` while still
    # allowing the next question to ask only for the missing end.
    if known is not None:
        start = changes.get("start", known.start)
        end = changes.get("end")
        if start is not None and end is not None:
            changes.update(start=start, end=end, known_temporal_facts=None)
        elif "start" in changes:
            changes.pop("start")
            changes["known_temporal_facts"] = known.model_copy(update={"start": start})
    remaining = list(previous.open_questions)
    remaining.remove(delta.answered_question)
    provisional = previous.model_copy(update=changes)
    for question in _required_revision_questions(provisional):
        if question not in remaining:
            remaining.append(question)
    changes.update(
        version=previous.version + 1,
        open_questions=remaining,
        status=(ProposalStatus.NEEDS_CLARIFICATION if remaining
                else ProposalStatus.PENDING_CONFIRMATION),
    )
    return Proposal.model_validate(previous.model_copy(update=changes).model_dump())


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
    action_router_call_id: str | None = Field(default=None, min_length=1, max_length=500)
    task_extraction: TaskExtraction | None = None
    event_extraction: EventExtraction | None = None
    extraction_count_conflicts: list[ExtractionCountConflict] = Field(default_factory=list)
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
        conflict_keys = [(item.category, item.router_call_id, item.extractor_call_id)
                         for item in self.extraction_count_conflicts]
        if len(conflict_keys) != len(set(conflict_keys)):
            raise ValueError("Zählerkonflikte dürfen nicht doppelt vorkommen")
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
