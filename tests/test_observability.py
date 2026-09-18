from __future__ import annotations

import json
import os
from io import StringIO
from time import time

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


def test_failure_details_and_stacktraces_are_redacted_in_structured_log(tmp_path):
    logger = JsonlLogger(tmp_path, secrets={"mail body marker"})
    logger.event("ERROR", "orchestrator", "processing_failed",
                 error=RuntimeError("password=bad mail body marker"),
                 stacktrace="Traceback: token=raw mail body marker")
    record = json.loads(logger.app.read_text(encoding="utf-8"))
    serialized = json.dumps(record)
    assert record["event"] == "processing_failed"
    assert "bad" not in serialized and "raw" not in serialized and "mail body marker" not in serialized


def test_logging_settings_module_level_validation():
    base = {"directory": "logs", "console": {},
            "file": {"filename": "application.jsonl", "max_bytes": 100, "backup_count": 1, "retention_days": 1},
            "llm": {"filename": "llm/requests.jsonl", "max_bytes": 100, "backup_count": 1, "retention_days": 1}}
    assert LoggingSettings.model_validate({**base, "modules": {"imap": "ERROR"}}).modules["imap"] == "ERROR"
    for bad in ({"": "INFO"}, {"imap": "TRACE"}):
        with pytest.raises(Exception): LoggingSettings.model_validate({**base, "modules": bad})
    for field, value in (("filename", "../bad"), ("filename", "/absolute"), ("max_bytes", 0),
                         ("filename", 4), ("backup_count", -1), ("retention_days", 0)):
        candidate = json.loads(json.dumps(base))
        candidate["file"][field] = value
        with pytest.raises(Exception): LoggingSettings.model_validate(candidate)


def test_independent_targets_levels_console_and_module_inheritance(tmp_path):
    console = StringIO()
    logger = JsonlLogger(
        tmp_path, True, True, "WARNING", {"quiet": "ERROR", "openrouter": "CRITICAL"},
        {"synthetic-secret"}, console_enabled=True, console_level="DEBUG", console=console,
        llm_level="DEBUG",
    )
    for level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        logger.event(level, "inherited", level.lower(), value="synthetic-secret")
    logger.event("WARNING", "quiet", "filtered")
    logger.event("ERROR", "quiet.child", "module-visible")
    logger.event("INFO", "inherited", "console-only")
    logger.llm_event("llm-debug", request="raw synthetic-secret", response="raw", level="DEBUG")
    app = [json.loads(row) for row in logger.app.read_text().splitlines()]
    llm = json.loads(logger.llm.read_text())
    assert [row["event"] for row in app] == ["warning", "error", "critical", "module-visible"]
    assert llm["event"] == "llm-debug"  # independent of the openrouter CRITICAL filter
    output = console.getvalue()
    assert "module-visible" in output and "console-only" in output and "llm-debug" not in output
    assert "synthetic-secret" not in output and "raw" not in output

    disabled = JsonlLogger(tmp_path / "disabled", file_enabled=False, console_enabled=False, llm_enabled=False)
    disabled.event("CRITICAL", "x", "no-file")
    disabled.llm_event("no-llm")
    assert not disabled.app.exists() and not disabled.llm.exists()
    with pytest.raises(ValueError, match="Logformat"):
        JsonlLogger(tmp_path / "bad-format", file_format="xml")
    with pytest.raises(ValueError, match="Loggröße"):
        JsonlLogger(tmp_path / "bad-size", llm_retention_days=0)


def test_rotation_backup_limit_retention_and_restart(tmp_path):
    options = dict(file_max_bytes=180, file_backup_count=2, file_retention_days=1,
                   llm_max_bytes=180, llm_backup_count=1, llm_retention_days=1)
    logger = JsonlLogger(tmp_path, **options)
    for number in range(8):
        logger.event("INFO", "test", "rotating", number=number, padding="x" * 80)
    assert logger.app.exists() and logger.app.with_name("application.jsonl.1").exists()
    assert logger.app.with_name("application.jsonl.2").exists()
    assert not logger.app.with_name("application.jsonl.3").exists()

    stale = logger.llm.with_name("requests.jsonl.1")
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("old")
    old = time() - 3 * 86400
    os.utime(stale, (old, old))
    JsonlLogger(tmp_path, **options)  # restart performs bounded cleanup
    assert not stale.exists()

    no_backups = JsonlLogger(tmp_path / "none", file_max_bytes=1, file_backup_count=0)
    no_backups.event("INFO", "test", "first")
    no_backups.event("INFO", "test", "second")
    assert no_backups.app.exists() and not no_backups.app.with_name("application.jsonl.1").exists()


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
    assert rows[0]["request"]["messages"] == [
        {"role": "system", "content": "system"},
        {"role": "user", "content": '{"internal_id": "mail", "proposal_id": "proposal"}'},
    ]
    assert rows[1]["response"] == good

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
