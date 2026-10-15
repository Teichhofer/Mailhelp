"""Credential settings on desktop, phones and with JavaScript disabled."""
from playwright.sync_api import expect

from checks import audit
from conftest import sign_in
from mailhelp.config import _dotenv


def credential_form(page, name):
    return page.locator(f'#settings-credentials form:has(input[name="name"][value="{name}"])')


def test_separate_credentials_area_is_accessible_and_saves_without_echoing_values(page, mailhelp):
    directory = mailhelp.site.archive.configuration.directory
    original = 'IMAP_PASSWORD="synthetic-before"\n# retained\n'
    (directory / ".env").write_text(original)
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/einstellungen")
    page.get_by_role("navigation", name="Einstellungsbereiche").get_by_role("link", name="Zugangsdaten").click()
    section = page.get_by_role("region", name="Zugangsdaten", exact=True)
    expect(section).to_be_visible()
    assert "synthetic-before" not in page.content()
    assert audit(page, "credentials-closed-" + page.device, page.mobile) == []
    details = credential_form(page, "IMAP_PASSWORD").locator("..")
    details.locator("summary").click()
    form = credential_form(page, "IMAP_PASSWORD")
    value = form.get_by_label("Neuer Wert für IMAP-Passwort", exact=True)
    expect(value).to_have_attribute("type", "password")
    expect(value).to_have_attribute("autocomplete", "new-password")
    expect(value).to_have_value("")
    assert audit(page, "credentials-open-" + page.device, page.mobile) == []
    config = (directory / "config.yaml").read_bytes()
    value.fill("synthetic-after")
    form.get_by_role("button", name="Zugang speichern", exact=True).click()
    expect(page.get_by_role("heading", name="Zugangsdaten gespeichert", exact=True)).to_be_visible()
    assert "synthetic-after" not in page.content()
    assert _dotenv(directory / ".env")["IMAP_PASSWORD"] == "synthetic-after"
    assert "# retained" in (directory / ".env").read_text()
    assert (directory / "config.yaml").read_bytes() == config
    assert mailhelp.writer.created == []
    page.get_by_role("link", name="Zurück zu Zugangsdaten").click()
    form = credential_form(page, "IMAP_PASSWORD")
    form.locator("..").locator("summary").click()
    expect(form.get_by_label("Neuer Wert für IMAP-Passwort", exact=True)).to_have_value("")
    page.emulate_media(color_scheme="dark")
    assert audit(page, "credentials-dark-" + page.device, page.mobile) == []
    assert page.errors == []


def test_credential_editing_works_without_javascript(browser, mailhelp):
    context = browser.new_context(java_script_enabled=False)
    page = context.new_page()
    try:
        sign_in(page, mailhelp)
        page.goto(mailhelp.url + "/einstellungen#settings-credentials")
        form = credential_form(page, "OPENROUTER_API_KEY")
        form.locator("..").locator("summary").click()
        form.get_by_label("Neuer Wert für OpenRouter API-Schlüssel", exact=True).fill("synthetic-api-key")
        form.get_by_role("button", name="Zugang speichern", exact=True).click()
        expect(page.get_by_role("heading", name="Zugangsdaten gespeichert", exact=True)).to_be_visible()
        assert "synthetic-api-key" not in page.content()
        directory = mailhelp.site.archive.configuration.directory
        assert _dotenv(directory / ".env")["OPENROUTER_API_KEY"] == "synthetic-api-key"
        assert mailhelp.writer.created == []
    finally:
        context.close()
