"""Fachmodelle für den Kontext Relevanz."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID
import re

from pydantic import AnyHttpUrl, Field, field_validator, model_validator

from ._base import CalendarDate, StrictModel


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
