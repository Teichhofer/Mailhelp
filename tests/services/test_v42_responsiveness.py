"""Web commands must not queue behind Telegram I/O or maintenance work."""
from threading import Event, Thread

from mailhelp.review.inbox import CommandInbox
from mailhelp.storage import JsonStore
from tests.fakes.factories import build_proposal
from tests.fakes.shared_review import command, setup, web


def test_a_web_command_finishes_while_telegram_delivery_is_still_blocked(tmp_path):
    with JsonStore(tmp_path) as store:
        dialog, telegram, _ = setup(store, build_proposal())
        web(dialog)
        dialog.commands = CommandInbox(store)
        sending, release, finished = Event(), Event(), Event()
        original = telegram.send
        def send(*args, **kwargs):
            sending.set()
            assert release.wait(10)
            original(*args, **kwargs)
        telegram.send = send
        sender = Thread(target=dialog.send, args=(2, "synthetic notification"))
        sender.start()
        operator = None
        try:
            assert sending.wait(5)
            entry, _ = dialog.commands.submit(command("reject"))
            dialog.outbox.background = lambda reference: "synthetic"
            def operate():
                dialog.poll_once()
                finished.set()
            operator = Thread(target=operate)
            operator.start()
            assert finished.wait(0.9), "Web command waited for blocked Telegram delivery"
            assert dialog.commands.get(entry.id).result.message == "Vorschlag verworfen."
            assert sender.is_alive() and not release.is_set()
        finally:
            release.set()
            sender.join(10)
            if operator is not None:
                operator.join(10)
        assert not sender.is_alive()


def test_queued_web_commands_precede_write_and_revision_resumption(tmp_path, monkeypatch):
    with JsonStore(tmp_path) as store:
        dialog, _, _ = setup(store, build_proposal())
        web(dialog)
        dialog.commands = CommandInbox(store)
        dialog.outbox.background = lambda reference: "synthetic"
        dialog.commands.submit(command("reject"))
        order = []
        execute = dialog.review.execute
        def review(item):
            order.append("command")
            return execute(item)
        monkeypatch.setattr(dialog.review, "execute", review)
        monkeypatch.setattr(dialog.write_executor, "resume", lambda: order.append("writes"))
        monkeypatch.setattr(dialog.revisions, "resume", lambda: order.append("revisions"))
        dialog.poll_once()
        assert order == ["command", "writes", "revisions"]


def test_enqueue_during_an_in_flight_send_preserves_order_and_does_not_duplicate(tmp_path):
    with JsonStore(tmp_path) as store:
        dialog, telegram, _ = setup(store, build_proposal())
        entered, release = Event(), Event()
        sent = []
        def send(chat, text, markup=None):
            if text == "first":
                entered.set()
                assert release.wait(10)
            sent.append(text)
        telegram.send = send
        sender = Thread(target=dialog.send, args=(2, "first"))
        sender.start()
        try:
            assert entered.wait(5)
            dialog.send(2, "second")
            assert [entry.text for entry in dialog.outbox.load().entries] == ["first", "second"]
            assert sent == []
        finally:
            release.set()
            sender.join(10)
        assert sent == ["first", "second"] and dialog.outbox.held_count() == 0


def test_the_delivery_port_flushes_a_proposal_by_default(tmp_path):
    with JsonStore(tmp_path) as store:
        item = build_proposal()
        dialog, telegram, _ = setup(store, item)
        assert dialog.delivery.enqueue(item) is not None
        assert len(telegram.sent) == 1 and telegram.sent[0][2]["inline_keyboard"]
        assert dialog.outbox.held_count() == 0
