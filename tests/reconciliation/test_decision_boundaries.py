"""Old approvals, expired sessions and untrusted semantic/source instructions."""
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from shared_telegram_dialog import callback
from web_scenario import mail_id, proposal, save_mail

from mailhelp.domain.proposal import DuplicateMatchInfo, ProposalStatus
from mailhelp.domain.proposal_sources import ProposalReference
from mailhelp.proposal_reconciliation import ProposalReconciliationService
from mailhelp.review.commands import ReviewCommand
from mailhelp.review.errors import StaleCommand
from mailhelp.review.results import ResultStatus
from mailhelp.telegram.callbacks import Decision, DecisionAction


def prepared(web):
    first = proposal(40, "base", title="Teilnahme bestätigen")
    second = proposal(41, "source", title=first.title, description="Zusatz")
    save_mail(web.store, 40, "synthetic@example.test", "Synthetisch", [first])
    save_mail(web.store, 41, "synthetic@example.test", "Synthetisch", [second])
    return first, second


@pytest.mark.parametrize("relation", ["merge_source", "separate_source"])
def test_telegram_association_tokens_bind_source_and_target_and_do_not_write(web, relation):
    first, second = prepared(web)
    service = ProposalReconciliationService(web.store)
    alias = service.merge(second, first, uncertain=True)
    current = service.required(first.source_mail_id, first.id)
    web.dialog.delivery.deliver(current)
    markup = web.telegram.sent[-1][2]
    choices = [Decision.parse(b["callback_data"], web.store) for row in markup["inline_keyboard"] for b in row]
    decision = next(d for d in choices if d.action.value == relation)
    assert decision.version == current.version and decision.additional_version == alias.version
    assert decision.additional_ref == ProposalReference(mail_id=alias.source_mail_id, proposal_id=alias.id)
    with pytest.raises(ValueError, match="Callback"):
        decision.encode()
    web.telegram.updates = [callback(1, decision.encode(web.store))]
    web.run()
    result = service.required(second.source_mail_id, second.id)
    assert (result.status == "merged") == (relation == "merge_source")
    assert web.writer.created == 0
    web.telegram.updates = [callback(2, decision.encode(web.store))]
    web.run()
    assert service.required(second.source_mail_id, second.id) == result


def test_merge_invalidates_old_confirmation_in_both_channels(web):
    first, second = prepared(web)
    old = Decision(mail_id=first.source_mail_id, proposal_id=first.id, version=1, action=DecisionAction.CONFIRM)
    ProposalReconciliationService(web.store).merge(second, first)
    with pytest.raises(StaleCommand):
        web.dialog.decision_service.decide(old, 1, 2)
    cmd = ReviewCommand(kind="confirm", source="web", actor="web:" + web.auth.sessions()[0].id,
        mail_id=first.source_mail_id, proposal_id=first.id, version=1, idempotency_key="old-confirmation")
    assert web.dialog.review.execute(cmd).status == ResultStatus.STALE
    assert web.writer.created == 0


@pytest.mark.parametrize("outcome", ["same", "failure", "exists", "expired"])
def test_read_preflight_rechecks_result_and_session_before_external_write(web, outcome):
    first, _ = prepared(web)
    def check(p):
        if outcome == "failure":
            return p.model_copy(update={"duplicate_check_failed": True, "status": ProposalStatus.NEEDS_CLARIFICATION,
                                        "open_questions": ["Dublettenprüfung fehlgeschlagen"]})
        if outcome == "exists":
            return p.model_copy(update={"status": ProposalStatus.ALREADY_EXISTS,
                "duplicate_match": DuplicateMatchInfo(source="todoist", matched_title=p.title)})
        if outcome == "expired":
            web.auth.revoke_all()
        return p
    web.dialog.decision_service.precheck = SimpleNamespace(check_proposal=check)
    cmd = ReviewCommand(kind="confirm", source="web", actor="web:" + web.auth.sessions()[0].id,
        mail_id=first.source_mail_id, proposal_id=first.id, version=1, idempotency_key="preflight-confirmation")
    result = web.dialog.review.execute(cmd)
    assert (result.status == ResultStatus.WRITTEN) == (outcome == "same")
    assert web.writer.created == int(outcome == "same")


def test_incomplete_or_irrelevant_source_binding_is_rejected():
    payload = dict(mail_id=mail_id(1), proposal_id="proposal", version=1, action=DecisionAction.MERGE_SOURCE)
    with pytest.raises(ValidationError, match="beide Vorschlagsversionen"):
        Decision(**payload)
    with pytest.raises(ValidationError, match="Nur Quellenentscheidungen"):
        Decision(**{**payload, "action": DecisionAction.CONFIRM, "additional_version": 1})
    with pytest.raises(ValidationError, match="Nur Quellenentscheidungen"):
        Decision(**{**payload, "action": DecisionAction.CONFIRM, "additional_ref":
                    ProposalReference(mail_id=mail_id(2), proposal_id="source")})
    command = dict(kind="merge_proposals", source="web", actor="web:synthetic", mail_id=mail_id(1),
                   proposal_id="proposal", version=1, idempotency_key="invalid-merge")
    with pytest.raises(ValidationError):
        ReviewCommand(**command)
    with pytest.raises(ValidationError):
        ReviewCommand(**{**command, "kind": "confirm", "proposal_hash": "0" * 64})


def test_missing_additional_record_blocks_telegram_delivery(web):
    first, second = prepared(web)
    service = ProposalReconciliationService(web.store)
    service.merge(second, first, uncertain=True)
    current = service.required(first.source_mail_id, first.id)
    web.store.delete(f"proposal-{second.source_mail_id}-{second.id}")
    with pytest.raises(ValueError, match="Quelle fehlt"):
        web.dialog.delivery.deliver(current)
    assert web.writer.created == 0


def test_recheck_unavailable_and_changed_target_do_not_commit_read_result(web):
    first, _ = prepared(web)
    cmd = ReviewCommand(kind="recheck_proposal", source="web", actor="web:" + web.auth.sessions()[0].id,
        mail_id=first.source_mail_id, proposal_id=first.id, version=1, idempotency_key="recheck-unavailable")
    assert web.dialog.review.execute(cmd).status == ResultStatus.INVALID
    def check(p):
        web.dialog.persist(first.model_copy(update={"version": 2}))
        return p
    web.dialog.decision_service.precheck = SimpleNamespace(check_proposal=check)
    assert web.dialog.review.execute(cmd).status == ResultStatus.STALE
    assert web.dialog.repository.load_current(first.source_mail_id, first.id).version == 2
    current = web.dialog.repository.load_current(first.source_mail_id, first.id)
    cmd = cmd.model_copy(update={"version": 2})
    def begin_edit(p):
        web.dialog.persist(current.model_copy(update={"status": ProposalStatus.NEEDS_CLARIFICATION}))
        return p
    web.dialog.decision_service.precheck = SimpleNamespace(check_proposal=begin_edit)
    assert web.dialog.review.execute(cmd).status == ResultStatus.STALE


def test_restore_command_rejects_missing_or_changed_embedded_record(web):
    first, _ = prepared(web)
    cmd = ReviewCommand(kind="restore_proposal", source="web", actor="web:" + web.auth.sessions()[0].id,
        mail_id=first.source_mail_id, proposal_id=first.id, version=999, proposal_hash="0" * 64,
        idempotency_key="changed-mail-record")
    assert web.dialog.review.execute(cmd).status == ResultStatus.STALE


def test_known_provider_change_with_same_target_name_never_reads_or_writes_the_new_service():
    import httpx
    from shared_core import proposal as task

    from mailhelp.external.confirmed import execute_confirmed
    from mailhelp.integrations import HttpWriter
    from mailhelp.precheck import DuplicatePreCheckService
    calls = []
    writer = HttpWriter("todoist", "synthetic-token", "inbox",
        transport=httpx.MockTransport(lambda req: calls.append(req)))
    try:
        item = task(status="confirmed", target_provider="microsoft_todo")
        result, details = execute_confirmed(item, writer, lambda p: pytest.fail("No state transition permitted"))
        assert details == {"target_mismatch": True} and result == item and calls == []
        checked = DuplicatePreCheckService(writer=writer).check_proposal(item)
        assert checked.duplicate_check_failed and calls == []
    finally:
        writer.close()


def test_a_new_open_candidate_invalidates_an_earlier_confirmation_before_any_writer_call(web):
    from mailhelp.domain.proposal_sources import ProposalSource
    first, second = prepared(web)
    first = first.model_copy(update={"sources": [ProposalSource(mail_id=first.source_mail_id, proposal_id=first.id,
        subject="synthetic", anchors=["thread"])]})
    second = second.model_copy(update={"sources": [ProposalSource(mail_id=second.source_mail_id, proposal_id=second.id,
        subject="synthetic", anchors=["thread"])]})
    web.dialog.persist(first)
    web.dialog.persist(second)
    decision = Decision(mail_id=first.source_mail_id, proposal_id=first.id, version=1, action=DecisionAction.CONFIRM)
    with pytest.raises(StaleCommand, match="Offene Entscheidungen"):
        web.dialog.decision_service.decide(decision, 1, 2)
    current = web.dialog.repository.load_current(first.source_mail_id, first.id)
    assert current.version == 2 and current.matching_candidates and current.status == "needs_clarification"
    assert web.writer.created == 0
