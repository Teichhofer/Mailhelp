"""A failed source folder is visible before any mail can be analysed."""
from playwright.sync_api import expect

from checks import audit
from conftest import sign_in


def test_status_shows_and_clears_folder_failures_in_both_themes(page, mailhelp):
    metrics = mailhelp.site.archive.metrics
    metrics.observe("optional_folder_failed", {"service": "imap", "account_id": "a" * 24,
                    "mailbox": 1, "folder": "Gesendet", "error": "IMAP-Ordner nicht lesbar: Gesendet"})
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/status")
    heading = page.get_by_role("heading", name="Aktuelle IMAP-Abruffehler")
    expect(heading).to_be_visible()
    expect(page.get_by_text("Postfach 1 · zusätzlicher Ordner: Gesendet")).to_be_visible()
    assert audit(page, "imap-errors-" + page.device, page.mobile) == []
    page.emulate_media(color_scheme="dark")
    assert audit(page, "imap-errors-dark-" + page.device, page.mobile) == []
    metrics.observe("messages_discovered", {"service": "imap", "account_id": "a" * 24,
                    "folder": "Gesendet", "available_count": 0})
    page.reload()
    expect(heading).to_have_count(0)
    assert mailhelp.writer.created == []
