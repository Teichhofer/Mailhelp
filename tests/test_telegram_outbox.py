"""Telegram outbox: hold notifications behind an open question, then send in order."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from mailhelp.config import TelegramSettings
from mailhelp.models import (
    MailState, Proposal, ProposalClarificationState, ProposalNotification,
    ProposalStatus, RelevanceDialogStatus,
    RelevanceDialog, TelegramOutboxEntry, TelegramOutboxGate, TelegramOutboxState,
)
from mailhelp.storage import JsonStore
from mailhelp.telegram import ProposalDeliveryService
from mailhelp.telegram.persistence import clarification_name, proposal_name
from test_telegram_dialog import (
    RevisionService, Telegram, callback, controller, message, proposal,
)
from mailhelp.telegram import TelegramDialogController

A, B, C, D = "a" * 24, "b" * 24, "c" * 24, "d" * 24


def item(mail_id, title, questions=(), **changes):
    return proposal(source_mail_id=mail_id, title=title,
                    open_questions=list(questions), **changes)


def stored(store, value, status="pending", relevance=None):
    """Persist a mail projection whose proposal notification is tracked."""
    state = MailState(
        id=value.source_mail_id, config_fingerprint="f" * 64,
        imap={"account_id": "0" * 24, "folder": "INBOX", "uidvalidity": 1,
              "uid": int(value.source_mail_id[0], 16)},
        proposals=[value],
        proposal_notifications=[ProposalNotification(
            proposal_id=value.id, proposal_version=value.version, status=status)],
        awaiting_relevance=relevance is not None and relevance.status == "open",
        relevance_dialog=relevance,
    )
    store.save(f"mail-{value.source_mail_id}", state.model_dump(mode="json"))


def texts(transport):
    return [text for _, text, _ in transport.sent]


def shown(transport, title):
    return any(title in text for text in texts(transport))


def notification(store, mail_id):
    return store.load_model(f"mail-{mail_id}", MailState).proposal_notifications[0].status


def outbox(store):
    return store.load_model("telegram-outbox", TelegramOutboxState)


def test_later_notifications_wait_until_the_question_is_clarified(tmp_path):
    """Regression: a new message must not follow an unanswered question."""
    with JsonStore(tmp_path) as store:
        c, t, _ = controller(store)
        first = item(A, "Frage A", ["Welches Datum?"])
        second = item(B, "Aufgabe B")
        third = item(C, "Frage C", ["Welcher Ort?"])
        fourth = item(D, "Aufgabe D")
        for value in (first, second, third, fourth):
            stored(store, value)
        c.send_proposal(first)
        c.send_proposal(second)
        c.send(2, "Zusammenfassung zu Mail C")
        c.send_proposal(third)
        c.send_proposal(fourth)

        assert shown(t, "Frage A") and not shown(t, "Aufgabe B")
        assert not shown(t, "Zusammenfassung zu Mail C")
        assert [entry.kind for entry in outbox(store).entries] == [
            "proposal", "message", "proposal", "proposal"]
        assert notification(store, A) == "completed"
        assert notification(store, B) == "queued"

        # "Klären" and its answer are direct replies and are never held back.
        t.updates = [callback(1, f"proposal:{A}:p1:1:edit")]
        c.poll_once()
        assert "Welches Datum?" in texts(t)[-2] and not shown(t, "Aufgabe B")
        t.updates = [message(2, "Am 21.10.2026")]
        c.poll_once()

        sent = texts(t)
        revised = max(i for i, text in enumerate(sent) if "Frage A" in text)
        order = [next(i for i, text in enumerate(sent) if title in text)
                 for title in ("Aufgabe B", "Zusammenfassung zu Mail C", "Frage C")]
        assert revised < order[0] < order[1] < order[2]
        assert not shown(t, "Aufgabe D")
        assert notification(store, B) == "completed"
        assert outbox(store).active.mail_id == C
        assert [entry.mail_id for entry in outbox(store).entries] == [D]


def test_rejecting_the_question_releases_the_next_message(tmp_path):
    with JsonStore(tmp_path) as store:
        c, t, _ = controller(store)
        first, second = item(A, "Frage A", ["Wann?"]), item(B, "Aufgabe B")
        stored(store, first), stored(store, second)
        c.send_proposal(first)
        c.send_proposal(second)
        assert not shown(t, "Aufgabe B")
        t.updates = [callback(1, f"proposal:{A}:p1:1:reject")]
        c.poll_once()
        assert shown(t, "Aufgabe B")
        assert outbox(store) == TelegramOutboxState()


def test_still_open_after_revision_keeps_holding(tmp_path):
    with JsonStore(tmp_path) as store:
        c, t, _ = controller(store)
        first = item(A, "Frage A", ["Datum?", "Ort?"])
        stored(store, first), stored(store, item(B, "Aufgabe B"))
        c.send_proposal(first)
        c.send_proposal(item(B, "Aufgabe B"))
        t.updates = [callback(1, f"proposal:{A}:p1:1:edit"), message(2, "Morgen")]
        c.poll_once()
        assert store.load_model(proposal_name(A, "p1"), Proposal).version == 2
        assert not shown(t, "Aufgabe B")


def test_proposals_without_questions_are_sent_without_holding(tmp_path):
    with JsonStore(tmp_path) as store:
        c, t, _ = controller(store)
        for mail_id, title in ((A, "Aufgabe A"), (B, "Aufgabe B")):
            value = item(mail_id, title)
            stored(store, value)
            c.send_proposal(value)
        assert shown(t, "Aufgabe A") and shown(t, "Aufgabe B")
        assert outbox(store) == TelegramOutboxState()


def test_disabled_setting_sends_immediately(tmp_path):
    assert TelegramSettings(user_id=1, chat_id=2).sequential_questions is True
    with JsonStore(tmp_path) as store:
        c = TelegramDialogController(store, Telegram(), 1, 2, _Log(), None, False,
                                     "UTC", RevisionService(),
                                     sequential_questions=False)
        first, second = item(A, "Frage A", ["Wann?"]), item(B, "Aufgabe B")
        c.send_proposal(first)
        c.send_proposal(second)
        assert shown(c.telegram, "Frage A") and shown(c.telegram, "Aufgabe B")


class _Log:
    def __init__(self): self.events = []
    def event(self, *args, **fields): self.events.append((args, fields))


def test_relevance_question_holds_and_decided_queued_one_is_skipped(tmp_path):
    with JsonStore(tmp_path) as store:
        c, t, log = controller(store)
        dialog = RelevanceDialog(mail_id=A)
        stored(store, item(A, "x"), status="completed", relevance=dialog)
        other = RelevanceDialog(mail_id=B)
        stored(store, item(B, "y"), status="completed", relevance=other)
        c.send_relevance(dialog, "Absender A", "Betreff A")
        c.send(2, "Info danach")
        c.send_relevance(other, "Absender B", "Betreff B")
        assert shown(t, "Betreff A") and not shown(t, "Info danach")

        # Mail B is answered by other means while still queued.
        decided = other.model_copy(update={
            "status": RelevanceDialogStatus.DECIDED, "decision": "irrelevant", "telegram_offset": 9})
        stored(store, item(B, "y"), status="completed", relevance=decided)
        c.flush_outbox()
        assert not shown(t, "Info danach")
        resolved = dialog.model_copy(update={
            "status": RelevanceDialogStatus.DECIDED, "decision": "relevant", "telegram_offset": 8})
        stored(store, item(A, "x"), status="completed", relevance=resolved)
        c.flush_outbox()
        assert shown(t, "Info danach") and not shown(t, "Betreff B")
        assert any(event[0][2] == "outbox_skipped_obsolete" for event in log.events)
        assert outbox(store) == TelegramOutboxState()


def test_obsolete_queued_proposals_are_skipped(tmp_path):
    with JsonStore(tmp_path) as store:
        c, t, _ = controller(store)
        gate = item(A, "Frage A", ["Wann?"])
        stored(store, gate)
        c.send_proposal(gate)
        rejected, revised, done, missing = (
            item(B, "Verworfen B"), item(C, "Alt C"), item(D, "Fertig D"),
            item("e" * 24, "Fehlt E"))
        for value in (rejected, revised, done):
            stored(store, value)
            c.send_proposal(value)
        c.outbox.enqueue_proposal(missing)
        store.save(proposal_name(B, "p1"), rejected.model_copy(
            update={"status": ProposalStatus.REJECTED}).model_dump(mode="json"))
        store.save(proposal_name(C, "p1"), revised.model_copy(
            update={"version": 2}).model_dump(mode="json"))
        state = store.load_model(f"mail-{D}", MailState)
        state.proposal_notifications[0].status = "completed"
        store.save(f"mail-{D}", state.model_dump(mode="json"))
        store.save(proposal_name(A, "p1"), gate.model_copy(
            update={"status": ProposalStatus.REJECTED}).model_dump(mode="json"))
        before = len(t.sent)
        c.flush_outbox()
        assert len(t.sent) == before
        assert outbox(store) == TelegramOutboxState()


def test_untracked_legacy_proposal_is_sent_without_status_marks(tmp_path):
    with JsonStore(tmp_path) as store:
        c, t, _ = controller(store)
        c.send_proposal(item(A, "Frage A", ["Wann?"]))
        c.send_proposal(item(B, "Aufgabe B"))
        assert shown(t, "Frage A") and not shown(t, "Aufgabe B")
        c.send_proposal(item(B, "Aufgabe B"))  # idempotent while queued
        assert len(outbox(store).entries) == 1
        store.save(proposal_name(A, "p1"), item(A, "Frage A", ["Wann?"], status="rejected")
                   .model_dump(mode="json"))
        c.flush_outbox()
        assert shown(t, "Aufgabe B")


def test_paused_revision_does_not_hold_messages(tmp_path):
    with JsonStore(tmp_path) as store:
        c, t, _ = controller(store)
        gate = item(A, "Frage A", ["Wann?"])
        stored(store, gate)
        c.send_proposal(gate)
        c.send(2, "Info")
        assert not shown(t, "Info")
        store.save(clarification_name(A, "p1", 1), ProposalClarificationState(
            mail_id=A, proposal_id="p1", version=1, question="Wann?",
            authorized_answer="Morgen", normalized_answer="Morgen", answer_status="valid",
            question_status="answered", proposal_revision_status="paused",
        ).model_dump(mode="json"))
        c.flush_outbox()
        assert shown(t, "Info")


def test_interrupted_send_is_not_repeated_after_restart(tmp_path):
    with JsonStore(tmp_path) as store:
        entry = TelegramOutboxEntry(id="1" * 32, kind="message", text="Unklar",
                                    status="sending",
                                    created_at=datetime.now(timezone.utc))
        waiting = TelegramOutboxEntry(id="2" * 32, kind="message", text="Danach",
                                      created_at=datetime.now(timezone.utc))
        store.save("telegram-outbox", TelegramOutboxState(
            entries=[entry, waiting]).model_dump(mode="json"))
        c, t, log = controller(store)
        c.flush_outbox()
        assert texts(t) == ["Danach"]
        assert any(event[0][2] == "outbox_delivery_uncertain" for event in log.events)


class _FailingTelegram(Telegram):
    def __init__(self, failing):
        super().__init__(); self.failing = failing
    def send(self, chat, text, reply_markup=None):
        if text in self.failing:
            raise RuntimeError("synthetic transport failure")
        super().send(chat, text, reply_markup)


def test_send_failure_is_raised_only_to_the_enqueuing_caller(tmp_path):
    with JsonStore(tmp_path) as store:
        t = _FailingTelegram({"Eigene"})
        c = TelegramDialogController(store, t, 1, 2, _Log(), None, False, "UTC",
                                     RevisionService())
        with pytest.raises(RuntimeError, match="synthetic"):
            c.send(2, "Eigene")
        assert outbox(store) == TelegramOutboxState()

        gate = item(A, "Frage A", ["Wann?"])
        c.send_proposal(gate)
        c.send(2, "Fremd")
        c.send(2, "Später")
        t.failing = {"Fremd"}
        store.save(proposal_name(A, "p1"), gate.model_copy(
            update={"status": ProposalStatus.REJECTED}).model_dump(mode="json"))
        c.send(2, "Neu")  # another caller: failure is logged, not raised
        assert not shown(t, "Später")
        assert [entry.text for entry in outbox(store).entries] == ["Später", "Neu"]
        assert any(event[0][2] == "outbox_delivery_failed" for event in c.logger.events)
        c.flush_outbox()
        assert texts(t)[-2:] == ["Später", "Neu"]


def test_status_lists_held_messages_and_open_shows_only_sent_proposals(tmp_path):
    with JsonStore(tmp_path) as store:
        c, t, _ = controller(store)
        gate, waiting = item(A, "Frage A", ["Wann?"]), item(B, "Aufgabe B")
        stored(store, gate), stored(store, waiting)
        c.send_proposal(gate)
        c.send_proposal(waiting)
        t.updates = [message(1, "/status")]
        c.poll_once()
        assert "„Aufgabe B“ · Version 1: Noch nicht gesendet" in texts(t)[-1]
        assert "Zurückgehaltene Nachrichten bis zur Erledigung der aktuellen Rückfrage: 1" in texts(t)[-1]
        before = len(t.sent)
        t.updates = [message(2, "/offen")]
        c.poll_once()
        presented = texts(t)[before + 1:]  # after the overview text
        assert any("Frage A" in text for text in presented)
        assert not any("Aufgabe B" in text for text in presented)


def test_delivery_service_without_outbox_and_already_delivered_versions(tmp_path):
    with JsonStore(tmp_path) as store:
        c, t, _ = controller(store)
        standalone = ProposalDeliveryService(c.repository, c.presenter, t, 2)
        standalone.enqueue(item(A, "Direkt A"))
        assert shown(t, "Direkt A")
        done, queued = item(B, "Fertig B"), item(C, "Wartend C")
        stored(store, done, status="completed")
        stored(store, queued, status="queued")
        c.delivery.enqueue(done)
        c.delivery.deliver(queued)
        assert not shown(t, "Fertig B") and not shown(t, "Wartend C")
        assert outbox(store) is None


def test_outbox_models_reject_incomplete_references():
    now = datetime.now(timezone.utc)
    with pytest.raises(ValidationError, match="Unvollständiger Verweis"):
        TelegramOutboxEntry(id="1" * 32, kind="proposal", mail_id=A, created_at=now)
    with pytest.raises(ValidationError, match="Zeitzone"):
        TelegramOutboxEntry(id="1" * 32, kind="message", text="x",
                            created_at=datetime(2026, 10, 7))
    with pytest.raises(ValidationError, match="Vorschlags-ID"):
        TelegramOutboxGate(kind="relevance", mail_id=A, proposal_id="p1", version=1)
    with pytest.raises(ValidationError, match="Vorschlags-ID"):
        TelegramOutboxGate(kind="proposal", mail_id=A, version=1)


def test_queue_survives_restart_and_ignores_unauthorized_answers(tmp_path):
    with JsonStore(tmp_path) as store:
        c, t, _ = controller(store)
        gate, waiting = item(A, "Frage A", ["Wann?"]), item(B, "Aufgabe B")
        stored(store, gate), stored(store, waiting)
        c.send_proposal(gate)
        c.send_proposal(waiting)
    with JsonStore(tmp_path) as store:
        restarted, t2, _ = controller(store)
        restarted.flush_outbox()
        t2.updates = [callback(1, f"proposal:{A}:p1:1:reject", user=9)]
        restarted.poll_once()
        assert not shown(t2, "Aufgabe B")
        t2.updates = [callback(2, f"proposal:{A}:p1:1:reject")]
        restarted.poll_once()
        assert shown(t2, "Aufgabe B")
        assert notification(store, B) == "completed"
        restarted.flush_outbox()
        assert sum("Aufgabe B" in text for text in texts(t2)) == 1
