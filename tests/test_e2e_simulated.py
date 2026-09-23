"""Secret-free end-to-end flow through all external trust boundaries."""
from __future__ import annotations

from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from threading import Event

import httpx

from mailhelp.analysis import Analyzer, LlmSchemaValidationExceeded
from mailhelp.application import Application
from mailhelp.config import PromptConfig, PromptStep, TargetSettings, Topic
from mailhelp.imap import FetchedMail
from mailhelp.logging import NullLogger
from mailhelp.models import ActionLedger, Proposal
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
            "telegram_answer_interpretation", "telegram_answer_clarification",
            "proposal_revision", "learning_classification", "learning_abstraction")})
    analyzer = Analyzer(router, prompts)
    telegram = FakeTelegram()
    calendar = ReconciledCalendar()
    fixture = Path(__file__).parent / "fixtures" / "nachholtermin_bildungsplannovellierung.eml"
    fetched = FetchedMail("INBOX", 7, 23, fixture.read_bytes(), "1" * 24,
                          datetime(2026, 9, 22, 7, 15, tzinfo=timezone.utc))
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


def test_nachholtermin_fixture_explicit_offset_confirmation_and_reconciliation(tmp_path):
    store, dialog, telegram, calendar, router, result = nachholtermin_flow(
        tmp_path / "complete", incomplete=False)
    try:
        assert result.outcome is ProcessingOutcome.COMPLETED
        assert router.calls == ["relevance", "summary", "action_router", "event_extraction"]
        assert len(result.state["proposals"]) == 1
        proposal = Proposal.model_validate(result.state["proposals"][0])
        assert proposal.status.value == "pending_confirmation"
        assert proposal.open_questions == []
        assert proposal.temporal_fact.normalized_date.isoformat() == "2026-09-23"
        assert proposal.start.isoformat() == "2026-09-23T09:00:00+01:00"
        assert proposal.end.isoformat() == "2026-09-23T10:00:00+01:00"
        assert proposal.start.astimezone(timezone.utc).isoformat() == "2026-09-23T08:00:00+00:00"
        assert proposal.end.astimezone(timezone.utc).isoformat() == "2026-09-23T09:00:00+00:00"
        assert calendar.create_calls == []

        assert_single_calendar_write_survives_restart(
            store, dialog, telegram, calendar, telegram_button(telegram, "Anlegen"), 100)
    finally:
        store.__exit__()


def test_nachholtermin_incomplete_is_completed_locally_then_idempotently_written(tmp_path):
    store, dialog, telegram, calendar, router, result = nachholtermin_flow(
        tmp_path / "incomplete", incomplete=True)
    try:
        proposal = Proposal.model_validate(result.state["proposals"][0])
        assert result.outcome is ProcessingOutcome.COMPLETED
        assert proposal.status.value == "needs_clarification"
        assert proposal.open_questions == ["Wann beginnt der Termin?"]
        initial_llm_calls = list(router.calls)

        telegram.updates = [callback_update(200, telegram_button(telegram, "Klären"))]
        dialog.poll_once()
        telegram.updates.append(message_update(201, "23.09.2026 9:00 bis 10uhr"))
        dialog.poll_once()

        assert router.calls == initial_llm_calls
        revised = store.load_model(
            f"proposal-{proposal.source_mail_id}-{proposal.id}", Proposal)
        assert revised is not None and revised.version == 2
        assert revised.status.value == "pending_confirmation" and revised.open_questions == []
        assert revised.start.isoformat() == "2026-09-23T09:00:00+01:00"
        assert revised.end.isoformat() == "2026-09-23T10:00:00+01:00"
        assert revised.start.astimezone(timezone.utc).isoformat() == "2026-09-23T08:00:00+00:00"
        assert revised.end.astimezone(timezone.utc).isoformat() == "2026-09-23T09:00:00+00:00"
        assert calendar.create_calls == []

        assert_single_calendar_write_survives_restart(
            store, dialog, telegram, calendar, telegram_button(telegram, "Anlegen"), 202)
    finally:
        store.__exit__()


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
