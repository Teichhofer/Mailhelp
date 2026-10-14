"""Fachmodelle für den Kontext Vorschläge und Revisionen."""
from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from typing import Any, Literal

from pydantic import AnyHttpUrl, Field, model_validator

from ._base import CalendarDate, StrictModel
from .proposal_sources import ProposalReference, ProposalSource
from .temporal import TemporalFact


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
    ALREADY_EXISTS = "already_exists"
    CONFIRMED = "confirmed"
    WRITING = "writing"
    CREATED = "created"
    SIMULATED = "simulated"
    REJECTED = "rejected"
    FAILED = "failed"
    UNCERTAIN = "uncertain"
    MERGED = "merged"


class DuplicateSource(StrEnum):
    ACTION_LEDGER = "action_ledger"
    GOOGLE_CALENDAR = "google_calendar"
    TODOIST = "todoist"


class DuplicateMatchInfo(StrictModel):
    source: DuplicateSource
    external_id: str | None = Field(default=None, max_length=500)
    external_link: str | None = Field(default=None, max_length=2000)
    matched_title: str = Field(min_length=1, max_length=500)
    matched_time: datetime | date | None = None
    similarity_score: float | None = Field(default=None, ge=0.0, le=1.0)
    details: str = Field(default="", max_length=1000)
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class KnownTemporalFacts(StrictModel):
    """Valid temporal facts retained while an event interval is incomplete."""

    date: CalendarDate | None = None
    start: datetime | None = None
    # A clock explicitly present in the mail can be retained before an
    # ambiguous/yearless calendar date has been resolved.
    start_time: time | None = None

    @model_validator(mode="after")
    def validate_facts(self) -> KnownTemporalFacts:
        if self.start is not None and (self.start.tzinfo is None or self.start.utcoffset() is None):
            raise ValueError("Eine bekannte Beginnzeit benötigt einen eindeutigen UTC-Offset")
        if self.date is None and self.start is None and self.start_time is None:
            raise ValueError("Mindestens ein bekannter Zeitfakt ist erforderlich")
        if self.date is not None and self.start is not None and self.start.date() != self.date:
            raise ValueError("Bekanntes Datum und bekannte Beginnzeit müssen zusammenpassen")
        if self.start is not None and self.start_time is not None:
            raise ValueError("Beginnzeit darf nicht zugleich vollständig und datumslos gespeichert sein")
        return self


class ActionLedgerEntry(StrictModel):
    """Human-readable record of an action successfully created externally."""

    action_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    action_key_version: Literal[1, 2] = 1
    mail_id: str = Field(pattern=r"^[a-f0-9]{24}$")
    proposal_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    proposal_version: int = Field(ge=1)
    kind: ProposalKind
    title: str = Field(min_length=1, max_length=500)
    target: str = Field(min_length=1, max_length=500)
    external_id: str | None = Field(default=None, max_length=500)
    external_link: str | None = Field(default=None, max_length=2000)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ActionLedger(StrictModel):
    """Durable, validated bookkeeping for completed calendar/task writes."""

    schema_version: Literal[1] = 1
    entries: list[ActionLedgerEntry] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_proposal_versions(self) -> ActionLedger:
        keys = [(item.mail_id, item.proposal_id, item.proposal_version) for item in self.entries]
        if len(keys) != len(set(keys)):
            raise ValueError("Angelegte Aktionen dürfen nicht doppelt verbucht werden")
        return self


class Proposal(StrictModel):
    schema_version: Literal[3] = 3
    target_profile: int = Field(default=1, ge=1, le=99)

    @model_validator(mode="before")
    @classmethod
    def upgrade_profile(cls, value: object) -> object:
        if isinstance(value, dict) and value.get("schema_version") == 2:
            return {**value, "schema_version": 3, "target_profile": 1}
        return value
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
    duration_minutes: int | None = Field(default=None, ge=1, le=1440)
    duration_is_upper_bound: bool = False
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
    # Set only by the deterministic Telegram fallback confirmation.  Keeping
    # the original classification makes the write boundary able to distinguish
    # a genuine new event from an explicitly authorised change fallback.
    explicit_create_fallback_confirmed: bool = False
    # A non-binding classification remains intact when the user explicitly
    # requests creation.  This decision is separate from the LLM-owned
    # classification and can only be set by the deterministic Telegram path.
    explicit_non_binding_create_confirmed: bool = False
    # Application-owned, version-bound authorization for a deliberate duplicate.
    explicit_duplicate_create_confirmed_version: int | None = Field(default=None, ge=1)
    duplicate_match: DuplicateMatchInfo | None = None
    target_event_id: str | None = Field(default=None, max_length=500)
    time_changes: list[str] = Field(default_factory=list)
    is_cancellation: bool = False
    meeting_mode: Literal["video", "in_person", "hybrid", "unknown"] = "unknown"
    end_origin: Literal["unknown", "mail_end", "mail_duration", "calendar", "standard", "manual"] = "unknown"
    default_duration_minutes: int | None = Field(default=None, ge=1, le=1440)
    sources: list[ProposalSource] = Field(default_factory=list, max_length=1000)
    protected_fields: list[str] = Field(default_factory=list, max_length=30)
    canonical_ref: ProposalReference | None = None
    target_provider: str = Field(default="", max_length=30)
    matching_candidates: list[ProposalReference] = Field(default_factory=list, max_length=50)
    pending_sources: list[ProposalReference] = Field(default_factory=list, max_length=50)
    merge_review_required: bool = False
    duplicate_check_failed: bool = False
    separated_from: list[ProposalReference] = Field(default_factory=list, max_length=50)

    @property
    def is_creatable(self) -> bool:
        """Shared business authorization rule for validation and write adapters."""
        if self.duplicate_check_failed:
            return False
        classification_allowed = (
            self.classification == ProposalClassification.NEW or
            (self.classification == ProposalClassification.CHANGE and
             (self.explicit_create_fallback_confirmed or self.target_event_id is not None)) or
            (self.classification == ProposalClassification.CANCELLATION and
             self.target_event_id is not None) or
            (self.classification == ProposalClassification.NON_BINDING and
             self.explicit_non_binding_create_confirmed)
        )
        return (self.status != ProposalStatus.MERGED and not self.pending_sources
                and not self.matching_candidates and classification_allowed and
                self.responsibility == ProposalResponsibility.USER and
                self.certainty == ProposalCertainty.CERTAIN)

    @model_validator(mode="after")
    def validate_consistency(self) -> Proposal:
        if self.merge_review_required and self.canonical_ref is None:
            raise ValueError("Ein ungeprüfter Zusatz benötigt seine kanonische Referenz")
        if self.default_duration_minutes is not None and (
                self.end_origin != "standard" or self.kind != ProposalKind.EVENT or
                self.start is None or self.end is None or self.all_day):
            raise ValueError("Standarddauer benötigt ein zeitgebundenes Terminintervall und Herkunft")
        if (self.status == ProposalStatus.MERGED) != (self.canonical_ref is not None):
            raise ValueError("Zusammengeführte Vorschläge benötigen eine kanonische Referenz")
        if self.canonical_ref is not None and (self.canonical_ref.mail_id, self.canonical_ref.proposal_id) == (
                self.source_mail_id, self.id):
            raise ValueError("Ein Vorschlag darf nicht auf sich selbst verweisen")
        if self.status == ProposalStatus.SIMULATED and (self.external_id is not None or self.external_link is not None):
            raise ValueError("Ein simulierter Vorschlag darf kein externes Ergebnis enthalten")
        if self.simulation_notified and self.status != ProposalStatus.SIMULATED:
            raise ValueError("Eine Simulation darf nur im simulierten Zustand als gemeldet markiert werden")
        if self.kind == ProposalKind.TASK and self.target_event_id is not None:
            raise ValueError("Nur Termine unterstützen Terminaktualisierungen")
        if self.is_cancellation and self.target_event_id is None:
            raise ValueError("Eine Stornierung erfordert eine Ziel-Event-ID")
        if self.status == ProposalStatus.ALREADY_EXISTS and self.open_questions:
            raise ValueError("Ein bereits vorhandener Eintrag darf keine offenen Fragen enthalten")
        if self.status == ProposalStatus.ALREADY_EXISTS and self.duplicate_match is None:
            raise ValueError("Ein bereits vorhandener Eintrag benötigt Duplikat-Informationen")
        ready = self.is_creatable and not self.open_questions
        if self.status == ProposalStatus.PENDING_CONFIRMATION and not ready:
            raise ValueError("Nur vollständige neue Vorschläge dürfen bestätigt werden")


        if self.kind == ProposalKind.TASK and (self.start is not None or self.end is not None or self.all_day):
            raise ValueError("Aufgaben dürfen keine Kalenderzeit enthalten")
        if self.kind != ProposalKind.EVENT and (self.duration_minutes is not None or
                                                self.duration_is_upper_bound):
            raise ValueError("Nur Termine dürfen eine Dauer enthalten")
        if self.duration_is_upper_bound and self.duration_minutes is None:
            raise ValueError("Eine Dauer-Obergrenze benötigt eine Dauer")
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
            if any(value.tzinfo is None or value.utcoffset() is None
                   for value in values if isinstance(value, datetime)):
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
    explicit_create_fallback_confirmed: bool | None = None
    explicit_non_binding_create_confirmed: bool | None = None
    target_event_id: str | None = Field(default=None, max_length=500)
    time_changes: list[str] | None = None
    is_cancellation: bool | None = None


class ProposalRevisionDelta(StrictModel):
    """Minimal LLM output: the answered question and explicitly changed fields."""

    answered_question: str = Field(min_length=1, max_length=4000)
    changes: ProposalRevisionChanges


def required_revision_questions(proposal: Proposal) -> list[str]:
    """Derive invariant clarification questions from the revised business facts."""
    questions: list[str] = []
    if proposal.duplicate_check_failed:
        questions.append("Dublettenprüfung nicht verfügbar; vor einer Anlage erneut prüfen.")
    if proposal.pending_sources or proposal.matching_candidates:
        questions.append("Zuordnung der zusätzlichen Quelle prüfen.")
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
        ProposalClassification.NON_BINDING: (
            None if proposal.explicit_non_binding_create_confirmed
            else "Soll der nicht bindende Hinweis dennoch als neuer Eintrag angelegt werden?"
        ),
        ProposalClassification.ALREADY_COMPLETED: "Der Eintrag ist bereits abgeschlossen und nicht direkt ausführbar.",
        ProposalClassification.CHANGE: (None if (proposal.explicit_create_fallback_confirmed
                                                 or proposal.target_event_id is not None)
                                        else "Welcher bestehende Eintrag soll geändert werden?"),
        ProposalClassification.CANCELLATION: (None if proposal.target_event_id is not None
                                              else "Welcher bestehende Eintrag soll storniert werden?"),
        ProposalClassification.RECURRING: "Wiederkehrende Einträge werden nicht automatisch angelegt.",
        ProposalClassification.UNSUPPORTED: "Diese Art von Eintrag wird nicht unterstützt.",
    }.get(proposal.classification)
    if classification:
        questions.append(classification)
    return questions


def invalidate_creation_permissions(proposal: Proposal) -> Proposal:
    """A material local revision needs fresh consent for every special creation."""
    candidate = proposal.model_copy(update={"explicit_create_fallback_confirmed": False,
        "explicit_non_binding_create_confirmed": False, "explicit_duplicate_create_confirmed_version": None})
    if candidate.status in {ProposalStatus.PENDING_CONFIRMATION, ProposalStatus.NEEDS_CLARIFICATION}:
        questions = list(dict.fromkeys([*candidate.open_questions, *required_revision_questions(candidate)]))
        candidate = candidate.model_copy(update={"open_questions": questions,
            "status": ProposalStatus.NEEDS_CLARIFICATION if questions else ProposalStatus.PENDING_CONFIRMATION})
    return Proposal.model_validate(candidate.model_dump())


def _check_revision_permissions(previous: Proposal, changes: dict[str, Any],
                                allow_create_fallback: bool) -> None:
    if "explicit_create_fallback_confirmed" in changes and not allow_create_fallback:
        raise ValueError("Die Ersatz-Neuanlage erfordert eine deterministische ausdrückliche Bestätigung")
    if "explicit_non_binding_create_confirmed" in changes and not allow_create_fallback:
        raise ValueError("Ein nicht bindender Hinweis erfordert eine deterministische ausdrückliche Bestätigung")
    if (previous.classification == ProposalClassification.CHANGE and
            changes.get("classification") == ProposalClassification.NEW):
        raise ValueError("Eine Terminänderung darf nicht als neuer Termin eingestuft werden")


def _revision_day(previous: Proposal, changes: dict[str, Any]) -> KnownTemporalFacts | None:
    """Fix the validated event day and check every changed date against it."""
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
        if known is not None and known.date is None:
            known = known.model_copy(update={"date": temporal_date})
            changes["known_temporal_facts"] = known
        elif known is None and previous.temporal_fact is None and previous.start is None:
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
    return known


def _revision_interval(previous: Proposal, changes: dict[str, Any], known: KnownTemporalFacts | None) -> None:
    """Keep a confirmed start, and half intervals in ``known_temporal_facts``."""
    confirmed_start = (known.start if known is not None else previous.start)
    if previous.all_day and isinstance(confirmed_start, date) and not isinstance(
        confirmed_start, datetime
    ):
        confirmed_start = None
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
        elif (changes.get("all_day") is True and isinstance(start, date)
              and not isinstance(start, datetime)):
            # A date-only all-day start is a complete proposal field, not a
            # timezone-less ``KnownTemporalFacts.start`` datetime.  Keeping it
            # in the latter would make Pydantic coerce the date to midnight and
            # incorrectly demand a UTC offset for a time the user never gave.
            changes.update(start=start, known_temporal_facts=None)
        elif "start" in changes:
            changes.pop("start")
            changes["known_temporal_facts"] = known.model_copy(
                update={"start": start, "start_time": None})


def apply_proposal_revision(previous: Proposal, delta: ProposalRevisionDelta, *,
                            allow_create_fallback: bool = False) -> Proposal:
    """Apply a validated delta locally; identity, lifecycle and version stay authoritative."""
    if delta.answered_question not in previous.open_questions:
        raise ValueError("Die beantwortete Frage ist im Vorschlag nicht offen")
    changes = delta.changes.model_dump(exclude_unset=True)
    _check_revision_permissions(previous, changes, allow_create_fallback)
    known = _revision_day(previous, changes)
    _revision_interval(previous, changes, known)
    remaining = list(previous.open_questions)
    remaining.remove(delta.answered_question)
    provisional = previous.model_copy(update=changes)
    for question in required_revision_questions(provisional):
        if question not in remaining:
            remaining.append(question)
    changes.update(
        version=previous.version + 1,
        explicit_duplicate_create_confirmed_version=None,
        open_questions=remaining,
        status=(ProposalStatus.NEEDS_CLARIFICATION if remaining
                else ProposalStatus.PENDING_CONFIRMATION),
    )
    return Proposal.model_validate(previous.model_copy(update=changes).model_dump())


class Actions(StrictModel):
    proposals: list[Proposal] = Field(default_factory=list, max_length=20)
