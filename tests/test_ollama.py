"""Experimental local mode: Ollama client against a simulated server."""
from __future__ import annotations

import json

import httpx
import pytest
from pydantic import BaseModel

from mailhelp.adapter import PermanentError, RetryableError
from mailhelp.ollama import LocalLlm, OllamaClient, parse_address
from mailhelp.openrouter import ProviderResponseInvalid

LOCAL = LocalLlm("192.168.1.20", 11434, "qwen2.5:7b-instruct")


class Answer(BaseModel):
    value: int


class Recorder:
    def __init__(self): self.events = []
    def event(self, *args, **fields): self.events.append((args[2], fields))
    def llm_event(self, event, **fields): self.events.append((event, fields))


def native(content='{"value": 1}', **changes):
    body = {"model": LOCAL.model, "created_at": "2026-10-08T12:00:00Z",
            "message": {"role": "assistant", "content": content}, "done": True,
            "done_reason": "stop", "prompt_eval_count": 12, "eval_count": 5}
    body.update(changes)
    return body


def client(handler, logger=None, local=LOCAL):
    return OllamaClient(local, 5, 0, 100, transport=httpx.MockTransport(handler),
                        logger=logger)


def test_complete_sends_native_chat_request_and_maps_the_answer():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=native())

    log = Recorder()
    llm = client(handler, log)
    call_id, content = llm.complete(
        "z-ai/glm-5.3-flash", {"temperature": 0.0, "max_tokens": 100, "top_p": 0.9,
                               "reasoning": {"effort": "low"}},
        "System", {"internal_id": "a" * 24}, stage="relevance",
        provider_preferences={"order": ["together"]}, response_schema=Answer)
    llm.close()

    assert content == {"value": 1} and call_id
    request = seen[0]
    assert str(request.url) == "http://192.168.1.20:11434/api/chat"
    assert "authorization" not in request.headers
    body = json.loads(request.content)
    # The local model replaces every OpenRouter route model; OpenRouter-only
    # settings (provider routing, reasoning) are not forwarded.
    assert body == {
        "model": "qwen2.5:7b-instruct",
        # The stage budget from prompts.yaml is stated in the system prompt.
        "messages": [{"role": "system", "content": "System\n\nAntworte in maximal 100 Token."},
                     {"role": "user", "content": json.dumps({"internal_id": "a" * 24})}],
        "stream": False,
        "format": Answer.model_json_schema(),
        "options": {"num_ctx": 65536, "temperature": 0.0, "num_predict": 100, "top_p": 0.9},
    }
    received = dict(log.events)["response_received"]
    assert received["provider"] == "ollama" and received["model"] == "qwen2.5:7b-instruct"
    assert received["token_usage"] == {"prompt_tokens": 12, "completion_tokens": 5}


def test_regression_length_limits_are_not_sent_as_ollama_grammar():
    """Regression 2026-10-08: Ollama rejected task, event and revision schemas.

    "Failed to initialize samplers: failed to parse grammar" (HTTP 400) for
    long ``maxLength`` limits. Lengths stay enforced by the local validation.
    """
    from mailhelp.models import ProposalRevisionDelta, TaskExtraction

    seen = []

    def handler(request):
        seen.append(json.loads(request.content)["format"])
        return httpx.Response(200, json=native('{"schema_version": 1, "tasks": []}'))

    def keywords(node):
        if isinstance(node, dict):
            return set(node) | {key for value in node.values() for key in keywords(value)}
        if isinstance(node, list):
            return {key for value in node for key in keywords(value)}
        return set()

    llm = client(handler)
    llm.complete("m", {}, "s", {}, response_schema=TaskExtraction)
    sent = seen[0]
    assert {"maxLength", "minLength"} & keywords(TaskExtraction.model_json_schema())
    assert not {"maxLength", "minLength"} & keywords(sent)
    # Everything else, e.g. enums, item limits and required fields, is kept.
    task = sent["$defs"]["ExtractedTask"]
    assert task["required"] and task["properties"]["certainty"]
    assert sent["properties"]["tasks"]["maxItems"] == 20
    # A property that happens to be called like a keyword is not removed.
    assert OllamaClient._grammar_schema(
        {"properties": {"maxLength": {"type": "integer", "maxLength": 3}}}
    ) == {"properties": {"maxLength": {"type": "integer"}}}
    assert "maxLength" in keywords(ProposalRevisionDelta.model_json_schema())


def test_regression_optional_fields_are_required_in_the_ollama_grammar():
    """Regression 2026-10-08 (Hy3): date_text and time_text were always null.

    Ollama's grammar let the model skip optional properties; Hy3 read
    "15.10.2026 um 14:00 Uhr" (see evidence) but omitted both fields. Every
    property is now required in the grammar; null stays allowed.
    """
    from mailhelp.models import EventExtraction

    sent = OllamaClient._grammar_schema(EventExtraction.model_json_schema())
    event = sent["$defs"]["ExtractedEvent"]
    assert event["required"] == list(event["properties"])
    assert {"date_text", "time_text", "end_time_text"} <= set(event["required"])
    assert {"type": "null"} in event["properties"]["date_text"]["anyOf"]
    assert sent["required"] == list(sent["properties"]) == ["schema_version", "events"]
    # The local validation keeps the original optional fields.
    original = EventExtraction.model_json_schema()["$defs"]["ExtractedEvent"]
    assert "date_text" not in original["required"]


def test_regression_revision_changes_stay_sparse_in_the_ollama_grammar():
    """Regression 2026-10-08 (Hy3): forcing every field broke the revision.

    A missing key in ``changes`` means "unchanged"; with all fields required
    Hy3 wrote every field as null and B1 rejected the delta.
    """
    from mailhelp.models import ProposalRevisionDelta

    sent = OllamaClient._grammar_schema(ProposalRevisionDelta.model_json_schema())
    changes = sent["$defs"]["ProposalRevisionChanges"]
    assert "required" not in changes and changes["properties"]["title"]
    assert sent["required"] == ["answered_question", "changes"]


def test_without_schema_the_json_mode_is_requested():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=native())

    client(handler).complete("m", {}, "s", {}, response_schema=None)
    assert seen[0]["format"] == "json" and seen[0]["options"] == {"num_ctx": 65536}
    # Without a configured budget no token sentence is added.
    assert seen[0]["messages"][0] == {"role": "system", "content": "s"}


@pytest.mark.parametrize(("answer", "reason"), [
    (native(done_reason="length"), "output_token_limit"),
    ({"error": "kaputt"}, "choices_missing"),
    (native(content=""), "message_content_empty"),
])
def test_unusable_answers_use_the_shared_provider_classification(answer, reason):
    llm = client(lambda request: httpx.Response(200, json=answer))
    with pytest.raises(ProviderResponseInvalid) as error:
        llm.complete("m", {}, "s", {}, response_schema=Answer)
    assert error.value.reason == reason


def test_envelope_without_optional_metadata():
    envelope = OllamaClient._envelope({"message": {"content": "{}"}, "eval_count": "x"})
    assert envelope == {"id": "ollama-response", "provider": "ollama",
                        "choices": [{"message": {"content": "{}"}, "finish_reason": None}],
                        "usage": {}}


@pytest.mark.parametrize(("status", "error_type", "detail"), [
    (404, PermanentError, "Ollama: HTTP 404 (Modell auf dem Ollama-Server nicht gefunden)"),
    (500, RetryableError, "Ollama: HTTP 500"),
])
def test_http_errors_get_a_safe_ollama_diagnostic(status, error_type, detail):
    llm = client(lambda request: httpx.Response(status, json={"error": "x"}))
    with pytest.raises(error_type, match=detail.replace("(", r"\(").replace(")", r"\)")):
        llm.complete("m", {}, "s", {}, response_schema=Answer)


def test_check_access_requires_the_installed_model():
    def tags(*names):
        return lambda request: httpx.Response(
            200, json={"models": [{"name": name, "model": name} for name in names]})

    client(tags("qwen2.5:7b-instruct")).check_access()
    client(tags("llama3:latest"), local=LocalLlm("localhost", 11434, "llama3")).check_access()
    with pytest.raises(ValueError, match="ollama pull qwen2.5:7b-instruct"):
        client(tags("llama3:latest")).check_access()
    with pytest.raises(ValueError, match="Schlüsselpfad models"):
        client(lambda request: httpx.Response(200, json=[])).check_access()


@pytest.mark.parametrize(("value", "expected"), [
    ("192.168.1.20:11434", ("192.168.1.20", 11434)),
    (" localhost:11434 ", ("localhost", 11434)),
    ("gpu-server.lan:8080", ("gpu-server.lan", 8080)),
    ("[::1]:11434", ("::1", 11434)),
])
def test_parse_address_accepts_host_and_port(value, expected):
    assert parse_address(value) == expected


@pytest.mark.parametrize(("value", "message"), [
    ("11434", "HOST:PORT"), (":11434", "HOST:PORT"),
    ("::1:11434", "eckigen Klammern"), ("[nope]:11434", "IPv6"),
    ("bad_host!:11434", "Hostname"), ("host:0", "Port"), ("host:70000", "Port"),
    ("host:abc", "Port"),
])
def test_parse_address_rejects_invalid_values(value, message):
    with pytest.raises(ValueError, match=message):
        parse_address(value)


def test_ipv6_base_url_uses_brackets():
    assert LocalLlm("::1", 11434, "m").base_url == "http://[::1]:11434"
    assert LOCAL.base_url == "http://192.168.1.20:11434"
