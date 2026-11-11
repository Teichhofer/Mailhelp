import pytest
import yaml

from mailhelp.rule_learning.validation import RuleConflict, RuleValidationService, parse_yaml
from tests.fakes.rule_learning import proposal, topic


@pytest.mark.parametrize("text", ["topics: [", "topics: []\ntopics: []", "? [list]\n: value", "!!python/object:evil {}"])
def test_unsafe_ambiguous_or_invalid_yaml_is_rejected(text):
    with pytest.raises(ValueError, match="YAML-Syntaxfehler"):
        parse_yaml(text)


@pytest.mark.parametrize("value", [{}, {"topics": []}, {"topics": [{"id": "x"}]},
                                   {"topics": [topic(enabled=False).model_dump()]}])
def test_the_complete_relevant_file_is_validated(value):
    with pytest.raises(ValueError, match="topics.yaml"):
        RuleValidationService.parse(yaml.safe_dump(value), "relevant")


def documents():
    return {"relevant": {"topics": [topic().model_dump()]}, "irrelevant": {"topics": []}}


def test_manual_changes_are_serialized_as_data_and_both_files_are_validated():
    value = topic(name="Name: [nicht YAML]", examples=["ein neuer Fall"], exclusions=["<script>kein Code</script>"])
    files = RuleValidationService.prepare(documents(), [{"index": 0, "topic": value.model_dump()}], [proposal()])
    saved = yaml.safe_load(files["topics.yaml"])["topics"][0]
    assert saved == value.model_dump() and yaml.safe_load(files["irrelevant_topics.yaml"]) == {"topics": []}


@pytest.mark.parametrize("choices", [[], [{"index": True}], [{"index": -1}], [{"index": 2}],
                                     [{"index": 0, "topic": topic(id="other").model_dump()}]])
def test_invalid_selection_or_stable_id_changes_are_rejected(choices):
    with pytest.raises(ValueError):
        RuleValidationService.prepare(documents(), choices, [proposal()])


def test_duplicate_selection_missing_original_and_cross_file_ids_are_rejected():
    choice = {"index": 0, "topic": topic().model_dump()}
    with pytest.raises(ValueError):
        RuleValidationService.prepare(documents(), [choice, choice], [proposal()])
    with pytest.raises(RuleConflict):
        RuleValidationService.prepare(documents(), [choice], [proposal(action="create")])
    with pytest.raises(RuleConflict):
        RuleValidationService.prepare(documents(), [{"index": 0, "topic": topic(id="absent").model_dump()}],
                                      [proposal(topic_id="absent", proposed=topic(id="absent"))])
    creation = proposal(category="irrelevant", action="create")
    with pytest.raises(ValueError, match="doppelt"):
        RuleValidationService.prepare(documents(), [choice], [creation])
    files = RuleValidationService.prepare(documents(), [{"index": 0, "topic": topic(id="new").model_dump()}], [creation])
    assert yaml.safe_load(files["irrelevant_topics.yaml"])["topics"][0]["id"] == "new"


def test_mailbox_scopes_cannot_silently_be_broadened_or_reference_missing_mailboxes():
    original = documents()
    original["relevant"]["topics"][0]["mailboxes"] = [1]
    with pytest.raises(ValueError, match="Postfachgrenzen"):
        RuleValidationService.prepare(original, [{"index": 0, "topic": topic().model_dump()}], [proposal()], {1})
    assert RuleValidationService.prepare(original, [{"index": 0, "topic": topic(mailboxes=[1]).model_dump()}],
                                         [proposal()], {1})
    created = proposal(topic_id="new", action="create", proposed=topic(id="new", mailboxes=[99]))
    with pytest.raises(ValueError, match="nicht konfiguriert"):
        RuleValidationService.prepare(documents(), [{"index": 0, "topic": created.proposed.model_dump()}], [created], {1})
