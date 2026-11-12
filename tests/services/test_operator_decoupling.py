"""Proof that operating Mailhelp no longer waits for mail analysis (Planung 3.6, Schritt 0.6).

The main thread is held inside a mail analysis by an event; the web action must finish
meanwhile. Synchronisation uses events with fixed time limits, never sleep().
"""
from __future__ import annotations

import json
from threading import Event, Thread
from types import SimpleNamespace

from mailhelp.logging import JsonlLogger
from mailhelp.mailbox.imap import FetchedMail
from mailhelp.review.inbox import CommandStatus
from mailhelp.telegram.receiver import TelegramInbox
from tests.fakes.shared_application import Imap, Orch, Telegram, app
from tests.fakes.shared_web_actions import web as web

LIMIT = 10


class HeldOrch(Orch):
    """Analyses a mail only after the test releases it."""

    def __init__(self):
        super().__init__()
        self.entered, self.release = Event(), Event()
        self.topic_changes = []

    def process(self, mail):
        self.entered.set()
        assert self.release.wait(LIMIT), "Die Mailanalyse wurde nicht freigegeben"
        return super().process(mail)

    def change_topics(self, topics):
        self.topic_changes.append(topics)


def operated(web, tmp_path):
    orch = HeldOrch()
    mail = FetchedMail("INBOX", 1, 5, b"Subject: Synthetisch\n\nText", "0" * 24)
    service = app(tmp_path, Imap([(1, [mail])]), Telegram([]), orch, store=web.store)
    service.dialog = web.dialog
    inbox = TelegramInbox(web.store)
    web.commands.wake = inbox.wake
    service.services.receiver = SimpleNamespace(inbox=inbox, stop=lambda: None)
    service._start_operator()
    return service, orch


def finished(web, service, entry_id) -> bool:
    """Wait for the operator thread to finish *entry_id*, pass by pass."""
    operator = service.services.operator
    for _ in range(LIMIT * 4):
        entry = web.commands.get(entry_id)
        if entry is not None and entry.status not in {CommandStatus.QUEUED, CommandStatus.RUNNING}:
            return True
        operator.served.clear()
        operator.served.wait(LIMIT / 4)
    return False


def test_a_web_confirmation_runs_while_a_mail_is_being_analysed(web, tmp_path, monkeypatch):
    logger = JsonlLogger(tmp_path / "logs")
    acceptance_logged = Event()
    event = logger.event

    def observe(level, module, name, **context):
        event(level, module, name, **context)
        if name == "command_submitted":
            acceptance_logged.set()

    monkeypatch.setattr(logger, "event", observe)
    web.dialog.logger = web.site.logger = logger
    service, orch = operated(web, tmp_path)
    main = Thread(target=service.mailbox.poll, name="mail-loop")
    main.start()
    try:
        assert orch.entered.wait(LIMIT)
        response = web.submit(web.form("/", kind="confirm", proposal_id="elternabend"), accept="application/json")
        entry_id = json.loads(response.body)["id"]
        assert finished(web, service, entry_id)
        # Acceptance logging and execution use separate queues. An entry arriving
        # after take_acceptances() can execute in this pass and be logged in the next.
        # Wait for the observed event before stopping the operator and reading the log.
        assert acceptance_logged.wait(LIMIT)
        # The confirmation was executed while the analysis still holds the main thread.
        assert main.is_alive() and not orch.release.is_set()
        assert web.commands.get(entry_id).status == CommandStatus.DONE and web.writer.created == 1
    finally:
        orch.release.set()
        main.join(LIMIT)
        service.stop()
        service.services.stop_operator()
    assert not main.is_alive() and orch.seen == [5]
    records = [json.loads(line) for line in logger.app.read_text(encoding="utf-8").splitlines()]
    submitted = next(record for record in records if record["event"] == "command_submitted")
    completed = next(record for record in records if record["event"] == "command_finished")
    assert submitted["command_id"] == completed["command_id"] == entry_id
    assert 0 <= completed["execution_ms"] <= completed["latency_ms"] + 10
    # An acceptance bound, not a synchronisation mechanism; the analysis is still held above.
    assert 0 <= completed["latency_ms"] < LIMIT * 1000
    print("SYNTHETIC_BUSY_CYCLE " + json.dumps(completed, sort_keys=True))


def test_topics_saved_during_an_analysis_apply_only_at_the_next_cycle(web, tmp_path):
    service, orch = operated(web, tmp_path)
    main = Thread(target=service.mailbox.poll, name="mail-loop")
    main.start()
    try:
        assert orch.entered.wait(LIMIT)
        # What the configuration service does for a saved topic change in the operator thread.
        service.request_topics([])
        assert orch.topic_changes == []
    finally:
        orch.release.set()
        main.join(LIMIT)
        service.stop()
        service.services.stop_operator()
    # The analysed mail kept its configuration; the change arrives between two cycles.
    assert orch.topic_changes == []
    service._apply_requested_configuration()
    assert orch.topic_changes == [[]]
