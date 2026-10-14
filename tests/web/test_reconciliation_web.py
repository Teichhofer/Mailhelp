"""Authenticated previews, local changes and stale/idempotent decision boundaries."""
import json
from types import SimpleNamespace

import pytest
from web_scenario import mail_id, proposal, save_mail

from mailhelp.config import EventDefaultsSettings
from mailhelp.domain.proposal import ProposalStatus
from mailhelp.domain.proposal_sources import ProposalReference, ProposalSource
from mailhelp.proposal_reconciliation import ProposalReconciliationService
from mailhelp.review.commands import CommandKind, CommandSource, ReviewCommand
from mailhelp.review.results import ResultStatus
from mailhelp.web.reconciliation_site import digest


def pair(web, *, uncertain=False):
    first = proposal(30, "first", title="Synthetische Aufgabe", description="Bisher",
        sources=[ProposalSource(mail_id=mail_id(30), proposal_id="first", subject="<script>", anchors=["thread"])])
    second = proposal(31, "second", title=first.title, description="Zusätzliche Angaben",
        sources=[ProposalSource(mail_id=mail_id(31), proposal_id="second", subject="<script>", anchors=["thread"])])
    save_mail(web.store, 30, "synthetic@example.test", "Synthetisch", [first])
    save_mail(web.store, 31, "synthetic@example.test", "Synthetisch", [second])
    if uncertain:
        service = ProposalReconciliationService(web.store)
        second = service.merge(second, first, uncertain=True)
        first = service.required(first.source_mail_id, first.id)
    return first, second


def post(web, **match):
    form = web.form("/abgleich", action="/abgleich", **match)
    response = web.browser.request("POST", "/abgleich", form)
    assert response.status == 303
    web.run()
    return form


def test_preview_is_read_only_escaped_and_merge_is_local_idempotent(web):
    first, second = pair(web)
    before = {p.name: p.read_bytes() for p in web.store.directory.glob("*.json")}
    page = web.browser.request("GET", "/abgleich")
    assert page.status == 200 and "Zusatz ausdrücklich" in page.body.decode()
    assert before == {p.name: p.read_bytes() for p in web.store.directory.glob("*.json")}
    form = post(web, kind="merge_proposals", proposal_id=second.id, target_proposal_id=first.id)
    assert web.dialog.repository.load_current(second.source_mail_id, second.id).status == "merged"
    assert web.writer.created == 0
    web.browser.request("POST", "/abgleich", form)
    web.run()
    assert web.dialog.repository.load_current(first.source_mail_id, first.id).version == 2
    redirect = web.browser.request("GET", f"/vorschlag/{second.source_mail_id}/{second.id}")
    assert redirect.headers["Location"] == f"/vorschlag/{first.source_mail_id}/{first.id}"
    source = web.browser.request("GET", f"/vorschlag/{first.source_mail_id}/{first.id}").body.decode()
    assert "Quellenmail" in source and "&lt;script&gt;" in source


@pytest.mark.parametrize("kind", ["merge_proposals", "separate_proposals"])
def test_uncertain_identity_has_two_explicit_local_choices(web, kind):
    first, second = pair(web, uncertain=True)
    post(web, kind=kind, proposal_id=second.id)
    current = web.dialog.repository.load_current(second.source_mail_id, second.id)
    assert (current.status == "merged") == (kind == "merge_proposals")
    assert not web.dialog.repository.load_current(first.source_mail_id, first.id).pending_sources
    assert web.writer.created == 0


def test_default_preview_does_not_change_existing_proposals_until_submitted(web):
    item = proposal(32, "legacy", kind="event", title="Skype-Termin",
        known_temporal_facts={"start": "2030-11-20T14:00:00+01:00"}, open_questions=["Wann endet der Termin?"])
    save_mail(web.store, 32, "synthetic@example.test", "Synthetisch", [item])
    form = web.form("/abgleich", action="/abgleich", kind="reapply_defaults", proposal_id=item.id)
    assert web.dialog.repository.load_current(item.source_mail_id, item.id).end is None
    assert web.browser.request("POST", "/abgleich", form).status == 303
    web.run()
    current = web.dialog.repository.load_current(item.source_mail_id, item.id)
    assert current.version == 2 and current.end.hour == 15 and current.end_origin == "standard"
    assert web.writer.created == 0


def test_missing_already_existing_event_restored_without_reopening_or_external_write(web):
    item = proposal(33, "existing", kind="event", title="Beiratssitzung", status="already_exists",
        duplicate_match={"source": "google_calendar", "matched_title": "Synthetic"},
        start="2030-11-20T14:00:00+01:00", end="2030-11-20T15:30:00+01:00")
    save_mail(web.store, 33, "synthetic@example.test", "Synthetisch", [item])
    web.store.delete(f"proposal-{item.source_mail_id}-{item.id}")
    post(web, kind="restore_proposal", proposal_id=item.id)
    current = web.dialog.repository.load_current(item.source_mail_id, item.id)
    assert current.status == "already_exists" and current.version == item.version
    page = web.browser.request("GET", f"/mail/{item.source_mail_id}").body.decode()
    assert "Bereits vorhanden" in page and "Beiratssitzung" in page
    assert web.writer.created == 0


def test_relation_display_is_bidirectional_and_ignores_unrelated_or_missing_target(web):
    first, second = pair(web)
    service = ProposalReconciliationService(web.store)
    event = proposal(34, "event", kind="event", title="Videokonferenz", status="already_exists",
        duplicate_match={"source": "google_calendar", "matched_title": "Synthetic"},
        start="2030-11-20T14:00:00+01:00", end="2030-11-20T15:30:00+01:00")
    save_mail(web.store, 34, "synthetic@example.test", "Synthetisch", [event])
    service.relate(first, event)
    service.relate(second, proposal(35, "missing"))
    for item, expected in ((first, "bereits im Kalender"), (event, first.title)):
        page = web.browser.request("GET", f"/vorschlag/{item.source_mail_id}/{item.id}")
        assert page.status == 200 and expected in page.body.decode()
    assert web.site.reconciliation_page.fragment("missing", "missing") == ""
    assert web.site.reconciliation_page.mail_summary("missing") == ""
    assert web.browser.request("GET", f"/vorschlag/{second.source_mail_id}/{second.id}").status == 200


def test_disappearing_relation_does_not_produce_an_unverified_link(web, monkeypatch):
    first, second = pair(web)
    ProposalReconciliationService(web.store).relate(first, second)
    peek = web.store.peek_model
    monkeypatch.setattr(web.store, "peek_model", lambda name, *args, **kwargs:
                        None if name.startswith("reconciliation-relation-") else peek(name, *args, **kwargs))
    with pytest.raises(ValueError, match="Verknüpfung"):
        web.site.reconciliation_page.fragment(first.source_mail_id, first.id)


def test_queued_local_merge_rechecks_revoked_session_and_both_versions(web):
    first, second = pair(web)
    form = web.form("/abgleich", action="/abgleich", kind="merge_proposals", proposal_id=second.id)
    assert web.browser.request("POST", "/abgleich", {**form, "csrf": "invalid"}).status == 403
    assert web.browser.request("POST", "/abgleich", form).status == 303
    web.auth.revoke_all()
    web.run()
    assert web.dialog.repository.load_current(second.source_mail_id, second.id) == second
    assert web.writer.created == 0


@pytest.mark.parametrize("changes", [{"version": "999"}, {"target_version": "999"},
    {"version": "invalid"}, {"kind": "confirm"}, {"target_mail_id": ""}])
def test_stale_or_invalid_form_never_changes_a_proposal(web, changes):
    first, second = pair(web)
    form = web.form("/abgleich", action="/abgleich", kind="merge_proposals", proposal_id=second.id)
    web.browser.request("POST", "/abgleich", {**form, **changes})
    web.run()
    assert web.dialog.repository.load_current(first.source_mail_id, first.id) == first
    assert web.dialog.repository.load_current(second.source_mail_id, second.id) == second
    assert web.writer.created == 0


def test_corrupt_current_record_and_canonical_cycle_are_blocked(web):
    first, second = pair(web)
    web.store.save(f"proposal-{first.source_mail_id}-{first.id}", {"bad": "record"})
    assert web.browser.request("GET", "/abgleich").status == 409
    assert web.browser.request("GET", f"/vorschlag/{first.source_mail_id}/{first.id}").status == 409
    for item, other in ((first, second), (second, first)):
        web.store.save(f"proposal-{item.source_mail_id}-{item.id}", item.model_copy(update={"status": ProposalStatus.MERGED,
            "canonical_ref": ProposalReference(mail_id=other.source_mail_id, proposal_id=other.id)}).model_dump(mode="json"))
    assert web.browser.request("GET", f"/vorschlag/{first.source_mail_id}/{first.id}").status == 409


@pytest.mark.parametrize("kind", [CommandKind.RESTORE, CommandKind.DEFAULTS])
def test_hash_bound_local_revision_rejects_changed_preview(web, kind):
    first, _ = pair(web)
    cmd = ReviewCommand(kind=kind, source=CommandSource.WEB,
        actor="web:" + web.auth.sessions()[0].id, idempotency_key="changed-preview", mail_id=first.source_mail_id,
        proposal_id=first.id, version=first.version, proposal_hash="0" * 64)
    assert web.dialog.review.execute(cmd).status == ResultStatus.STALE
    assert web.dialog.repository.load_current(first.source_mail_id, first.id) == first


def test_recheck_failure_then_recovery_keeps_separate_confirmation(web):
    first, _ = pair(web)
    failed = first.model_copy(update={"duplicate_check_failed": True, "status": ProposalStatus.NEEDS_CLARIFICATION,
        "open_questions": ["Dublettenprüfung nicht verfügbar; vor einer Anlage erneut prüfen."]})
    web.dialog.persist(failed)
    web.dialog.decision_service.precheck = SimpleNamespace(check_proposal=lambda p: p)
    post(web, kind="recheck_proposal", proposal_id=first.id)
    current = web.dialog.repository.load_current(first.source_mail_id, first.id)
    assert current.version == 2 and not current.duplicate_check_failed and current.status == "pending_confirmation"
    assert web.writer.created == 0


def test_default_command_uses_active_settings_and_refuses_closed_target(web):
    first, _ = pair(web)
    defaults = EventDefaultsSettings(video_duration_minutes=75)
    web.dialog.review.configuration = SimpleNamespace(active=SimpleNamespace(event_defaults=defaults))
    web.site.archive.configuration = web.dialog.review.configuration
    assert web.site.reconciliation_page.defaults() == defaults
    closed = first.model_copy(update={"status": ProposalStatus.REJECTED})
    web.dialog.persist(closed)
    cmd = ReviewCommand(kind="reapply_defaults", source="web", actor="web:" + web.auth.sessions()[0].id,
        mail_id=closed.source_mail_id, proposal_id=closed.id, version=closed.version,
        idempotency_key="closed-defaults", proposal_hash=digest(defaults.model_dump()))
    assert web.dialog.review.execute(cmd).status == ResultStatus.STALE


def test_abgleich_endpoint_rejects_otherwise_valid_non_reconciliation_command(web):
    first, second = pair(web)
    form = web.form("/abgleich", action="/abgleich", kind="merge_proposals", proposal_id=second.id)
    form = {k: v for k, v in form.items() if not k.startswith("target_")}
    form["kind"] = "confirm"
    assert web.browser.request("POST", "/abgleich", form).status == 422
    assert web.writer.created == 0


def test_preview_missing_canonical_target_and_disappearing_mail_fail_safely(web, monkeypatch):
    first, second = pair(web, uncertain=True)
    web.store.delete(f"proposal-{first.source_mail_id}-{first.id}")
    assert web.browser.request("GET", "/abgleich").status == 200
    names = web.store.names
    monkeypatch.setattr(web.store, "names", lambda prefix="":
                        ["mail-" + "f" * 24] if prefix == "mail-" else names(prefix))
    assert web.browser.request("GET", "/abgleich").status == 409


def test_closed_candidate_offers_separation_without_editing_or_notifying_the_closed_target(web):
    first, second = pair(web)
    first = first.model_copy(update={"status": ProposalStatus.CONFIRMED})
    second = second.model_copy(update={"status": ProposalStatus.NEEDS_CLARIFICATION,
        "matching_candidates": [ProposalReference(mail_id=first.source_mail_id, proposal_id=first.id)],
        "open_questions": ["Zuordnung der zusätzlichen Quelle prüfen."]})
    web.dialog.repository.save_revision(first)
    web.dialog.repository.save_revision(second)
    form = web.form("/abgleich", action="/abgleich", kind="separate_proposals", proposal_id=second.id)
    assert web.browser.request("POST", "/abgleich", form).status == 303
    # Execute queued review commands alone; the separate write-recovery test
    # covers a confirmed target. This command must not perform that recovery write.
    web.dialog._process_commands()
    assert web.dialog.repository.load_current(first.source_mail_id, first.id) == first
    assert not web.dialog.repository.load_current(second.source_mail_id, second.id).matching_candidates
    assert web.writer.created == 0


def test_regression_restoring_a_confirmed_projection_never_creates_a_new_write_version(web):
    item = proposal(70, "interrupted", status="confirmed")
    save_mail(web.store, 70, "synthetic@example.test", "Synthetisch", [item])
    web.store.delete(f"proposal-{item.source_mail_id}-{item.id}")
    form = web.form("/abgleich", action="/abgleich", kind="restore_proposal", proposal_id=item.id)
    web.browser.request("POST", "/abgleich", form)
    web.dialog._process_commands()
    restored = web.dialog.repository.load_current(item.source_mail_id, item.id)
    web.dialog.write_executor.execute(restored)
    assert web.writer.created == 0
    assert restored.version == item.version and restored.status == "uncertain"


def test_restore_recovery_recognizes_a_repaired_open_record_without_new_version(web):
    first, _ = pair(web)
    command = ReviewCommand(kind="restore_proposal", source="web", actor="web:" + web.auth.sessions()[0].id,
        mail_id=first.source_mail_id, proposal_id=first.id, version=first.version,
        proposal_hash=digest(first.model_dump(mode="json")), idempotency_key="restored-before-result")
    assert web.dialog.review.reconcile(command).status == ResultStatus.DONE
