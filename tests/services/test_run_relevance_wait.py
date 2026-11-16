"""Waiting for open relevance questions and Telegram polling during a run."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from mailhelp.mailbox.imap import FetchedMail
from mailhelp.processing.orchestrator import ProcessingOutcome, ProcessingResult
from mailhelp.proposals.integrations import OAuthTokenError
from mailhelp.telegram.commands import STARTUP
from tests.fakes.shared_application import Imap, Orch, Telegram, app

# Since 2.3 the writers are built in mailhelp.external.providers.


def test_run_waits_for_open_relevance_before_polling_imap(tmp_path):
    class ControlledStop:
        def __init__(self):
            self.stopped=False
            self.waits=[]
        def is_set(self): return self.stopped
        def set(self): self.stopped=True
        def wait(self, seconds):
            self.waits.append(seconds)
            self.stopped=True
            return True
    class Dialog:
        def __init__(self): self.polls=0
        def poll_once(self, timeout=None):
            self.polls += 1
            self.open = False
        open = True
        def awaiting_decision(self): return self.open
        def awaiting_relevance_decision(self): return self.open

    service=app(tmp_path,Imap([(1,[])]),Telegram([]),Orch())
    stop=ControlledStop()
    service.stop_event=stop
    service.dialog=Dialog()
    service.run()

    assert service.dialog.polls == 2
    assert service.imap.calls == [("INBOX",0,None,None,())]
    assert stop.waits == [service.settings.poll_interval_seconds]


def test_mail_batch_does_not_poll_telegram_without_an_open_question(tmp_path):
    mails = [FetchedMail("INBOX", 7, uid, b"synthetic") for uid in (1, 2)]

    class Dialog:
        def __init__(self): self.timeouts = []
        def poll_once(self, timeout=None): self.timeouts.append(timeout)

    service = app(tmp_path, Imap([(7, mails)]), Telegram([]), Orch())
    service.dialog = Dialog()
    service.dialog.awaiting_decision = lambda: False
    service.dialog.awaiting_relevance_decision = lambda: False

    results = service.mailbox.poll()

    assert len(results) == 2
    assert service.orchestrator.seen == [1, 2]
    assert service.dialog.timeouts == []


def test_open_relevance_blocks_next_mail_even_in_bounded_run(tmp_path):
    mails = [FetchedMail("INBOX", 7, uid, b"x") for uid in (1, 2, 3)]

    class Dialog:
        open = False
        polls = 0
        def poll_once(self, timeout=None):
            self.polls += 1
            self.open = False
        def awaiting_decision(self): return self.open
        def awaiting_relevance_decision(self): return self.open

    dialog = Dialog()
    class OpensDialog(Orch):
        def process(self, mail):
            result = super().process(mail)
            if mail.uid == 2:
                dialog.open = True
            return result

    service = app(tmp_path, Imap([(7, mails)]), Telegram([]), OpensDialog())
    service.dialog = dialog

    service.run(max_mails=3)

    assert service.orchestrator.seen == [1, 2, 3]
    assert dialog.open is False
    assert dialog.polls == 1


def test_versioned_answer_is_processed_before_later_mail(tmp_path):
    reference = ("a" * 24, "proposal-2", 3)

    class Dialog:
        def __init__(self):
            self.updates=[]
            self.handled=[]
            self.executions=[]
            self.polls=0
            self.open=False
        def poll_once(self, timeout=None):
            self.polls += 1
            if not self.open:
                return
            for update in self.updates:
                identity = (update["mail_id"], update["proposal_id"], update["version"])
                if identity not in self.executions:
                    self.handled.append(update)
                    self.executions.append(identity)
            self.updates.clear()
            self.open = False
        def awaiting_decision(self): return self.open
        def awaiting_relevance_decision(self): return self.open
        def awaiting_relevance_decision(self): return self.open

    class ProposesOnTwo(Orch):
        def process(self, mail):
            self.seen.append(mail.uid)
            if mail.uid == 2 and not dialog.handled:
                dialog.open = True
            outcome = (ProcessingOutcome.WAITING if dialog.open
                       else ProcessingOutcome.COMPLETED)
            return ProcessingResult(outcome, {})

    dialog = Dialog()
    arrived_ten_minutes_later = {
        "received_at": datetime.now(UTC) + timedelta(minutes=10),
        "mail_id": reference[0], "proposal_id": reference[1], "version": reference[2],
    }
    # Telegram may redeliver an update; the immutable proposal revision still
    # authorizes exactly one simulated external write.
    dialog.updates.extend([arrived_ten_minutes_later, arrived_ten_minutes_later.copy()])
    mails = [FetchedMail("INBOX", 7, uid, b"synthetic") for uid in (1, 2, 3)]
    first = app(tmp_path, Imap([(7, mails)]), Telegram([]), ProposesOnTwo())
    first.dialog = dialog
    first.run(max_mails=3)

    assert [(item["mail_id"], item["proposal_id"], item["version"])
            for item in dialog.handled] == [reference]
    assert dialog.executions == [reference]
    assert first.orchestrator.seen == [1, 2, 2, 3]
    assert dialog.polls == 1


def test_existing_relevance_is_resolved_before_processing_mail(tmp_path):
    class Dialog:
        def __init__(self):
            self.polls = 0
            self.open = True
        def poll_once(self, timeout=None):
            self.polls += 1
            self.open = False
        def awaiting_decision(self): return self.open
        def awaiting_relevance_decision(self): return self.open

    service = app(tmp_path, Imap([]), Telegram([]), Orch())
    service.dialog = Dialog()
    service._wait_for_user = True

    result = service._process_mail(FetchedMail("INBOX", 7, 1, b"synthetic"))

    assert result.outcome is ProcessingOutcome.COMPLETED
    assert service.dialog.polls == 1


def test_relevance_wait_returns_when_shutdown_interrupts_it(tmp_path):
    class OpensDialog(Orch):
        def process(self, mail):
            dialog.open = True
            return ProcessingResult(ProcessingOutcome.COMPLETED, {})

    class Dialog:
        open = False
        def awaiting_decision(self): return self.open
        def awaiting_relevance_decision(self): return self.open
        def poll_once(self, timeout=None): raise RuntimeError("network")

    class StopOnWait:
        stopped = False
        def is_set(self): return self.stopped
        def wait(self, _seconds):
            self.stopped = True
            return True

    dialog = Dialog()
    service = app(tmp_path, Imap([]), Telegram([]), OpensDialog())
    service.dialog = dialog
    service.stop_event = StopOnWait()
    service._wait_for_user = True

    result = service._process_mail(FetchedMail("INBOX", 7, 1, b"synthetic"))

    assert result.outcome is ProcessingOutcome.COMPLETED


def test_run_waits_when_regular_telegram_poll_opens_dialog(tmp_path):
    calls = []
    class Dialog:
        def __init__(self):
            self.open = False
            self.polls = 0
        def awaiting_decision(self): return self.open
        def awaiting_relevance_decision(self): return self.open
        def poll_once(self, timeout=None):
            calls.append("telegram")
            self.polls += 1
            self.open = self.polls == 1

    class ControlledStop:
        def __init__(self): self.stopped = False
        def is_set(self): return self.stopped
        def set(self): self.stopped = True
        def wait(self, _seconds):
            self.stopped = True
            return True

    service = app(tmp_path, Imap([(1, [])]), Telegram([]), Orch())
    service.dialog = Dialog()
    service.stop_event = ControlledStop()
    original_poll_imap = service._poll_imap
    def poll_imap(max_mails=None):
        calls.append("imap")
        return original_poll_imap(max_mails)
    service._poll_imap = poll_imap

    service.run()

    assert calls == ["imap", "telegram", "telegram"]
    assert service.dialog.polls == 2
    assert not service.dialog.open


def test_bounded_run_processes_imap_without_regular_telegram_poll(tmp_path):
    mail = FetchedMail("INBOX", 7, 1, b"synthetic")
    telegram = Telegram([])
    service = app(tmp_path, Imap([(7, [mail])]), telegram, Orch())

    service.run(max_mails=1)

    assert service.orchestrator.seen == [1]
    assert telegram.offsets == []


def test_waiting_relevance_handles_closed_dialog_and_poll_failure(tmp_path):
    class WaitingOrchestrator(Orch):
        def process(self, mail):
            return ProcessingResult(ProcessingOutcome.WAITING, {})

    class Dialog:
        def __init__(self, open): self.open = open
        def awaiting_decision(self): return self.open
        def awaiting_relevance_decision(self): return self.open
        def awaiting_relevance_decision(self): return self.open
        def poll_once(self, timeout=None): raise RuntimeError("network")

    service = app(tmp_path, Imap([]), Telegram([]), WaitingOrchestrator())
    service.dialog = Dialog(False)
    service._wait_for_user = True
    assert service._process_mail(FetchedMail("INBOX", 7, 1, b"synthetic")).outcome \
        is ProcessingOutcome.WAITING
    assert service._wait_for_telegram_decision() is False

    class StopOnWait:
        def __init__(self): self.stopped = False
        def is_set(self): return self.stopped
        def wait(self, _seconds):
            self.stopped = True
            return True

    service.dialog.open = True
    service.stop_event = StopOnWait()
    assert service._process_mail(FetchedMail("INBOX", 7, 1, b"synthetic")).outcome \
        is ProcessingOutcome.WAITING
    assert service.stop_event.is_set()


def test_run_keeps_imap_interval_without_open_dialog(tmp_path):
    class ControlledStop:
        def __init__(self):
            self.stopped=False
            self.waits=[]
        def is_set(self): return self.stopped
        def set(self): self.stopped=True
        def wait(self, seconds):
            self.waits.append(seconds)
            self.stopped=True
            return True

    service=app(tmp_path,Imap([(1,[])]),Telegram([]),Orch())
    stop=ControlledStop()
    service.stop_event=stop
    service.run()

    assert service.imap.calls == [("INBOX",0,None,None,())]
    assert stop.waits == [service.settings.poll_interval_seconds]


def test_telegram_poll_failure_backs_off_and_shutdown_interrupts_it(tmp_path):
    class ControlledStop:
        def __init__(self):
            self.stopped=False
            self.waits=[]
        def is_set(self): return self.stopped
        def set(self): self.stopped=True
        def wait(self, seconds):
            self.waits.append(seconds)
            self.stopped=True
            return True
    class FailingDialog:
        def __init__(self): self.polls=0
        def poll_once(self, timeout=None):
            self.polls += 1
            raise RuntimeError("network")
        def awaiting_decision(self): return True
        def awaiting_relevance_decision(self): return True

    service=app(tmp_path,Imap([]),Telegram([]),Orch())
    stop=ControlledStop()
    service.stop_event=stop
    service.dialog=FailingDialog()
    service.run()

    assert service.dialog.polls == 1
    assert stop.waits == [5]
    assert stop.is_set()


@pytest.mark.parametrize("notification_error", [None, RuntimeError("telegram down")])
def test_google_oauth_failure_stops_application_without_retry(tmp_path, notification_error):
    class FailingDialog:
        def __init__(self): self.polls = 0
        def poll_once(self, timeout=None):
            self.polls += 1
            raise OAuthTokenError(
                "Google OAuth-Anmeldung abgelehnt: Zugangsdaten erneuern und "
                "'mailhelp --check-access' ausführen."
            )
        def awaiting_decision(self): return True
        def awaiting_relevance_decision(self): return True

    telegram = Telegram([])
    if notification_error is not None:
        telegram.send = lambda *_args: (_ for _ in ()).throw(notification_error)
    service = app(tmp_path, Imap([]), telegram, Orch())
    service.dialog = FailingDialog()

    result = service.run()

    assert result is not None and "check-access" in result
    assert service.stop_event.is_set()
    assert service.dialog.polls == 1
    assert not [event for event in service.logger.events if event[0][2] == "poll_failed"]
    fatal_event = next(
        event for event in service.logger.events
        if event[0][2] == "fatal_google_oauth_error"
    )
    assert fatal_event[0] == (
        "CRITICAL", "application", "fatal_google_oauth_error"
    )
    if notification_error is None:
        assert telegram.sent[0][1] == STARTUP
        assert "Mailhelp wird beendet" in telegram.sent[1][1]
    else:
        assert any(
            event[0][2] == "fatal_error_notification_failed"
            for event in service.logger.events
        )


def test_shutdown_requested_during_long_poll_stops_before_retry(tmp_path):
    class Dialog:
        def __init__(self, stop):
            self.stop=stop
            self.polls=0
        def poll_once(self, timeout=None):
            self.polls += 1
            self.stop.set()
        def awaiting_decision(self): return True
        def awaiting_relevance_decision(self): return True

    service=app(tmp_path,Imap([]),Telegram([]),Orch())
    service.dialog=Dialog(service.stop_event)
    service.run()

    assert service.dialog.polls == 1
