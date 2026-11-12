"""5.7.7: the model names only what changes; Mailhelp assembles and validates the complete topic."""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import RuleAnalysis, RuleProposal, RuleTopic, checked_text

# Bounds of the model answer; a full topic per proposal made the answer exceed the output limit.
MAX_PROPOSALS, MAX_ADDED, MAX_EVIDENCE_IDS, MAX_RATIONALE = 10, 10, 10, 500
# 5.7.7: weak, repetitive signals are counted locally and only a few examples are sent.
WEAK = "rejected_proposal"
REPRESENTATIVES, SHORT_TEXT = 5, 300


def checked_entries(values: list[str]) -> list[str]:
    for value in values:
        checked_text(value)
        if len(value) > 500:
            raise ValueError("Ein Beispiel oder Ausschluss darf höchstens 500 Zeichen enthalten")
    return values


class RuleChanges(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    add_examples: list[str] = Field(default_factory=list, max_length=MAX_ADDED)
    remove_examples: list[str] = Field(default_factory=list, max_length=30)
    add_exclusions: list[str] = Field(default_factory=list, max_length=MAX_ADDED)
    remove_exclusions: list[str] = Field(default_factory=list, max_length=30)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, min_length=1, max_length=1000)
    enabled: bool | None = None

    @field_validator("add_examples", "remove_examples", "add_exclusions", "remove_exclusions")
    @classmethod
    def entries(cls, values: list[str]) -> list[str]:
        return checked_entries(values)

    @field_validator("name", "description")
    @classmethod
    def text(cls, value: str | None) -> str | None:
        return None if value is None else checked_text(value)


class RuleSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    topic_id: str = Field(pattern=r"^[a-z0-9_-]+$", max_length=64)
    category: Literal["relevant", "irrelevant"]
    action: Literal["modify", "create", "disable"]
    rationale: str = Field(min_length=1, max_length=MAX_RATIONALE)
    evidence: list[str] = Field(min_length=1, max_length=MAX_EVIDENCE_IDS)
    changes: RuleChanges = Field(default_factory=RuleChanges)

    @field_validator("rationale")
    @classmethod
    def reason(cls, value: str) -> str:
        return checked_text(value)


class RuleSuggestions(BaseModel):
    """The closed answer contract of ``decision_rule_learning`` since 5.7.7."""
    model_config = ConfigDict(extra="forbid", strict=True)
    proposals: list[RuleSuggestion] = Field(default_factory=list, max_length=MAX_PROPOSALS)

    @model_validator(mode="after")
    def unique(self) -> RuleSuggestions:
        keys = [(item.category, item.topic_id) for item in self.proposals]
        if len(keys) != len(set(keys)):
            raise ValueError("Ein Thema darf nur einmal je Analyse vorgeschlagen werden")
        return self


def merged(entries: list[str], removed: list[str], added: list[str], label: str, topic_id: str) -> list[str]:
    missing = [value for value in removed if value not in entries]
    if missing:
        raise ValueError(f"{topic_id}: zu entfernende {label} fehlen im Thema: {missing[0][:80]}")
    kept = [value for value in entries if value not in removed]
    return kept + [value for value in dict.fromkeys(added) if value not in kept]


def assemble(documents: dict[str, Any], suggestions: RuleSuggestions) -> RuleAnalysis:
    """Build complete proposals from the current topic files and the requested changes."""
    existing = {category: {topic["id"]: topic for topic in document["topics"]}
                for category, document in documents.items()}
    proposals = []
    for item in suggestions.proposals:
        changes, current = item.changes, existing[item.category].get(item.topic_id)
        if item.action == "create":
            if any(item.topic_id in topics for topics in existing.values()):
                raise ValueError(f"{item.topic_id}: Themen-ID ist bereits vergeben")
            if changes.name is None or changes.description is None or not changes.add_examples:
                raise ValueError(f"{item.topic_id}: neues Thema braucht name, description und add_examples")
            if changes.remove_examples or changes.remove_exclusions:
                raise ValueError(f"{item.topic_id}: ein neues Thema hat nichts zu entfernen")
            topic: dict[str, Any] = {"id": item.topic_id, "name": changes.name, "description": changes.description,
                                     "enabled": changes.enabled is not False, "mailboxes": None,
                                     "examples": list(dict.fromkeys(changes.add_examples)),
                                     "exclusions": list(dict.fromkeys(changes.add_exclusions))}
        else:
            if current is None:
                raise ValueError(f"{item.topic_id}: Thema fehlt in den {item.category} Regeln")
            topic = dict(current)
            if item.action == "disable":
                if changes != RuleChanges(enabled=False) and changes != RuleChanges():
                    raise ValueError(f"{item.topic_id}: disable enthält keine weiteren Änderungen")
                topic["enabled"] = False
            else:
                topic["examples"] = merged(current["examples"], changes.remove_examples, changes.add_examples,
                                           "Beispiele", item.topic_id)
                topic["exclusions"] = merged(current["exclusions"], changes.remove_exclusions,
                                             changes.add_exclusions, "Ausschlüsse", item.topic_id)
                for field in ("name", "description", "enabled"):
                    if getattr(changes, field) is not None:
                        topic[field] = getattr(changes, field)
            if topic == current:
                raise ValueError(f"{item.topic_id}: der Vorschlag ändert nichts")
        proposals.append(RuleProposal(topic_id=item.topic_id, category=item.category, action=item.action,
                                      rationale=item.rationale, evidence=item.evidence,
                                      proposed=RuleTopic.model_validate(topic)))
    return RuleAnalysis(proposals=proposals)


def condense(evidence: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Strong signals go in full; repetitive rejections as a count per topic set plus a few examples."""
    sent, groups = [], defaultdict(list)
    for item in evidence:
        if item["signal"] == WEAK:
            groups[tuple(item["topic_ids"])].append(item)
        else:
            sent.append(item)
    summary = []
    for topic_ids, items in groups.items():
        sent.extend({**item, "text": item["text"][:SHORT_TEXT]} for item in items[:REPRESENTATIVES])
        summary.append({"signal": WEAK, "topic_ids": list(topic_ids), "count": len(items),
                        "shown": min(len(items), REPRESENTATIVES)})
    return sent, summary


def compact_topics(documents: dict[str, Any], evidence: list[dict[str, Any]]) -> dict[str, Any]:
    """Topics without evidence are sent with id, name and description only."""
    named = {topic_id for item in evidence for topic_id in item["topic_ids"]}
    return {category: {"topics": [topic if topic["id"] in named else
                                  {key: topic[key] for key in ("id", "name", "description", "enabled")}
                                  for topic in document["topics"]]}
            for category, document in documents.items()}
