"""Fachmodelle für den Kontext Vorschläge und Revisionen."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID
import re

from pydantic import AnyHttpUrl, Field, field_validator, model_validator

from ._base import CalendarDate, StrictModel
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
    # A clock explicitly present in the mail can be retained before an
    # ambiguous/yearless calendar date has been resolved.
    start_time: time | None = None

    @model_validator(mode="after")
    def validate_facts(self) -> "KnownTemporalFacts":
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

    @model_validator(mode="after")
    def validate_consistency(self) -> "Proposal":
        if self.status == ProposalStatus.SIMULATED and (self.external_id is not None or self.external_link is not None):
            raise ValueError("Ein simulierter Vorschlag darf kein externes Ergebnis enthalten")
        if self.simulation_notified and self.status != ProposalStatus.SIMULATED:
            raise ValueError("Eine Simulation darf nur im simulierten Zustand als gemeldet markiert werden")
        creatable_classification = (
            self.classification == ProposalClassification.NEW or
            (self.classification == ProposalClassification.CHANGE and
             self.explicit_create_fallback_confirmed)
        )
        ready = (creatable_classification and
                 self.responsibility == ProposalResponsibility.USER and
                 self.certainty == ProposalCertainty.CERTAIN and not self.open_questions)
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
    explicit_create_fallback_confirmed: bool | None = None


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
        ProposalClassification.CHANGE: (None if proposal.explicit_create_fallback_confirmed
                                        else "Welcher bestehende Eintrag soll geändert werden?"),
        ProposalClassification.CANCELLATION: "Welcher bestehende Eintrag soll storniert werden?",
        ProposalClassification.RECURRING: "Wiederkehrende Einträge werden nicht automatisch angelegt.",
        ProposalClassification.UNSUPPORTED: "Diese Art von Eintrag wird nicht unterstützt.",
    }.get(proposal.classification)
    if classification:
        questions.append(classification)
    return questions


def apply_proposal_revision(previous: Proposal, delta: ProposalRevisionDelta, *,
                            allow_create_fallback: bool = False) -> Proposal:
    """Apply a validated delta locally; identity, lifecycle and version stay authoritative."""
    if delta.answered_question not in previous.open_questions:
        raise ValueError("Die beantwortete Frage ist im Vorschlag nicht offen")
    changes = delta.changes.model_dump(exclude_unset=True)
    if "explicit_create_fallback_confirmed" in changes and not allow_create_fallback:
        raise ValueError("Die Ersatz-Neuanlage erfordert eine deterministische ausdrückliche Bestätigung")
    if (previous.classification == ProposalClassification.CHANGE and
            changes.get("classification") == ProposalClassification.NEW):
        raise ValueError("Eine Terminänderung darf nicht als neuer Termin eingestuft werden")
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
        elif "start" in changes:
            changes.pop("start")
            changes["known_temporal_facts"] = known.model_copy(
                update={"start": start, "start_time": None})
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
