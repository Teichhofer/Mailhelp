"""Regression coverage for approved targets, preflight recovery and reminders."""
from datetime import datetime, timezone
import json

import httpx
import pytest

from mailhelp.action_normalization import MailDateContext
from mailhelp.adapter import RetryableError
from mailhelp.config import TargetSettings
from mailhelp.integrations import HttpWriter, execute_confirmed
from mailhelp.models import ActionLedger, ExtractedTask, Proposal, ProposalStatus
from mailhelp.openrouter import RateLimitExceeded
from mailhelp.proposal_builder import ProposalBuilder
from mailhelp.storage import JsonStore
from mailhelp.telegram.ledger import ActionLedgerService
from test_core import proposal
from test_telegram_dialog import callback, controller
from test_write_improvements import event


@pytest.mark.parametrize("kind", ["task", "event"])
@pytest.mark.parametrize("status", ["confirmed", "writing", "uncertain"])
@pytest.mark.parametrize("test_mode", [False, True])
def test_changed_target_never_reconciles_or_writes(kind, status, test_mode):
    requests, saved = [], []
    writer = HttpWriter("todoist" if kind == "task" else "google_calendar",
        "synthetic", "new-target", calendar_timezone="UTC",
        transport=httpx.MockTransport(lambda request: requests.append(request)))
    item = (proposal if kind == "task" else event)(target="approved-target", status=status)
    try:
        changed, result = execute_confirmed(item, writer, saved.append, test_mode)
        assert changed == item and result == {"target_mismatch": True}
        with pytest.raises(ValueError, match="Vorschlagsziel"):
            writer.create(item, "key")
        assert requests == [] and saved == []
    finally:
        writer.close()


def test_target_change_survives_restart_and_new_target_needs_new_confirmation(tmp_path):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"results": [], "next_cursor": None}
            if request.method == "GET" else {"id": "created"})
    writer = HttpWriter("todoist", "synthetic", "new-target", transport=httpx.MockTransport(handler))
    item = proposal(target="approved-target", status="confirmed")
    name = f"proposal-{item.source_mail_id}-{item.id}"
    try:
        for _ in range(2):
            with JsonStore(tmp_path) as store:
                dialog, telegram, _ = controller(store, writers={"todoist": writer})
                dialog.persist(item)
                dialog.poll_once()
                dialog.poll_once()
                assert len(telegram.polls) == 2  # mismatch cannot starve Telegram
                assert len(telegram.sent) == 1 and "Ziel geändert" in telegram.sent[0][1]
                assert store.load(name)["status"] == "confirmed"
                assert requests == []
        with JsonStore(tmp_path) as store:
            dialog, telegram, _ = controller(store, writers={"todoist": writer})
            revised = item.model_copy(update={"version": 2, "target": "new-target",
                                               "status": ProposalStatus.PENDING_CONFIRMATION})
            dialog.send_proposal(revised)
            for update in [callback(1, f"proposal:{item.source_mail_id}:p1:1:confirm"),
                           callback(2, f"proposal:{item.source_mail_id}:p1:2:confirm", user=9)]:
                telegram.updates = [update]
                dialog.poll_once()
            assert requests == []
            telegram.updates = [callback(3, f"proposal:{item.source_mail_id}:p1:2:confirm")]
            dialog.poll_once()
            assert store.load(name)["status"] == "created"
            assert json.loads(requests[-1].content)["project_id"] == "new-target"
    finally:
        writer.close()


@pytest.mark.parametrize("failure", ["rate_limit", "invalid_llm", "read_timeout", "http_503", "invalid_page"])
@pytest.mark.parametrize("operation", ["create", "patch", "skip"])
def test_calendar_preflight_failure_retries_after_restart_without_false_uncertainty(tmp_path, failure, operation):
    from mailhelp.models import CalendarDuplicateDecision
    requests = []
    failing = True
    item = event(status="confirmed", description="Agenda")
    name = f"proposal-{item.source_mail_id}-{item.id}"
    def matcher(*_):
        assert store.load(name)["status"] == "confirmed"
        if failing:
            if failure == "rate_limit":
                raise RateLimitExceeded(2000000000)
            raise ValueError("synthetic invalid LLM response")
        return "call", CalendarDuplicateDecision(same_event=operation != "create",
            missing_fields=["description"] if operation == "patch" else [], reason="synthetic")
    def handler(request):
        requests.append(request)
        if request.method != "GET":
            assert store.load(name)["status"] == "writing"
            return httpx.Response(200, json={"id": "created"})
        if "privateExtendedProperty" in request.url.params:
            return httpx.Response(200, json={"items": []})
        if failing:
            if failure == "read_timeout":
                raise httpx.ReadTimeout("synthetic", request=request)
            if failure == "http_503":
                return httpx.Response(503)
            if failure == "invalid_page":
                return httpx.Response(200, json={"items": "invalid"})
        return httpx.Response(200, json={"items": [{"id": "old", "start": {}, "end": {}}]})
    writer = HttpWriter("google_calendar", "synthetic", "calendar", calendar_timezone="UTC",
        transport=httpx.MockTransport(handler), calendar_matcher=matcher)
    try:
        with JsonStore(tmp_path) as store:
            store.save(name, item.model_dump(mode="json"))
            with pytest.raises((RateLimitExceeded, ValueError, RetryableError)):
                execute_confirmed(item, writer, lambda p: store.save(name, p.model_dump(mode="json")))
            assert store.load(name)["status"] == "confirmed"
            assert all(r.method == "GET" for r in requests)
        failing = False
        with JsonStore(tmp_path) as store:
            saved = []
            def persist(value):
                saved.append(value.status.value)
                store.save(name, value.model_dump(mode="json"))
            current = store.load_model(name, Proposal)
            result, _ = execute_confirmed(current, writer, persist)
            assert result.status == ProposalStatus.CREATED
            assert saved == (["created"] if operation == "skip" else ["writing", "created"])
            assert [r.method for r in requests if r.method != "GET"] == (
                [] if operation == "skip" else ["PATCH" if operation == "patch" else "POST"])
    finally:
        writer.close()


@pytest.mark.parametrize("operation", ["POST", "PATCH"])
@pytest.mark.parametrize("failure", ["timeout", "invalid_response"])
def test_prepared_write_keeps_ambiguous_result_protected_across_restart(tmp_path, operation, failure):
    from mailhelp.models import CalendarDuplicateDecision
    requests = []
    found = False
    item = event(status="confirmed", description="Agenda")
    name = f"proposal-{item.source_mail_id}-{item.id}"
    def handler(request):
        requests.append(request)
        if request.method == "GET":
            if "privateExtendedProperty" in request.url.params:
                return httpx.Response(200, json={"items": [{"id": "result"}] if found else []})
            return httpx.Response(200, json={"items": [{"id": "old", "start": {}, "end": {}}]})
        assert request.method == operation and store.load(name)["status"] == "writing"
        if failure == "timeout":
            raise httpx.ReadTimeout("synthetic", request=request)
        return httpx.Response(200, json={})
    writer = HttpWriter("google_calendar", "synthetic", "calendar", calendar_timezone="UTC",
        transport=httpx.MockTransport(handler), calendar_matcher=lambda *_: (
            "call", CalendarDuplicateDecision(same_event=operation == "PATCH",
                missing_fields=["description"] if operation == "PATCH" else [], reason="same")))
    try:
        with JsonStore(tmp_path) as store:
            dialog, _, _ = controller(store, writers={"google_calendar": writer})
            dialog.persist(item)
            if failure == "invalid_response":
                with pytest.raises(ValueError):
                    dialog.poll_once()
                assert store.load(name)["status"] == "writing"
            else:
                dialog.poll_once()
                assert store.load(name)["status"] == "uncertain"
        for recovery in [False, True]:
            found = recovery
            with JsonStore(tmp_path) as store:
                dialog, _, _ = controller(store, writers={"google_calendar": writer})
                dialog.poll_once()
                assert store.load(name)["status"] == ("created" if found else "uncertain")
        assert len([r for r in requests if r.method != "GET"]) == 1
    finally:
        writer.close()


def reminder(mail_id, subject, day="2026-10-06", description="Unterlagen an Frau Muster senden"):
    context = MailDateContext("valid", f"{day}T10:00:00Z", f"{day}T10:00:00Z", "UTC")
    return ProposalBuilder(mail_id, TargetSettings(todoist_project="inbox", google_calendar="calendar"),
        context, "sender@example.test", subject).build([ExtractedTask(title="Unterlagen senden",
            description=description, evidence="Bitte senden", responsibility="user", certainty="certain",
            classification="new")], [])[0]


def test_reminder_requires_duplicate_confirmation_even_with_different_source(tmp_path):
    from test_telegram_dialog import Writer
    writer = Writer()
    first = reminder("a" * 24, "Original")
    second = reminder("b" * 24, "Erinnerung", "2026-10-07")
    with JsonStore(tmp_path) as store:
        dialog, _, _ = controller(store)
        dialog.persist(first.model_copy(update={"status": ProposalStatus.CREATED, "external_id": "old"}))
    with JsonStore(tmp_path) as store:
        dialog, telegram, _ = controller(store, writers={"todoist": writer})
        dialog.send_proposal(second)
        telegram.updates = [callback(1, telegram.sent[-1][2]["inline_keyboard"][0][0]["callback_data"])]
        dialog.poll_once()
        assert writer.created == 0
        assert "Erneut anlegen" == telegram.sent[-2][2]["inline_keyboard"][0][0]["text"]


@pytest.mark.parametrize("change", [{"title": "Andere Aufgabe"}, {"description": "Andere Sachdaten"},
    {"target": "other-project"}, {"due": datetime(2026, 10, 10, tzinfo=timezone.utc)}])
def test_task_identity_preserves_business_differences(change):
    original = reminder("a" * 24, "Original")
    changed = original.model_copy(update=change)
    assert ActionLedgerService.action_key(original) != ActionLedgerService.action_key(changed)


@pytest.mark.parametrize("source", ["snapshot", "current", "missing", "wrong_version"])
def test_legacy_ledger_keys_upgrade_only_from_matching_persisted_proposal(tmp_path, source):
    first = reminder("a" * 24, "Original")
    second = reminder("b" * 24, "Erinnerung", "2026-10-07")
    with JsonStore(tmp_path) as store:
        ledger = ActionLedgerService(store)
        ledger.book_created(first.model_copy(update={"external_id": "old"}))
        raw = store.load("action-ledger")
        raw["entries"][0].pop("action_key_version")  # old persisted schema
        raw["entries"][0]["action_key"] = "0" * 64
        store.save("action-ledger", raw)
        name = f"proposal-{first.source_mail_id}-{first.id}"
        if source != "missing":
            record = first.model_copy(update={"version": 2}) if source == "wrong_version" else first
            store.save(name + ("-v1" if source == "snapshot" else ""), record.model_dump(mode="json"))
        assert bool(ledger.prior_actions(second)) == (source in {"snapshot", "current"})
    with JsonStore(tmp_path) as store:
        ledger = ActionLedgerService(store)
        assert bool(ledger.prior_actions(second)) == (source in {"snapshot", "current"})
        saved = store.load_model("action-ledger", ActionLedger)
        assert saved.entries[0].action_key_version == (2 if source in {"snapshot", "current"} else 1)
