from __future__ import annotations

import copy
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from mailhelp.config import Settings, _validated_file
from mailhelp.integrations import HttpWriter, _with_external_result
from mailhelp.models import (ImapCheckpoint, MailState, Proposal, TelegramDialogState,
                             TelegramOffset, ValidationIssue, WriteAttemptReference)
from mailhelp.openrouter import OpenRouterClient, _path
from mailhelp.storage import CorruptState, JsonStore
from mailhelp.telegram import TelegramClient, TelegramUpdatesResponse, TelegramWriteResponse, _validation_path
from test_core import proposal


def valid_settings(tmp_path: Path) -> dict:
    return {
        "timezone": "UTC", "poll_interval_seconds": 5, "test_mode": False,
        "data_directory": str(tmp_path / "data"),
        "imap": {"host": "example.test", "port": 993, "folders": ["INBOX"]},
        "telegram": {"user_id": 1, "chat_id": -2},
        "targets": {"todoist_project": "inbox", "google_calendar": "primary"},
        "limits": {"max_mail_bytes": 1024, "llm_calls_per_minute": 1},
        "retries": {"validation": 0},
        "timeouts": {**{name: {"timeout_seconds": 1.0, "retries": 0, "initial_backoff_seconds": 0.0, "max_backoff_seconds": 1.0} for name in ("imap", "telegram", "openrouter", "todoist", "google_calendar")}, "telegram_poll_seconds": 1},
        "logging": {"directory": str(tmp_path / "logs"), "console": {"enabled": False}, "file": {"filename": "application.jsonl", "max_bytes": 10000, "backup_count": 1, "retention_days": 30}, "llm": {"filename": "llm/requests.jsonl", "max_bytes": 10000, "backup_count": 1, "retention_days": 30}},
    }


def test_mail_state_v5_metadata_is_closed_and_round_trips(tmp_path):
    now = datetime.now(timezone.utc)
    state = MailState(
        id="a" * 24, imap={"account_id":"0"*24,"folder": "INBOX", "uidvalidity": 1, "uid": 2},
        created_at=now, updated_at=now, config_fingerprint="f" * 64,
        validation_errors=[ValidationIssue(stage="relevance", code="invalid_shape", path=["decision"], occurred_at=now)],
        write_attempts=[WriteAttemptReference(mail_id="a" * 24, proposal_id="p1", proposal_version=2, service="todoist",
                                              idempotency_key="mailhelp:aaaaaaaaaaaaaaaaaaaaaaaa:p1:v2")],
    )
    with JsonStore(tmp_path / "states") as store:
        store.save("mail-a", state.model_dump(mode="json"))
        loaded = store.load_model("mail-a", MailState)
    assert loaded == state and loaded.schema_version == 5
    value = state.model_dump(mode="json")
    with pytest.raises(ValidationError):
        MailState.model_validate({**value, "unknown": True})
    with pytest.raises(ValidationError, match="doppelt"):
        MailState.model_validate({**value, "write_attempts": [
            state.write_attempts[0].model_dump(), state.write_attempts[0].model_dump()]})
    with pytest.raises(ValidationError, match="Zeitzone"):
        MailState.model_validate({**value, "created_at": now.replace(tzinfo=None)})
    with pytest.raises(ValidationError, match="vor created_at"):
        MailState.model_validate({**value, "updated_at": "2000-01-01T00:00:00Z"})
    with pytest.raises(ValidationError, match="zur Mail"):
        MailState.model_validate({**value, "write_attempts": [{
            **state.write_attempts[0].model_dump(), "mail_id": "b" * 24,
        }]})


def test_settings_reject_missing_extra_types_ranges_and_semantics(tmp_path):
    base = valid_settings(tmp_path)
    assert Settings.model_validate(base).timezone == "UTC"
    for mode in ("ssl", "starttls", "plain"):
        configured=copy.deepcopy(base); configured["imap"].update(connection_mode=mode, historical_start="2025-01-02T03:04:05+01:00")
        assert Settings.model_validate(configured).imap.connection_mode == mode
    mutations = [
        lambda x: x.pop("imap"),
        lambda x: x.update(extra=True),
        lambda x: x["imap"].update(extra=True),
        lambda x: x["imap"].update(port="993"),
        lambda x: x["imap"].update(port=0),
        lambda x: x["imap"].update(port=65536),
        lambda x: x["imap"].update(folders=[]),
        lambda x: x["imap"].update(folders=["INBOX", "INBOX"]),
        lambda x: x["imap"].update(folders=[""]),
        lambda x: x["imap"].update(folders=["bad\0name"]),
        lambda x: x["imap"].update(connection_mode="tls"),
        lambda x: x["imap"].update(historical_start="2025-01-02T03:04:05"),
        lambda x: x["imap"].update(historical_start="not-a-date"),
        lambda x: x["imap"].update(historical_start=123),
        lambda x: x.update(timezone="Moon/Base"),
        lambda x: x.update(poll_interval_seconds=4),
        lambda x: x.update(poll_interval_seconds=86401),
        lambda x: x["limits"].update(max_mail_bytes=100_000_001),
        lambda x: x["limits"].update(llm_calls_per_minute=0),
        lambda x: x["limits"].update(llm_calls_per_minute=601),
        lambda x: x["retries"].update(network=-1),
        lambda x: x["retries"].update(validation=11),
        lambda x: x["timeouts"].update(openrouter_seconds=0.5),
        lambda x: x["timeouts"].update(telegram_seconds=301.0),
        lambda x: x["timeouts"].update(telegram_poll_seconds=51),
        lambda x: x["timeouts"].update(integration_seconds="30"),
        lambda x: x["logging"]["file"].update(level="TRACE"),
        lambda x: x.update(data_directory="../secret"),
        lambda x: x.update(data_directory="bad\0path"),
        lambda x: x.update(data_directory=123),
        lambda x: x["logging"].update(directory=123),
        lambda x: x["telegram"].update(user_id=0),
        lambda x: x["targets"].update(todoist_project=""),
    ]
    for mutate in mutations:
        candidate = copy.deepcopy(base); mutate(candidate)
        with pytest.raises(ValidationError): Settings.model_validate(candidate)
    with pytest.raises(ValueError, match=r"config.yaml.*imap.port") as error:
        bad=copy.deepcopy(base); bad["imap"]["port"]=0; _validated_file(Path("config.yaml"), Settings, bad)
    assert "secret" not in str(error.value)


def test_versioned_state_models_and_schema_quarantine(tmp_path):
    assert ImapCheckpoint(uidvalidity=1, uid=2).schema_version == 1
    assert TelegramOffset(offset=2).schema_version == 1
    assert TelegramDialogState().proposal_id is None
    with pytest.raises(ValidationError): TelegramDialogState(proposal_id="p")
    with pytest.raises(ValidationError): TelegramDialogState(version=1)
    with JsonStore(tmp_path) as store:
        store.save("mail-bad", {"schema_version": 3, "id": "secret-content", "imap": {}, "steps": {}})
        with pytest.raises(CorruptState, match=r"mail-bad.invalid.*id") as error:
            store.load_model("mail-bad", MailState)
        assert "secret-content" not in str(error.value) and (tmp_path / "mail-bad.invalid").exists()
        assert store.load_model("missing", TelegramOffset, TelegramOffset()).offset == 0


def test_openrouter_corrupt_responses_are_named_and_sanitized():
    assert _path(ValueError()) == "<json>"
    cases = [
        ({"choices": []}, "id"),
        ({"id": "x", "choices": []}, "choices"),
        ({"id": "x", "choices": [{"message": {"content": "[1]"}}]}, "content"),
        ({"id": "x", "choices": [{"message": {"content": "private-not-json"}}]}, "<json>"),
    ]
    for data, path in cases:
        transport=httpx.MockTransport(lambda request, data=data: httpx.Response(200,json=data,request=request))
        client=OpenRouterClient("top-secret",1,0,10,transport)
        with pytest.raises(ValueError, match="OpenRouter") as error: client.complete("m",{},"s",{})
        assert "top-secret" not in str(error.value)
        client.close()


def test_telegram_response_models_and_write_validation():
    assert _validation_path(ValueError()) == "<json>"
    real_update={"ok":True,"result":[{"update_id":7,"irrelevant_update_field":"ignored",
        "message":{"message_id":11,"from":{"id":1,"is_bot":False,"first_name":"Ada","language_code":"de"},
                   "chat":{"id":-2,"type":"private","first_name":"Ada"},"date":1_789_000_000,
                   "text":"Antwort","entities":[{"type":"bold","offset":0,"length":1}]}}],
        "response_metadata":"ignored"}
    parsed=TelegramUpdatesResponse.model_validate(real_update)
    assert parsed.result[0].message.sender.id == 1
    assert parsed.model_dump(by_alias=True) == {"ok":True,"result":[{"update_id":7,"message":{
        "message_id":11,"from":{"id":1},"chat":{"id":-2},"text":"Antwort"},"callback_query":None}]}
    assert TelegramWriteResponse.model_validate({"ok":True,"result":{"message_id":12,"date":1_789_000_001,
        "chat":{"id":-2,"type":"private"},"text":"Gesendet"},"extra":"ignored"}).result.message_id == 12
    assert TelegramWriteResponse.model_validate({"ok":True,"result":True,"description":"answered"}).result is True
    with pytest.raises(ValidationError): TelegramUpdatesResponse.model_validate({"ok":False,"result":[]})
    with pytest.raises(ValidationError): TelegramWriteResponse.model_validate({"ok":False,"result":True})
    with pytest.raises(ValidationError): TelegramUpdatesResponse.model_validate({"ok":True,"result":[{"update_id":1,"message":{"message_id":1,"from":{"id":"1"},"chat":{"id":2},"text":"x"}}]})
    for operation in ("send", "answer"):
        client=TelegramClient("top-secret",1,httpx.MockTransport(lambda request: httpx.Response(200,json={"ok":True},request=request)))
        with pytest.raises(ValueError, match="Telegram") as error:
            client.send(1,"x") if operation == "send" else client.answer_callback("c","x")
        assert "top-secret" not in str(error.value)
        client.close()


def test_integration_response_boundaries_and_required_ids():
    with pytest.raises(ValueError, match="id"): _with_external_result(proposal(status="writing"), {})
    cases = [
        ("todoist", "GET", {}),
        ("todoist", "POST", {"description":"no id"}),
        ("google_calendar", "GET", {"wrong": []}),
        ("google_calendar", "POST", {"htmlLink":"https://private.invalid"}),
    ]
    for service, method, data in cases:
        def handler(request, data=data): return httpx.Response(200,json=data,request=request)
        writer=HttpWriter(service,"top-secret","target",transport=httpx.MockTransport(handler),
                          calendar_timezone="UTC" if service == "google_calendar" else None)
        with pytest.raises(ValueError) as error:
            if method == "GET": writer.reconcile("key")
            elif service == "todoist": writer.create(proposal(status="confirmed"),"key")
            else:
                from datetime import datetime, timedelta, timezone
                now=datetime.now(timezone.utc)
                writer.create(proposal(kind="event",start=now,end=now+timedelta(hours=1),status="confirmed"),"key")
        assert service.split("_")[0].lower() in str(error.value).lower() and "top-secret" not in str(error.value)
        writer.close()


def test_event_boundary_rejects_incomplete_contradictory_and_naive_values():
    aware=datetime(2026,5,10,10,tzinfo=timezone(timedelta(hours=2)))
    # An explicitly incomplete proposal may retain a missing endpoint for a
    # visible clarification, but it cannot contain an unsafe or mixed value.
    assert proposal(kind="event",open_questions=["Wann endet es?"],start=aware).end is None
    invalid = [
        {"kind":"event","start":aware},
        {"kind":"event","start":aware.replace(tzinfo=None),"end":aware.replace(tzinfo=None)+timedelta(hours=1)},
        {"kind":"event","start":date(2026,5,10),"end":date(2026,5,11)},
        {"kind":"event","all_day":True,"start":aware,"end":aware+timedelta(days=1)},
        {"kind":"event","all_day":True,"start":date(2026,5,10),"end":date(2026,5,10)},
        {"kind":"event","all_day":True,"start":date(2026,5,11),"end":date(2026,5,10)},
    ]
    for values in invalid:
        with pytest.raises(ValidationError): proposal(**values)
    complete=proposal(kind="event",all_day=True,start=date(2026,5,10),end=date(2026,5,11))
    assert type(complete.start) is date and type(complete.end) is date


def test_calendar_writer_requires_valid_configured_iana_timezone():
    with pytest.raises(ValueError,match="konfigurierte IANA"):
        HttpWriter("google_calendar","x","primary")
    with pytest.raises(ValueError,match="Unbekannte IANA"):
        HttpWriter("google_calendar","x","primary",calendar_timezone="Moon/Base")
