"""Secret-free end-to-end flow through all external trust boundaries."""
from __future__ import annotations

from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from threading import Event

from mailhelp.analysis import Analyzer, LlmSchemaValidationExceeded
from mailhelp.application import Application
from mailhelp.config import PromptConfig, PromptStep, TargetSettings, Topic
from mailhelp.imap import FetchedMail
from mailhelp.logging import NullLogger
from mailhelp.models import Proposal
from mailhelp.orchestrator import Orchestrator, ProcessingOutcome
from mailhelp.storage import JsonStore
from mailhelp.telegram import TelegramDialogController


class SimulatedOpenRouter:
    def complete(self, _model, _parameters, system, payload, **_metadata):
        if system == "relevance":
            return "r", {"decision": "relevant", "topic_ids": ["arbeit"], "reason": "Aufgabe und Termin"}
        if system == "summary":
            return "s", {"sentences": ["Eine Aufgabe ist fällig.", "Ein Termin wurde vereinbart."], "deadlines": ["30. September"]}
        if system == "action_router":
            return "ar", {"action_state": "task_and_event", "task_count": 1,
                          "event_count": 1, "reason": "Aufgabe und Termin erkannt."}
        if system == "task_extraction":
            return "t", {"schema_version": 1, "tasks": [{"title": "Unterlagen senden",
                "description": "", "evidence": "Bitte senden", "responsibility": "user",
                "certainty": "certain", "classification": "new", "due_text": "30. September"}]}
        return "e", {"schema_version": 1, "events": [{"title": "Besprechung",
            "description": None, "evidence": "8. Oktober von 09:00 bis 10:00",
            "date_text": "8. Oktober", "time_text": "09:00", "end_time_text": "10:00",
            "time_requirement": "timed", "location": None, "video_link": None, "responsibility": "user",
            "certainty": "certain", "classification": "new"}]}


class FakeImap:
    account_id = "1" * 24
    last_uidvalidity = 7

    def __init__(self, fetched):
        self.fetched = fetched
        self.calls = []

    def fetch_since(self, folder, uid, uidvalidity, max_count=None, completed_uid_ranges=()):
        self.calls.append((folder, uid, uidvalidity))
        value, self.fetched = self.fetched, []
        return value

    def fetch_uid(self, *_args):
        raise AssertionError("no restart fetch expected")


class FakeTelegram:
    def __init__(self):
        self.sent = []
        self.answers = []
        self.updates = []
        self.polls = []
        self.removed = []

    def send(self, chat_id, text, reply_markup=None):
        self.sent.append((chat_id, text, reply_markup))

    def poll(self, offset):
        self.polls.append(offset)
        return self.updates

    def answer_callback(self, callback_id, text):
        self.answers.append((callback_id, text))

    def remove_inline_keyboard(self, chat_id, message_id):
        self.removed.append((chat_id, message_id))


class FakeWriter:
    def __init__(self, prefix):
        self.prefix = prefix
        self.created = []

    def reconcile(self, key):
        assert key not in {item[1] for item in self.created}
        return None

    def create(self, proposal, key):
        self.created.append((proposal, key))
        return {"id": f"{self.prefix}-1", "url": f"https://example.test/{self.prefix}/1"}


class SettingsStub:
    class Imap:
        folders = ["INBOX"]
        historical_start = None
    imap = Imap()


def raw_mail():
    message = EmailMessage()
    message["From"] = "Synthetischer Absender <absender@example.test>"
    message["To"] = "Testkonto <testkonto@example.test>"
    message["Date"] = "Thu, 17 Sep 2026 10:00:00 +0200"
    message["Message-ID"] = "<e2e@example.test>"
    message["Subject"] = "Aufgabe und Termin"
    message.set_content("Bitte senden Sie Unterlagen. Besprechung am 8. Oktober von 09:00 bis 10:00 Uhr.")
    return message.as_bytes()


def callback_update(update_id, callback_data):
    return {"update_id": update_id, "callback_query": {"id": f"cb-{update_id}", "from": {"id": 42},
            "message": {"message_id": update_id, "from": {"id": 42}, "chat": {"id": 99}, "text": "Vorschlag"},
            "data": callback_data}}


def test_imap_llm_persists_separate_raw_extractions(tmp_path):
    prompts = PromptConfig(defaults={"model": "fake", "parameters": {}}, prompts={
        step: PromptStep(system_prompt=step) for step in ("relevance", "summary", "action_router", "task_extraction", "event_extraction", "telegram_answer_interpretation", "telegram_answer_clarification", "proposal_revision", "learning_classification", "learning_abstraction")})
    analyzer = Analyzer(SimulatedOpenRouter(), prompts)
    telegram = FakeTelegram()
    todoist, calendar = FakeWriter("todoist"), FakeWriter("calendar")
    fetched = FetchedMail("INBOX", 7, 1, raw_mail(), "1" * 24, datetime(2026, 9, 17, 8, 0, tzinfo=timezone.utc))
    imap = FakeImap([fetched])
    with JsonStore(tmp_path / "state") as store:
        dialog = TelegramDialogController(store, telegram, 42, 99, NullLogger(),
                                          {"todoist": todoist, "google_calendar": calendar}, False, "Europe/Berlin")
        orchestrator = Orchestrator(analyzer, store, dialog, 99,
            [Topic(id="arbeit", name="Arbeit", enabled=True, description="Beruf")], 100_000,
            targets=TargetSettings(todoist_project="project", google_calendar="calendar"),
            user_timezone="Europe/Berlin")
        dialog.relevance_handler = orchestrator
        app = Application(SettingsStub(), store, NullLogger(), imap, analyzer.client, analyzer,
                          telegram, todoist, calendar, orchestrator, Event(), dialog)

        results = app._poll_imap()
        assert [result.outcome for result in results] == [ProcessingOutcome.COMPLETED]
        state = results[0].state
        assert state["task_extraction"]["tasks"][0]["due_text"] == "30. September"
        assert state["event_extraction"]["events"][0]["time_text"] == "09:00"
        assert len(state["proposals"]) == 2
        assert all(item["status"] == "pending_confirmation" for item in state["proposals"])
        assert state["proposals"][1]["temporal_fact"]["normalized_date"] == "2026-10-08"
        assert todoist.created == calendar.created == []


def test_synthetic_council_mail_keeps_summary_when_action_detection_fails(tmp_path):
    class CouncilRouter(SimulatedOpenRouter):
        def complete(self, model, parameters, system, payload, **metadata):
            if system == "action_router":
                raise LlmSchemaValidationExceeded("action_router")
            return super().complete(model, parameters, system, payload, **metadata)

    prompts = PromptConfig(defaults={"model": "fake", "parameters": {}}, prompts={
        step: PromptStep(system_prompt=step)
        for step in ("relevance", "summary", "action_router", "task_extraction", "event_extraction", "telegram_answer_interpretation", "telegram_answer_clarification", "proposal_revision", "learning_classification", "learning_abstraction")
    })
    telegram = FakeTelegram()
    message = EmailMessage()
    message["From"] = "Gemeinderat <rat@example.test>"
    message["Subject"] = "Synthetische Gemeinderatssitzung"
    message.set_content("Die Sitzung findet statt; die Aktionsanalyse ist absichtlich defekt.")
    fetched = FetchedMail("INBOX", 7, 2, message.as_bytes(), "1" * 24)
    with JsonStore(tmp_path / "council") as store:
        result = Orchestrator(
            Analyzer(CouncilRouter(), prompts), store, telegram, 99,
            [Topic(id="arbeit", name="Arbeit", enabled=True, description="Beruf")], 100_000,
        ).process(fetched)
    assert result.outcome is ProcessingOutcome.COMPLETED_WITH_ACTION_ERROR
    assert result["steps"]["summary_notification"] == "completed"
    assert result["steps"]["action_detection"] == "failed"
    assert "Zusammenfassung:" in telegram.sent[0][1]
    assert "Stufe action_router:" in telegram.sent[1][1]


def test_test_mode_end_to_end_never_calls_writer_and_survives_restart(tmp_path):
    telegram = FakeTelegram()
    writer = FakeWriter("forbidden")
    item = Proposal.model_validate({
        "id": "task", "version": 1, "kind": "task", "responsibility": "user",
        "certainty": "certain", "classification": "new", "title": "Nur testen",
        "evidence": "synthetisch", "source_mail_id": "a" * 24, "target": "inbox",
    })
    decision = f"proposal:{item.source_mail_id}:{item.id}:{item.version}:confirm"
    with JsonStore(tmp_path / "test") as store:
        dialog = TelegramDialogController(
            store, telegram, 42, 99, NullLogger(), {"todoist": writer}, True,
        )
        dialog.persist(item)
        telegram.updates = [callback_update(0, decision), callback_update(1, decision)]
        dialog.poll_once()
        dialog.poll_once()
        assert writer.created == []
        assert store.load(f"proposal-{item.source_mail_id}-{item.id}")["status"] == "simulated"
        assert sum("simuliert" in text for _, text, _ in telegram.sent) == 1

        restarted_transport = FakeTelegram()
        restarted = TelegramDialogController(
            store, restarted_transport, 42, 99, NullLogger(), {"todoist": writer}, True,
        )
        restarted.poll_once()
        assert restarted_transport.polls == [2]
        assert restarted_transport.sent == [] and writer.created == []
