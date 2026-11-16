"""The analyzer: provider calls, retry categories and budgets."""
from __future__ import annotations

import json

import httpx
import pytest

from mailhelp.config import Topic
from mailhelp.domain.revision_errors import ContradictoryRevision
from mailhelp.llm.adapter import RetryableError
from mailhelp.llm.openrouter import InvalidJson, OpenRouterClient, ProviderResponseInvalid, RateLimitExceeded
from mailhelp.processing.analysis import (
    JSON_REPAIR_INSTRUCTION,
    SCHEMA_REPAIR_INSTRUCTION,
    Analyzer,
    LlmInvalidJson,
    LlmProviderResponseInvalid,
    LlmSchemaValidationFailed,
    validate_revision_successor,
)
from tests.fakes.shared_core import prompt_config, proposal
from tests.fakes.shared_services import (
    FakeCompleter,
    RetrySequence,
    mock_response,
)


def test_openrouter(monkeypatch):
    data={"id":"completion-1","choices":[{"message":{"content":json.dumps({"decision":"irrelevant","reason":"x"})}}]}
    client=OpenRouterClient("secret", 1, 0, 1, httpx.MockTransport(mock_response(data=data)))
    call, result=client.complete("m", {}, "s", {"x":1})
    assert call and result["decision"] == "irrelevant"
    with pytest.raises(RateLimitExceeded): client.complete("m", {}, "s", {})
    client.calls[0] -= 61
    client.complete("m", {}, "s", {})
    client.close()
    attempts=[]
    def flaky(request):
        attempts.append(1)
        if len(attempts) == 1: raise httpx.ConnectError("x", request=request)
        return httpx.Response(500, request=request)
    client=OpenRouterClient("x",1,1,10,httpx.MockTransport(flaky), sleep=lambda x: attempts.append(x))
    with pytest.raises(RetryableError): client.complete("m", {}, "s", {})






def test_revision_keeps_known_date_and_start_and_never_infers_all_day():
    original = proposal(kind="event", status="needs_clarification",
                        open_questions=["Wann endet der Termin?"],
                        known_temporal_facts={"date": "2026-10-21",
                                              "start": "2026-10-21T10:00:00+02:00"})
    base = {**original.model_dump(mode="json"), "version": 2,
            "open_questions": [], "status": "pending_confirmation",
            "known_temporal_facts": None}
    valid = validate_revision_successor(original, {
        **base, "start": "2026-10-21T10:00:00+02:00",
        "end": "2026-10-21T11:00:00+02:00"})
    assert valid.start.isoformat() == "2026-10-21T10:00:00+02:00"
    for change in (
        {"all_day": True, "start": "2026-10-21", "end": "2026-10-22"},
        {"start": "2026-10-22T10:00:00+02:00", "end": "2026-10-22T11:00:00+02:00"},
        {"start": "2026-10-21T09:00:00+02:00", "end": "2026-10-21T11:00:00+02:00"},
    ):
        with pytest.raises(ContradictoryRevision):
            validate_revision_successor(original, {**base, **change})
    with pytest.raises(ContradictoryRevision, match="nicht verloren"):
        validate_revision_successor(original, {**base, "start": None, "end": None,
                                                "open_questions": ["Wann endet der Termin?"],
                                                "status": "needs_clarification"})
    with pytest.raises(ContradictoryRevision, match="nicht verändert"):
        validate_revision_successor(original, {
            **original.model_dump(mode="json"), "version": 2,
            "known_temporal_facts": {"date": "2026-10-21",
                                      "start": "2026-10-21T09:00:00+02:00"}})
    task = proposal(open_questions=["Datum?"])
    successor = {**task.model_dump(mode="json"), "version": 2,
                 "open_questions": [], "status": "pending_confirmation"}
    for changed, message in (({"source_mail_id": "b" * 24}, "Ursprungsmail"),
                             ({"version": 3}, "exakt um eins"),
                             ({"status": "needs_clarification"}, "offenen Fragen")):
        with pytest.raises(ContradictoryRevision, match=message):
            validate_revision_successor(task, {**successor, **changed})


@pytest.mark.parametrize(("failure", "repair_key"), [
    (ProviderResponseInvalid("message_content_null"), None),
    (InvalidJson(), "json_repair_instruction"),
    ({}, "previous_validation_error"),
])
def test_analyzer_classifies_retry_payloads_and_call_attempts(failure, repair_key):
    valid={"sentences":["Eins.","Zwei."],"deadlines":[]}
    client=RetrySequence([failure,valid])
    call_id,result=Analyzer(client,prompt_config()).summary({"subject":"synthetic"})

    assert call_id=="provider-call-2" and result.sentences==["Eins.","Zwei."]
    assert client.call_ids==["provider-call-1","provider-call-2"]
    assert len(client.payloads)==2
    assert client.payloads[0]=={"mail":{"subject":"synthetic"}}
    if repair_key is None:
        assert client.payloads[1]==client.payloads[0]
    else:
        assert repair_key in client.payloads[1]
    assert ("previous_validation_error" in client.payloads[1]) == (
        repair_key == "previous_validation_error"
    )
    if repair_key == "json_repair_instruction":
        assert client.payloads[1][repair_key]==JSON_REPAIR_INSTRUCTION
        assert client.systems[1].endswith(JSON_REPAIR_INSTRUCTION)
        assert "Pydantic" not in client.payloads[1][repair_key]
    else:
        assert JSON_REPAIR_INSTRUCTION not in client.systems[1]
    if repair_key == "previous_validation_error":
        assert "sentences" in client.payloads[1][repair_key]
        assert client.systems[1].endswith(SCHEMA_REPAIR_INSTRUCTION)


@pytest.mark.parametrize(("failure", "error_type", "limit_name"), [
    (ProviderResponseInvalid("message_missing"), LlmProviderResponseInvalid, "provider_retries"),
    (InvalidJson(), LlmInvalidJson, "json_repair_retries"),
    ({}, LlmSchemaValidationFailed, "schema_repair_retries"),
])
def test_analyzer_exhausts_each_retry_category_independently(failure, error_type, limit_name):
    values=[failure,failure]
    client=RetrySequence(values)
    limits={"provider_retries":0,"json_repair_retries":0,"schema_repair_retries":0}
    limits[limit_name]=1
    with pytest.raises(error_type):
        Analyzer(client,prompt_config(),**limits).summary({})
    assert client.call_ids==["provider-call-1","provider-call-2"]


def test_analyzer_flat_retry_budget_and_diagnostic_is_not_leaked():
    valid={"sentences":["Eins.","Zwei."],"deadlines":[]}
    client=RetrySequence([{},ProviderResponseInvalid("choice_missing"),InvalidJson(),valid])
    call_id,_=Analyzer(client,prompt_config(),provider_retries=1,
                       json_repair_retries=1,schema_repair_retries=1).summary({})
    assert call_id=="provider-call-4"
    assert "previous_validation_error" in client.payloads[1]
    assert client.payloads[2]=={"mail":{}}
    assert client.payloads[3]["json_repair_instruction"]==JSON_REPAIR_INSTRUCTION
    assert all("previous_validation_error" not in payload for payload in client.payloads[2:])


@pytest.mark.parametrize("kwargs", [
    {"validation_retries":-1}, {"provider_retries":-1},
    {"json_repair_retries":-1}, {"schema_repair_retries":-1},
])
def test_analyzer_rejects_negative_retry_limits(kwargs):
    with pytest.raises(ValueError,match="nicht negativ"):
        Analyzer(RetrySequence([]),prompt_config(),**kwargs)


def test_analyzer():
    client=FakeCompleter([{}, {"decision":"relevant","topic_ids":["x"],"reason":"yes"}, {"sentences":["a","b"],"deadlines":[]}, {"schema_version":1,"tasks":[]}, {"schema_version":1,"events":[]}])
    analyzer=Analyzer(client,prompt_config(),1)
    topic=Topic(id="x",name="X",enabled=True,description="D")
    assert analyzer.relevance({},[topic])[1].decision == "relevant"
    assert analyzer.summary({})[1].sentences == ["a","b"]
    assert analyzer.extract_tasks({}, expected_count=0)[1].tasks == []
    assert analyzer.extract_events({}, expected_count=0)[1].events == []
    with pytest.raises(ValueError): Analyzer(FakeCompleter([{},{}]),prompt_config(),1).summary({})
    with pytest.raises(LlmSchemaValidationFailed):
        Analyzer(FakeCompleter([{"decision":"relevant","topic_ids":["bad"],"reason":"x"}]),prompt_config(),schema_repair_retries=0).relevance({}, [topic])
    with pytest.raises(LlmSchemaValidationFailed):
        Analyzer(FakeCompleter([{"decision":"relevant","topic_ids":[],"reason":"x"}]),prompt_config(),schema_repair_retries=0).relevance({}, [topic])
