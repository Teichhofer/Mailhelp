"""6.0.5: rejected changes are named to the model and filtered out if it proposes them again."""
from pathlib import Path

import yaml

from mailhelp.rule_learning.models import RuleAnalysis
from mailhelp.rule_learning.rejections import rejection, remember
from mailhelp.rule_learning.service import HISTORY
from tests.fakes.rule_learning import RuleHarness, proposal, record, topic

OTHER = proposal(proposed=topic(exclusions=["Gutschein"]).model_dump())


def reject_first(harness, key="reject-1"):
    state = harness.review()
    harness.service.change("web:a", state.version, key, "apply", {"confirm": True, "choices": [], "rejected": [0]})
    return harness.service.history()


def again(harness, key):
    harness.log(record())
    state = harness.service.state("web:a")
    harness.service.change("web:a", state.version, key, "analyze", {"confirm": True, "scope": "all"})
    assert harness.service.tick()
    return harness.service.state("web:a")


def test_regression_a_rejected_proposal_returned_by_the_model_is_not_shown_again(tmp_path):
    """Regression 6.0: the same rule proposal came back in the next analysis after it was not wanted."""
    harness = RuleHarness(tmp_path)
    assert [item.topic_id for item in reject_first(harness).rejected] == ["school"]
    # The model ignores the instruction and repeats the change.
    state = again(harness, "analyze-2")
    assert state.status == "done" and state.proposals == [] and state.suppressed == 1
    assert state.message == "Keine neuen Vorschläge; 1 bereits abgelehnter Vorschlag wurde ausgeblendet."
    # The analysed decisions count as analysed anyway.
    assert harness.service.history().decision_ids == ["decision-1"]
    payload = harness.analyzer.calls[-1]
    assert payload["rejected"] == [{"category": "relevant", "topic_id": "school", "action": "modify",
                                    "changes": {"add_exclusions": ["unverbindliche werbung"]}}]


def test_new_proposals_stay_and_the_summary_counts_the_hidden_ones(tmp_path):
    harness = RuleHarness(tmp_path)
    reject_first(harness)
    harness.analyzer.result = RuleAnalysis(proposals=[proposal(), proposal(
        action="create", category="irrelevant", topic_id="noise", proposed=topic(id="noise", name="Werbung"))])
    state = again(harness, "analyze-2")
    assert state.status == "review" and [item.topic_id for item in state.proposals] == ["noise"]
    assert state.suppressed == 1


def test_a_readmitted_proposal_may_appear_again(tmp_path):
    harness = RuleHarness(tmp_path)
    history = reject_first(harness)
    harness.service.readmit("web:a", history.rejected_version, "readmit-key-1", history.rejected[0].fingerprint)
    state = again(harness, "analyze-2")
    assert state.status == "review" and len(state.proposals) == 1 and state.suppressed == 0
    assert harness.analyzer.calls[-1]["rejected"] == []


def test_a_different_change_of_a_rejected_topic_is_still_proposed(tmp_path):
    harness = RuleHarness(tmp_path)
    reject_first(harness)
    harness.analyzer.result = RuleAnalysis(proposals=[OTHER])
    state = again(harness, "analyze-2")
    assert state.status == "review" and state.suppressed == 0 and len(state.proposals) == 1


def test_the_payload_sends_changes_of_present_topics_and_only_20_newest_new_topics(tmp_path):
    harness = RuleHarness(tmp_path)
    created = [rejection(proposal(action="create", category="irrelevant", topic_id=f"neu-{index}",
                                  proposed=topic(id=f"neu-{index}", name=f"Neu {index}").model_dump()),
                         None, float(index)) for index in range(25)]
    present = rejection(proposal(), topic().model_dump(mode="json"), 99.0)
    harness.store.save(HISTORY, remember(harness.service.history(), [present, *created]).model_dump(mode="json"))
    documents = {"relevant": {"topics": [topic().model_dump(mode="json")]}, "irrelevant": {"topics": []}}
    sent = harness.service.rejected_payload(documents)
    assert sent[0]["topic_id"] == "school" and len(sent) == 21
    assert [item["topic_id"] for item in sent[1:]] == [f"neu-{index}" for index in range(5, 25)]
    # Only what changes, without empty lists: here a new topic without examples.
    assert sent[1]["changes"] == {"name": "neu 5", "description": "verbindliche schulaufgaben", "enabled": True}


def test_the_review_summary_names_hidden_proposals(tmp_path):
    from mailhelp.web.rule_learning_site import RuleLearningSite
    harness = RuleHarness(tmp_path)
    reject_first(harness)
    harness.analyzer.result = RuleAnalysis(proposals=[proposal(), proposal(
        action="create", category="irrelevant", topic_id="noise", proposed=topic(id="noise", name="Werbung"))])
    state = again(harness, "analyze-2")
    site = RuleLearningSite.__new__(RuleLearningSite)
    site.site = type("Site", (), {"auth": type("Auth", (), {"csrf_token": staticmethod(lambda _id: "c")})()})()
    session = type("Session", (), {"id": "a"})()
    assert "1 bereits abgelehnter Vorschlag wurde ausgeblendet" in site.review(session, state, {})
    from mailhelp.rule_learning.service import hidden_text
    assert hidden_text(3) == "3 bereits abgelehnte Vorschläge wurden ausgeblendet"


def test_both_shipped_prompts_name_the_rejected_changes():
    for path in ("prompts.yaml", "src/mailhelp/defaults/prompts.yaml"):
        step = yaml.safe_load(Path(path).read_text(encoding="utf-8"))["prompts"]["decision_rule_learning"]
        assert '"rejected" nennt Änderungen, die der Nutzer ausdrücklich abgelehnt hat' in step["system_prompt"]
        assert 'aus "rejected" hat der Nutzer abgelehnt' in step["output_token_retry"]["system_prompt"]
