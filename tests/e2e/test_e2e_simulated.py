"""Secret-free end-to-end flow through all external trust boundaries."""
from __future__ import annotations

from datetime import UTC, datetime
from email.message import EmailMessage
from threading import Event

from shared_e2e_simulated import FakeImap as FakeImap
from shared_e2e_simulated import FakeTelegram as FakeTelegram
from shared_e2e_simulated import FakeWriter as FakeWriter
from shared_e2e_simulated import NachholterminRouter as NachholterminRouter
from shared_e2e_simulated import ReconciledCalendar as ReconciledCalendar
from shared_e2e_simulated import SettingsStub as SettingsStub
from shared_e2e_simulated import SimulatedOpenRouter as SimulatedOpenRouter
from shared_e2e_simulated import (
    assert_single_calendar_write_survives_restart as assert_single_calendar_write_survives_restart,
)
from shared_e2e_simulated import callback_update as callback_update
from shared_e2e_simulated import message_update as message_update
from shared_e2e_simulated import nachholtermin_flow as nachholtermin_flow
from shared_e2e_simulated import raw_mail as raw_mail
from shared_e2e_simulated import telegram_button as telegram_button

from mailhelp.analysis import Analyzer, LlmSchemaValidationExceeded
from mailhelp.application import Application
from mailhelp.config import PromptConfig, PromptStep, TargetSettings, Topic
from mailhelp.imap import FetchedMail
from mailhelp.logging import NullLogger
from mailhelp.models import Proposal
from mailhelp.orchestrator import Orchestrator, ProcessingOutcome
from mailhelp.storage import JsonStore
from mailhelp.telegram import TelegramDialogController


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
        assert proposal.start.astimezone(UTC).isoformat() == "2026-09-23T08:00:00+00:00"
        assert proposal.end.astimezone(UTC).isoformat() == "2026-09-23T09:00:00+00:00"
        assert calendar.create_calls == []

        assert_single_calendar_write_survives_restart(
            store, dialog, telegram, calendar, telegram_button(telegram, "Im Kalender anlegen"), 100)
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
        assert revised.start.astimezone(UTC).isoformat() == "2026-09-23T08:00:00+00:00"
        assert revised.end.astimezone(UTC).isoformat() == "2026-09-23T09:00:00+00:00"
        assert calendar.create_calls == []

        assert_single_calendar_write_survives_restart(
            store, dialog, telegram, calendar, telegram_button(telegram, "Im Kalender anlegen"), 202)
    finally:
        store.__exit__()


def test_imap_llm_persists_separate_raw_extractions(tmp_path):
    prompts = PromptConfig(defaults={"model": "fake", "parameters": {}}, prompts={
        step: PromptStep(system_prompt=step) for step in ("relevance", "summary", "action_router", "task_extraction", "event_extraction", "mail_question_resolution", "telegram_answer_interpretation", "telegram_answer_clarification", "proposal_revision", "learning_classification", "learning_abstraction", "calendar_duplicate")})
    analyzer = Analyzer(SimulatedOpenRouter(), prompts)
    telegram = FakeTelegram()
    todoist, calendar = FakeWriter("todoist"), FakeWriter("calendar")
    fetched = FetchedMail("INBOX", 7, 1, raw_mail(), "1" * 24, datetime(2026, 9, 17, 8, 0, tzinfo=UTC))
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

        results = app.mailbox.poll()
        assert [result.outcome for result in results] == [ProcessingOutcome.COMPLETED]
        state = results[0].state
        assert state["task_extraction"]["tasks"][0]["due_text"] == "30. September"
        assert state["event_extraction"]["events"][0]["time_text"] == "09:00"
        assert len(state["proposals"]) == 2
        assert all(item["status"] == "pending_confirmation" for item in state["proposals"])
        assert state["proposals"][1]["temporal_fact"]["normalized_date"] == "2026-10-08"
        assert todoist.created == calendar.created == []

        def reject_buttons():
            return [button["callback_data"] for _, _, markup in telegram.sent
                    if markup for row in markup["inline_keyboard"]
                    for button in row if button["text"] == "Verwerfen"]

        # Only one open decision is shown; the second follows its resolution.
        assert sum(markup is not None for _, _, markup in telegram.sent) == 1
        assert len(reject_buttons()) == 1
        telegram.updates = [callback_update(1, reject_buttons()[0])]
        dialog.poll_once()
        second = orchestrator.process(fetched)
        assert second.outcome is ProcessingOutcome.COMPLETED
        assert len(reject_buttons()) == 2 and len(set(reject_buttons())) == 2

        telegram.updates = [callback_update(2, reject_buttons()[1])]
        dialog.poll_once()
        completed = orchestrator.process(fetched)
        assert completed.outcome is ProcessingOutcome.COMPLETED
        assert all(item["status"] == "rejected" for item in completed.state["proposals"])


def test_synthetic_council_mail_keeps_summary_when_action_detection_fails(tmp_path):
    class CouncilRouter(SimulatedOpenRouter):
        def complete(self, model, parameters, system, payload, **metadata):
            if system == "action_router":
                raise LlmSchemaValidationExceeded("action_router")
            return super().complete(model, parameters, system, payload, **metadata)

    prompts = PromptConfig(defaults={"model": "fake", "parameters": {}}, prompts={
        step: PromptStep(system_prompt=step)
        for step in ("relevance", "summary", "action_router", "task_extraction", "event_extraction", "mail_question_resolution", "telegram_answer_interpretation", "telegram_answer_clarification", "proposal_revision", "learning_classification", "learning_abstraction", "calendar_duplicate")
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
    assert "• " in telegram.sent[0][1]
    assert "Schritt action_router:" in telegram.sent[1][1]


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


def test_nachholtermin_clarified_and_confirmed_in_the_web(tmp_path):
    """Mail in, answered and confirmed in the browser, written once, Telegram consistent."""
    import re
    from html import unescape

    from shared_web_auth import LOCAL, SECRET, Browser, code_from

    from mailhelp.config import WebSettings
    from mailhelp.review.inbox import CommandInbox
    from mailhelp.review.views import ReviewViews
    from mailhelp.web import WebApp
    from mailhelp.web.auth import WebAuth
    from mailhelp.web.site import MailhelpSite

    store, dialog, telegram, calendar, router, result = nachholtermin_flow(
        tmp_path / "web", incomplete=True)
    try:
        proposal = Proposal.model_validate(result.state["proposals"][0])
        old_card_button = telegram_button(telegram, "Klären")
        dialog.commands = CommandInbox(store)
        messages = []
        auth = WebAuth(store, SECRET, 30, messages.append)
        dialog.review.web_authorizer = lambda actor: auth.active(actor.removeprefix("web:"))
        app = WebApp([LOCAL])
        MailhelpSite(app, auth, WebSettings(), "Etc/GMT-1", NullLogger(),
                     ReviewViews(store, "Etc/GMT-1"), dialog.commands)
        browser = Browser(app)
        csrf = browser.csrf()
        browser.request("POST", "/anmelden/code", {"csrf": csrf})
        browser.request("POST", "/anmelden", {"csrf": csrf, "code": code_from(messages)})

        def form(kind):
            html = browser.request("GET", "/").body.decode()
            for block in re.findall(r'<form method="post" action="/aktion"[^>]*>(.*?)</form>', html, re.S):
                fields = {name: unescape(value) for name, value in re.findall(
                    r'<input type="hidden" name="([^"]+)" value="([^"]*)">', block)}
                if fields["kind"] == kind:
                    return fields
            raise AssertionError(kind)

        initial_llm_calls = list(router.calls)
        browser.request("POST", "/aktion", {**form("answer"), "text": "23.09.2026 9:00 bis 10uhr"})
        dialog.poll_once()
        assert router.calls == initial_llm_calls
        revised = store.load_model(f"proposal-{proposal.source_mail_id}-{proposal.id}", Proposal)
        assert (revised.version, revised.status.value) == (2, "pending_confirmation")
        assert calendar.create_calls == []
        location = browser.request("POST", "/aktion", form("confirm")).headers["Location"]
        dialog.poll_once()
        assert len(calendar.create_calls) == 1 and calendar.create_calls[0][0].version == 2
        assert browser.request("GET", location).headers["Location"].startswith("/?ergebnis=")
        # Telegram saw the revision and the write; its old button is now stale.
        texts = [text for _, text, _ in telegram.sent]
        assert any("Übernommen" in text for text in texts)
        telegram.updates = [callback_update(300, old_card_button)]
        dialog.poll_once()
        assert "Schaltfläche ist veraltet" in telegram.sent[-1][1]
        restarted = TelegramDialogController(
            store, FakeTelegram(), 42, 99, NullLogger(), {"google_calendar": calendar}, False,
            "Etc/GMT-1", commands=CommandInbox(store))
        restarted.poll_once()
        assert len(calendar.create_calls) == 1
    finally:
        store.__exit__()
