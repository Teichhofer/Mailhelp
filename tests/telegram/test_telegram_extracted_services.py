"""Focused crash-boundary tests for extracted Telegram services."""
from unittest.mock import Mock

import pytest

from mailhelp.models import MailState, Proposal, ProposalNotification
from mailhelp.storage import JsonStore
from mailhelp.telegram import (
    Decision, DecisionAction, ProposalDecisionService,
    ProposalDeliveryService, ProposalPresenter, ProposalRepository,
)


MAIL_ID = "a" * 24


def proposal(**changes) -> Proposal:
    values = {
        "id": "p1", "version": 1, "kind": "task",
        "responsibility": "user", "certainty": "certain",
        "classification": "new", "title": "Aufgabe",
        "description": "Text", "evidence": "Beleg",
        "source_mail_id": MAIL_ID, "target": "inbox",
    }
    values.update(changes)
    return Proposal.model_validate(values)


def mail(item: Proposal, *, notification=True) -> MailState:
    return MailState(
        id=MAIL_ID, config_fingerprint="f" * 64,
        imap={"account_id": "0" * 24, "folder": "INBOX",
              "uidvalidity": 1, "uid": 1},
        proposals=[item],
        proposal_notifications=([ProposalNotification(
            proposal_id=item.id, proposal_version=item.version)]
            if notification else []),
    )


@pytest.mark.parametrize("fail_at", [1, 2, 3])
def test_repository_repairs_crash_after_each_ordered_write(tmp_path, fail_at):
    class InterruptingStore(JsonStore):
        writes = 0
        armed = False

        def save(self, name, value):
            if self.armed:
                self.writes += 1
                if self.writes == fail_at:
                    raise RuntimeError("simulierter Absturz")
            super().save(name, value)

    initial = proposal(title="Alt")
    revised = proposal(version=2, title="Neu")
    with InterruptingStore(tmp_path) as store:
        store.save(f"mail-{MAIL_ID}", mail(initial).model_dump(mode="json"))
        repository = ProposalRepository(store)
        store.armed = True
        with pytest.raises(RuntimeError, match="Absturz"):
            repository.save_revision(revised)
        store.armed = False
        repository.save_revision(revised)
        assert repository.load_version(MAIL_ID, "p1", 2) == revised
        assert repository.load_current(MAIL_ID, "p1") == revised
        assert repository.load_mail(MAIL_ID).proposals == [revised]


def test_repository_named_operations_cover_missing_and_idempotent_states(tmp_path):
    item = proposal()
    with JsonStore(tmp_path) as store:
        repository = ProposalRepository(store)
        assert repository.load_current(MAIL_ID, "p1") is None
        assert repository.load_version(MAIL_ID, "p1", 1) is None
        assert repository.load_mail(MAIL_ID) is None
        assert repository.notification_status(item) is None
        assert not repository.mark_notification_sending(item)
        repository.record_write_attempt(item)  # no mail projection

        store.save(f"mail-{MAIL_ID}", mail(item, notification=False).model_dump(mode="json"))
        assert repository.notification_status(item) is None
        assert not repository.mark_notification_completed(item)
        repository.record_write_attempt(item)
        repository.record_write_attempt(item)
        assert len(repository.load_mail(MAIL_ID).write_attempts) == 1


def test_delivery_marks_before_send_and_only_completes_after_success(tmp_path):
    item = proposal()
    with JsonStore(tmp_path) as store:
        store.save(f"mail-{MAIL_ID}", mail(item).model_dump(mode="json"))
        repository = ProposalRepository(store)
        presenter = ProposalPresenter("UTC", lambda decision: decision.encode(store))
        telegram = Mock()
        telegram.send.side_effect = RuntimeError("Netz getrennt")
        delivery = ProposalDeliveryService(repository, presenter, telegram, 2)
        with pytest.raises(RuntimeError, match="Netz"):
            delivery.deliver(item)
        assert repository.notification_status(item) == "sending"

        telegram.send.reset_mock(side_effect=True)
        delivery.deliver(item)
        telegram.send.assert_not_called()  # ambiguous first send is not repeated
        state = repository.load_mail(MAIL_ID)
        state.proposal_notifications[0].status = "pending"
        store.save(f"mail-{MAIL_ID}", state.model_dump(mode="json"))
        delivery.deliver(item)
        assert repository.notification_status(item) == "completed"
        telegram.send.reset_mock()
        delivery.deliver(item)
        telegram.send.assert_not_called()


def test_delivery_does_not_send_if_pending_transition_was_lost():
    repository = Mock()
    repository.load_mail.return_value = None
    repository.notification_status.return_value = "pending"
    repository.mark_notification_sending.return_value = False
    presenter = Mock()
    presenter.present.return_value = Mock(parts=("text",), reply_markup={})
    telegram = Mock()
    ProposalDeliveryService(repository, presenter, telegram, 2).deliver(proposal())
    telegram.send.assert_not_called()


def test_decision_service_rejects_identity_before_loading_state():
    repository = Mock()
    service = ProposalDecisionService(
        Mock(), repository, Mock(), Mock(), Mock(), Mock(), 1, 2)
    decision = Decision(mail_id=MAIL_ID, proposal_id="p1", version=1,
                        action=DecisionAction.CONFIRM)
    with pytest.raises(PermissionError, match="autorisiert"):
        service.decide(decision, 9, 2)
    repository.load_current.assert_not_called()
