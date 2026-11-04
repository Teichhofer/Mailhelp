"""P8: two independent authenticated contexts show an actual stale-version conflict."""
import pytest
from playwright.sync_api import expect
from web_scenario import mail_id, proposal, save_mail

from conftest import sign_in


@pytest.mark.parametrize("first", [0, 1])
def test_two_contexts_show_version_conflict_without_losing_saved_edit(browser, mailhelp, first):
    contexts = [browser.new_context(java_script_enabled=False) for _ in range(2)]
    try:
        pages = [context.new_page() for context in contexts]
        path = f"/vorschlag/{mail_id(1)}/formular/bearbeiten"
        for index, page in enumerate(pages):
            sign_in(page, mailhelp, f"Sitzung {index + 1}")
            page.goto(mailhelp.url + path)
            page.get_by_label("Titel", exact=True).fill(f"Änderung aus Sitzung {index + 1}")
        winner, loser = pages[first], pages[1 - first]
        winner.get_by_role("button", name="Speichern", exact=True).click()
        expect(winner.get_by_role("status")).to_contain_text("separat bestätigen", timeout=10000)
        loser.get_by_role("button", name="Speichern", exact=True).click()
        expect(loser.locator("main")).to_contain_text("inzwischen geändert oder entschieden")
        current = mailhelp.dialog.repository.load_current(mail_id(1), "formular")
        assert current.version == 2 and current.title == f"Änderung aus Sitzung {first + 1}"
        assert current.status == "pending_confirmation" and mailhelp.writer.created == []
    finally:
        for context in contexts:
            context.close()


def test_unverifiable_legacy_approval_is_visibly_blocked(browser, mailhelp):
    old = proposal(80, "legacy", title="Ungeprüfter Altbestand", status="confirmed")
    save_mail(mailhelp.store, 80, "synthetic@example.test", "Altbestand", [old])
    raw = old.model_dump(mode="json")
    raw.pop("confirmed_web_actor")
    mailhelp.store.save(f"proposal-{old.source_mail_id}-{old.id}", raw)
    mailhelp.dialog.poll_once()
    context = browser.new_context(java_script_enabled=False)
    try:
        page = context.new_page()
        sign_in(page, mailhelp)
        page.goto(f"{mailhelp.url}/vorschlag/{old.source_mail_id}/{old.id}")
        expect(page.locator("main")).to_contain_text("Freigabe des Altbestands nicht prüfbar")
        expect(page.get_by_role("button", name="Als Aufgabe anlegen", exact=True)).to_have_count(0)
        assert mailhelp.writer.created == []
    finally:
        context.close()
