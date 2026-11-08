"""Planung Lernmodus, L.4: OpenRouter reports the token usage of an answer to the caller."""
import json

import httpx

from mailhelp.llm.openrouter import OpenRouterClient
from tests.fakes.shared_services import mock_response


def answer(**extra):
    return {"id": "completion-1", "choices": [{"message": {"content": json.dumps({"ok": True})}}], **extra}


def test_the_reported_usage_reaches_the_caller():
    usage = {"prompt_tokens": 3_000, "completion_tokens": 500, "total_tokens": 3_500}
    client = OpenRouterClient("secret", 10, 0, 10, httpx.MockTransport(mock_response(data=answer(usage=usage))))
    reported = []
    client.complete("m", {}, "s", {"x": 1}, usage=reported.append)
    client.close()
    assert reported == [usage]


def test_without_a_report_or_a_receiver_nothing_is_called():
    client = OpenRouterClient("secret", 10, 0, 10, httpx.MockTransport(mock_response(data=answer())))
    reported = []
    client.complete("m", {}, "s", {"x": 1}, usage=reported.append)  # the answer carries no usage
    client.complete("m", {}, "s", {"x": 1})                         # no receiver
    client.close()
    assert reported == []
