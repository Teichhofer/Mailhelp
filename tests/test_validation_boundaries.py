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
from mailhelp.models import (DuplicateDecision, DuplicateIndex, DuplicateIndexEntry, ExtractionCountConflict, ImapCheckpoint, MailState, Proposal, ProposalNotification, TelegramDialogState,
                             TelegramOffset, ValidationIssue, WriteAttemptReference)
from mailhelp.openrouter import InvalidJson, OpenRouterClient, ProviderResponseInvalid, _path
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
        "retries": {"provider_retry": 0, "json_repair": 0, "schema_repair": 0},
        "timeouts": {**{name: {"timeout_seconds": 1.0, "retries": 0, "initial_backoff_seconds": 0.0, "max_backoff_seconds": 1.0} for name in ("imap", "telegram", "openrouter", "todoist", "google_calendar")}, "telegram_poll_seconds": 1},
        "logging": {"directory": str(tmp_path / "logs"), "console": {"enabled": False}, "file": {"filename": "application.jsonl", "max_bytes": 10000, "backup_count": 1, "retention_days": 30}, "llm": {"filename": "llm/requests.jsonl", "max_bytes": 10000, "backup_count": 1, "retention_days": 30}},
    }


def test_mail_state_v9_metadata_is_closed_and_round_trips(tmp_path):
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
    assert loaded == state and loaded.schema_version == 9


def test_extraction_count_conflicts_are_strict_and_unique():
    values = dict(category="task", expected_count=2, actual_count=1,
                  router_call_id="router", extractor_call_id="extractor")
    conflict = ExtractionCountConflict(**values)
    with pytest.raises(ValidationError, match="unterschiedliche"):
        ExtractionCountConflict(**{**values, "actual_count": 2})
    with pytest.raises(ValidationError, match="UTC-Offset"):
        ExtractionCountConflict(**values, notification_marked_at=datetime.now())
    state_values = dict(id="a" * 24, config_fingerprint="f" * 64,
                        imap={"account_id": "0" * 24, "folder": "INBOX",
                              "uidvalidity": 1, "uid": 2})
    with pytest.raises(ValidationError, match="nicht doppelt"):
        MailState(**state_values, extraction_count_conflicts=[conflict, conflict])


def test_mail_state_v6_is_explicitly_migrated(tmp_path):
    now = datetime.now(timezone.utc)
    state = MailState(
        id="a" * 24, config_fingerprint="f" * 64,
        imap={"account_id": "0" * 24, "folder": "INBOX", "uidvalidity": 1, "uid": 2},
        write_attempts=[WriteAttemptReference(
            mail_id="a" * 24, proposal_id="p1", proposal_version=2, service="todoist",
            idempotency_key="mailhelp:aaaaaaaaaaaaaaaaaaaaaaaa:p1:v2",
        )],
    )
    old = state.model_dump(mode="json")
    old["schema_version"] = 6
    old["steps"]["notification"] = "completed"
    del old["steps"]["summary_notification"]
    del old["steps"]["proposal_notification"]
    with JsonStore(tmp_path / "states") as store:
        store.save("mail-a", old)
        migrated = store.load_model("mail-a", MailState)
        persisted = store.load("mail-a")
    assert migrated.steps.summary_notification == "completed"
    assert migrated.steps.proposal_notification == "completed"
    assert persisted["schema_version"] == 9 and "notification" not in persisted["steps"]
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


def test_mail_state_v8_migrates_pipeline_and_validates_notification_keys(tmp_path):
    item = proposal(source_mail_id="a" * 24)
    state = MailState(
        id="a" * 24, config_fingerprint="f" * 64,
        imap={"account_id": "0" * 24, "folder": "INBOX", "uidvalidity": 1, "uid": 2},
        proposals=[item],
    )
    old = state.model_dump(mode="json")
    old["schema_version"] = 8
    old["steps"].pop("normalization")
    old["steps"].pop("proposal_building")
    old.pop("normalized_proposals")
    old.pop("proposal_notifications")
    old["steps"]["action_detection"] = "completed"
    old["steps"]["proposal_notification"] = "sending"
    with JsonStore(tmp_path / "v8") as store:
        store.save("mail-a", old)
        migrated = store.load_model("mail-a", MailState)
    assert migrated.steps.normalization == migrated.steps.proposal_building == "completed"
    assert migrated.normalized_proposals == [item]
    assert migrated.proposal_notifications == [ProposalNotification(
        proposal_id=item.id, proposal_version=item.version, status="sending")]

    value = state.model_dump(mode="json")
    duplicate = ProposalNotification(proposal_id=item.id, proposal_version=item.version)
    with pytest.raises(ValidationError, match="doppelt"):
        MailState.model_validate({**value, "proposal_notifications": [duplicate, duplicate]})
    with pytest.raises(ValidationError, match="Vorschlagsversion"):
        MailState.model_validate({**value, "proposal_notifications": [
            ProposalNotification(proposal_id="missing", proposal_version=1)]})


def test_settings_reject_missing_extra_types_ranges_and_semantics(tmp_path):
    base = valid_settings(tmp_path)
    assert Settings.model_validate(base).timezone == "UTC"
    for mode in ("ssl", "starttls", "plain"):
        configured=copy.deepcopy(base); configured["imap"].update(connection_mode=mode, historical_start="2025-01-02T03:04:05+01:00", global_newest_first=True)
        parsed = Settings.model_validate(configured).imap
        assert parsed.connection_mode == mode and parsed.global_newest_first
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
        lambda x: x["imap"].update(batch_size=0),
        lambda x: x["imap"].update(batch_size=1001),
        lambda x: x["imap"].update(global_newest_first="true"),
        lambda x: x.update(timezone="Moon/Base"),
        lambda x: x.update(poll_interval_seconds=4),
        lambda x: x.update(poll_interval_seconds=86401),
        lambda x: x["limits"].update(max_mail_bytes=100_000_001),
        lambda x: x["limits"].update(llm_calls_per_minute=0),
        lambda x: x["limits"].update(llm_calls_per_minute=601),
        lambda x: x["retries"].update(network=-1),
        lambda x: x["retries"].update(provider_retry=11),
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
    with pytest.raises(ValidationError, match="UID-Bereiche"):
        ImapCheckpoint(start_uid=2, completed_uid_ranges=[(2,3)])
    with pytest.raises(ValidationError, match="UID-Bereiche"):
        ImapCheckpoint(completed_uid_ranges=[(4,3)])
    assert TelegramOffset(offset=2).schema_version == 1
    identity = {"account_id": "0" * 24, "folder": "INBOX", "uidvalidity": 1, "uid": 2}
    entry = DuplicateIndexEntry(mail_id="a" * 24, imap=identity,
                                message_ids=["<one@example.test>"], content_fingerprint="f" * 64)
    assert DuplicateIndex(entries=[entry]).schema_version == 1
    with pytest.raises(ValidationError, match="doppelt"):
        DuplicateIndex(entries=[entry, entry.model_copy(update={"mail_id": "b" * 24})])
    with pytest.raises(ValidationError, match="doppelt"):
        DuplicateIndexEntry(mail_id="a" * 24, imap=identity,
                            message_ids=["<one@example.test>", "<one@example.test>"], content_fingerprint="f" * 64)
    with pytest.raises(ValidationError):
        DuplicateIndexEntry(mail_id="a" * 24, imap=identity,
                            message_ids=["not-normalized"], content_fingerprint="f" * 64)
    assert DuplicateDecision(outcome="new", reason="no_match").previous_mail_id is None
    with pytest.raises(ValidationError, match="Mailbezug"):
        DuplicateDecision(outcome="duplicate", reason="same_message")
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
    with pytest.raises(ValidationError) as validation_error:
        TelegramOffset.model_validate({"offset": "bad"})
    assert _path(validation_error.value) == "offset"
    cases = [
        ([], "invalid_provider_envelope"),
        ({"id":"x"}, "choices_missing"),
        ({"id": "x", "choices": []}, "choice_missing"),
        ({"id":"x", "choices":[{}]}, "message_missing"),
        ({"id":"x", "choices":[{"message":{"content":None}}]}, "message_content_null"),
        ({"id":"x", "choices":[{"finish_reason":"length", "message":{"content":None}}]}, "output_token_limit"),
        ({"id":"x", "choices":[{"finish_reason":"length", "message":{"content":"{\"partial\":"}}]}, "output_token_limit"),
        ({"id":"x", "choices":[{"message":{"content":"  "}}]}, "message_content_empty"),
        ({"id":"x", "choices":"bad"}, "invalid_provider_envelope"),
        ({"id":"x", "choices":[{"message":{"content":3}}]}, "invalid_provider_envelope"),
        ({"id":"x", "choices":[{"message":{}}]}, "invalid_provider_envelope"),
        ({"id":"x", "choices":[3]}, "invalid_provider_envelope"),
        ({"choices":[{"message":{"content":"{}"}}]}, "invalid_provider_envelope"),
    ]
    for data, reason in cases:
        transport=httpx.MockTransport(lambda request, data=data: httpx.Response(200,json=data,request=request))
        client=OpenRouterClient("top-secret",1,0,10,transport)
        with pytest.raises(ProviderResponseInvalid) as error: client.complete("m",{},"s",{})
        assert error.value.reason == reason
        assert "top-secret" not in str(error.value)
        client.close()

    transport=httpx.MockTransport(lambda request: httpx.Response(200,text="not-provider-json",request=request))
    with pytest.raises(ProviderResponseInvalid) as error:
        OpenRouterClient("secret",1,0,10,transport).complete("m",{},"s",{})
    assert error.value.reason == "invalid_provider_envelope"
    data={"id":"x","choices":[{"message":{"content":"private-not-json"}}]}
    transport=httpx.MockTransport(lambda request: httpx.Response(200,json=data,request=request))
    with pytest.raises(InvalidJson) as error:
        OpenRouterClient("secret",1,0,10,transport).complete("m",{},"s",{})
    assert "private-not-json" not in str(error.value)

    # JSON syntax is the client's boundary; shape belongs to the Analyzer schema.
    data={"id":"x","choices":[{"message":{"content":"[1]"}}]}
    transport=httpx.MockTransport(lambda request: httpx.Response(200,json=data,request=request))
    assert OpenRouterClient("secret",1,0,10,transport).complete("m",{},"s",{})[1] == [1]


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
        ("todoist", "GET", {"results": []}),
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
    writer=HttpWriter("todoist","top-secret","target",transport=httpx.MockTransport(
        lambda request: httpx.Response(200,content=b"not-json",request=request)))
    with pytest.raises(ValueError, match="Todoist tasks.*<json>") as error:
        writer.reconcile("key")
    assert "top-secret" not in str(error.value)
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


def test_task_deadline_boundary_preserves_dates_and_rejects_unsafe_combinations():
    date_only = proposal(due="2026-10-01")
    instant = proposal(due="2026-10-01T17:00:00+02:00")
    assert type(date_only.due) is date
    assert isinstance(instant.due, datetime) and instant.due.utcoffset() == timedelta(hours=2)
    for values in (
        {"due":"2026-10-01T17:00:00"},
        {"start":"2026-10-01T17:00:00+02:00"},
        {"kind":"event", "due":"2026-10-01", "start":"2026-10-01T17:00:00+02:00",
         "end":"2026-10-01T18:00:00+02:00"},
    ):
        with pytest.raises(ValidationError):
            proposal(**values)


def test_proposal_video_link_accepts_only_bounded_http_urls():
    assert str(proposal(video_link="https://video.example.test/room").video_link) == "https://video.example.test/room"
    assert proposal(video_link=None).video_link is None
    for invalid in ("ftp://video.example.test/room", "not-a-url", "https://example.test/" + "x" * 2000):
        with pytest.raises(ValidationError):
            proposal(video_link=invalid)


def test_calendar_writer_requires_valid_configured_iana_timezone():
    with pytest.raises(ValueError,match="konfigurierte IANA"):
        HttpWriter("google_calendar","x","primary")
    with pytest.raises(ValueError,match="Unbekannte IANA"):
        HttpWriter("google_calendar","x","primary",calendar_timezone="Moon/Base")
