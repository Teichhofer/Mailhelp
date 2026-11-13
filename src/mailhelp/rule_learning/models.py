"""Closed contracts for untrusted model suggestions and manually edited topic rules."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..config import Topic


def checked_text(value: str) -> str:
    if not value.strip() or any(ord(char) < 32 and char not in "\n\r\t" for char in value):
        raise ValueError("Text darf nicht leer sein oder unzulässige Steuerzeichen enthalten")
    return value


class RuleTopic(Topic):
    id: str = Field(pattern=r"^[a-z0-9_-]+$", max_length=64)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=1000)
    examples: list[str] = Field(default_factory=list, max_length=30)
    exclusions: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("name", "description")
    @classmethod
    def text_fields(cls, value: str) -> str:
        return checked_text(value)

    @field_validator("examples", "exclusions")
    @classmethod
    def text_lists(cls, values: list[str]) -> list[str]:
        for value in values:
            checked_text(value)
            if len(value) > 500:
                raise ValueError("Ein Beispiel oder Ausschluss darf höchstens 500 Zeichen enthalten")
        return values


class RuleProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    topic_id: str = Field(pattern=r"^[a-z0-9_-]+$", max_length=64)
    category: Literal["relevant", "irrelevant"]
    action: Literal["modify", "create", "disable"]
    rationale: str = Field(min_length=1, max_length=1000)
    evidence: list[str] = Field(min_length=1, max_length=20)
    proposed: RuleTopic

    @model_validator(mode="after")
    def consistent_action(self) -> RuleProposal:
        checked_text(self.rationale)
        if self.proposed.id != self.topic_id or (self.action == "disable" and self.proposed.enabled):
            raise ValueError("Themenkennung oder Deaktivierung widerspricht dem Vorschlag")
        return self


class RuleAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    proposals: list[RuleProposal] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def unique_changes(self) -> RuleAnalysis:
        keys = [(item.category, item.topic_id) for item in self.proposals]
        if len(keys) != len(set(keys)):
            raise ValueError("Ein Thema darf nur einmal je Analyse vorgeschlagen werden")
        return self


class RuleState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    version: int = 0
    owner: str = ""
    created_at: float = 0
    status: Literal["empty", "queued", "running", "review", "committing", "done", "failed", "interrupted"] = "empty"
    hashes: dict[str, str] = Field(default_factory=dict)
    documents: dict[str, Any] = Field(default_factory=dict)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    skipped: int = 0
    # 5.7.6: which decisions were chosen and how many the payload limit left out.
    scope: Literal["new", "all"] = "new"
    trimmed: int = 0
    # 5.7.7: repeated rejections sent only as a count (not as individual examples).
    condensed: int = 0
    proposals: list[RuleProposal] = Field(default_factory=list)
    receipts: dict[str, str] = Field(default_factory=dict)
    commit: dict[str, str] = Field(default_factory=dict)
    message: str = ""


class RuleChangeSet(BaseModel):
    """6.0.3: what a proposal changes against the current rule, normalized for comparison.

    Lists hold casefolded entries with collapsed whitespace, sorted and unique; the single
    fields are set only when they change. No rationale and no evidence: the history is durable.
    """
    model_config = ConfigDict(extra="forbid")
    add_examples: list[str] = Field(default_factory=list, max_length=60)
    remove_examples: list[str] = Field(default_factory=list, max_length=60)
    add_exclusions: list[str] = Field(default_factory=list, max_length=60)
    remove_exclusions: list[str] = Field(default_factory=list, max_length=60)
    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    enabled: bool | None = None


class RejectedRuleProposal(BaseModel):
    """6.0.3: a rule proposal the user rejected; it must not be proposed again."""
    model_config = ConfigDict(extra="forbid")
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    category: Literal["relevant", "irrelevant"]
    topic_id: str = Field(pattern=r"^[a-z0-9_-]+$", max_length=64)
    topic_name: str = Field(max_length=200)
    action: Literal["modify", "create", "disable"]
    changes: RuleChangeSet
    rejected_at: float


class RuleHistory(BaseModel):
    """Public analysis metadata survives removal of private review contents."""
    model_config = ConfigDict(extra="forbid")
    analyzed_at: float = 0
    # 5.7.6: every analysed decision is remembered, so "only new" works across the whole log.
    decision_ids: list[str] = Field(default_factory=list, max_length=10_000)
    # 6.0.3: rejected proposals (newest last, at most 500) and a version for "Wieder zulassen".
    rejected: list[RejectedRuleProposal] = Field(default_factory=list, max_length=500)
    rejected_version: int = Field(default=0, ge=0)
    # 6.0.4: idempotency receipts of "Wieder zulassen" (digest of actor and key -> fingerprint digest).
    receipts: dict[str, str] = Field(default_factory=dict)
