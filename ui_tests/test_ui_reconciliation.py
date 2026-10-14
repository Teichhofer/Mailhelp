"""Local reconciliation on desktop, narrow phones and without JavaScript."""
from playwright.sync_api import expect
from web_scenario import proposal, save_mail

from checks import audit
from conftest import sign_in
from mailhelp.domain.proposal_sources import ProposalReference


def legacy(mailhelp):
    item = proposal(50, "legacy", kind="event", title="Skype-Konferenz", evidence="Synthetische Online-Einladung",
        known_temporal_facts={"start": "2030-11-20T14:00:00+01:00"}, open_questions=["Wann endet der Termin?"])
    save_mail(mailhelp.store, 50, "synthetic@example.test", "Synthetische Einladung", [item])
    return item


def test_preview_is_accessible_and_explicit_duration_revision_is_local(page, mailhelp):
    item = legacy(mailhelp)
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/abgleich")
    expect(page.get_by_role("heading", name="Vorschlagsabgleich", exact=True)).to_be_visible()
    assert audit(page, "reconciliation-" + page.device, page.mobile) == []
    page.get_by_role("button", name="Dauerannahme ausdrücklich übernehmen").click()
    expect(page.get_by_role("status").filter(has_text="separat bestätigen")).to_be_visible(timeout=10000)
    current = mailhelp.dialog.repository.load_current(item.source_mail_id, item.id)
    assert current.end.hour == 15 and current.default_duration_minutes == 60 and current.version == 2
    assert mailhelp.writer.created == []


def test_duration_preview_and_revision_work_without_javascript(browser, mailhelp):
    item = legacy(mailhelp)
    context = browser.new_context(java_script_enabled=False, viewport={"width": 390, "height": 844})
    page = context.new_page()
    try:
        sign_in(page, mailhelp)
        page.goto(mailhelp.url + "/abgleich")
        page.get_by_role("button", name="Dauerannahme ausdrücklich übernehmen").click()
        expect(page.get_by_role("status")).to_contain_text("separat bestätigen", timeout=10000)
        assert mailhelp.dialog.repository.load_current(item.source_mail_id, item.id).version == 2
        assert mailhelp.writer.created == []
    finally:
        context.close()


def test_closed_match_can_be_kept_independent_without_an_external_write(page, mailhelp):
    target = proposal(60, "closed", title="Synthetische Aufgabe", status="rejected")
    source = proposal(61, "independent", title=target.title,
        matching_candidates=[ProposalReference(mail_id=target.source_mail_id, proposal_id=target.id)],
        open_questions=["Zuordnung der zusätzlichen Quelle prüfen."])
    save_mail(mailhelp.store, 60, "synthetic@example.test", "Synthetisch", [target])
    save_mail(mailhelp.store, 61, "synthetic@example.test", "Synthetisch", [source])
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/abgleich")
    page.get_by_role("button", name="Als eigenen Vorschlag behalten", exact=True).click()
    expect(page.get_by_role("status").filter(has_text="separat bestätigen")).to_be_visible(timeout=10000)
    assert mailhelp.dialog.repository.load_current(target.source_mail_id, target.id) == target
    assert mailhelp.dialog.repository.load_current(source.source_mail_id, source.id).matching_candidates == []
    assert mailhelp.writer.created == []
