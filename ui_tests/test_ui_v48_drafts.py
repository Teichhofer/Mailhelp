"""Reply previews and clipboard behavior on desktop and small screens."""
from types import SimpleNamespace

from playwright.sync_api import expect

from checks import audit
from conftest import sign_in
from pages import SettingsPage
from tests.scenarios.web_scenario import mail_id


def show_preview(page, mailhelp):
    text = "Vielen Dank.\n[Termin vorschlagen]\n\nGrüße"
    mailhelp.site.experience.drafts = SimpleNamespace(
        available=lambda _: True,
        get=lambda _: {"version": 1, "status": "saved", "text": text, "auto": True})
    sign_in(page, mailhelp)
    page.goto(f"{mailhelp.url}/mail/{mail_id(1)}")
    return text


def test_saved_draft_is_readonly_and_copies_exact_text(page, mailhelp):
    text = show_preview(page, mailhelp)
    expect(page.get_by_label("Antworttext")).to_have_value(text)
    expect(page.get_by_label("Antworttext")).to_have_attribute("readonly", "")
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    page.get_by_role("button", name="Antworttext kopieren").click()
    expect(page.locator("[data-copy-status]")).to_have_text("Antworttext kopiert.")
    # Windows normalizes native clipboard line endings to CRLF.
    assert page.evaluate("navigator.clipboard.readText()").replace("\r\n", "\n") == text
    assert audit(page, f"v48-draft-{page.device}", page.mobile) == []
    assert page.errors == []


def test_copy_refusal_and_unavailable_clipboard_offer_manual_copy(page, mailhelp):
    show_preview(page, mailhelp)
    page.evaluate("Object.defineProperty(navigator, 'clipboard', {configurable:true, value: "
                  "{writeText: () => Promise.reject(new Error('denied'))}})")
    page.get_by_role("button", name="Antworttext kopieren").click()
    expect(page.locator("[data-copy-status]")).to_contain_text("Kopieren nicht erlaubt")
    page.evaluate("Object.defineProperty(navigator, 'clipboard', {configurable:true, value:undefined})")
    page.get_by_role("button", name="Antworttext kopieren").click()
    expect(page.locator("[data-copy-status]")).to_contain_text("manuell kopieren")
    assert page.errors == []


def test_draft_switch_and_manual_folder_can_be_saved_in_the_browser(page, mailhelp):
    sign_in(page, mailhelp)
    settings = SettingsPage(page, mailhelp.url).open("antworten")
    setting = settings.expand("Antwortentwürfe zulassen")
    assert audit(page, f"v48-settings-{page.device}", page.mobile) == []
    setting.get_by_label("Neuer Wert").select_option("false")
    setting.get_by_role("button", name="Prüfen").click()
    settings.confirm()
    expect(page.locator("main")).to_contain_text("Gespeichert", timeout=10000)
    assert mailhelp.site.archive.configuration.active.drafts.enabled is False
    settings.open("antworten")
    setting = settings.expand("Entwurfsordner überschreiben")
    settings.propose(setting, "Antworten")
    settings.confirm()
    expect(page.locator("main")).to_contain_text("Gespeichert", timeout=10000)
    assert mailhelp.site.archive.configuration.active.drafts.folder == "Antworten"
    assert page.errors == []
