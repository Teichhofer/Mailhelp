"""Details: the complete mail behind a proposal or relevance question."""
from __future__ import annotations

from playwright.sync_api import expect

from checks import audit
from conftest import item, sign_in
from web_scenario import mail_id


def test_details_show_the_complete_mail(page, mailhelp):
    sign_in(page, mailhelp)
    desktop = page.device == "desktop"
    if desktop:
        # The split view shows the details next to the list, without leaving the overview.
        item(page, f"#v-{mail_id(1)}-elternabend")
        scope, prefix = page.locator(".detail-pane"), "#detail-"
    else:
        page.locator(f"#v-{mail_id(1)}-elternabend").get_by_role("link", name="Details").click()
        scope, prefix = page, "#"
    # The source is a secondary section of the decision (progressive disclosure).
    scope.get_by_text("Quellbeleg aus E-Mail / Anhang").click()
    mail = scope.locator(prefix + "mail")
    expect(mail.get_by_role("heading", name="Mail")).to_be_visible()
    expect(mail).to_contain_text("Klassenleitung 4b <klasse4b@schule.test>")
    expect(mail).to_contain_text("Viele Grüße")
    # Links inside the mail are text, never clickable.
    assert mail.locator("a").count() == 0
    assert audit(page, f"details-mail-{page.device}", page.mobile) == []
    if desktop:
        relevance = item(page, f"#r-{mail_id(7)}")
        expect(scope.locator("#detail-mail")).to_contain_text("Hallentraining")
    else:
        page.get_by_role("link", name="← Zur Übersicht").click()
        page.locator(f"#r-{mail_id(7)}").get_by_role("link", name="Details").click()
        expect(page.locator("#mail")).to_contain_text("Hallentraining")
        relevance = page
    assert audit(page, f"details-relevanz-{page.device}", page.mobile) == []
    relevance.get_by_role("button", name="Relevant", exact=True).click()
    expect(page.get_by_role("heading", name="Offene Entscheidungen")).to_be_visible(timeout=10000)
    assert page.errors == []
