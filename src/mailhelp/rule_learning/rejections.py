"""6.0.3: rejected rule proposals – normalized change sets, fingerprints and the suppression rule.

A fingerprint recognises the *same* change (same category, topic, action and normalized entries).
A proposal whose changes consist only of entries that were already rejected for the same topic
and action is suppressed as well. A differently worded but equivalent rule cannot be recognised
deterministically; for that the prompt names the rejected changes (6.0.5).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from .models import RejectedRuleProposal, RuleChangeSet, RuleHistory, RuleProposal

LIMIT = 500
LISTS = ("examples", "exclusions")


def normalize(text: str) -> str:
    return " ".join(text.casefold().split())


def _entries(values: list[str] | None) -> set[str]:
    return {normalize(value) for value in values or [] if normalize(value)}


def change_set(old: dict[str, Any] | None, proposed: dict[str, Any]) -> RuleChangeSet:
    """The change of *proposed* against the current rule *old* (None for a new topic)."""
    values: dict[str, Any] = {}
    for key in LISTS:
        before, after = _entries((old or {}).get(key)), _entries(proposed.get(key))
        values[f"add_{key}"] = sorted(after - before)
        values[f"remove_{key}"] = sorted(before - after)
    for key in ("name", "description"):
        new = normalize(proposed.get(key) or "")
        if old is None or new != normalize(old.get(key) or ""):
            values[key] = new or None
    if old is None or bool(proposed.get("enabled", True)) != bool(old.get("enabled", True)):
        values["enabled"] = bool(proposed.get("enabled", True))
    return RuleChangeSet.model_validate(values)


def fingerprint(category: str, topic_id: str, action: str, changes: RuleChangeSet) -> str:
    payload = json.dumps([category, topic_id, action, changes.model_dump(mode="json")], sort_keys=True,
                         ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def rejection(proposal: RuleProposal, old: dict[str, Any] | None, now: float) -> RejectedRuleProposal:
    changes = change_set(old, proposal.proposed.model_dump(mode="json"))
    return RejectedRuleProposal(
        fingerprint=fingerprint(proposal.category, proposal.topic_id, proposal.action, changes),
        category=proposal.category, topic_id=proposal.topic_id, topic_name=proposal.proposed.name,
        action=proposal.action, changes=changes, rejected_at=now)


def _contained(changes: RuleChangeSet, earlier: list[RejectedRuleProposal]) -> bool:
    """Every entry of *changes* was already rejected for this topic and action."""
    if not earlier or changes == RuleChangeSet():
        return False
    for key in ("add_examples", "remove_examples", "add_exclusions", "remove_exclusions"):
        known = {entry for item in earlier for entry in getattr(item.changes, key)}
        if not set(getattr(changes, key)) <= known:
            return False
    for key in ("name", "description", "enabled"):
        value = getattr(changes, key)
        if value is not None and value not in {getattr(item.changes, key) for item in earlier}:
            return False
    return True


def suppressed(proposal: RuleProposal, old: dict[str, Any] | None, rejected: list[RejectedRuleProposal]) -> bool:
    """True if the user already rejected this change (same fingerprint or only rejected entries)."""
    changes = change_set(old, proposal.proposed.model_dump(mode="json"))
    if fingerprint(proposal.category, proposal.topic_id, proposal.action, changes) in {
            item.fingerprint for item in rejected}:
        return True
    same = [item for item in rejected if (item.category, item.topic_id, item.action)
            == (proposal.category, proposal.topic_id, proposal.action)]
    return _contained(changes, same)


def remember(history: RuleHistory, items: list[RejectedRuleProposal]) -> RuleHistory:
    """Add rejections (a repeated fingerprint replaces its older entry); the oldest beyond 500 drop out."""
    if not items:
        return history
    fresh = {item.fingerprint for item in items}
    kept = [item for item in history.rejected if item.fingerprint not in fresh] + items
    return history.model_copy(update={"rejected": kept[-LIMIT:], "rejected_version": history.rejected_version + 1})


def readmit(history: RuleHistory, value: str) -> RuleHistory:
    """Remove one rejection; the proposal may be suggested again."""
    kept = [item for item in history.rejected if item.fingerprint != value]
    if len(kept) == len(history.rejected):
        return history
    return history.model_copy(update={"rejected": kept, "rejected_version": history.rejected_version + 1})


__all__ = ["change_set", "fingerprint", "readmit", "rejection", "remember", "suppressed"]
