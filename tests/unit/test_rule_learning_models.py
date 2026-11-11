import pytest

from mailhelp.rule_learning.models import RuleAnalysis, RuleTopic
from tests.fakes.rule_learning import proposal, topic


@pytest.mark.parametrize("change", [
    {"id": "Ungültige ID!"}, {"name": ""}, {"name": " "}, {"name": "x" * 201},
    {"description": ""}, {"description": "x" * 1001}, {"description": "bad\x00"},
    {"examples": [""]}, {"exclusions": ["x" * 501]}, {"examples": ["x"] * 31},
    {"enabled": "true"}, {"mailboxes": [1, 1]}, {"unknown": "x"},
])
def test_invalid_manually_edited_topics_are_rejected(change):
    with pytest.raises(ValueError):
        RuleTopic.model_validate({**topic().model_dump(), **change})


def test_valid_multiline_text_examples_exclusions_and_scope_are_preserved():
    value = topic(description="Zeile 1\nZeile 2", examples=["Termin"], exclusions=["Werbung"], mailboxes=[1])
    assert value.description.endswith("Zeile 2") and value.mailboxes == [1]
    assert proposal().proposed.id == "school"


@pytest.mark.parametrize("changes", [{"topic_id": "other"}, {"action": "disable"}, {"rationale": "  "}])
def test_inconsistent_or_empty_model_changes_are_rejected(changes):
    with pytest.raises(ValueError):
        proposal(**changes)


def test_duplicate_changes_are_rejected_and_an_empty_analysis_is_valid():
    assert RuleAnalysis().proposals == []
    with pytest.raises(ValueError, match="einmal"):
        RuleAnalysis(proposals=[proposal(), proposal()])
    assert proposal(action="disable", proposed=topic(enabled=False)).action == "disable"
