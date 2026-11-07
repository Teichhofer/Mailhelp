"""Local completion preserves positive learning evidence without authorizing a provider."""
import hashlib
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from mailhelp.external.confirmed import execute_confirmed
from mailhelp.llm.learning import LearningMode
from mailhelp.mailbox.imap import FetchedMail
from mailhelp.models import IrrelevantSenders, Proposal, ProposalStatus
from mailhelp.review.inbox import CommandInbox
from mailhelp.review.learning_log import DecisionLearningLog, learning_path, preserves_relevance
from mailhelp.review.views import ReviewViews
from mailhelp.storage import JsonStore
from mailhelp.telegram.callbacks import Decision, DecisionAction, apply_decision
from tests.fakes.factories import build_proposal
from tests.fakes.shared_review import MAIL, command, setup, web
from tests.fakes.shared_telegram_dialog import Writer, callback


@pytest.mark.parametrize("clarification", [False, True])
@pytest.mark.parametrize("test_mode", [False, True])
@pytest.mark.parametrize("source", ["web", "telegram"])
def test_already_done_is_a_local_version_bound_decision_with_positive_learning(tmp_path, clarification, test_mode, source):
    item = build_proposal(open_questions=["Wann?"] if clarification else [])
    writer = Writer()
    with JsonStore(tmp_path) as store:
        dialog, _, logger = setup(store, item, writers={"todoist": writer}, test_mode=test_mode)
        service = web(dialog)
        dialog.learning = DecisionLearningLog(store, "unlimited", logger)
        request = command("already_done", source=source, actor="web:session" if source == "web" else "telegram:1:2")
        result = service.execute(request)
        assert result.status == "done" and "schon erledigt" in result.message
        current = dialog.repository.load_current(MAIL, "p1")
        assert (current.version, current.status, current.resolution) == (1, "rejected", "already_done")
        assert current.classification == item.classification and current.external_id is None
        assert writer.created == writer.reconciled == 0
        assert service.execute(request).status == "stale"
        assert service.execute(command("confirm")).status == "stale"
        records = [json.loads(line) for line in learning_path(tmp_path).read_text().splitlines()]
        assert len(records) == 1
        assert (records[0]["operation"], records[0]["decision"], records[0]["relevance_preserved"]) == (
            "already_done", "relevant", True)
        assert records[0]["idempotency_key"] == request.idempotency_key
        assert records[0]["proposal"]["result"]["resolution"] == "already_done"
        assert store.load(f"history-{MAIL}")["events"][-1]["kind"] == "already_done"
        assert preserves_relevance(store, MAIL)
        assert ReviewViews(store, "UTC").proposal(MAIL, "p1").state == "Schon erledigt"
        assert ReviewViews(store, "UTC").system().already_done == 1


def test_a_crash_after_local_commit_reconciles_without_repeating_or_relearning(tmp_path):
    with JsonStore(tmp_path) as store:
        dialog, _, logger = setup(store, build_proposal())
        dialog.learning = DecisionLearningLog(store, "unlimited", logger)
        web(dialog)
        inbox = CommandInbox(store)
        request = command("already_done")
        entry, new = inbox.submit(request)
        assert new and inbox.submit(request) == (entry, False)
        inbox.start(entry.id)
        assert dialog.review.execute(request).status == "done"
        assert CommandInbox(store).recover(dialog.review.reconcile) == 1
        assert CommandInbox(store).get(entry.id).status == "done"
        assert CommandInbox(store).recover(dialog.review.reconcile) == 0
        assert len(learning_path(tmp_path).read_text().splitlines()) == 1


@pytest.mark.parametrize("changes", [{"version": 2}, {"actor": "web:revoked"},
                                     {"source": "telegram", "actor": "telegram:9:2"}])
def test_stale_or_unauthorized_local_closure_changes_nothing(tmp_path, changes):
    with JsonStore(tmp_path) as store:
        item = build_proposal()
        dialog, _, _ = setup(store, item)
        result = web(dialog).execute(command("already_done", **changes))
        assert result.status in {"stale", "unauthorized"}
        assert dialog.repository.load_current(MAIL, "p1") == item
        assert not learning_path(tmp_path).exists()


def test_telegram_button_closes_the_exact_version_and_removes_the_keyboard(tmp_path):
    with JsonStore(tmp_path) as store:
        item = build_proposal()
        dialog, telegram, _ = setup(store, item)
        buttons = dialog.presenter.present(item).reply_markup["inline_keyboard"]
        button = next(button for row in buttons for button in row if button["text"] == "✓ Schon erledigt")
        telegram.updates = [callback(1, button["callback_data"])]
        dialog.poll_once()
        assert dialog.repository.load_current(MAIL, "p1").resolution == "already_done"
        assert telegram.removed == [(2, 1)]
        assert "relevant vermerkt" in telegram.sent[-1][1]


def test_the_resolution_is_valid_only_on_a_rejected_proposal_and_old_records_default_to_none():
    item = build_proposal()
    assert item.resolution is None
    with pytest.raises(ValidationError, match="Schon erledigt benötigt"):
        Proposal.model_validate({**item.model_dump(), "resolution": "already_done"})
    closed = apply_decision(item, Decision(mail_id=MAIL, proposal_id="p1", version=1, action=DecisionAction.ALREADY_DONE), 1, 2, 1, 2)
    assert closed.resolution == "already_done"
    assert apply_decision(closed, Decision(mail_id=MAIL, proposal_id="p1", version=1, action=DecisionAction.ALREADY_DONE), 1, 2, 1, 2) == closed


def test_learning_does_not_ask_a_model_to_reclassify_a_proven_relevant_mail(tmp_path):
    fetched = FetchedMail("INBOX", 1, 1, b"From: a@example.test\nSubject: Task\n\nDone")
    identity = f"{fetched.account_id}:{fetched.folder}:{fetched.uidvalidity}:{fetched.uid}"
    mail_id = hashlib.sha256(identity.encode()).hexdigest()[:24]
    with JsonStore(tmp_path / "mail") as store:
        dialog, _, logger = setup(store, build_proposal(source_mail_id=mail_id), mail_id=mail_id)
        dialog.learning = DecisionLearningLog(store, "unlimited", logger)
        assert web(dialog).execute(command("already_done", mail_id=mail_id)).status == "done"
        mode = LearningMode(None, SimpleNamespace(), [], None, [], tmp_path / "topics.yaml", [],
                            tmp_path / "irrelevant_topics.yaml", JsonStore(tmp_path / "config"), decision_store=store)
        # No analyzer methods exist: even a relevance call would fail this proof.
        assert mode.classify(fetched, IrrelevantSenders()) == (None, None, False)
        assert not mode.topics_path.exists() and not mode.irrelevant_topics_path.exists()
        # Retained positive records still protect after authoritative records are removed.
        store.delete(f"mail-{mail_id}")
        store.delete(f"proposal-{mail_id}-p1")
        assert preserves_relevance(store, mail_id)
        assert not preserves_relevance(store, "f" * 24)
        assert mode.classify(fetched, IrrelevantSenders()) == (None, None, False)


def test_positive_learning_survives_a_crash_before_projection_or_learning_log(tmp_path):
    with JsonStore(tmp_path) as store:
        item = build_proposal()
        setup(store, item)
        closed = item.model_copy(update={"status": ProposalStatus.REJECTED, "resolution": "already_done"})
        store.save(f"proposal-{MAIL}-p1", closed.model_dump(mode="json"))
        assert not learning_path(tmp_path).exists()
        assert preserves_relevance(store, MAIL)
        store.delete(f"mail-{MAIL}")
        assert preserves_relevance(store, MAIL)


def test_even_an_unvalidated_status_copy_of_an_already_done_item_cannot_write():
    item = build_proposal(status="rejected", resolution="already_done")
    malformed = item.model_copy(update={"status": ProposalStatus.CONFIRMED})
    writer = Writer()
    with pytest.raises(ValueError):
        execute_confirmed(malformed, writer, lambda proposal: None, authorize=lambda: True)
    assert writer.created == writer.reconciled == 0


def test_empty_records_and_version_snapshots_do_not_invent_positive_learning(tmp_path):
    with JsonStore(tmp_path) as store:
        store.save(f"proposal-{MAIL}-empty", None)
        item = build_proposal(status="rejected", resolution="already_done")
        store.save(f"proposal-{MAIL}-p1-v1", item.model_dump(mode="json"))
        assert preserves_relevance(store, MAIL) is False


@pytest.mark.parametrize("changes", [{"status": "rejected"}, {"status": "created", "external_id": "other-action"},
                                     {"version": 2}, {"version": 2, "status": "rejected", "resolution": "already_done"}])
def test_recovery_never_attributes_another_decision_or_version_to_already_done(tmp_path, changes):
    with JsonStore(tmp_path) as store:
        dialog, _, logger = setup(store, build_proposal(**changes))
        dialog.learning = DecisionLearningLog(store, "unlimited", logger)
        result = web(dialog).reconcile(command("already_done"))
        assert result.status == "failed"
        assert not learning_path(tmp_path).exists()
