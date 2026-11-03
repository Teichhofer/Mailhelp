"""Telegram input and web commands beside the mail loop (Planung 3.6, Schritt 0.5); no sleep()."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from shared_application import Imap, Orch, Telegram, app

from mailhelp.runtime.operator_thread import OperatorThread
from mailhelp.telegram.receiver import TelegramInbox


def test_a_failed_pass_is_retried_and_a_successful_one_waits_for_input():
    passes, waits = iter([False, True]), []

    def wait(seconds):
        waits.append(seconds)
        operator.stop()
        return True

    operator = OperatorThread(lambda: next(passes), wait, lambda: None, retry_seconds=0, idle_seconds=7)
    operator.run()
    assert waits == [7] and operator.served.is_set()


def test_stopping_during_a_pass_ends_without_waiting_for_input():
    woken = []

    def serve():
        operator.stop()
        return True

    operator = OperatorThread(serve, lambda seconds: pytest.fail("no wait after stop"), lambda: woken.append(1),
                              retry_seconds=0, idle_seconds=7)
    operator.run()
    assert woken == [1] and operator.served.is_set()


class Dialog:
    """Answers a waiting relevance question whenever the operator thread serves it."""

    def __init__(self):
        self.open, self.polls = False, 0

    def awaiting_relevance_decision(self):
        return self.open

    def poll_once(self, timeout=None):
        self.polls += 1
        self.open = False


def test_the_operator_serves_the_dialog_while_the_mail_loop_only_waits(tmp_path):
    service = app(tmp_path, Imap([]), Telegram([]), Orch())
    service.dialog = Dialog()
    # Without the receiver's inbox there is nothing to wait on: no operator thread.
    service._start_operator()
    assert service.services.operator is None
    inbox = TelegramInbox(service.store)
    service.services.receiver = SimpleNamespace(inbox=inbox, stop=lambda: None)
    service._start_operator()
    operator = service.services.operator
    assert operator is not None and operator.served.wait(5) and service.dialog.polls >= 1
    # A blocking relevance question is answered by the operator thread, not by polling here.
    service.dialog.open = True
    inbox.wake()
    assert service._wait_for_telegram_decision() is True and not service.dialog.open
    # Between cycles the mail loop no longer handles input itself.
    polls = service.dialog.polls
    service._idle(0)
    service._idle = lambda delay: None
    assert service._cycle(None, False) is True
    service.stop()
    service.services.stop_operator()
    assert not operator.is_alive() and service.services.operator is None
    assert service.dialog.polls >= polls


def test_settings_and_topics_from_a_web_command_wait_for_the_next_cycle(tmp_path):
    service = app(tmp_path, Imap([]), Telegram([]), Orch())
    applied = []
    service.apply_settings = lambda settings: applied.append(("settings", settings))
    service.orchestrator.change_topics = lambda topics: applied.append(("topics", topics))
    service.request_settings(service.settings)
    service.request_topics([])
    assert applied == []
    service._apply_requested_configuration()
    assert applied == [("settings", service.settings), ("topics", [])]
    service._apply_requested_configuration()
    assert len(applied) == 2


def test_without_the_operator_thread_the_mail_loop_still_serves_input_between_cycles(tmp_path):
    service = app(tmp_path, Imap([]), Telegram([]), Orch())
    service.dialog = Dialog()
    service.services.receiver = SimpleNamespace(inbox=TelegramInbox(service.store), stop=lambda: None)
    service._idle = lambda delay: None
    assert service._cycle(None, False) is True and service.dialog.polls == 1
