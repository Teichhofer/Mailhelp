"""Regression tests for races at real persistence and external-write boundaries."""
from types import SimpleNamespace

import pytest

from mailhelp.external.contracts import PreparedWrite, TargetWriter
from mailhelp.models import ProposalStatus
from mailhelp.review.inbox import CommandStatus
from tests.fakes.safety_harness import Gate
from tests.scenarios.web_scenario import mail_id


def current(web):
    return web.dialog.repository.load_current(mail_id(1), "formular")


def test_confirmation_does_not_overwrite_a_revision_committed_during_precheck(web):
    """Before the fix: the old confirmation replaced the new manual revision."""
    gate = Gate()
    original = current(web)
    def check(item):
        gate.hold()
        return item
    web.dialog.decision_service.precheck = SimpleNamespace(check_proposal=check)
    fields = web.form("/", kind="confirm", proposal_id="formular")
    response = web.submit(fields)
    with gate.during(web.run):
        revised = original.model_copy(update={"version": 2, "title": "Manuell geändert"})
        web.dialog.repository.save_revision(revised)
    assert current(web) == revised
    assert web.writer.created == 0
    entry = web.commands.get(response.headers["Location"].rsplit("/", 1)[1])
    assert entry.status == CommandStatus.REJECTED and entry.result.status.value == "stale"


@pytest.mark.parametrize("revocation", ["revoked", "expired"])
def test_saved_web_authorization_is_rechecked_after_restart(web, revocation):
    """Before the fix: a deferred CONFIRMED write forgot its authorizing session."""
    web.dialog.write_executor.writers.clear()
    web.submit(web.form("/", kind="confirm", proposal_id="formular"))
    web.run()
    assert current(web).status == ProposalStatus.CONFIRMED
    if revocation == "revoked":
        web.auth.revoke_all()
    else:
        from datetime import timedelta
        now = web.auth.clock()
        web.auth.clock = lambda: now + timedelta(days=31)
    from mailhelp.telegram import TelegramDialogController
    from tests.fakes.shared_telegram_dialog import Writer
    writer = Writer()
    restarted = TelegramDialogController(web.store, web.telegram, 1, 2, web.logger, {"todoist": writer})
    restarted.review.web_authorizer = web.dialog.review.web_authorizer
    restarted.poll_once()
    restarted.poll_once()
    assert writer.created == 0
    assert current(web).status == ProposalStatus.CONFIRMED


def test_web_session_revoked_during_provider_preparation_cannot_write(web):
    class PreparedProvider(TargetWriter):
        service = "todoist"
        target = "Inbox"
        target_profile = 1
        provider = "todoist"
        created = 0
        def check_access(self): pass
        def close(self): pass
        def reconcile(self, key): return None
        def create(self, item, key):
            self.created += 1
            return {"id": "external"}
        def prepare(self, item, key):
            web.auth.revoke_all()
            return PreparedWrite(lambda: self.create(item, key))
    writer = PreparedProvider()
    web.dialog.write_executor.writers["todoist"] = writer
    web.submit(web.form("/", kind="confirm", proposal_id="formular"))
    web.run()
    assert writer.created == 0


@pytest.mark.parametrize("suffix", ["corrupt", "invalid"])
def test_quarantined_authority_remains_blocking_on_repeated_reads(tmp_path, suffix):
    from mailhelp.storage import CorruptState, JsonStore
    with JsonStore(tmp_path) as store:
        (tmp_path / f"action-ledger.{suffix}").write_text("damaged", encoding="utf-8")
        for _ in range(2):
            with pytest.raises(CorruptState):
                store.load("action-ledger", {"entries": []})


def test_edit_does_not_overwrite_a_concurrent_commit(web, monkeypatch):
    import mailhelp.review.service as review_module
    gate, edit = Gate(), review_module.edit_proposal
    original = current(web)
    path = f"/vorschlag/{mail_id(1)}/formular/bearbeiten"
    form = {**web.form(path, action=path), "title": "Bearbeitungsversuch"}
    def held(*args):
        result = edit(*args)
        gate.hold()
        return result
    monkeypatch.setattr(review_module, "edit_proposal", held)
    response = web.browser.request("POST", path, form)
    with gate.during(web.run):
        revised = original.model_copy(update={"version": 2, "title": "Bereits gespeichert"})
        web.dialog.repository.save_revision(revised)
    assert current(web) == revised and web.writer.created == 0
    entry = web.commands.get(response.headers["Location"].rsplit("/", 1)[1])
    assert entry.result.status.value == "stale"


@pytest.mark.parametrize("suffix", ["corrupt", "invalid"])
def test_repaired_authority_can_retain_quarantined_copy(web, suffix):
    from mailhelp.proposals.proposal_reconciliation import ProposalReconciliationService
    name = f"proposal-{mail_id(1)}-formular"
    path = web.store.directory / f"{name}.{suffix}"
    path.write_text("damaged previous copy", encoding="utf-8")
    original = current(web)
    service = ProposalReconciliationService(web.store)
    service.recover()
    assert current(web) == original and path.exists()


@pytest.mark.parametrize("field", ["confirmed_web_actor", "reconciliation_journal"])
def test_ai_successor_cannot_change_application_owned_safety_metadata(web, field):
    from mailhelp.processing.analysis import ContradictoryRevision, validate_revision_successor
    original = current(web).model_copy(update={"confirmed_web_actor": "web:" + "a" * 16,
        "reconciliation_journal": "reconciliation-merge-" + "b" * 64})
    candidate = original.model_copy(update={"version": 2, field: None})
    with pytest.raises(ContradictoryRevision, match="Herkunftsfelder"):
        validate_revision_successor(original, candidate)


def test_restart_does_not_recreate_authority_from_a_misnamed_confirmed_record(web):
    """A valid JSON model under the wrong filename is still a damaged authority."""
    original = current(web).model_copy(update={"status": ProposalStatus.CONFIRMED})
    correct = f"proposal-{original.source_mail_id}-{original.id}"
    web.store.delete(correct)
    web.store.save(f"proposal-{mail_id(99)}-{original.id}", original.model_dump(mode="json"))
    for _ in range(2):
        with pytest.raises(ValueError, match="Vorschlagsbestand"):
            web.run()
        assert web.writer.created == 0 and web.store.load(correct) is None


@pytest.mark.parametrize("versioned", [False, True])
def test_legacy_unattributed_confirmation_is_not_a_replacement_for_live_authorization(web, versioned):
    original = current(web).model_copy(update={"status": ProposalStatus.CONFIRMED})
    value = original.model_dump(mode="json")
    value.pop("confirmed_web_actor")
    if not versioned:
        value.pop("schema_version")
    web.store.save(f"proposal-{original.source_mail_id}-{original.id}", value)
    # Even a permissive host integration cannot invent the missing historical binding.
    web.dialog.review.web_authorizer = lambda actor: True
    for _ in range(2):
        web.run()
        assert web.writer.created == 0 and current(web).status == ProposalStatus.CONFIRMED
    assert sum("Anlage blockiert" in text for _, text, _ in web.telegram.sent) == 1
    view = web.site.views.proposal(original.source_mail_id, original.id)
    assert "Altbestands nicht prüfbar" in view.state


def test_interrupted_legacy_migration_never_turns_missing_proof_into_telegram_consent(web):
    from mailhelp.storage import CorruptState
    original = current(web).model_copy(update={"status": ProposalStatus.CONFIRMED})
    raw = original.model_dump(mode="json")
    raw.update(schema_version=2)
    raw.pop("confirmed_web_actor")
    web.store.save(f"proposal-{original.source_mail_id}-{original.id}", raw)
    web.store.save("command-inbox", {"schema_version": 999})
    for _ in range(2):
        with pytest.raises(CorruptState):
            web.run()
        assert web.writer.created == 0


@pytest.mark.parametrize("live", [False, True])
@pytest.mark.parametrize("receipt", ["matching", "duplicate", "queued", "rejected", "telegram", "telegram_other_actor", "bad_actor", "other_kind", "other_version", "admin"])
def test_legacy_confirmation_uses_only_an_executed_matching_channel_receipt(web, live, receipt):
    from mailhelp.configuration import AdminCommand, AdminKind
    from mailhelp.review.commands import CommandKind, CommandSource, ReviewCommand
    from mailhelp.review.results import ResultStatus, ReviewResult
    original = current(web).model_copy(update={"status": ProposalStatus.CONFIRMED})
    actor = "web:" + web.auth.sessions()[0].id
    command = ReviewCommand(kind=CommandKind.CONFIRM_DUPLICATE if receipt == "duplicate" else
        CommandKind.REJECT if receipt == "other_kind" else CommandKind.CONFIRM,
        source=CommandSource.TELEGRAM if receipt.startswith("telegram") else CommandSource.WEB,
        actor="telegram:1:2" if receipt == "telegram" else "telegram:99:2" if receipt == "telegram_other_actor"
              else "invalid-web-actor" if receipt == "bad_actor" else actor, mail_id=original.source_mail_id,
        proposal_id=original.id, version=2 if receipt == "other_version" else 1, idempotency_key="legacy-receipt")
    if receipt == "admin":
        command = AdminCommand(kind=AdminKind.SETTINGS, actor=actor, expected_hash="0" * 64,
            idempotency_key="legacy-admin", patch={"poll_interval_seconds": 10}, acknowledged=True)
    entry, _ = web.commands.submit(command)
    if receipt != "queued":
        web.commands.start(entry.id)
        if receipt != "matching":
            web.commands.finish(entry.id, ReviewResult(status=ResultStatus.UNAUTHORIZED if receipt == "rejected"
                else ResultStatus.DONE, message="Stored receipt"))
    value = original.model_dump(mode="json")
    value.pop("confirmed_web_actor")
    web.store.save(f"proposal-{original.source_mail_id}-{original.id}", value)
    if not live:
        web.auth.revoke_all()
    for _ in range(2):
        web.run()
    expected = receipt == "telegram" or live and receipt in {"matching", "duplicate"}
    assert web.writer.created == int(expected)
    assert current(web).status == (ProposalStatus.CREATED if expected else ProposalStatus.CONFIRMED)
