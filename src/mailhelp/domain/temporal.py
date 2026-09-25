"""Fachmodelle für den Kontext Datum und Zeit."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID
import re

from pydantic import AnyHttpUrl, Field, field_validator, model_validator

from ._base import CalendarDate, StrictModel


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
