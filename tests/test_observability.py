from __future__ import annotations

import json

import httpx
import pytest

from mailhelp.config import LoggingSettings
from mailhelp.integrations import HttpWriter
from mailhelp.logging import JsonlLogger, NullLogger, redact
from mailhelp.openrouter import OpenRouterClient
from mailhelp.telegram import TelegramClient
from test_core import proposal


class Capture:
    def __init__(self):
        self.events = []

    def event(self, level, module, event, **context):
        self.events.append((level, module, event, context))

    def llm_event(self, event, request=None, response=None, **context):
        self.events.append(("LLM", "openrouter", event, {"request": request, "response": response, **context}))


def test_levels_jsonl_and_recursive_redaction(tmp_path):
    logger = JsonlLogger(tmp_path, True, True, "WARNING", {"worker": "DEBUG"}, {"known-value", ""})
    logger.event("INFO", "other", "hidden")
    logger.event("DEBUG", "worker", "visible", nested=[{"Authorization": "Bearer abc"}],
                 error=RuntimeError("password=bad known-value"), raw=b"token=bytes", odd=object())
    logger.llm_event("done", request={"prompt": "known-value"}, response=("api_key=x",), level="WARNING")
    app = [json.loads(line) for line in logger.app.read_text(encoding="utf-8").splitlines()]
    llm = json.loads(logger.llm.read_text(encoding="utf-8"))
    assert [item["event"] for item in app] == ["visible"]
    serialized = json.dumps([app, llm])
    assert "known-value" not in serialized and "bad" not in serialized and "bytes" not in serialized
    assert app[0]["nested"][0]["Authorization"] == "***"
    with pytest.raises(ValueError): JsonlLogger(tmp_path, level="TRACE")
    with pytest.raises(ValueError): JsonlLogger(tmp_path, module_levels={"x": "TRACE"})
    with pytest.raises(ValueError): logger.event("TRACE", "x", "bad")
    NullLogger().event("INFO", "x", "ignored")
    NullLogger().llm_event("ignored")
    with pytest.raises(ValueError): NullLogger().event("TRACE", "x", "bad")
    assert redact(None) is None and redact({"items": {"a", "b"}})["items"]


def test_logging_settings_module_level_validation():
    base = {"directory": "logs", "level": "INFO"}
    assert LoggingSettings.model_validate({**base, "module_levels": {"imap": "ERROR"}}).module_levels["imap"] == "ERROR"
    for bad in ({"": "INFO"}, {"imap": "TRACE"}):
        with pytest.raises(Exception): LoggingSettings.model_validate({**base, "module_levels": bad})


def test_openrouter_correlated_response_raw_switch_and_error(tmp_path):
    good = {"id": "call", "choices": [{"message": {"content": "{}"}}], "usage": {"total_tokens": 4, "cost": 0.2}}
    logger = JsonlLogger(tmp_path / "raw", True, True)
    client = OpenRouterClient("known", 1, 0, 10, httpx.MockTransport(lambda request: httpx.Response(200, json=good, request=request)), logger=logger)
    call_id, _ = client.complete("model", {"temperature": 0}, "system", {"internal_id": "mail", "proposal_id": "proposal"})
    client.close()
    rows = [json.loads(line) for line in logger.llm.read_text().splitlines()]
    assert [row["event"] for row in rows] == ["request_started", "response_received"]
    assert all(row["call_id"] == call_id and row["mail_id"] == "mail" and row["proposal_id"] == "proposal" for row in rows)
    assert rows[1]["token_usage"]["total_tokens"] == 4 and rows[1]["reported_cost"] == .2
    assert "request" in rows[0] and "response" in rows[1]

    capture = Capture()
    failing = OpenRouterClient("secret", 1, 0, 10, httpx.MockTransport(lambda request: httpx.Response(400, text="token=leak", request=request)), logger=capture)
    with pytest.raises(Exception): failing.complete("model", {}, "system", {"mail_id": "m"})
    failing.close()
    assert [event[2] for event in capture.events] == ["request_started", "retry_failed", "request_failed"]
    assert capture.events[-1][3]["attempt"] == 1 and "Traceback" in capture.events[-1][3]["stacktrace"]


def test_network_adapter_failure_events():
    capture = Capture()
    telegram = TelegramClient("secret", 1, httpx.MockTransport(lambda request: (_ for _ in ()).throw(httpx.ConnectError("token=bad", request=request))), logger=capture)
    with pytest.raises(Exception): telegram.poll(0)
    telegram.close()
    assert capture.events[-1][2] == "poll_failed"

    writer = HttpWriter("todoist", "secret", "target", transport=httpx.MockTransport(
        lambda request: httpx.Response(503, text="secret", request=request)), logger=capture)
    with pytest.raises(Exception): writer.create(proposal(status="confirmed"), "request-id")
    writer.close()
    failed = capture.events[-1]
    assert failed[2] == "create_failed" and failed[3]["proposal_id"] == "p1"
