"""Telegram answers to open questions: interpretation, failures and restart recovery."""
from __future__ import annotations

import httpx
import pytest
from pydantic import ValidationError

from mailhelp.config import OutputTokenRetry
from mailhelp.domain.processing import (
    AnswerStatus,
    ProposalClarificationState,
    ProposalRevisionStatus,
    QuestionStatus,
    TelegramDialogState,
)
from mailhelp.domain.revision_errors import ContradictoryRevision
from mailhelp.llm.openrouter import ProviderResponseInvalid
from mailhelp.persistence.storage import JsonStore
from mailhelp.processing.analysis import (
    Analyzer,
    LlmInvalidJson,
    LlmProviderResponseInvalid,
    LlmSchemaValidationFailed,
    LlmTokenLimitExceeded,
)
from mailhelp.telegram import (
    TelegramDialogController,
)
from tests.fakes.log_fakes import RecordingLogger as Logger
from tests.fakes.shared_core import prompt_config
from tests.fakes.shared_telegram_dialog import (
    FailingRevisionService,
    InterpretationErrorService,
    RevisionService,
    Telegram,
    UnusableAnswerService,
    Writer,
    callback,
    controller,
    message,
    proposal,
)
from tests.fakes.shared_telegram_dialog import (
    OperationallyFailingRevisionService as OperationallyFailingRevisionService,
)


def test_same_llm_id_from_two_mails_survives_restart_and_writes_separately(tmp_path):
    first_mail, second_mail = "a" * 24, "b" * 24
    first_writer, second_writer = Writer(), Writer()
    with JsonStore(tmp_path) as store:
        c,t,_=controller(store, writers={"todoist":first_writer})
        c.persist(proposal(source_mail_id=first_mail))
        c.persist(proposal(source_mail_id=second_mail))
        assert store.load(f"proposal-{first_mail}-p1")["source_mail_id"] == first_mail
        assert store.load(f"proposal-{second_mail}-p1")["source_mail_id"] == second_mail
        t.updates=[callback(1,f"proposal:{first_mail}:p1:1:confirm")]
        c.poll_once()
        assert first_writer.created == 1

        restarted,t2,_=controller(store,[callback(2,f"proposal:{second_mail}:p1:1:confirm")],
                                  {"todoist":second_writer})
        restarted.poll_once()
        assert second_writer.created == 0
        repeat_message = next(message for message in t2.sent if message[2] is not None)
        repeat_data = repeat_message[2]["inline_keyboard"][0][0]["callback_data"]
        t2.updates = [callback(3, repeat_data)]
        restarted.poll_once()
        assert second_writer.created == 1
        assert store.load(f"proposal-{first_mail}-p1")["external_id"] == "external-1"
        assert store.load(f"proposal-{second_mail}-p1")["external_id"] == "external-1"

        # A fresh Telegram update cannot execute the already-created first proposal again.
        t2.updates=[callback(4,f"proposal:{first_mail}:p1:1:confirm")]
        restarted.poll_once()
        assert first_writer.created == 1 and second_writer.created == 1
        assert "Schaltfläche ist veraltet" in t2.sent[-1][1]

def test_edit_question_answer_new_version_then_reject(tmp_path):
    with JsonStore(tmp_path) as store:
        c,t,_=controller(store)
        c.send_proposal(proposal(open_questions=["Wann?", "Wo?"]))
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["status"]=="needs_clarification"
        labels=[button["text"] for button in t.sent[-1][2]["inline_keyboard"][0]]
        assert labels == ["Klären", "Verwerfen"] and "Bestätigen" not in labels
        t.updates=[callback(1,"proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:1:confirm"), callback(2,"proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:1:edit")]
        c.poll_once()
        assert any("konnte nicht verarbeitet" in text for _, text, _ in t.sent)
        assert store.load("telegram-dialog")["proposal_id"]=="p1"
        t.updates=[message(3,"Morgen")]
        c.poll_once()
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v2")["open_questions"]==["Wo?"]
        # Select edit and answer the remaining question, producing a confirmable v3.
        t.updates=[callback(4,"proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:2:edit"),message(5,"Berlin")]
        c.poll_once()
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["version"]==3 and store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["status"]=="pending_confirmation"
        t.updates=[callback(6,"proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:3:reject")]
        c.poll_once()
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["status"]=="rejected"
        assert "verworfen" in t.sent[-1][1]


def test_non_binding_question_accepts_no_as_rejection_without_llm(tmp_path):
    class LlmMustNotRun(RevisionService):
        def interpret_telegram_answer(self, item, question, answer):
            raise AssertionError("Eine eindeutige Ablehnung darf keinen LLM-Aufruf auslösen")

    with JsonStore(tmp_path) as store:
        c, t, log = controller(store, revision_service=LlmMustNotRun())
        c.send_proposal(proposal(
            classification="non_binding",
            open_questions=[
                "Soll der nicht bindende Hinweis dennoch als neuer Eintrag angelegt werden?"
            ],
        ))
        edit = t.sent[-1][2]["inline_keyboard"][0][0]["callback_data"]
        t.updates = [callback(1, edit), message(2, "  NEIN!  ")]

        c.poll_once()

        saved = store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")
        clarification = store.load("clarification-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v1")
        assert saved["status"] == "rejected"
        assert clarification["answer_status"] == "valid"
        assert clarification["normalized_answer"] == "Nein"
        assert clarification["proposal_revision_status"] == "completed"
        assert store.load("telegram-dialog")["proposal_id"] is None
        assert "verworfen" in t.sent[-1][1]
        assert any(event[0][2] == "proposal_rejected_by_clarification" for event in log.events)


def test_non_binding_question_accepts_yes_as_separate_persisted_decision(tmp_path):
    class LlmMustNotRun(RevisionService):
        def interpret_telegram_answer(self, item, question, answer):
            raise AssertionError("Eine eindeutige Zustimmung darf keinen LLM-Aufruf auslösen")

        def revise_proposal(self, item, question, answer):
            raise AssertionError("Die eindeutige Zustimmung wird deterministisch revidiert")

    with JsonStore(tmp_path) as store:
        c, t, _ = controller(store, revision_service=LlmMustNotRun())
        question = "Soll der nicht bindende Hinweis dennoch als neuer Eintrag angelegt werden?"
        c.send_proposal(proposal(
            classification="non_binding", open_questions=[question],
        ))
        edit = t.sent[-1][2]["inline_keyboard"][0][0]["callback_data"]
        t.updates = [callback(1, edit), message(2, "  JA!  ")]

        c.poll_once()

        saved = store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")
        assert saved["version"] == 2
        assert saved["classification"] == "non_binding"
        assert saved["explicit_non_binding_create_confirmed"] is True
        assert saved["open_questions"] == []
        assert saved["status"] == "pending_confirmation"
        assert "❓ Offen" not in t.sent[-1][1]
        assert question not in t.sent[-1][1].split("\n\n")[-1]


def test_invalid_unauthorized_missing_and_stale_dialogs(tmp_path):
    with JsonStore(tmp_path) as store:
        bad=[{"not":"an update"}, {"update_id":1,"message":{"private":"do not log"}}, message(2,user=9), message(3,chat=9), callback(4,"bad"), callback(5,"proposal:aaaaaaaaaaaaaaaaaaaaaaaa:missing:1:confirm"), callback(6,"proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:1:confirm",user=9)]
        c,t,log=controller(store,bad)
        c.poll_once()
        assert store.load("telegram-offset")["offset"]==7
        assert any("syntaktisch" in item[1] for item in t.sent)
        assert any("Nicht autorisierte" in text for _,text,_ in t.sent)
        assert "private" not in repr(log.events)

        c.persist(proposal(version=2))
        store.save("telegram-dialog",{"mail_id":"a"*24,"proposal_id":"p1","version":1})
        t.updates=[message(7)]
        c.poll_once()
        assert "veraltet" in t.sent[-1][1]
        store.save("telegram-dialog",{"mail_id":"a"*24,"proposal_id":"gone","version":1})
        t.updates=[message(8)]
        c.poll_once()
        assert "nicht gefunden" in t.sent[-1][1]
        t.updates=[message(9)]
        c.poll_once()
        assert "Keine offene" in t.sent[-1][1]

        c.revisions.revision_service=FailingRevisionService()
        c.persist(proposal(version=2, description="x"*3995, status="needs_clarification"))
        store.save("telegram-dialog",{"mail_id":"a"*24,"proposal_id":"p1","version":2})
        t.updates=[message(10,"zu lang")]
        c.poll_once()
        assert "gespeicherten Antwort" in t.sent[-1][1]
        assert store.load("telegram-dialog")["version"] is None
        saved = store.load("clarification-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v2")
        assert saved["normalized_answer"] == "zu lang"
        assert saved["proposal_revision_status"] == "retry_required"


def test_unusable_answer_gets_llm_generated_concrete_follow_up(tmp_path):
    service = UnusableAnswerService()
    with JsonStore(tmp_path) as store:
        current = proposal(version=2, open_questions=["Welches Datum?"])
        c,t,log = controller(store, revision_service=service)
        c.persist(current)
        store.save("telegram-dialog", TelegramDialogState(
            mail_id=current.source_mail_id, proposal_id=current.id, version=2).model_dump())
        c.revisions.answer("irgendwann")
        assert "Bitte konkreter beantworten: Welches Datum?" in t.sent[-1][1]
        assert t.sent[-1][1].startswith("❓ ") and "„Aufgabe“ · /abbrechen" in t.sent[-1][1]
        assert [call[0] for call in service.calls] == ["interpret", "clarify"]
        assert store.load("telegram-dialog")["version"] == 2
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["version"] == 2
        saved = store.load("clarification-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v2")
        assert saved["answer_status"] == "invalid"
        assert saved["proposal_revision_status"] == "pending"
        event = next(entry for entry in log.events
                     if entry[0][2] == "answer_clarification_requested")
        assert event[1]["error_class"] == "IncompleteUserAnswer"


@pytest.mark.parametrize(("error", "error_class"), [
    (LlmTokenLimitExceeded("telegram_answer_interpretation", "output_token_limit"),
     "LlmTokenLimitExceeded"),
    (LlmInvalidJson("telegram_answer_interpretation"), "LlmInvalidJson"),
    (LlmSchemaValidationFailed("telegram_answer_interpretation"),
     "LlmSchemaValidationFailed"),
    (LlmProviderResponseInvalid("telegram_answer_interpretation", "provider_unavailable"),
     "LlmProviderResponseInvalid"),
    (httpx.ReadTimeout("timeout"), "ReadTimeout"),
])
def test_technical_answer_errors_are_consumed_without_reasking(
        tmp_path, error, error_class):
    with JsonStore(tmp_path) as store:
        item = proposal(open_questions=["Welches Datum?"])
        c, transport, log = controller(
            store, [message(4, "vertrauliche Antwort")],
            revision_service=InterpretationErrorService(error))
        c.persist(item)
        store.save("telegram-dialog", TelegramDialogState(
            mail_id=item.source_mail_id, proposal_id=item.id,
            version=1).model_dump(mode="json"))

        c.poll_once()

        expected_message = (
            "Technischer Abbruch: Das Modell hat sein Ausgabetokenlimit erreicht. "
            "Die sicher gespeicherte Antwort wird mit der Ausweichstrategie erneut bewertet."
            if isinstance(error, LlmTokenLimitExceeded) else
            "Die interne Verarbeitung ist verzögert. "
            "Die sicher gespeicherte Antwort wird erneut bewertet.")
        assert transport.sent[-1][1] == expected_message
        assert "Welches Datum?" not in transport.sent[-1][1]
        assert store.load("telegram-offset")["offset"] == 5
        assert store.load("telegram-dialog")["proposal_id"] == "p1"
        saved = store.load("clarification-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v1")
        assert saved["answer_status"] == "pending"
        assert saved["authorized_answer"] == "vertrauliche Antwort"
        assert saved["interpretation_status"] == "retry_required"
        assert saved["interpretation_attempts"] == 1
        assert saved["next_interpretation_at"] is not None
        event = next(entry for entry in log.events
                     if entry[0][2] == "answer_revision_failed")
        assert event[1]["error_class"] == error_class
        assert event[1]["proposal_reference"] == "aaaaaaaaaaaaaaaaaaaaaaaa:p1:v1"
        assert event[1]["revision_status"] == "retry_required"
        assert "vertrauliche Antwort" not in repr(log.events)


def test_contradictory_answer_is_domain_failure_not_incomplete(tmp_path):
    with JsonStore(tmp_path) as store:
        item = proposal(open_questions=["Welches Datum?"])
        c, transport, log = controller(
            store, [message(2, "Antwort")],
            revision_service=InterpretationErrorService(
                ContradictoryRevision("synthetic-private-clock", "known_clock_changed")))
        c.persist(item)
        store.save("telegram-dialog", TelegramDialogState(
            mail_id=item.source_mail_id, proposal_id=item.id,
            version=1).model_dump(mode="json"))

        c.poll_once()

        assert "widerspricht" in transport.sent[-1][1]
        assert "Welches Datum?" not in transport.sent[-1][1]
        assert store.load("telegram-offset")["offset"] == 3
        saved = store.load("clarification-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v1")
        assert saved["answer_status"] == "pending"
        assert saved["authorized_answer"] == "Antwort"
        assert saved["interpretation_status"] == "retry_required"
        event = next(entry for entry in log.events
                     if entry[0][2] == "answer_revision_failed")
        assert event[1]["error_class"] == "ContradictoryRevision"
        assert event[1]["revision_contract"] == "known_clock_changed"
        assert "synthetic-private-clock" not in str(log.events)


def test_interpretation_timeout_is_resumed_from_persisted_answer_after_restart(tmp_path):
    directory = tmp_path / "restart-interpretation"
    secret = "streng vertrauliche Terminantwort"
    with JsonStore(directory) as store:
        item = proposal(open_questions=["Welches Datum?"])
        c, _, log = controller(store, [message(4, secret)],
                               revision_service=InterpretationErrorService(
                                   httpx.ReadTimeout(secret)))
        c.persist(item)
        store.save("telegram-dialog", TelegramDialogState(
            mail_id=item.source_mail_id, proposal_id=item.id,
            version=1).model_dump(mode="json"))
        c.poll_once()
        name = "clarification-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v1"
        saved = store.load(name)
        assert saved["authorized_answer"] == secret
        assert secret not in repr(log.events)
        saved["next_interpretation_at"] = None
        store.save(name, saved)

    with JsonStore(directory) as store:
        service = RevisionService()
        c, _, log = controller(store, revision_service=service)
        c.poll_once()
        assert [call[3] for call in service.calls if call[0] == "interpret"] == [secret]
        saved = store.load("clarification-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v1")
        assert saved["interpretation_status"] == "completed"
        assert saved["proposal_revision_status"] == "completed"
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["version"] == 2
        assert secret not in repr(log.events)


def test_interpretation_retry_budget_pauses_without_deleting_answer(tmp_path):
    secret = "private Antwort"
    with JsonStore(tmp_path) as store:
        item = proposal(open_questions=["Datum?"])
        service = InterpretationErrorService(httpx.ReadTimeout(secret))
        c, transport, log = controller(store, [message(1, secret)],
                                       revision_service=service)
        c.revisions.interpretation_attempts = 2
        c.persist(item)
        store.save("telegram-dialog", TelegramDialogState(
            mail_id=item.source_mail_id, proposal_id=item.id,
            version=1).model_dump(mode="json"))
        c.poll_once()
        name = "clarification-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v1"
        pending = store.load(name)
        pending["next_interpretation_at"] = None
        store.save(name, pending)
        c.poll_once()
        paused = store.load(name)
        assert paused["interpretation_attempts"] == 2
        assert paused["interpretation_status"] == "paused"
        assert paused["next_interpretation_at"] is None
        assert paused["authorized_answer"] == secret
        calls = len(service.calls)
        c.poll_once()
        assert len(service.calls) == calls
        assert "pausiert" in transport.sent[-1][1]
        assert secret not in repr(log.events)


def test_token_limit_fallback_parameters_persist_and_pause_after_restart(tmp_path):
    class TruncatedCompleter:
        def __init__(self):
            self.requests = []

        def complete(self, model, parameters, system, payload, **metadata):
            self.requests.append((parameters, system, payload, metadata))
            raise ProviderResponseInvalid("output_token_limit")

    cfg = prompt_config()
    step = cfg.prompts["telegram_answer_interpretation"]
    step.parameters = {"temperature": 0.0, "max_tokens": 500}
    step.output_token_retry = OutputTokenRetry(
        system_prompt="Nur usable, normalized_answer und reason.",
        parameters={"max_tokens": 180})
    completer = TruncatedCompleter()
    service = Analyzer(completer, cfg, provider_retries=3)
    directory = tmp_path / "token-limit-restart"
    secret = "am ersten Oktober"

    with JsonStore(directory) as store:
        item = proposal(open_questions=["Welches Datum?"])
        c, _, _ = controller(store, [message(1, secret)], revision_service=service)
        c.revisions.interpretation_attempts = 2
        c.persist(item)
        store.save("telegram-dialog", TelegramDialogState(
            mail_id=item.source_mail_id, proposal_id=item.id,
            version=1).model_dump(mode="json"))
        c.poll_once()
        saved = store.load("clarification-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v1")
        assert saved["interpretation_status"] == "retry_required"
        assert saved["authorized_answer"] == secret
        saved["next_interpretation_at"] = None
        store.save("clarification-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v1", saved)

    with JsonStore(directory) as store:
        c, transport, _ = controller(store, revision_service=service)
        c.revisions.interpretation_attempts = 2
        c.poll_once()
        paused = store.load("clarification-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v1")
        assert paused["interpretation_status"] == "paused"
        assert paused["authorized_answer"] == secret
        assert paused["next_interpretation_at"] is None
        assert "pausiert" in transport.sent[-1][1]

    assert len(completer.requests) == 4
    assert [request[0]["max_tokens"] for request in completer.requests] == [
        500, 500, 500, 500]
    assert [request[1] for request in completer.requests[1::2]] == [
        step.output_token_retry.system_prompt, step.output_token_retry.system_prompt]


def test_duplicate_delivery_does_not_reinterpret_persisted_answer(tmp_path):
    with JsonStore(tmp_path) as store:
        item = proposal(open_questions=["Datum?"])
        service = InterpretationErrorService(httpx.ReadTimeout("timeout"))
        c, transport, _ = controller(store, [message(3, "erste Antwort")],
                                     revision_service=service)
        c.persist(item)
        store.save("telegram-dialog", TelegramDialogState(
            mail_id=item.source_mail_id, proposal_id=item.id,
            version=1).model_dump(mode="json"))
        c.poll_once()
        transport.updates = [message(3, "erste Antwort")]
        store.save("telegram-offset", {"schema_version": 1, "offset": 3})
        c.poll_once()
        assert store.load("clarification-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v1")[
            "interpretation_attempts"] == 1
        assert "bereits sicher gespeichert" in transport.sent[-1][1]


def test_failed_answer_persistence_does_not_advance_offset_or_log_answer(tmp_path):
    secret = "darf niemals im Fehler stehen"
    class FailingStore(JsonStore):
        fail = True
        def save(self, name, value):
            if self.fail and name.startswith("clarification-"):
                raise OSError("Zustand konnte nicht gespeichert werden")
            super().save(name, value)

    with FailingStore(tmp_path) as store:
        item = proposal(open_questions=["Datum?"])
        c, _, log = controller(store, [message(9, secret)])
        c.persist(item)
        store.save("telegram-dialog", TelegramDialogState(
            mail_id=item.source_mail_id, proposal_id=item.id,
            version=1).model_dump(mode="json"))
        with pytest.raises(OSError, match="Zustand konnte nicht gespeichert"):
            c.poll_once()
        assert store.load("telegram-offset") is None
        assert secret not in repr(log.events)
        store.fail = False
        c.poll_once()
        assert store.load("telegram-offset")["offset"] == 10


def test_revision_unavailable_preserves_dialog(tmp_path):
    with JsonStore(tmp_path) as store:
        transport=Telegram([message(1,"Neuer Titel")])
        log=Logger()
        c=TelegramDialogController(store,transport,1,2,log)
        c.persist(proposal(status="needs_clarification"))
        store.save("telegram-dialog",{"mail_id":"a"*24,"proposal_id":"p1","version":1})
        c.poll_once()
        assert "nicht verfügbar" in transport.sent[-1][1]
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["version"]==1
        assert store.load("telegram-dialog")["proposal_id"]=="p1"


def test_operational_reply_failure_keeps_valid_answer_and_is_acknowledged(tmp_path):
    with JsonStore(tmp_path) as store:
        c,t,log=controller(store, [message(4, "Neuer Titel")],
                           revision_service=OperationallyFailingRevisionService())
        c.persist(proposal(status="needs_clarification"))
        store.save("telegram-dialog", {"mail_id":"a"*24,"proposal_id":"p1","version":1})
        c.poll_once()
        assert store.load("telegram-offset")["offset"] == 5
        assert store.load("telegram-dialog")["proposal_id"] is None
        saved = store.load("clarification-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v1")
        assert saved["normalized_answer"] == "Neuer Titel"
        assert saved["question_status"] == "answered"
        assert saved["answer_status"] == "valid"
        assert saved["proposal_revision_status"] == "retry_required"
        event = next(item for item in log.events if item[0][2] == "answer_revision_failed")
        assert event[1]["error_class"] == "TechnicalRevisionError"
        assert event[1]["revision_status"] == "retry_required"
        assert "provider unavailable" not in repr(event)


def test_answer_is_persisted_and_dialog_closed_before_revision(tmp_path):
    events = []
    class OrderedStore(JsonStore):
        def save(self, name, value):
            super().save(name, value)
            if name.startswith("clarification-"):
                events.append(("answer", value["normalized_answer"]))
            elif name == "telegram-dialog" and value["proposal_id"] is None:
                events.append(("dialog", None))
    class OrderedRevision(RevisionService):
        def revise_proposal(self, item, question, answer):
            assert events == [("answer", None), ("answer", "2026-10-21"),
                              ("dialog", None)]
            events.append(("revision", answer))
            return super().revise_proposal(item, question, answer)
        def interpret_telegram_answer(self, item, question, answer):
            return "interpret", type("Interpretation", (), {
                "usable": True, "normalized_answer": "2026-10-21", "reason": "ok"})()
    with OrderedStore(tmp_path) as store:
        item = proposal(open_questions=["Welches Datum?"])
        c,_,_=controller(store, revision_service=OrderedRevision())
        c.persist(item)
        store.save("telegram-dialog", TelegramDialogState(
            mail_id=item.source_mail_id, proposal_id=item.id, version=1).model_dump(mode="json"))
        events.clear()
        c.revisions.answer("am nächsten Mittwoch")
        assert events[:4] == [("answer", None), ("answer", "2026-10-21"),
                              ("dialog", None), ("revision", "2026-10-21")]
        assert store.load("clarification-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v1")["proposal_revision_status"] == "completed"


@pytest.mark.parametrize("error", [
    ValueError("schema"), RuntimeError("output_token_limit"),
    LlmInvalidJson("proposal_revision"),
])
def test_revision_failures_only_mark_revision_retry_required(tmp_path, error):
    class Failure(RevisionService):
        def revise_proposal(self, item, question, answer):
            raise error
    with JsonStore(tmp_path) as store:
        item=proposal(open_questions=["Welches Datum?"])
        c,_,_=controller(store, revision_service=Failure())
        c.persist(item)
        store.save("telegram-dialog", TelegramDialogState(
            mail_id=item.source_mail_id, proposal_id=item.id, version=1).model_dump(mode="json"))
        c.revisions.answer("2026-10-21")
        saved=store.load_model("clarification-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v1", ProposalClarificationState)
        assert (saved.question_status, saved.answer_status, saved.normalized_answer,
                saved.proposal_revision_status) == (
                    QuestionStatus.ANSWERED, AnswerStatus.VALID, "2026-10-21",
                    ProposalRevisionStatus.RETRY_REQUIRED)


def test_restart_retries_normalized_answer_and_ok_is_not_old_answer(tmp_path):
    class CrashAfterAnswer(JsonStore):
        crash = True
        def save(self, name, value):
            super().save(name, value)
            if self.crash and name == "telegram-dialog" and value["proposal_id"] is None:
                raise RuntimeError("simulated crash")
    directory=tmp_path/"restart"
    with CrashAfterAnswer(directory) as store:
        item=proposal(open_questions=["Welches Datum?"])
        c,_,_=controller(store)
        c.persist(item)
        store.save("telegram-dialog", TelegramDialogState(
            mail_id=item.source_mail_id, proposal_id=item.id, version=1).model_dump(mode="json"))
        with pytest.raises(RuntimeError, match="simulated crash"):
            c.revisions.answer("2026-10-21")
        assert store.load("clarification-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v1")["normalized_answer"] == "2026-10-21"
    with JsonStore(directory) as store:
        service=RevisionService()
        c,t,_=controller(store, [message(1, "Ok")], revision_service=service)
        c.poll_once()
        revision_calls=[call for call in service.calls if not isinstance(call[0], str)]
        assert revision_calls[0][2] == "2026-10-21"
        assert not any(call[0] == "interpret" and call[3] == "Ok" for call in service.calls)
        assert store.load("clarification-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v1")["normalized_answer"] == "2026-10-21"
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["version"] == 2
        assert "Keine offene" in t.sent[-1][1]


def test_clarification_schema_migration_and_validation(tmp_path):
    name="clarification-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v1"
    with JsonStore(tmp_path) as store:
        base={"schema_version":1, "mail_id":"a"*24, "proposal_id":"p1",
              "version":1, "question":"Welches Datum?"}
        store.save(name, {**base, "normalized_answer":"2026-10-21"})
        migrated=store.load_model(name, ProposalClarificationState)
        assert migrated.schema_version == 4 and migrated.answer_status == AnswerStatus.VALID
        assert store.load(name)["normalized_answer"] == "2026-10-21"
        store.save(name, base)
        open_state=store.load_model(name, ProposalClarificationState)
        assert open_state.question_status == QuestionStatus.OPEN
        assert open_state.answer_status == AnswerStatus.PENDING
    with pytest.raises(ValidationError, match="normalisierte Antwort"):
        ProposalClarificationState(mail_id="a"*24, proposal_id="p1", version=1,
                                   question="Datum?", normalized_answer="2026-10-21")
    with pytest.raises(ValidationError, match="offene Frage"):
        ProposalClarificationState(mail_id="a"*24, proposal_id="p1", version=1,
                                   question="Datum?", answer_status=AnswerStatus.INVALID,
                                   proposal_revision_status=ProposalRevisionStatus.RETRY_REQUIRED)
    with pytest.raises(ValidationError, match="UTC-Offset"):
        ProposalClarificationState(
            mail_id="a"*24, proposal_id="p1", version=1, question="Datum?",
            question_status="answered", answer_status="valid",
            normalized_answer="2026-10-21", proposal_revision_status="retry_required",
            next_revision_at="2026-09-22T12:00:00")
    with pytest.raises(ValidationError, match="Interpretationsversuche"):
        ProposalClarificationState(
            mail_id="a"*24, proposal_id="p1", version=1, question="Datum?",
            interpretation_attempts=1)
    with pytest.raises(ValidationError, match="Interpretationsstatus"):
        ProposalClarificationState(
            mail_id="a"*24, proposal_id="p1", version=1, question="Datum?",
            interpretation_status="retry_required")
    with pytest.raises(ValidationError, match="Interpretationszeitpunkt"):
        ProposalClarificationState(
            mail_id="a"*24, proposal_id="p1", version=1, question="Datum?",
            next_interpretation_at="2026-09-22T12:00:00+00:00")


def test_clarification_recovery_edge_paths(tmp_path):
    class InterpretationFailure(RevisionService):
        def interpret_telegram_answer(self, item, question, answer):
            raise LlmInvalidJson("telegram_answer_interpretation")
    with JsonStore(tmp_path) as store:
        item=proposal(open_questions=["Datum?"])
        c,t,_=controller(store, revision_service=InterpretationFailure())
        c.persist(item)
        dialog=TelegramDialogState(mail_id=item.source_mail_id, proposal_id=item.id, version=1)
        store.save("telegram-dialog", dialog.model_dump(mode="json"))
        c.revisions.answer("raw")
        assert "Verarbeitung ist verzögert" in t.sent[-1][1]

        # An invalid prior response is replaceable; it is not mistaken for a
        # still pending delivery.
        invalid = store.load("clarification-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v1")
        invalid.update(answer_status="invalid", interpretation_status="completed")
        store.save("clarification-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v1", invalid)
        c.revisions.revision_service = InterpretationFailure()
        c.revisions.answer("2026-10-21")

        answered=ProposalClarificationState(
            mail_id=item.source_mail_id, proposal_id=item.id, version=1,
            question="Datum?", question_status=QuestionStatus.ANSWERED,
            answer_status=AnswerStatus.VALID, normalized_answer="2026-10-21",
            proposal_revision_status=ProposalRevisionStatus.RETRY_REQUIRED)
        name="clarification-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v1"
        store.save(name, answered.model_dump(mode="json"))
        c.revisions.revision_service=RevisionService()
        c.revisions.answer("Ok")
        assert "bereits gespeichert" in t.sent[-1][1]

        # A successor published before a crash makes retry completion
        # idempotent and never invokes the LLM again.
        c.persist(proposal(version=2))
        c.revisions._revise_answered(answered)
        assert store.load(name)["proposal_revision_status"] == "completed"

        missing=answered.model_copy(update={"proposal_id":"missing"})
        c.revisions._revise_answered(missing)
        c.revisions._interpret_pending(answered.model_copy(update={
            "question_status": QuestionStatus.OPEN,
            "answer_status": AnswerStatus.PENDING,
            "normalized_answer": None,
            "proposal_revision_status": ProposalRevisionStatus.PENDING,
            "authorized_answer": "gespeichert",
        }))
        c.revisions.revision_service=None
        c.revisions._revise_answered(answered.model_copy(update={"version":2}))

        c.revisions.revision_service=RevisionService()
        original_handle = c.updates.handle
        c.updates.handle=lambda update: (_ for _ in ()).throw(RuntimeError("persistence"))
        t.updates=[message(7)]
        with pytest.raises(RuntimeError, match="persistence"):
            c.poll_once()

        c.revisions.revision_service = RevisionService()
        c.updates.handle = original_handle
        c.poll_once()
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["version"] == 2
        assert store.load("telegram-dialog")["retry_required"] is False


def test_revision_resume_handles_stale_unavailable_and_repeated_failure(tmp_path):
    base={"mail_id":"a"*24,"proposal_id":"p1","version":1,
          "retry_required":True,"question":"Welche Änderung?",
          "normalized_answer":"Neu"}
    with JsonStore(tmp_path) as store:
        c,_,log=controller(store, revision_service=OperationallyFailingRevisionService())
        c.persist(proposal(status="needs_clarification"))
        store.save("telegram-dialog",base)
        c.poll_once()
        assert any(item[0][2] == "answer_revision_resume_failed" for item in log.events)

        c.revisions.revision_service=RevisionService()
        c.poll_once()
        assert store.load("telegram-dialog")["retry_required"] is False
        assert any(item[0][2] == "answer_revision_resumed" for item in log.events)

        c.revisions.revision_service=None
        store.save("telegram-dialog",{**base,"version":2})
        c.poll_once()
        assert store.load("telegram-dialog")["retry_required"] is True

        store.save("telegram-dialog",{**base,"version":3})
        c.poll_once()
        assert store.load("telegram-dialog")["retry_required"] is False
    with pytest.raises(Exception, match="Revisions-Retry"):
        TelegramDialogState(retry_required=True)


def test_unexpected_interpretation_failure_remains_unacknowledged(tmp_path):
    class Broken(RevisionService):
        def interpret_telegram_answer(self, item, question, answer):
            raise RuntimeError("temporary")
    with JsonStore(tmp_path) as store:
        c,_,_=controller(store,[message(8,"Antwort")],revision_service=Broken())
        c.persist(proposal(status="needs_clarification"))
        store.save("telegram-dialog",{"mail_id":"a"*24,"proposal_id":"p1","version":1})
        with pytest.raises(RuntimeError,match="temporary"):
            c.poll_once()


def test_unrelated_telegram_update_does_not_block_following_reply(tmp_path):
    unrelated = {"update_id": 1, "my_chat_member": {"private": "not logged"}}
    with JsonStore(tmp_path) as store:
        c,t,log=controller(store, [unrelated, message(2)])
        c.poll_once()
        assert store.load("telegram-offset")["offset"] == 3
        assert "Keine offene" in t.sent[-1][1]
        assert "private" not in repr(log.events)
