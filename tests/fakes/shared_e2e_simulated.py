"""Shared synthetic fixtures and doubles; no test-module dependencies."""
from __future__ import annotations

from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path

import httpx

from mailhelp.analysis import Analyzer
from mailhelp.config import PromptConfig, PromptStep, TargetSettings, Topic
from mailhelp.imap import FetchedMail
from mailhelp.logging import NullLogger
from mailhelp.models import ActionLedger
from mailhelp.orchestrator import Orchestrator
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

    def poll(self, offset, timeout=None):
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

def message_update(update_id, text):
    return {"update_id": update_id, "message": {"message_id": update_id,
            "from": {"id": 42}, "chat": {"id": 99}, "text": text}}

class NachholterminRouter:
    """Schema-validating LLM double; only extraction completeness is variable."""

    def __init__(self, incomplete=False):
        self.incomplete = incomplete
        self.calls = []

    def complete(self, _model, _parameters, system, payload, **_metadata):
        self.calls.append(system)
        if system == "relevance":
            return "relevance-call", {"decision": "relevant", "topic_ids": ["arbeit"],
                                      "reason": "Ein konkreter Termin ist enthalten."}
        if system == "summary":
            return "summary-call", {"sentences": ["Ein synthetischer Nachholtermin wurde angekündigt."],
                                    "deadlines": []}
        if system == "action_router":
            return "router-call", {"action_state": "event", "task_count": 0,
                                   "event_count": 1, "reason": "Termin erkannt."}
        if system == "event_extraction":
            return "event-call", {"schema_version": 1, "events": [{
                "title": "Auftakt der Bildungsplannovellierung", "description": None,
                "evidence": "Mi, 23.09.2026, 09:00 Uhr bis 10:00 Uhr (UTC+01:00)",
                "date_text": "23.09.2026", "time_text": None if self.incomplete else "09:00 Uhr",
                "end_time_text": None if self.incomplete else "10:00 Uhr",
                "timezone_offset_text": "UTC+01:00", "time_requirement": "timed",
                "location": None, "video_link": None, "responsibility": "user",
                "certainty": "certain", "classification": "new",
            }]}
        if system == "mail_question_resolution":
            return "mail-question-call", {"usable": False, "normalized_answer": None,
                                           "reason": "Die Beginnzeit fehlt in der Mail."}
        raise AssertionError(f"Unerwarteter LLM-Aufruf: {system}")

class ReconciledCalendar:
    """Simulate a response loss after Google accepted the sole create request."""

    def __init__(self):
        self.create_calls = []
        self.reconcile_calls = []
        self.remote = {}

    def create(self, proposal, key):
        self.create_calls.append((proposal, key))
        self.remote[key] = {"id": "calendar-event-1", "url": "https://example.test/calendar/1"}
        raise httpx.ReadTimeout("synthetic response loss")

    def reconcile(self, key):
        self.reconcile_calls.append(key)
        return self.remote.get(key)

def nachholtermin_flow(tmp_path, *, incomplete):
    router = NachholterminRouter(incomplete)
    prompts = PromptConfig(defaults={"model": "fake", "parameters": {}}, prompts={
        step: PromptStep(system_prompt=step) for step in (
            "relevance", "summary", "action_router", "task_extraction", "event_extraction",
            "mail_question_resolution", "telegram_answer_interpretation", "telegram_answer_clarification",
            "proposal_revision", "learning_classification", "learning_abstraction", "calendar_duplicate")})
    analyzer = Analyzer(router, prompts)
    telegram = FakeTelegram()
    calendar = ReconciledCalendar()
    fixture = Path(__file__).parents[1] / "fixtures" / "nachholtermin_bildungsplannovellierung.eml"
    fetched = FetchedMail("INBOX", 7, 23, fixture.read_bytes(), "1" * 24,
                          datetime(2026, 9, 22, 7, 15, tzinfo=UTC))
    store = JsonStore(tmp_path).__enter__()
    dialog = TelegramDialogController(
        store, telegram, 42, 99, NullLogger(), {"google_calendar": calendar}, False,
        "Etc/GMT-1", analyzer)
    orchestrator = Orchestrator(
        analyzer, store, dialog, 99,
        [Topic(id="arbeit", name="Arbeit", enabled=True, description="Beruf")], 100_000,
        targets=TargetSettings(todoist_project="project", google_calendar="calendar"),
        user_timezone="Etc/GMT-1")
    result = orchestrator.process(fetched)
    return store, dialog, telegram, calendar, router, result

def telegram_button(telegram, label):
    return next(button["callback_data"] for _, _, markup in reversed(telegram.sent)
                if markup for row in markup["inline_keyboard"] for button in row
                if button["text"] == label)

def assert_single_calendar_write_survives_restart(store, dialog, telegram, calendar,
                                                  decision, update_id):
    telegram.updates = [callback_update(update_id, decision)]
    dialog.poll_once()
    assert len(calendar.create_calls) == 1
    proposal = calendar.create_calls[0][0]
    # The executor persists CONFIRMED before advancing to WRITING and calling
    # the adapter; reaching this boundary therefore proves the version-bound
    # confirmation was accepted, rather than a direct unconfirmed write.
    assert proposal.status.value == "writing"
    assert proposal.version >= 1
    assert telegram.answers[-1] == (f"cb-{update_id}", "Aktion wird verarbeitet …")
    assert store.load(f"proposal-{proposal.source_mail_id}-{proposal.id}")["status"] == "uncertain"

    replay = FakeTelegram()
    replay.updates = [callback_update(update_id, decision)]
    restarted = TelegramDialogController(
        store, replay, 42, 99, NullLogger(), {"google_calendar": calendar}, False,
        "Etc/GMT-1")
    restarted.poll_once()

    assert len(calendar.create_calls) == 1
    # One pre-write reconciliation and one restart reconciliation use the same
    # idempotency key; neither issues another create request.
    assert calendar.reconcile_calls == [calendar.create_calls[0][1]] * 2
    saved = store.load(f"proposal-{proposal.source_mail_id}-{proposal.id}")
    assert saved["status"] == "created" and saved["external_id"] == "calendar-event-1"
    ledger = store.load_model("action-ledger", ActionLedger)
    assert ledger is not None and len(ledger.entries) == 1
    assert ledger.entries[0].proposal_version == proposal.version
