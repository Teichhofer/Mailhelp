"""Mailhelp 2.3 in the browser: full-text search, original documents and the provider choice."""
from __future__ import annotations

from email.message import EmailMessage

from playwright.sync_api import expect
from web_scenario import mail_id

from checks import audit
from conftest import sign_in
from mailhelp.attachments import AttachmentCache
from mailhelp.config import OriginalAttachmentSettings
from mailhelp.models import MailState
from pages import SettingsPage

PDF = b"%PDF-1.7 synthetische Rechnung"


def store_mail(store, text: str, attachments: list[dict]) -> None:
    name = f"mail-{mail_id(1)}"
    state = store.load_model(name, MailState)
    mail = {"headers": {"from": "Schule <info@schule.example>", "subject": "Klassenfahrt"}, "text": text,
            "date_header_parsed": "2026-10-06T10:41:14+00:00", "extracted_attachments": attachments}
    store.save(name, state.model_copy(update={"mail": mail}).model_dump(mode="json"))


def test_search_finds_attachment_text_and_shows_the_place(page, mailhelp):
    store_mail(mailhelp.store, "Die Fahrt kostet 120 Euro.",
               [{"filename": "Elternbrief.pdf", "text": "Treffpunkt am Hauptbahnhof, Gleis 3"}])
    sign_in(page, mailhelp)
    page.goto(f"{mailhelp.url}/mails")
    page.get_by_label("Suche", exact=True).fill("hauptbahnhof")
    page.get_by_role("button", name="Suchen").click()
    hit = page.locator(".search-hit")
    expect(hit).to_contain_text("Gefunden in Anhang „Elternbrief.pdf“")
    expect(hit.locator("mark")).to_have_text("Hauptbahnhof")
    assert audit(page, f"v23-suche-{page.device}", page.mobile) == []
    page.get_by_label("Suchen in").select_option("meta")
    page.get_by_role("button", name="Suchen").click()
    expect(page.get_by_text("Keine gespeicherte Mail passt zu dieser Suche.")).to_be_visible()
    assert page.errors == []


def test_original_document_is_offered_as_a_download(page, mailhelp):
    message = EmailMessage()
    message.set_content("Siehe Anhang.")
    message.add_attachment(PDF, maintype="application", subtype="pdf", filename="Rechnung März.pdf")
    entries = [{"filename": "Rechnung März.pdf", "text": "Betrag 120 Euro"}]
    AttachmentCache(mailhelp.store).prepare(mail_id(1), message.as_bytes(), entries, OriginalAttachmentSettings())
    store_mail(mailhelp.store, "Siehe Anhang.", entries)
    sign_in(page, mailhelp)
    page.goto(f"{mailhelp.url}/mail/{mail_id(1)}")
    link = page.get_by_role("link", name="Original herunterladen")
    expect(link).to_have_attribute("download", "")
    assert audit(page, f"v23-original-{page.device}", page.mobile) == []
    with page.expect_download() as download:
        link.click()
    assert download.value.suggested_filename == "Rechnung März.pdf"
    assert download.value.path().read_bytes() == PDF
    assert page.errors == []


def test_provider_choice_in_the_settings(page, mailhelp):
    sign_in(page, mailhelp)
    settings = SettingsPage(page, mailhelp.url).open()
    calendar = settings.expand("Kalenderdienst")
    choice = calendar.get_by_label("Neuer Wert")
    expect(choice.locator("option")).to_have_text(["Google Kalender", "CalDAV (Nextcloud, iCloud, …)",
                                                   "Outlook / Microsoft 365"])
    tasks = settings.expand("Aufgabendienst")
    expect(tasks.get_by_label("Neuer Wert").locator("option")).to_have_count(4)
    assert audit(page, f"v23-anbieter-{page.device}", page.mobile) == []
    assert page.errors == []
