"""Responsive Telegram input: receiver thread, durable inbox and its consumers."""
from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace

import httpx
import pytest

from mailhelp.adapter import PermanentError
from mailhelp.imap import FetchedMail
from mailhelp.logging import JsonlLogger
from mailhelp.storage import JsonStore
from mailhelp.telegram import TelegramClient, TelegramDialogController
from mailhelp.telegram.receiver import ACKNOWLEDGEMENT, TelegramInbox, TelegramReceiver
from test_application import Imap, Orch, Telegram as AppTelegram, app
from test_telegram_dialog import Logger, RevisionService, Telegram, callback, message, proposal

REJECT = "proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:1:reject"
EDIT = "proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:1:edit"


def ids(inbox):
    return [entry.update_id for entry in inbox.pending()]


def test_inbox_stores_updates_durably_in_order_and_without_duplicates(tmp_path):
    with JsonStore(tmp_path) as store:
        inbox = TelegramInbox(store)
        assert inbox.pending() == [] and inbox.next_offset() == 0
        inbox.add([message(5), {"no": "id"}, message(3), {"update_id": True}], acknowledged={3})
        inbox.add([message(5, "später erneut geliefert")], set())
        assert ids(inbox) == [3, 5]
        assert [entry.acknowledged for entry in inbox.pending()] == [True, False]
        assert inbox.pending()[1].update["message"]["text"] == "Antwort"
        # Durable and readable: a fresh instance sees the same queue.
        assert TelegramInbox(store).next_offset() == 6
        assert json.loads((tmp_path / "telegram-inbox.json").read_text(encoding="utf-8"))["schema_version"] == 1
        inbox.remove(3)
        assert ids(inbox) == [5]


def test_inbox_wait_returns_on_arrival_or_wake_and_times_out_otherwise(tmp_path):
    with JsonStore(tmp_path) as store:
        inbox = TelegramInbox(store)
        assert inbox.wait(0.01) is False
        inbox.add([message(1)], set())
        assert inbox.wait(0) is True and inbox.wait(0) is False
        inbox.wake()
        assert inbox.wait(5) is True
        arrival = threading.Timer(0.05, lambda: inbox.add([message(2)], set()))
        started = time.monotonic()
        arrival.start()
        assert inbox.wait(5) is True and time.monotonic() - started < 2
        arrival.join()


class Source:
    """Telegram stand-in: each poll returns the next result (list or exception)."""

    def __init__(self, results, fail_answers=(), on_empty=None):
        self.results, self.fail_answers, self.on_empty = list(results), set(fail_answers), on_empty
        self.offsets, self.answered = [], []

    def poll(self, offset, timeout=None):
        self.offsets.append(offset)
        if not self.results:
            if self.on_empty:
                self.on_empty()
            return []
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def answer_callback(self, callback_id, text):
        if callback_id in self.fail_answers:
            raise RuntimeError("synthetic acknowledgement failure")
        self.answered.append((callback_id, text))


def receiver(store, source, offset=0):
    log = Logger()
    return TelegramReceiver(source, TelegramInbox(store), offset, log, 0.01), log


def events(log):
    return [args[2] for args, _ in log.events]


def test_receiver_acknowledges_button_presses_at_once_and_stores_them_before_confirming(tmp_path):
    with JsonStore(tmp_path) as store:
        source = Source([[callback(7, REJECT), message(8), callback(9, EDIT), {"update_id": "x"}]],
                        fail_answers={"c9"})
        thread, log = receiver(store, source, offset=7)
        assert thread.receive_once() is True
        # Only callbacks are acknowledged; a failed acknowledgement is retried by the dialog.
        assert source.answered == [("c7", ACKNOWLEDGEMENT)]
        assert [(entry.update_id, entry.acknowledged) for entry in thread.inbox.pending()] == [
            (7, True), (8, False), (9, False)]
        assert thread.offset == 10 and source.offsets == [7]
        assert {"receiver_acknowledgement_failed", "receiver_invalid_update",
                "receiver_updates_stored"} <= set(events(log))
        # The next long-poll confirms the stored updates to Telegram.
        assert thread.receive_once() is True and source.offsets == [7, 10]


def test_receiver_keeps_its_offset_when_polling_or_storing_fails(tmp_path, monkeypatch):
    with JsonStore(tmp_path) as store:
        thread, log = receiver(store, Source([RuntimeError("offline"), [message(4)]]), offset=4)
        assert thread.receive_once() is False and "receiver_poll_failed" in events(log)
        monkeypatch.setattr(thread.inbox, "add", lambda *args: (_ for _ in ()).throw(OSError("disk")))
        assert thread.receive_once() is False and thread.offset == 4
        assert "receiver_inbox_failed" in events(log)
        # A poll aborted by shutdown is not an error.
        quiet, quiet_log = receiver(store, Source([RuntimeError("closed")]))
        quiet.stop_event.set()
        assert quiet.receive_once() is False and "receiver_poll_failed" not in events(quiet_log)


def test_receiver_thread_runs_until_stopped_and_backs_off_after_errors(tmp_path):
    with JsonStore(tmp_path) as store:
        holder = {}
        source = Source([RuntimeError("offline"), [callback(3, REJECT)]],
                        on_empty=lambda: holder["thread"].stop())
        thread, log = receiver(store, source, offset=3)
        holder["thread"] = thread
        thread.start()
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert ids(thread.inbox) == [3] and thread.offset == 4
        assert events(log)[0] == "receiver_started" and events(log)[-1] == "receiver_stopped"
        # stop() also wakes a main thread waiting on the inbox.
        thread.inbox.wait(0)
        thread.stop()
        assert thread.inbox.wait(0) is True


def dialog(store, inbox=None):
    transport, log = Telegram(), Logger()
    controller = TelegramDialogController(store, transport, 1, 2, log, None, False, "UTC",
                                          RevisionService(), inbox=inbox)
    return controller, transport


def test_dialog_processes_the_inbox_without_polling_and_without_a_second_acknowledgement(tmp_path):
    with JsonStore(tmp_path) as store:
        inbox = TelegramInbox(store)
        controller, transport = dialog(store, inbox)
        controller.send_proposal(proposal())
        inbox.add([callback(4, REJECT)], acknowledged={4})
        inbox.add([callback(5, EDIT)], set())
        assert controller.receive_offset() == 6
        controller.poll_once()
        assert transport.polls == []
        assert transport.answered == [("c5", "Aktion wird verarbeitet …")]
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["status"] == "rejected"
        assert inbox.pending() == [] and store.load("telegram-offset")["offset"] == 6


def test_dialog_inbox_drops_stale_and_invalid_updates_but_keeps_failed_ones(tmp_path, monkeypatch):
    with JsonStore(tmp_path) as store:
        inbox = TelegramInbox(store)
        controller, transport = dialog(store, inbox)
        store.save("telegram-offset", {"offset": 10})
        inbox.add([callback(3, "relevance:aaaaaaaaaaaaaaaaaaaaaaaa:1:relevant"),
                   {"update_id": 11, "message": {"unexpected": True}}], set())
        controller.poll_once()
        # A replayed relevance answer is reported; a schema-invalid update is discarded.
        assert ("c3", "Diese Relevanzantwort wurde bereits verarbeitet.") in transport.answered
        assert any("syntaktisch ungültig" in text for _, text, _ in transport.sent)
        assert inbox.pending() == [] and store.load("telegram-offset")["offset"] == 12
        inbox.add([message(12)], set())
        monkeypatch.setattr(controller, "_handle", lambda update: (_ for _ in ()).throw(RuntimeError("down")))
        with pytest.raises(RuntimeError):
            controller.poll_once()
        assert ids(inbox) == [12] and store.load("telegram-offset")["offset"] == 12


def test_dialog_without_inbox_continues_after_processed_updates(tmp_path):
    with JsonStore(tmp_path) as store:
        controller, _ = dialog(store)
        store.save("telegram-offset", {"offset": 7})
        assert controller.receive_offset() == 7


class InboxDialog:
    """Dialog stand-in that records when inbox updates are processed."""

    def __init__(self, inbox, order, on_poll=None):
        self.inbox, self.order, self.on_poll = inbox, order, on_poll

    def receive_offset(self): return 5
    def awaiting_decision(self): return False
    def awaiting_relevance_decision(self): return False

    def poll_once(self, timeout=None):
        for entry in self.inbox.pending():
            self.order.append(("telegram", entry.update_id))
            self.inbox.remove(entry.update_id)
        if self.on_poll:
            self.on_poll()


def test_button_press_during_a_mail_batch_is_processed_before_the_next_mail(tmp_path):
    """Regression: input was only fetched after the whole mail batch, so a
    pressed button stayed unanswered for minutes and looked ignored."""
    mails = [FetchedMail("INBOX", 7, uid, b"synthetic") for uid in (1, 2)]
    order = []
    with JsonStore(tmp_path / "state") as store:
        inbox = TelegramInbox(store)
        orchestrator = Orch()
        analyse = orchestrator.process

        def process(mail):
            order.append(("mail", mail.uid))
            if mail.uid == 1:  # the user presses a button while mail 1 is analysed
                inbox.add([callback(9, REJECT)], {9})
            return analyse(mail)

        orchestrator.process = process
        service = app(tmp_path, Imap([(7, mails)]), AppTelegram([]), orchestrator)
        service.dialog = InboxDialog(inbox, order)
        service._receiver = SimpleNamespace(inbox=inbox, stop=lambda: None)
        service._poll_imap()
    assert order == [("mail", 1), ("telegram", 9), ("mail", 2)]


def test_input_arriving_while_idle_is_processed_at_once(tmp_path):
    """Regression: the idle wait between mail cycles did not look at Telegram."""
    order = []
    with JsonStore(tmp_path / "state") as store:
        inbox = TelegramInbox(store)
        service = app(tmp_path, Imap([]), AppTelegram([]), Orch())
        service.dialog = InboxDialog(inbox, order, on_poll=lambda: order and service.stop_event.set())
        service._receiver = SimpleNamespace(inbox=inbox, stop=lambda: None)
        arrival = threading.Timer(0.05, lambda: inbox.add([message(4)], set()))
        started = time.monotonic()
        arrival.start()
        service._idle(30)
        arrival.join()
        assert order == [("telegram", 4)] and time.monotonic() - started < 5
        # Without input the idle wait simply ends at its deadline.
        service.stop_event.clear()
        started = time.monotonic()
        service._idle(0.05)
        assert time.monotonic() - started < 5 and order == [("telegram", 4)]


def test_application_starts_and_stops_the_receiver_thread(tmp_path):
    with JsonStore(tmp_path / "state") as store:
        inbox = TelegramInbox(store)
        source = Source([], on_empty=lambda: time.sleep(0.01))
        service = app(tmp_path, Imap([]), source, Orch())
        service.dialog = InboxDialog(inbox, [])
        service._start_receiver()
        thread = service._receiver
        assert thread.is_alive() and thread.offset == 5
        service.stop()
        assert thread.stop_event.is_set() and service.orchestrator.stop_called
        service._stop_receiver()
        assert not thread.is_alive() and service._receiver is None
        service._stop_receiver()


def test_logger_writes_whole_lines_from_concurrent_threads(tmp_path):
    logger = JsonlLogger(tmp_path, file_max_bytes=2_000, file_backup_count=50, console_enabled=True,
                         console=__import__("io").StringIO())

    def write(name):
        for index in range(100):
            logger.event("INFO", "telegram", "concurrent", thread=name, index=index)

    threads = [threading.Thread(target=write, args=(name,)) for name in "ab"]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    lines = [line for path in tmp_path.glob("application.jsonl*")
             for line in path.read_text(encoding="utf-8").splitlines()]
    assert sorted((json.loads(line)["thread"], json.loads(line)["index"]) for line in lines) == sorted(
        (name, index) for name in "ab" for index in range(100))



NOT_MODIFIED = ("Bad Request: message is not modified: specified new message content and reply "
                "markup are exactly the same as a current content and reply markup of the message")


def test_removing_an_already_removed_keyboard_is_success(tmp_path):
    responses = [httpx.Response(400, json={"ok": False, "error_code": 400, "description": NOT_MODIFIED}),
                 httpx.Response(400, json={"ok": False, "error_code": 400, "description": "Bad Request: chat not found"})]
    log = Logger()
    client = TelegramClient("secret", 1, httpx.MockTransport(lambda request: responses.pop(0)), logger=log)
    client.remove_inline_keyboard(2, 7)
    assert events(log) == ["inline_keyboard_already_removed"]
    with pytest.raises(PermanentError):
        client.remove_inline_keyboard(2, 7)
    client.close()


class FloodTelegram(Telegram):
    """Telegram stand-in whose keyboard removal fails like the real API did."""

    def __init__(self, failure):
        super().__init__()
        self.failure = failure

    def remove_inline_keyboard(self, chat_id, message_id):
        if self.removed:
            raise self.failure
        super().remove_inline_keyboard(chat_id, message_id)


def clarification_prompts(transport):
    return [text for _, text, _ in transport.sent if text.startswith("Rückfrage zu")]


@pytest.mark.parametrize("failure,notice", [
    (None, "Änderungsmodus läuft bereits"),
    # Even if removing the keyboard fails permanently, the press is not repeated.
    (PermanentError("Telegram editMessageReplyMarkup: message is not modified"), "wurde verworfen"),
])
def test_repeated_manual_review_press_sends_the_question_once(tmp_path, failure, notice):
    """Regression: a second "Manuell prüfen" press failed on the already removed
    keyboard, stayed in the inbox and resent the question before every mail."""
    with JsonStore(tmp_path) as store:
        inbox = TelegramInbox(store)
        transport = FloodTelegram(failure) if failure else Telegram()
        controller = TelegramDialogController(store, transport, 1, 2, Logger(), None, False, "UTC",
                                              RevisionService(), inbox=inbox)
        controller.send_proposal(proposal(open_questions=["Wann?"]))
        inbox.add([callback(1, EDIT), callback(2, EDIT)], acknowledged={1, 2})
        for _ in range(5):  # the main thread processes the inbox before every mail
            controller.poll_once()
        assert len(clarification_prompts(transport)) == 1
        assert any(notice in text for _, text, _ in transport.sent)
        assert inbox.pending() == [] and store.load("telegram-offset")["offset"] == 3


def test_a_permanently_failing_update_is_dropped_once_with_a_notice(tmp_path, monkeypatch):
    with JsonStore(tmp_path) as store:
        inbox = TelegramInbox(store)
        controller, transport = dialog(store, inbox)
        inbox.add([message(4), message(5)], set())
        handled = []

        def handle(update):
            handled.append(update.update_id)
            if update.update_id == 4:
                raise PermanentError("synthetic permanent failure")

        monkeypatch.setattr(controller, "_handle", handle)
        controller.poll_once()
        assert handled == [4, 5] and inbox.pending() == []
        assert sum("wurde verworfen" in text for _, text, _ in transport.sent) == 1


def test_transient_failures_are_retried_with_backoff_then_dropped(tmp_path, monkeypatch):
    clock = [1_000.0]
    monkeypatch.setattr("mailhelp.telegram.dialog.time.time", lambda: clock[0])
    monkeypatch.setattr("mailhelp.telegram.receiver.time.time", lambda: clock[0])
    with JsonStore(tmp_path) as store:
        inbox = TelegramInbox(store)
        controller, transport = dialog(store, inbox)
        inbox.add([message(4), message(5)], set())
        handled = []

        def handle(update):
            handled.append(update.update_id)
            if update.update_id == 4:
                raise RuntimeError("synthetic network failure")

        monkeypatch.setattr(controller, "_handle", handle)
        with pytest.raises(RuntimeError):
            controller.poll_once()
        assert [(entry.update_id, entry.attempts, entry.not_before) for entry in inbox.pending()] == [
            (4, 1, 1_030.0), (5, 0, None)]
        # Before the retry time nothing is processed, and later input keeps its place.
        controller.poll_once()
        assert handled == [4]
        clock[0] = 1_030.0
        with pytest.raises(RuntimeError):
            controller.poll_once()
        assert inbox.pending()[0].not_before == 1_090.0
        clock[0] = 1_090.0
        controller.poll_once()  # third failure: dropped with a notice, then 5 follows
        assert handled == [4, 4, 4, 5] and inbox.pending() == []
        assert sum("wurde verworfen" in text for _, text, _ in transport.sent) == 1
