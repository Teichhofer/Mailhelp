"""Secret-free end-to-end flow through all external trust boundaries."""
from __future__ import annotations

from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from threading import Event

from mailhelp.analysis import Analyzer
from mailhelp.application import Application
from mailhelp.config import PromptConfig, PromptStep, TargetSettings, Topic
from mailhelp.imap import FetchedMail
from mailhelp.logging import NullLogger
from mailhelp.models import Proposal
from mailhelp.orchestrator import Orchestrator, ProcessingOutcome
from mailhelp.storage import JsonStore
from mailhelp.telegram import TelegramDialogController


class SimulatedOpenRouter:
    def complete(self, _model, _parameters, system, payload):
        mail_id = payload["mail"]["internal_id"]
        if system == "relevance":
            return "r", {"decision": "relevant", "topic_ids": ["arbeit"], "reason": "Aufgabe und Termin"}
        if system == "summary":
            return "s", {"sentences": ["Eine Aufgabe ist fällig.", "Ein Termin wurde vereinbart."], "deadlines": ["30. September"]}
        return "a", {"proposals": [
            {"id": "task", "version": 1, "kind": "task", "responsibility": "user", "certainty": "certain", "classification": "new", "title": "Unterlagen senden", "evidence": "Bitte senden", "source_mail_id": mail_id, "due": "2026-09-30T17:00:00+02:00", "target": "untrusted"},
            {"id": "event", "version": 1, "kind": "event", "responsibility": "user", "certainty": "certain", "classification": "new", "title": "Besprechung", "evidence": "8. Oktober von 09:00 bis 10:00", "source_mail_id": mail_id, "start": "2026-10-08T09:00:00+02:00", "end": "2026-10-08T10:00:00+02:00", "target": "untrusted"},
        ]}


class FakeImap:
    account_id = "1" * 24
    last_uidvalidity = 7

    def __init__(self, fetched):
        self.fetched = fetched
        self.calls = []

    def fetch_since(self, folder, uid, uidvalidity):
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

    def send(self, chat_id, text, reply_markup=None):
        self.sent.append((chat_id, text, reply_markup))

    def poll(self, offset):
        assert offset == 0
        return self.updates

    def answer_callback(self, callback_id, text):
        self.answers.append((callback_id, text))


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


def test_imap_llm_telegram_confirmation_to_fake_writers(tmp_path):
    prompts = PromptConfig(defaults={"model": "fake", "parameters": {}}, prompts={
        step: PromptStep(system_prompt=step) for step in ("relevance", "summary", "actions", "proposal_revision")})
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
        callbacks = [row[2]["inline_keyboard"][0][0]["callback_data"] for row in telegram.sent if row[2]]
        assert len(callbacks) == 2 and all(value.endswith(":confirm") for value in callbacks)
        telegram.updates = [callback_update(index, value) for index, value in enumerate(callbacks)]
        app._poll_telegram()

        assert len(todoist.created) == len(calendar.created) == 1
        assert todoist.created[0][0].target == "project"
        assert calendar.created[0][0].target == "calendar"
        assert all(store.load_model(f"proposal-{item[0].source_mail_id}-{item[0].id}", Proposal).status == "created"
                   for item in (todoist.created[0], calendar.created[0]))
        assert store.load("telegram-offset")["offset"] == 2
