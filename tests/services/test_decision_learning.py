from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from mailhelp.config import RetentionSettings
from mailhelp.models import MailState, RelevanceDialogStatus, TelegramDialogState
from mailhelp.review.learning_log import DecisionLearningLog, learning_path, prune
from mailhelp.runtime.retention import RetentionService
from mailhelp.storage import JsonStore
from tests.fakes.log_fakes import RecordingLogger as Logger
from tests.fakes.shared_telegram_dialog import (
    RelevanceHandler,
    callback,
    controller,
    message,
    proposal,
    relevance_state,
)

MAIL = "a" * 24
NOW = datetime(2026, 11, 2, 12, tzinfo=UTC)


def records(store):
    path = learning_path(store.directory)
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def mail_state(*proposals, **changes):
    return MailState.model_validate({
        "id": MAIL, "config_fingerprint": "f" * 64,
        "imap": {"account_id": "0" * 24, "folder": "INBOX", "uidvalidity": 1, "uid": 1},
        "mail": {"text": "Bitte bis Freitag erledigen."}, "display_headers": {"sender": "A <a@x.test>", "subject": "Frist"},
        "relevance": {"decision": "relevant", "reason": "Frist", "topic_ids": []},
        "llm_call_ids": ["call-1"], "proposals": [item.model_dump(mode="json") for item in proposals], **changes})


def learning(store, period="unlimited", **options):
    return DecisionLearningLog(store, period, Logger(), clock=lambda: NOW, **options)


def test_telegram_clarification_answers_and_decision_are_recorded_with_context(tmp_path):
    with JsonStore(tmp_path) as store:
        initial = proposal(open_questions=["Wann?", "Wo?"])
        store.save(f"mail-{MAIL}", mail_state(initial).model_dump(mode="json"))
        dialog, transport, _ = controller(store)
        dialog.learning = learning(store)
        dialog.send_proposal(initial)
        # The rejected confirm of an unclear proposal is no decision and leaves no record.
        transport.updates = [callback(1, f"proposal:{MAIL}:p1:1:confirm"), callback(2, f"proposal:{MAIL}:p1:1:edit"),
                             message(3, "Morgen")]
        dialog.poll_once()
        transport.updates = [callback(4, f"proposal:{MAIL}:p1:2:edit"), message(5, "Berlin")]
        dialog.poll_once()
        transport.updates = [callback(6, f"proposal:{MAIL}:p1:3:reject")]
        dialog.poll_once()
        saved = records(store)
        assert [(item["kind"], item["version"], item["answer"]) for item in saved] == [
            ("clarify", 1, None), ("answer", 1, "Morgen"), ("clarify", 2, None), ("answer", 2, "Berlin"),
            ("reject", 3, None)]
        assert {item["source"] for item in saved} == {"telegram"}
        rejected = saved[-1]
        assert rejected["mail"] == {"headers": {"sender": "A <a@x.test>", "subject": "Frist"},
                                    "content": {"text": "Bitte bis Freitag erledigen."}}
        assert rejected["analysis"]["relevance"]["reason"] == "Frist"
        assert rejected["analysis"]["llm_call_ids"] == ["call-1"] and rejected["llm_content"] is None
        assert rejected["proposal"]["original"]["version"] == 1
        assert rejected["proposal"]["decided"]["version"] == 3
        assert rejected["proposal"]["result"]["status"] == "rejected"
        assert rejected["proposal"]["changes"]["open_questions"] == [["Wann?", "Wo?"], []]
        assert "status" not in rejected["proposal"]["changes"]
        # A repeated or reconciled decision is recorded once.
        dialog.learning.proposal_decision(MAIL, "p1", 3, "reject", "web", "other-key")
        restarted = learning(store)
        restarted.proposal_decision(MAIL, "p1", 3, "reject", "web", "other-key")
        assert len(records(store)) == 5


def test_relevance_decisions_by_button_and_free_text_are_recorded(tmp_path):
    other = "b" * 24
    with JsonStore(tmp_path) as store:
        store.save(f"mail-{MAIL}", relevance_state(MAIL).model_dump(mode="json"))
        dialog, transport, _ = controller(store, [callback(1, f"relevance:{MAIL}:1:relevant")])
        dialog.learning = learning(store)
        dialog.relevance_handler = RelevanceHandler(store)
        dialog.poll_once()
        store.save(f"mail-{other}", relevance_state(other).model_dump(mode="json"))
        transport.updates = [message(2, "irrelevant")]
        dialog.poll_once()
        assert [(item["mail_id"], item["kind"], item["decision"], item["proposal"]) for item in records(store)] == [
            (MAIL, "relevance", "relevant", None), (other, "relevance", "irrelevant", None)]


def test_free_text_without_learning_or_accepted_answer_records_nothing(tmp_path):
    with JsonStore(tmp_path) as store:
        initial = proposal(open_questions=["Wann?"])
        store.save(f"mail-{MAIL}", mail_state(initial).model_dump(mode="json"))
        dialog, transport, _ = controller(store)
        dialog.send_proposal(initial)
        transport.updates = [message(1, "Ohne offene Rückfrage")]
        dialog.poll_once()
        transport.updates = [callback(2, f"proposal:{MAIL}:p1:1:edit"), message(3, "Morgen")]
        dialog.poll_once()
        assert not learning_path(store.directory).exists()
        dialog.learning = learning(store)
        transport.updates = [message(4, "Ohne offene Rückfrage")]
        dialog.poll_once()
        # An answer the clarification did not accept (here: a different text) is not recorded.
        pointer = TelegramDialogState(mail_id=MAIL, proposal_id="p1", version=1)
        dialog.updates._record_answer(pointer, "Nicht diese Antwort", 5)
        dialog.updates._record_answer(pointer.model_copy(update={"version": 9}), "Morgen", 6)
        assert records(store) == []


def test_missing_state_proposal_and_snapshots(tmp_path):
    with JsonStore(tmp_path) as store:
        log = learning(store)
        log.proposal_decision(MAIL, "p1", 1, "confirm", "web", "key-1")
        log.relevance_decision(MAIL, "web", "key-1")
        store.save(f"mail-{MAIL}", mail_state().model_dump(mode="json"))
        log.proposal_decision(MAIL, "p1", 1, "confirm", "web", "key-1")
        log.relevance_decision(MAIL, "web", "key-1")
        assert records(store) == []
        # Without snapshots the normalized proposal is the original; the decided version is the current one.
        normalized = proposal(source_mail_id=MAIL, title="Erster Vorschlag")
        current = proposal(source_mail_id=MAIL, version=2, title="Geändert")
        store.save(f"mail-{MAIL}", mail_state(current, normalized_proposals=[
            normalized.model_dump(mode="json")]).model_dump(mode="json"))
        store.save(f"proposal-{MAIL}-p1", current.model_dump(mode="json"))
        log.proposal_decision(MAIL, "p1", 2, "confirm", "web", "key-2")
        # An unknown version has no decided proposal and therefore no changes.
        store.save(f"mail-{MAIL}", mail_state(current).model_dump(mode="json"))
        log.proposal_decision(MAIL, "p1", 7, "confirm", "web", "key-3")
        first, unknown = records(store)
        assert first["proposal"]["original"]["title"] == "Erster Vorschlag"
        assert first["proposal"]["decided"]["title"] == "Geändert"
        assert first["proposal"]["changes"] == {"title": ["Erster Vorschlag", "Geändert"]}
        assert unknown["proposal"]["original"] is None and unknown["proposal"]["decided"] is None
        assert unknown["proposal"]["changes"] == {}


def test_full_llm_content_is_copied_only_when_enabled(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    lines = [{"call_id": "call-1", "event": "request_started", "stage": "relevance", "model": "m",
              "request": {"messages": ["Prompt"]}},
             {"call_id": "call-1", "event": "token_usage_recorded"},
             {"call_id": "other", "event": "response_received", "response": "fremd"}]
    (logs / "requests.jsonl").write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")
    (logs / "requests.jsonl.1").write_text(json.dumps(
        {"call_id": "call-1", "event": "response_received", "response": "Antwort"}) + "\n", encoding="utf-8")
    with JsonStore(tmp_path / "data") as store:
        store.save(f"mail-{MAIL}", relevance_state(MAIL).model_copy(update={
            "llm_call_ids": ["call-1"], "awaiting_relevance": False, "relevance_dialog": relevance_state(MAIL).relevance_dialog.model_copy(
                update={"decision": "relevant", "status": RelevanceDialogStatus.DECIDED, "telegram_offset": 2})}).model_dump(mode="json"))
        learning(store, llm_logs=[logs / "requests.jsonl", logs / "requests.jsonl.1",
                                  logs / "requests.jsonl.2"]).relevance_decision(MAIL, "web", "key-1")
        (saved,) = records(store)
    assert saved["llm_content"] == [
        {"call_id": "call-1", "stage": "relevance", "model": "m", "event": "request_started",
         "request": {"messages": ["Prompt"]}, "response": None},
        {"call_id": "call-1", "stage": None, "model": None, "event": "response_received", "request": None,
         "response": "Antwort"}]


def test_disabled_recording_and_failures_never_stop_the_decision(tmp_path):
    with JsonStore(tmp_path) as store:
        store.save(f"mail-{MAIL}", relevance_state(MAIL).model_copy(update={
            "awaiting_relevance": False, "relevance_dialog": relevance_state(MAIL).relevance_dialog.model_copy(
                update={"decision": "relevant", "status": RelevanceDialogStatus.DECIDED, "telegram_offset": 2})}).model_dump(mode="json"))
        learning(store, "disabled").relevance_decision(MAIL, "web", "key-1")
        assert records(store) == []
        store.save(f"proposal-{MAIL}-p1", {"kaputt": True})
        store.save(f"mail-{MAIL}", mail_state().model_dump(mode="json"))
        failing = learning(store)
        failing.proposal_decision(MAIL, "p1", 1, "confirm", "web", "key-1")
        assert failing.logger.events == [(("WARNING", "learning", "decision_record_failed"),
                                          {"error_class": "ValidationError"})]
        assert records(store) == []


def test_retention_prunes_records_by_the_configured_period(tmp_path):
    path = learning_path(tmp_path)
    assert prune(tmp_path, 30, NOW) == 0
    path.parent.mkdir()
    entries = [{"id": "old", "recorded_at": (NOW - timedelta(days=40)).isoformat()},
               {"id": "new", "recorded_at": (NOW - timedelta(days=2)).isoformat()},
               {"id": "naive", "recorded_at": "2026-11-01T10:00:00"},
               {"id": "invalid", "recorded_at": "gestern"}]
    path.write_text("\n".join(json.dumps(item) for item in entries) + "\nkaputt\n[1]\n", encoding="utf-8")
    assert prune(tmp_path, "unlimited", NOW) == 0
    assert prune(tmp_path, 30, NOW) == 3
    assert [json.loads(line)["id"] for line in path.read_text(encoding="utf-8").splitlines()] == ["new"]
    before = path.stat().st_mtime_ns
    assert prune(tmp_path, 30, NOW) == 0 and path.stat().st_mtime_ns == before
    with JsonStore(tmp_path) as store:
        result = RetentionService(store, RetentionSettings(decision_learning_days="disabled"), Logger(),
                                  lambda: NOW).run()
        assert result.scanned == 0 and path.read_text(encoding="utf-8") == ""
    assert RetentionSettings().decision_learning_days == "unlimited"


def test_live_retention_change_reaches_the_recorder(tmp_path):
    from types import SimpleNamespace

    from mailhelp.runtime.application import Application
    from mailhelp.runtime.metrics import MetricsRecorder
    from tests.fakes.shared_application import settings as app_settings

    configured = app_settings(tmp_path)
    with JsonStore(tmp_path / "data") as store:
        recorder = learning(store)
        app = SimpleNamespace(logger=SimpleNamespace(metrics=MetricsRecorder(tmp_path / "m.jsonl", configured.metrics)),
                              settings=configured, mailbox=SimpleNamespace(settings=configured),
                              dialog=SimpleNamespace(learning=recorder), store=store,
                              orchestrator=SimpleNamespace(reconciliation=SimpleNamespace(max_candidates=8)))
        changed = configured.model_copy(update={"retention": configured.retention.model_copy(
            update={"decision_learning_days": "disabled"})})
        Application.apply_settings(app, changed)
        assert recorder.period == "disabled"
