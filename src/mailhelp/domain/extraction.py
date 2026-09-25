"""Fachmodelle für den Kontext LLM-Extraktion."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID
import re

from pydantic import AnyHttpUrl, Field, field_validator, model_validator

from ._base import CalendarDate, StrictModel
from .temporal import TimeRequirement


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
    tasks: list[ExtractedTask] = Field(max_length=20)


class ExtractedEvent(StrictModel):
    """Unnormalised event facts; missing facts remain explicitly absent."""

    title: str = Field(min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=4000)
    evidence: str = Field(min_length=1, max_length=2000)
    date_text: str | None = Field(default=None, min_length=1, max_length=500)
    time_text: str | None = Field(default=None, min_length=1, max_length=500)
    end_time_text: str | None = Field(default=None, min_length=1, max_length=500)
    duration_minutes: int | None = Field(default=None, ge=1, le=1440)
    duration_is_upper_bound: bool = False
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
    events: list[ExtractedEvent] = Field(max_length=20)


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
