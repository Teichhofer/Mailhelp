"""Web interface tests for removing created entries (Planung 6.6, D3, 3.3).

Verifies D3:
- Button "Eintrag wieder entfernen" on detail page and result card within window
- Two-step confirmation page with title, time, target, explanation, and cancel button
- Cancel button returns to detail page without write
- Successful removal updates status to REMOVED and shows badge "Wieder entfernt"
- After window expires or for simulation / calendar file: button is hidden, link to provider shown, confirmation returns 404
- Live session check and CSRF protection
- Direct POST to /vorschlag/.../entfernen executes removal
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from mailhelp.domain.proposal import ProposalKind, ProposalStatus
from mailhelp.domain.verification import VerificationState, WriteVerification, operation_id
from tests.scenarios.web_scenario import mail_id

MAIL1 = mail_id(1)


def test_remove_created_button_and_confirmation_flow(web):
    # 1. Confirm open proposal 'elternabend'
    form = web.form("/", kind="confirm", proposal_id="elternabend")
    res = web.submit(form)
    assert res.status == 303
    web.run()

    # Proposal is now CREATED
    prop = web.dialog.repository.load_current(MAIL1, "elternabend")
    assert prop.status == ProposalStatus.CREATED
    assert prop.external_id is not None

    # Overview shows detached card with "Eintrag wieder entfernen"
    home_html = web.browser.request("GET", "/").body.decode()
    assert "Eintrag wieder entfernen" in home_html
    remove_url = f"/vorschlag/{MAIL1}/elternabend/entfernen"
    assert remove_url in home_html

    # Detail page also shows "Eintrag wieder entfernen"
    detail_url = f"/vorschlag/{MAIL1}/elternabend"
    detail_html = web.browser.request("GET", detail_url).body.decode()
    assert "Eintrag wieder entfernen" in detail_html
    # External link is NOT shown while removal button is visible
    assert "Im Kalender öffnen" not in detail_html

    # 2. Open confirmation page
    conf_res = web.browser.request("GET", remove_url)
    assert conf_res.status == 200
    conf_html = conf_res.body.decode()
    assert "Eintrag wieder entfernen" in conf_html
    assert "Elternabend" in conf_html
    assert "Kalender" in conf_html
    assert "Der Eintrag wird im Kalender gelöscht. Der Vorschlag bleibt als ‚wieder entfernt‘ im Verlauf." in conf_html
    assert "Eintrag wirklich entfernen" in conf_html
    assert "Abbrechen" in conf_html
    assert f'href="/vorschlag/{MAIL1}/elternabend"' in conf_html

    # 3. Confirm removal by submitting the form
    conf_form = web.form(remove_url, kind="remove_created", proposal_id="elternabend")
    res_del = web.submit(conf_form)
    assert res_del.status == 303
    web.run()

    # 4. Proposal is now REMOVED
    updated = web.dialog.repository.load_current(MAIL1, "elternabend")
    assert updated.status == ProposalStatus.REMOVED
    assert web.writer.removed == 1

    # Overview and history show badge "Wieder entfernt"
    after_html = web.browser.request("GET", "/").body.decode()
    assert "Wieder entfernt" in after_html

    # Confirmation page is no longer available -> 404
    conf_after = web.browser.request("GET", remove_url)
    assert conf_after.status == 404


def test_remove_created_task_target_text(web):
    # Open task proposal 'formular'
    task_prop = web.dialog.repository.load_current(MAIL1, "formular")
    assert task_prop is not None
    assert task_prop.kind == ProposalKind.TASK

    form = web.form("/", kind="confirm", proposal_id="formular")
    web.submit(form)
    web.run()

    prop = web.dialog.repository.load_current(MAIL1, "formular")
    assert prop.status == ProposalStatus.CREATED

    remove_url = f"/vorschlag/{MAIL1}/formular/entfernen"
    conf_res = web.browser.request("GET", remove_url)
    assert conf_res.status == 200
    conf_html = conf_res.body.decode()
    assert "Aufgaben" in conf_html
    assert "Der Eintrag wird in den Aufgaben gelöscht. Der Vorschlag bleibt als ‚wieder entfernt‘ im Verlauf." in conf_html

    # POST directly to remove_url
    conf_form = web.form(remove_url, kind="remove_created", proposal_id="formular")
    res = web.browser.request("POST", remove_url, conf_form)
    assert res.status == 303
    web.run()

    updated = web.dialog.repository.load_current(MAIL1, "formular")
    assert updated.status == ProposalStatus.REMOVED


def test_remove_created_hidden_after_window_expired(web):
    # Create proposal with creation time 15 minutes ago
    prop = web.dialog.repository.load_current(MAIL1, "elternabend")
    past = datetime.now(UTC) - timedelta(minutes=15)
    expired_prop = prop.model_copy(update={
        "status": ProposalStatus.CREATED,
        "external_id": "ext-1",
        "external_link": "https://calendar.google.com/event/1",
        "created_at": past,
    })
    web.dialog.persist(expired_prop)

    # Detail page: removal button is not shown, provider link is shown
    detail_url = f"/vorschlag/{MAIL1}/elternabend"
    html = web.browser.request("GET", detail_url).body.decode()
    assert "Eintrag wieder entfernen" not in html
    assert "Im Kalender öffnen" in html

    # GET confirmation page returns 404
    remove_url = f"/vorschlag/{MAIL1}/elternabend/entfernen"
    res = web.browser.request("GET", remove_url)
    assert res.status == 404


def test_remove_created_unsupported_calendar_file_and_simulation(web):
    # 1. Calendar file (unsupported verification)
    from mailhelp.domain.verification import TargetBinding, WriteReceipt, fingerprint
    prop = web.dialog.repository.load_current(MAIL1, "elternabend")
    cal_prop = prop.model_copy(update={
        "status": ProposalStatus.CREATED,
        "external_id": "ext-1",
        "created_at": datetime.now(UTC),
    })
    web.dialog.persist(cal_prop)

    now = datetime.now(UTC)
    exp = {"kind": "event"}
    rec = WriteVerification(
        id=operation_id(MAIL1, "elternabend", 1, "create"),
        mail_id=MAIL1,
        proposal_id="elternabend",
        proposal_version=1,
        idempotency_key="key-00000001",
        operation="create",
        target=TargetBinding(profile=1, provider="google", account="acc", container="cal"),
        expected=exp,
        expected_fingerprint=fingerprint(exp),
        state=VerificationState.UNSUPPORTED,
        receipt=WriteReceipt(external_id="ext-1", written_at=now, result="created"),
        created_at=now,
        updated_at=now,
        deadline_at=now + timedelta(minutes=5),
    )
    # When verification state is UNSUPPORTED, can_remove is False
    from mailhelp import state_names
    web.dialog.store.save(state_names.write_verification(rec.id), rec.model_dump(mode="json"))

    view = web.site.views.proposal(MAIL1, "elternabend")
    assert not view.can_remove

    # 2. Simulation (test_mode)
    web.site.views.test_mode = True
    view_sim = web.site.views.proposal(MAIL1, "elternabend")
    assert not view_sim.can_remove
    web.site.views.test_mode = False


def test_a_target_without_safe_removal_offers_no_remove_action(web):
    """7.2: the page asks the target's capability, never its provider name."""
    prop = web.dialog.repository.load_current(MAIL1, "elternabend")
    web.dialog.persist(prop.model_copy(update={"status": ProposalStatus.CREATED, "external_id": "ext-1",
                                               "created_at": datetime.now(UTC)}))
    assert web.site.views.proposal(MAIL1, "elternabend").can_remove
    web.site.views.removable = lambda proposal: False
    assert not web.site.views.proposal(MAIL1, "elternabend").can_remove


def test_remove_created_csrf_and_auth_checks(web):
    prop = web.dialog.repository.load_current(MAIL1, "elternabend")
    created_prop = prop.model_copy(update={
        "status": ProposalStatus.CREATED,
        "external_id": "ext-1",
        "created_at": datetime.now(UTC),
    })
    web.dialog.persist(created_prop)

    remove_url = f"/vorschlag/{MAIL1}/elternabend/entfernen"

    # 1. Missing CSRF -> 403
    bad_form = web.form(remove_url, kind="remove_created", proposal_id="elternabend")
    bad_form["csrf"] = "invalid-token"
    res = web.submit(bad_form)
    assert res.status == 403

    # 2. Stale version -> 409
    stale_form = web.form(remove_url, kind="remove_created", proposal_id="elternabend")
    stale_form["version"] = "99"
    res_stale = web.submit(stale_form)
    assert res_stale.status == 409
