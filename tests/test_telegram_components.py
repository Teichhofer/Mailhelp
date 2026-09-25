"""Contract tests for the components behind the Telegram routing controller."""
from unittest.mock import Mock

from mailhelp.models import Proposal
from mailhelp.storage import JsonStore
from mailhelp.telegram import (
    ActionLedgerService, ConfirmedWriteExecutor,
    AuthorizedUpdateValidator,
    Decision, DecisionAction,
    ProposalRevisionProcessor,
    RelevanceDecision,
    TelegramDialogController,
    clarification_name, proposal_name, proposal_version_name,
)


def _proposal() -> Proposal:
    return Proposal.model_validate({
        "id": "p1", "version": 1, "kind": "task", "responsibility": "user",
        "certainty": "certain", "classification": "new", "title": "Aufgabe",
        "description": "Text", "evidence": "Beleg",
        "source_mail_id": "a" * 24, "target": "inbox",
    })


def _controller(store: JsonStore) -> TelegramDialogController:
    telegram = Mock()
    telegram.poll.return_value = []
    return TelegramDialogController(store, telegram, 1, 2, Mock())


def test_validation_component_is_the_authorization_and_decoding_boundary(tmp_path):
    with JsonStore(tmp_path) as store:
        validator = AuthorizedUpdateValidator(store, 1, 2)
        decision = Decision(mail_id="a" * 24, proposal_id="p1", version=1,
                            action=DecisionAction.CONFIRM)
        token = decision.encode(store)

        assert validator.authorized(1, 2)
        assert not validator.authorized(9, 2)
        assert validator.decision(token) == decision
        assert validator.relevance_decision(
            RelevanceDecision(mail_id="a" * 24, version=1,
                              decision="relevant").encode()).decision == "relevant"


def test_controller_uses_independent_services_without_compatibility_methods(tmp_path):
    with JsonStore(tmp_path) as store:
        controller = _controller(store)
        assert isinstance(controller.write_executor, ConfirmedWriteExecutor)
        assert isinstance(controller.revisions, ProposalRevisionProcessor)
        for removed in ("_execute", "_resume_writes", "_answer",
                        "_resume_revisions", "_resume_revision"):
            assert not hasattr(controller, removed)


def test_revision_service_public_api_handles_absent_dialog_and_resume(tmp_path):
    with JsonStore(tmp_path) as store:
        controller = _controller(store)
        controller.revisions.answer("synthetische Antwort")
        controller.revisions.resume()
        controller.telegram.send.assert_called_once_with(2, "Keine offene Rückfrage. Bitte zuerst „Ändern“ wählen.")

def test_persistence_names_are_available_without_the_dialog_controller():
    mail_id = "a" * 24
    assert proposal_name(mail_id, "p1") == f"proposal-{mail_id}-p1"
    assert proposal_version_name(mail_id, "p1", 2) == f"proposal-{mail_id}-p1-v2"
    assert clarification_name(mail_id, "p1", 2) == f"clarification-{mail_id}-p1-v2"
def test_telegram_implementations_live_in_their_domain_modules():
    """Guard against turning the compatibility module back into a monolith."""
    from mailhelp.telegram import (
        AuthorizedUpdateValidator,
        ConfirmedWriteExecutor,
        Decision,
        ProposalRevisionProcessor,
        RelevanceDialogProcessor,
        TelegramClient,
        TelegramDialogController,
    )
    from mailhelp.telegram import _core

    expected_modules = {
        AuthorizedUpdateValidator: "mailhelp.telegram.authorization",
        ConfirmedWriteExecutor: "mailhelp.telegram.writes",
        Decision: "mailhelp.telegram.callbacks",
        ProposalRevisionProcessor: "mailhelp.telegram.revisions",
        RelevanceDialogProcessor: "mailhelp.telegram.relevance",
        TelegramClient: "mailhelp.telegram.client",
        TelegramDialogController: "mailhelp.telegram.dialog",
    }
    for implementation, module_name in expected_modules.items():
        assert implementation.__module__ == module_name
        assert getattr(_core, implementation.__name__) is implementation
