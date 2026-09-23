"""Contract tests for the components behind the Telegram routing controller."""
from unittest.mock import Mock

from mailhelp.models import Proposal
from mailhelp.storage import JsonStore
from mailhelp.telegram import (
    ActionLedgerService,
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


def test_controller_compatibility_methods_delegate_to_extracted_components(tmp_path):
    with JsonStore(tmp_path) as store:
        controller = _controller(store)
        item = _proposal()
        assert controller._action_key(item) == ActionLedgerService.action_key(item)

        controller.relevance.all = Mock(return_value=[])
        assert controller._all_relevance_dialogs() == []

        controller.write_executor.resume = Mock()
        controller._resume_writes()
        controller.write_executor.resume.assert_called_once_with()

        controller._resume_durable_revisions = Mock()
        controller._resume_revisions()
        controller._resume_durable_revisions.assert_called_once_with()

        controller._resume_legacy_revision = Mock()
        controller._resume_revision()
        controller._resume_legacy_revision.assert_called_once_with()


def test_revision_component_exposes_only_answer_and_resume_operations():
    owner = Mock()
    component = ProposalRevisionProcessor(owner)
    component.answer("synthetische Antwort")
    component.resume()
    owner._process_answer.assert_called_once_with("synthetische Antwort")
    owner._resume_durable_revisions.assert_called_once_with()
    owner._resume_legacy_revision.assert_called_once_with()


def test_persistence_names_are_available_without_the_dialog_controller():
    mail_id = "a" * 24
    assert proposal_name(mail_id, "p1") == f"proposal-{mail_id}-p1"
    assert proposal_version_name(mail_id, "p1", 2) == f"proposal-{mail_id}-p1-v2"
    assert clarification_name(mail_id, "p1", 2) == f"clarification-{mail_id}-p1-v2"
