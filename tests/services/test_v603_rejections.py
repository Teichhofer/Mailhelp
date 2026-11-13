"""6.0.3: rejected rule proposals are stored as normalized change sets with a fingerprint."""
import json

import pytest
from pydantic import ValidationError

from mailhelp.rule_learning.models import RejectedRuleProposal, RuleChangeSet, RuleHistory
from mailhelp.rule_learning.rejections import (
    LIMIT,
    change_set,
    fingerprint,
    readmit,
    rejection,
    remember,
    suppressed,
)
from tests.fakes.rule_learning import proposal, topic

OLD = topic(examples=["Elternabend"]).model_dump(mode="json")


def proposed(**changes):
    return proposal(proposed=topic(**changes).model_dump())


def test_the_change_set_is_normalized_and_only_names_what_changes():
    changes = change_set(OLD, {**OLD, "examples": ["Elternabend", "  Klassen   FAHRT "],
                               "exclusions": ["Werbung", "werbung"], "name": "Schule"})
    assert changes == RuleChangeSet(add_examples=["klassen fahrt"], add_exclusions=["werbung"])
    removed = change_set(OLD, {**OLD, "examples": [], "description": "Neu", "enabled": False})
    assert removed == RuleChangeSet(remove_examples=["elternabend"], description="neu", enabled=False)
    created = change_set(None, {"name": "Sport", "description": "Verein", "examples": ["Training"]})
    assert created == RuleChangeSet(add_examples=["training"], name="sport", description="verein", enabled=True)
    # A rejection stores the change only: no rationale, no evidence.
    stored = rejection(proposal(), OLD, 5.0).model_dump()
    assert set(stored) == {"fingerprint", "category", "topic_id", "topic_name", "action", "changes", "rejected_at"}
    assert "rationale" not in json.dumps(stored) and "decision-1" not in json.dumps(stored)


def test_fingerprints_are_equal_for_the_same_change_only():
    same = change_set(OLD, {**OLD, "exclusions": ["Unverbindliche  Werbung"]})
    other = change_set(OLD, {**OLD, "exclusions": ["Newsletter"]})
    matching = proposed(examples=["Elternabend"], exclusions=["unverbindliche werbung"])
    assert fingerprint("relevant", "school", "modify", same) == rejection(matching, OLD, 1.0).fingerprint
    assert fingerprint("relevant", "school", "modify", other) != fingerprint("relevant", "school", "modify", same)
    assert fingerprint("irrelevant", "school", "modify", same) != fingerprint("relevant", "school", "modify", same)
    assert fingerprint("relevant", "school", "disable", same) != fingerprint("relevant", "school", "modify", same)


def test_regression_a_rejected_change_and_its_parts_are_suppressed():
    """Regression 6.0: an unticked or unwanted proposal came back unchanged in the next analysis."""
    rejected = [rejection(proposed(exclusions=["Werbung", "Newsletter"]), OLD, 1.0)]
    assert suppressed(proposed(exclusions=["werbung ", "NEWSLETTER"]), OLD, rejected)  # same change
    assert suppressed(proposed(exclusions=["Werbung"]), OLD, rejected)  # only rejected entries
    assert not suppressed(proposed(exclusions=["Werbung", "Gutschein"]), OLD, rejected)  # something new
    assert not suppressed(proposed(exclusions=["Werbung"]), OLD, [])
    other_topic = rejection(proposal(topic_id="sport", proposed=topic(id="sport", exclusions=["Werbung"])
                                     .model_dump()), None, 1.0)
    assert not suppressed(proposed(exclusions=["Werbung"]), OLD, [other_topic])
    # Single fields count only with the same rejected value; no change at all is never "contained".
    renamed = [rejection(proposed(name="Schulpost"), OLD, 1.0)]
    assert suppressed(proposed(name="schulpost"), OLD, renamed)
    assert not suppressed(proposed(name="Schulbriefe"), OLD, renamed)
    assert not suppressed(proposal(proposed=topic(examples=["Elternabend"]).model_dump()), OLD, renamed)


def test_history_keeps_500_newest_and_readmission_changes_the_version():
    old = RuleHistory.model_validate({"analyzed_at": 3.0, "decision_ids": ["a"]})  # stored before 6.0
    assert old.rejected == [] and old.rejected_version == 0
    first = rejection(proposal(), OLD, 1.0)
    history = remember(old, [first])
    assert history.rejected == [first] and history.rejected_version == 1 and history.decision_ids == ["a"]
    again = rejection(proposal(), OLD, 2.0)
    assert remember(history, [again]).rejected == [again]  # the same change is stored once
    assert remember(history, []) is history
    many = [RejectedRuleProposal(**{**first.model_dump(), "fingerprint": f"{index:064x}", "rejected_at": index})
            for index in range(LIMIT + 3)]
    full = remember(history, many)
    assert len(full.rejected) == LIMIT and full.rejected[0].rejected_at == 3
    admitted = readmit(history, first.fingerprint)
    assert admitted.rejected == [] and admitted.rejected_version == 2
    assert readmit(history, "f" * 64) is history
    with pytest.raises(ValidationError):
        RuleHistory(rejected=many)
