"""Fachmodelle für den Kontext Relevanz."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from ._base import StrictModel

ADDRESS = re.compile(r"^[^@\s<>]+@[^@\s<>]+$")
DOMAIN = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
# 7.7: a pattern is an address with one to three ``*``; no other wildcard, never a regular expression.
PATTERN = re.compile(r"^[a-z0-9._%+*-]+@[a-z0-9.*-]+$")
MAX_WILDCARDS = 3


def subject_key(text: str) -> str:
    """Subjects are compared without case, Unicode variants and repeated spaces (7.7)."""
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


class ListSignals(StrictModel):
    """7.7: bounded, untrusted list and automation headers of a mail, used only by the prefilter.

    They are stored beside the mail, never inside it, so no model input changes.
    """

    list_id: str = Field(default="", max_length=200)
    list_unsubscribe: bool = False
    precedence: str = Field(default="", max_length=50)
    auto_submitted: str = Field(default="", max_length=50)


class SenderRule(StrictModel):
    """7.7: one prefilter rule.

    ``ignore`` files a mail as irrelevant, ``vip`` makes it relevant without the relevance call, and
    ``allow_only`` only lifts every ignore rule and header filter for this sender.
    """

    id: str = Field(pattern=r"^[a-f0-9]{16}$")
    kind: Literal["address", "domain", "pattern", "subject"]
    value: str = Field(min_length=1, max_length=120)
    action: Literal["ignore", "vip", "allow_only"] = "ignore"
    subdomains: bool = True
    topic_ids: list[str] = Field(default_factory=list, max_length=20)
    mailbox: int | None = Field(default=None, ge=1, le=99)
    enabled: bool = True
    note: str = Field(default="", max_length=200)
    created_at: datetime
    origin: Literal["manual", "mail", "hint", "telegram", "migration"] = "manual"

    @staticmethod
    def identity(kind: str, value: str, mailbox: int | None) -> str:
        """Stable across saves, so a repeated command never creates a second rule."""
        return hashlib.sha256(f"{kind}\0{value}\0{mailbox or 0}".encode()).hexdigest()[:16]

    @model_validator(mode="after")
    def valid_rule(self) -> SenderRule:
        checks = {"address": ADDRESS.fullmatch(self.value) is not None and self.value == self.value.casefold(),
                  "domain": DOMAIN.fullmatch(self.value) is not None,
                  "pattern": PATTERN.fullmatch(self.value) is not None
                  and 1 <= self.value.count("*") <= MAX_WILDCARDS and self.value.strip("*@.") != "",
                  "subject": self.value == subject_key(self.value)}
        if not checks[self.kind]:
            raise ValueError("Ungültiger Wert für diese Regelart")
        if self.kind == "subject" and self.action != "ignore":
            raise ValueError("Ein Betreff kann eine Mail nur aussortieren")
        if self.topic_ids and self.action != "vip":
            raise ValueError("Themen gibt nur eine VIP-Regel vor")
        if self.id != self.identity(self.kind, self.value, self.mailbox):
            raise ValueError("Regelkennung passt nicht zur Regel")
        return self


class HeaderPrefilter(StrictModel):
    """7.7: header filters are off after an update; a trial only counts, it never decides."""

    automated: Literal["off", "trial", "on"] = "off"
    lists: Literal["off", "trial", "on"] = "off"
    trial_since: dict[Literal["automated", "lists"], datetime] = Field(default_factory=dict)
    list_exceptions: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def valid_exceptions(self) -> HeaderPrefilter:
        if (self.list_exceptions != sorted(set(self.list_exceptions))
                or any(not 0 < len(item) <= 200 or item != item.casefold() for item in self.list_exceptions)):
            raise ValueError("Verteiler-Ausnahmen müssen kleingeschrieben, eindeutig und sortiert sein")
        return self


class RuleHits(StrictModel):
    count: int = Field(default=0, ge=0)
    last: datetime | None = None


class PrefilterHits(StrictModel):
    """7.7: how often each rule decided (``rules``) and how often a header trial would have (``trial``).

    Kept apart from the rule file, so counting never competes with web changes or learning jobs.
    """

    schema_version: Literal[1] = 1
    rules: dict[str, RuleHits] = Field(default_factory=dict)
    trial: dict[str, RuleHits] = Field(default_factory=dict)


class IrrelevantSenders(StrictModel):
    """Durable, human-readable sender prefilter learned from rejected topics.

    Schema 3 (7.7) keeps the simple lists of schema 2 unchanged – exact addresses, exact domains and
    the per-mailbox exceptions – and adds the rules and the header filters beside them.
    """

    schema_version: Literal[3] = 3
    addresses: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    mailboxes: dict[str, SenderRules] = Field(default_factory=dict, max_length=99)
    rules: list[SenderRule] = Field(default_factory=list, max_length=1000)
    headers: HeaderPrefilter = Field(default_factory=HeaderPrefilter)

    @model_validator(mode="before")
    @classmethod
    def upgrade_sender_scope(cls, value: object) -> object:
        if isinstance(value, dict) and value.get("schema_version") in {1, 2}:
            return {**value, "schema_version": 3}
        return value

    @model_validator(mode="after")
    def valid_entries(self) -> IrrelevantSenders:
        if any(not re.fullmatch(r"[1-9][0-9]?", key) for key in self.mailboxes):
            raise ValueError("Absenderfilter benötigen Postfachnummern zwischen 1 und 99")
        if (self.addresses != sorted(set(self.addresses))
                or any(address != address.casefold() or not ADDRESS.fullmatch(address)
                       for address in self.addresses)):
            raise ValueError("Absenderadressen müssen gültig, kleingeschrieben und eindeutig sein")
        if (self.domains != sorted(set(self.domains))
                or any(domain != domain.casefold() or not DOMAIN.fullmatch(domain)
                       for domain in self.domains)):
            raise ValueError("Absenderdomains müssen gültig, kleingeschrieben und eindeutig sein")
        if len({rule.id for rule in self.rules}) != len(self.rules):
            raise ValueError("Jede Regel darf nur einmal vorkommen")
        return self


class SenderRules(StrictModel):
    addresses: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    allow: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_entries(self) -> SenderRules:
        IrrelevantSenders(addresses=self.addresses, domains=self.domains)
        IrrelevantSenders(addresses=self.allow)
        return self


IrrelevantSenders.model_rebuild()


class Relevance(StrictModel):
    decision: Literal["relevant", "irrelevant", "unclear"]
    # Deliberately no default: OpenRouter derives its structured-output schema
    # from this model, so every provider response must contain the field even
    # when the correct value is an empty list.
    topic_ids: list[str]
    reason: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def consistent_topics(self) -> Relevance:
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
    def consistent_decision(self) -> RelevanceDialog:
        decided = self.status == RelevanceDialogStatus.DECIDED
        has_complete_decision = self.decision is not None and self.telegram_offset is not None
        has_partial_decision = (self.decision is None) != (self.telegram_offset is None)
        if has_partial_decision or decided != has_complete_decision:
            raise ValueError("Entscheidung und Telegram-Offset müssen gemeinsam gesetzt sein")
        return self
