"""5.7.7: the model returns changes, the input is condensed and a truncated answer is retried smaller."""
import json
from pathlib import Path

import httpx
import pytest
import yaml
from pydantic import ValidationError

from mailhelp.config import PromptConfig
from mailhelp.llm.openrouter import OpenRouterClient, ProviderResponseInvalid
from mailhelp.logging import JsonlLogger
from mailhelp.processing.analysis import Analyzer, LlmTokenLimitExceeded
from mailhelp.rule_learning.changes import (
    RuleChanges,
    RuleSuggestions,
    assemble,
    compact_topics,
    condense,
)
from mailhelp.rule_learning.models import RuleAnalysis
from tests.fakes.rule_learning import RuleHarness, record, topic
from tests.fakes.shared_core import prompt_config
from tests.fakes.shared_services import RetrySequence
from tests.fakes.shared_web_actions import web as web  # noqa: F401

SCHOOL = topic(examples=["Elternabend", "Ausflug"], exclusions=["Newsletter"], mailboxes=[2]).model_dump()
DOCUMENTS = {"relevant": {"topics": [SCHOOL]},
             "irrelevant": {"topics": [{**SCHOOL, "id": "ads", "name": "Werbung", "mailboxes": None}]}}


def suggestion(**changes):
    data = {"topic_id": "school", "category": "relevant", "action": "modify", "rationale": "Korrektur",
            "evidence": ["decision-1"], "changes": {"add_exclusions": ["Werbung"]}}
    return {**data, **changes}


def build(*items):
    return assemble(DOCUMENTS, RuleSuggestions.model_validate({"proposals": list(items)}))


def test_modify_keeps_id_and_mailboxes_and_merges_entries_without_duplicates():
    result = build(suggestion(changes={"add_examples": ["Zeugnis", "Zeugnis", "Ausflug"],
                                       "remove_examples": ["Elternabend"], "remove_exclusions": ["Newsletter"],
                                       "add_exclusions": ["Werbung"], "name": "Schule neu",
                                       "description": "Neu", "enabled": True}))
    proposed = result.proposals[0].proposed
    assert proposed.id == "school" and proposed.mailboxes == [2] and proposed.name == "Schule neu"
    assert proposed.examples == ["Ausflug", "Zeugnis"] and proposed.exclusions == ["Werbung"]
    assert proposed.description == "Neu" and result.proposals[0].rationale == "Korrektur"


def test_create_and_disable_are_assembled_from_their_few_fields():
    result = build(suggestion(topic_id="sport", action="create",
                              changes={"name": "Sport", "description": "Vereinssport", "add_examples": ["Training"],
                                       "add_exclusions": ["Werbung"]}),
                   suggestion(category="irrelevant", topic_id="ads", action="disable", changes={}),
                   suggestion(topic_id="hidden", action="create",
                              changes={"name": "Aus", "description": "Aus", "add_examples": ["a"],
                                       "enabled": False}))
    created, disabled, hidden = (item.proposed for item in result.proposals)
    assert created.enabled and created.mailboxes is None and created.examples == ["Training"]
    assert disabled.enabled is False and disabled.examples == SCHOOL["examples"]
    assert hidden.enabled is False
    assert build(suggestion(action="disable", changes={"enabled": False})).proposals[0].proposed.enabled is False


@pytest.mark.parametrize(("item", "message"), [
    (suggestion(topic_id="ads", action="create", changes={"name": "x", "description": "x", "add_examples": ["x"]}),
     "bereits vergeben"),
    (suggestion(topic_id="new", action="create", changes={"name": "x", "add_examples": ["x"]}), "braucht name"),
    (suggestion(topic_id="new", action="create", changes={"name": "x", "description": "x"}), "braucht name"),
    (suggestion(topic_id="new", action="create", changes={"name": "x", "description": "x", "add_examples": ["x"],
                                                           "remove_exclusions": ["x"]}), "nichts zu entfernen"),
    (suggestion(topic_id="missing"), "fehlt in den relevant Regeln"),
    (suggestion(category="irrelevant"), "fehlt in den irrelevant Regeln"),
    (suggestion(action="disable", changes={"name": "x"}), "keine weiteren Änderungen"),
    (suggestion(changes={"remove_examples": ["Gibt es nicht"]}), "zu entfernende Beispiele fehlen"),
    (suggestion(changes={"remove_exclusions": ["Gibt es nicht"]}), "zu entfernende Ausschlüsse fehlen"),
    (suggestion(changes={"add_examples": ["Ausflug"]}), "ändert nichts"),
    (suggestion(changes={}), "ändert nichts"),
])
def test_inconsistent_changes_are_rejected(item, message):
    with pytest.raises(ValueError, match=message):
        build(item)


def test_the_answer_contract_is_small_and_closed():
    with pytest.raises(ValidationError):
        RuleSuggestions.model_validate({"proposals": [suggestion(topic_id=f"t{index}") for index in range(11)]})
    with pytest.raises(ValidationError, match="nur einmal"):
        RuleSuggestions.model_validate({"proposals": [suggestion(), suggestion()]})
    with pytest.raises(ValidationError):
        RuleSuggestions.model_validate({"proposals": [suggestion(rationale="x" * 501)]})
    with pytest.raises(ValidationError):
        RuleSuggestions.model_validate({"proposals": [suggestion(evidence=[f"d{index}" for index in range(11)])]})
    with pytest.raises(ValidationError):
        RuleSuggestions.model_validate({"proposals": [suggestion(proposed=SCHOOL)]})
    for changes in ({"add_examples": ["x" * 501]}, {"add_exclusions": [" "]}, {"name": "a\x00"},
                    {"add_examples": [str(index) for index in range(11)]}, {"unknown": 1}):
        with pytest.raises(ValidationError):
            RuleChanges.model_validate(changes)
    with pytest.raises(ValidationError):
        RuleSuggestions.model_validate({"proposals": [suggestion(rationale="\x01")]})
    assert RuleChanges.model_validate({"name": "Gut"}).name == "Gut"


def test_strong_signals_go_in_full_and_rejections_are_counted_per_topic_set():
    rejections = [{"id": f"r{index}", "signal": "rejected_proposal", "topic_ids": ["school"], "text": "y" * 900}
                  for index in range(7)]
    other = {"id": "o", "signal": "rejected_proposal", "topic_ids": [], "text": "kurz"}
    strong = {"id": "c", "signal": "manual_correction", "topic_ids": ["school"], "text": "z" * 900}
    sent, groups = condense([*rejections, strong, other])
    assert [item["id"] for item in sent] == ["c", "r0", "r1", "r2", "r3", "r4", "o"]
    assert sent[0]["text"] == "z" * 900 and len(sent[1]["text"]) == 300
    assert groups == [{"signal": "rejected_proposal", "topic_ids": ["school"], "count": 7, "shown": 5},
                      {"signal": "rejected_proposal", "topic_ids": [], "count": 1, "shown": 1}]


def test_topics_without_evidence_are_sent_briefly():
    topics = compact_topics(DOCUMENTS, [{"topic_ids": ["school"]}])
    assert topics["relevant"]["topics"][0] == SCHOOL
    assert topics["irrelevant"]["topics"][0] == {"id": "ads", "name": "Werbung",
                                                 "description": SCHOOL["description"], "enabled": True}


def test_the_service_sends_a_condensed_payload_and_a_smaller_retry(tmp_path):
    harness = RuleHarness(tmp_path)
    harness.log(*[record(f"decision-{index}") for index in range(8)],
                record("decision-edit", "edit", proposal={"changes": {"title": "Neu"}}))
    harness.analyzer.result = RuleSuggestions.model_validate({"proposals": [suggestion(evidence=["decision-edit"])]})
    harness.analyze()
    assert harness.service.tick()
    state = harness.service.state("web:a")
    assert state.status == "review" and state.condensed == 3 and len(state.evidence) == 9
    assert state.proposals[0].proposed.exclusions == ["Werbung"]
    payload, retry = harness.analyzer.calls[0], harness.analyzer.retries[0]
    assert [item["id"] for item in payload["decisions"]][0] == "decision-edit" and len(payload["decisions"]) == 6
    assert payload["groups"][0]["count"] == 8 and "secret-token" not in json.dumps(payload)
    assert [item["id"] for item in retry["decisions"]] == [item["id"] for item in payload["decisions"]][:3]


def test_the_review_names_condensed_rejections(web, tmp_path):
    harness = RuleHarness(tmp_path, web.store, web.dialog.review.web_authorizer)
    web.site.rule_learning.service = harness.service
    session = web.auth.sessions()[0]
    harness.log(*[record(f"decision-{index}") for index in range(7)])
    harness.analyzer.result = RuleAnalysis(proposals=[])
    harness.analyze("web:" + session.id)
    harness.service.tick()
    html = web.browser.request("GET", "/lernen/entscheidungen").body.decode()
    assert "2 gleichartige Ablehnungen nur als Anzahl übertragen" in html


def analyzer(client, retry=True):
    data = prompt_config().model_dump()
    data["prompts"]["decision_rule_learning"] = {"system_prompt": "Voller Prompt", "model_route": "action_router",
                                                 "parameters": {"max_tokens": 16000}}
    if retry:
        data["prompts"]["decision_rule_learning"]["output_token_retry"] = {
            "system_prompt": "Knapper Prompt", "parameters": {"max_tokens": 8000}}
    return Analyzer(client, PromptConfig.model_validate(data), validation_retries=1)


PAYLOAD = {"topics": {}, "decisions": [{"id": "decision-1"}, {"id": "decision-2"}]}
SMALL = {"topics": {}, "decisions": [{"id": "decision-1"}]}


def test_a_truncated_answer_is_retried_once_smaller_not_identically():
    # 5.7.7 regression: the second request after output_token_limit repeated the first one.
    client = RetrySequence([ProviderResponseInvalid("output_token_limit"), {"proposals": [suggestion()]}])
    _call, result = analyzer(client).decision_rule_learning(
        PAYLOAD, assemble=lambda suggestions: assemble(DOCUMENTS, suggestions), retry_payload=SMALL)
    assert client.payloads == [PAYLOAD, SMALL] and client.systems == ["Voller Prompt", "Knapper Prompt"]
    assert client.parameters[1]["max_tokens"] == 16000  # never smaller than the truncated budget
    assert result.proposals[0].proposed.exclusions == ["Newsletter", "Werbung"]
    client = RetrySequence([ProviderResponseInvalid("output_token_limit")] * 2)
    with pytest.raises(LlmTokenLimitExceeded):
        analyzer(client).decision_rule_learning(PAYLOAD, retry_payload=SMALL)
    assert len(client.payloads) == 2


def test_without_a_configured_retry_prompt_the_payload_is_not_swapped():
    client = RetrySequence([ProviderResponseInvalid("output_token_limit"), {"proposals": []}])
    analyzer(client, retry=False).decision_rule_learning(PAYLOAD, retry_payload=SMALL)
    assert client.payloads == [PAYLOAD, PAYLOAD]


def test_an_answer_that_cannot_be_assembled_gets_one_schema_repair():
    client = RetrySequence([{"proposals": [suggestion(topic_id="missing")]}, {"proposals": [suggestion()]}])
    _call, result = analyzer(client).decision_rule_learning(
        PAYLOAD, assemble=lambda suggestions: assemble(DOCUMENTS, suggestions))
    assert len(client.payloads) == 2 and "fehlt in den relevant Regeln" in client.payloads[1]["previous_validation_error"]
    assert result.proposals[0].topic_id == "school"


@pytest.mark.parametrize("path", ["prompts.yaml", "src/mailhelp/defaults/prompts.yaml"])
def test_the_shipped_prompt_asks_for_changes_and_has_a_smaller_retry(path):
    step = yaml.safe_load(Path(path).read_text(encoding="utf-8"))["prompts"]["decision_rule_learning"]
    assert "NUR, was sich ändert" in step["system_prompt"] and "vollständiges Topic" not in step["system_prompt"]
    assert "höchstens 5 Einträge" in step["output_token_retry"]["system_prompt"]


def truncated(body):
    def handler(request):
        return httpx.Response(200, json=body, request=request)
    return handler


def test_a_truncated_answer_logs_its_token_usage_and_length_but_not_its_text(tmp_path):
    # 5.7.7 regression: output_token_limit was logged without usage, so the cause stayed unknown.
    body = {"id": "x", "provider": "Parasail", "cost": 0.004,
            "usage": {"prompt_tokens": 60000, "completion_tokens": 16000,
                      "completion_tokens_details": {"reasoning_tokens": 15000}},
            "choices": [{"finish_reason": "length",
                         "message": {"content": '{"proposals": [{"secret partial', "reasoning": "denken"}}]}
    logger = JsonlLogger(tmp_path, include_llm_requests=False, include_llm_responses=False)
    client = OpenRouterClient("key", 1, 0, 10, httpx.MockTransport(truncated(body)), logger=logger)
    with pytest.raises(ProviderResponseInvalid):
        client.complete("model", {}, "system", {}, stage="decision_rule_learning")
    client.close()
    text = logger.llm.read_text()
    row = next(item for item in map(json.loads, text.splitlines()) if item["event"] == "provider_response_invalid")
    assert row["completion_tokens"] == 16000 and row["reasoning_tokens"] == 15000
    assert row["token_usage"]["prompt_tokens"] == 60000 and row["reported_cost"] == 0.004
    assert row["partial_content_length"] == 31 and row["partial_reasoning_length"] == 6
    assert len(row["partial_content_sha256"]) == 64 and "secret partial" not in text


@pytest.mark.parametrize("body", [
    {"id": "x", "choices": [{"finish_reason": "length", "message": {"content": None}}]},
    {"id": "x", "usage": {"completion_tokens": 5, "completion_tokens_details": None},
     "choices": [{"finish_reason": "length"}]},
    {"id": "x", "usage": "kaputt", "choices": [{"finish_reason": "length", "message": "kaputt"}]},
])
def test_truncation_details_tolerate_incomplete_provider_envelopes(tmp_path, body):
    logger = JsonlLogger(tmp_path)
    client = OpenRouterClient("key", 1, 0, 10, httpx.MockTransport(truncated(body)), logger=logger)
    with pytest.raises(ProviderResponseInvalid):
        client.complete("model", {}, "system", {})
    client.close()
    row = next(item for item in map(json.loads, logger.llm.read_text().splitlines())
               if item["event"] == "provider_response_invalid")
    assert row["partial_content_length"] == 0 and row["partial_content_sha256"] is None
    assert row["reasoning_tokens"] is None
