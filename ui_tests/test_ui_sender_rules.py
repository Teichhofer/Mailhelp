"""7.7.3: the sender rules page in real browsers – preview, save, switch off, remove."""
from __future__ import annotations

from playwright.sync_api import expect

from conftest import sign_in
from mailhelp.persistence.storage import JsonStore


def test_a_rule_is_previewed_saved_switched_off_and_removed(page, mailhelp, tmp_path):
    configuration = mailhelp.site.archive.configuration
    with JsonStore(tmp_path / "absender") as senders:
        configuration.senders = senders
        try:
            sign_in(page, mailhelp)
            page.goto(f"{mailhelp.url}/einstellungen/ignorierte-absender")
            expect(page.get_by_role("heading", name="Absender-Regeln", exact=True)).to_be_visible()
            page.get_by_label("Art").select_option("pattern")
            page.get_by_label("Wert").fill("no-reply@*")
            page.get_by_role("button", name="Treffer prüfen").click()
            expect(page.get_by_text("Diese Regel würde")).to_be_visible()
            page.get_by_role("button", name="Regel speichern").click()
            main = page.locator("main")
            expect(main).to_contain_text("wird künftig ohne KI-Aufruf aussortiert", timeout=10000)
            expect(page.locator(".sender-list").first).to_contain_text("no-reply@*")
            page.get_by_role("button", name="Ausschalten").click()
            expect(main).to_contain_text("Regel ausgeschaltet.", timeout=10000)
            page.get_by_role("button", name="Entfernen").click()
            expect(main).to_contain_text("Regel für „no-reply@*“ entfernt.", timeout=10000)
            expect(main).to_contain_text("Derzeit wird kein Absender ignoriert.")
            assert page.errors == []
        finally:
            configuration.senders = None
