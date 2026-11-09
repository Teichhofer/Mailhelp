"""Text answers report what really happened (5.0.3) and never try to resolve a reconciliation block."""
from __future__ import annotations

import pytest

from mailhelp.domain.processing import ProposalClarificationState
from mailhelp.domain.proposal import MATCHING_QUESTION, RECONCILIATION_HINT, SOURCE_QUESTION
from mailhelp.llm.adapter import RetryableError
from mailhelp.models import TelegramDialogState
from mailhelp.review import CommandKind, ResultStatus
from mailhelp.storage import JsonStore
from tests.fakes.shared_review import command, mail_state, setup, web
from tests.fakes.shared_telegram_dialog import (
    InterpretationErrorService,
    UnusableAnswerService,
    controller,
    proposal,
)

MAIL = "a" * 24
BLOCKED = [MATCHING_QUESTION, SOURCE_QUESTION]


def prepared(store, item, revision_service=None):
    store.save(f"mail-{MAIL}", mail_state(MAIL, 1, [item]).model_dump(mode="json"))
    dialog, telegram, log = controller(store, revision_service=revision_service)
    dialog.persist(item)
    return dialog, telegram, log


def clarification(store, version=1):
    return store.load_model(f"clarification-{MAIL}-p1-v{version}", ProposalClarificationState)


def test_a_web_answer_to_a_reconciliation_block_is_refused_without_a_language_model(tmp_path):
    """Regression: "Es ist freigegeben, ich will die Aufgabe anlegen" was sent to the LLM,
    judged incomplete and the web still reported "Antwort übernommen"."""
    item = proposal(status="needs_clarification", open_questions=BLOCKED)
    with JsonStore(tmp_path) as store:
        dialog, telegram, _ = setup(store, item)
        result = web(dialog).execute(command(CommandKind.ANSWER, text="Es ist freigegeben, ich will die Aufgabe anlegen"))
        assert (result.status, result.message) == (ResultStatus.NEEDS_ANSWER, RECONCILIATION_HINT)
        assert dialog.revisions.revision_service.calls == []
        assert clarification(store) is None
        assert store.load(f"proposal-{MAIL}-p1")["version"] == 1
        assert store.load_model("telegram-dialog", TelegramDialogState) is None


def test_a_telegram_answer_to_a_reconciliation_block_points_to_the_reconciliation(tmp_path):
    item = proposal(status="needs_clarification", open_questions=BLOCKED)
    with JsonStore(tmp_path) as store:
        dialog, telegram, log = prepared(store, item)
        store.save("telegram-dialog", TelegramDialogState(mail_id=MAIL, proposal_id="p1", version=1)
                   .model_dump(mode="json"))
        assert dialog.revisions.answer("Bitte anlegen") == RECONCILIATION_HINT
        assert dialog.revisions.revision_service.calls == []
        assert any(RECONCILIATION_HINT in text for _, text, _ in telegram.sent)
        assert ("answer_rejected", "reconciliation_required") in {
            (key[2], fields.get("reason")) for key, fields in log.events}
        assert clarification(store) is None


def test_a_further_real_question_is_answered_while_the_block_stays(tmp_path):
    item = proposal(status="needs_clarification", open_questions=[MATCHING_QUESTION, "Bis wann?"])
    with JsonStore(tmp_path) as store:
        dialog, _, _ = setup(store, item)
        result = web(dialog).execute(command(CommandKind.ANSWER, text="Freitag"))
        assert result.status == ResultStatus.DONE
        assert dialog.revisions.revision_service.calls[0][2] == "Bis wann?"
        assert clarification(store).question == "Bis wann?"


def test_an_unusable_web_answer_shows_the_follow_up_question(tmp_path):
    """Regression: the follow-up was only sent to Telegram; the web said "übernommen"."""
    item = proposal(status="needs_clarification", open_questions=["Bis wann ist es fällig?"])
    with JsonStore(tmp_path) as store:
        dialog, telegram, _ = prepared(store, item, UnusableAnswerService())
        result = web(dialog).execute(command(CommandKind.ANSWER, text="bald"))
        assert result.status == ResultStatus.NEEDS_ANSWER
        assert result.message == ("Antwort nicht übernommen – Rückfrage: "
                                  "Bitte konkreter beantworten: Bis wann ist es fällig?")
        assert clarification(store).answer_status == "invalid"
        assert store.load(f"proposal-{MAIL}-p1")["version"] == 1


def test_a_deferred_interpretation_is_reported_as_saved(tmp_path):
    item = proposal(status="needs_clarification", open_questions=["Bis wann?"])
    with JsonStore(tmp_path) as store:
        dialog, _, _ = prepared(store, item, InterpretationErrorService(RetryableError("später")))
        result = web(dialog).execute(command(CommandKind.ANSWER, text="Freitag"))
        assert (result.status, result.message) == (
            ResultStatus.DONE, "Antwort gespeichert – die Auswertung wird automatisch wiederholt.")


@pytest.mark.parametrize("state", ["missing", "invalid"])
def test_an_answer_without_a_usable_result_is_not_reported_as_taken(tmp_path, monkeypatch, state):
    item = proposal(status="needs_clarification", open_questions=["Bis wann?"])
    with JsonStore(tmp_path) as store:
        dialog, _, _ = setup(store, item)
        if state == "missing":
            dialog.revisions.revision_service = None
        else:
            def unusable(answer):
                store.save(f"clarification-{MAIL}-p1-v1", ProposalClarificationState(
                    mail_id=MAIL, proposal_id="p1", version=1, question="Bis wann?", authorized_answer=answer,
                    answer_status="invalid", interpretation_status="completed").model_dump(mode="json"))
            monkeypatch.setattr(dialog.revisions, "answer", unusable)
        result = web(dialog).execute(command(CommandKind.ANSWER, text="Freitag"))
        assert (result.status, result.message) == (
            ResultStatus.NEEDS_ANSWER, "Antwort nicht übernommen; der Vorschlag ist unverändert.")
