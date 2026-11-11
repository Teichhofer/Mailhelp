"""5.7.2: a topic is edited on its own page, previewed and saved only after an explicit confirmation."""
import yaml
from playwright.sync_api import expect

from checks import audit
from conftest import sign_in


def topics(mailhelp, name="topics.yaml"):
    directory = mailhelp.site.archive.configuration.directory
    return yaml.safe_load((directory / name).read_text(encoding="utf-8"))["topics"]


def test_topic_editor572_preview_and_confirmation_with_id_suggestion(page, mailhelp):
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/themen/relevant/school")
    expect(page.get_by_role("heading", name="Schule", exact=True)).to_be_visible()
    assert audit(page, "topic-editor572-edit-" + page.device, page.mobile) == []
    page.get_by_label("Beschreibung", exact=True).fill("Schulpost und Elternbriefe")
    page.get_by_label("Beispiele", exact=True).fill("Elternabend; Klasse 3\nZeugnis")
    page.get_by_role("button", name="Änderung prüfen", exact=True).click()
    expect(page.get_by_role("heading", name="Änderung prüfen", exact=True)).to_be_visible()
    expect(page.get_by_text("geändert", exact=True)).to_have_count(2)
    assert audit(page, "topic-editor572-preview-" + page.device, page.mobile) == []
    assert topics(mailhelp)[0]["description"] == "Schule", "Die Vorschau schreibt nichts"
    page.get_by_label("Änderung ausdrücklich speichern", exact=True).check()
    page.get_by_role("button", name="Änderung speichern", exact=True).click()
    expect(page.locator("main")).to_contain_text("Themen gespeichert", timeout=10000)
    assert topics(mailhelp)[0]["examples"] == ["Elternabend; Klasse 3", "Zeugnis"]
    # A new topic gets its ID from the name until the ID is typed by hand.
    page.goto(mailhelp.url + "/themen/ausschluss/neu")
    page.get_by_label("Name", exact=True).fill("Größere Ausflüge")
    expect(page.get_by_label("Themen-ID", exact=True)).to_have_value("groessere-ausfluege")
    page.get_by_label("Themen-ID", exact=True).fill("ausflug")
    page.get_by_label("Name", exact=True).fill("Ausflüge")
    expect(page.get_by_label("Themen-ID", exact=True)).to_have_value("ausflug")
    page.get_by_label("Themen-ID", exact=True).fill("")
    page.get_by_label("Name", exact=True).fill("!!!")
    expect(page.get_by_label("Themen-ID", exact=True)).to_have_value("thema")
    page.get_by_label("Name", exact=True).fill("Werbung")
    expect(page.get_by_label("Themen-ID", exact=True)).to_have_value("werbung")
    page.get_by_role("button", name="Änderung prüfen", exact=True).click()
    expect(page.get_by_role("alert")).to_contain_text("Beschreibung")
    expect(page.get_by_label("Name", exact=True)).to_have_value("Werbung")
    # The only console message is the intended 422 of the rejected preview.
    assert [error for error in page.errors if "status of 422" not in error] == []


def test_topic_editor572_works_without_javascript(page, mailhelp):
    page.cdp.send("Emulation.setScriptExecutionDisabled", {"value": True})
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/themen/ausschluss/neu")
    page.get_by_label("Name", exact=True).fill("Werbung")
    page.get_by_label("Beschreibung", exact=True).fill("Newsletter und Angebote")
    page.get_by_role("button", name="Änderung prüfen", exact=True).click()
    expect(page.get_by_role("heading", name="Änderung prüfen", exact=True)).to_be_visible()
    expect(page.get_by_text("Neues Thema: alle Felder", exact=True)).to_be_visible()
    page.get_by_label("Änderung ausdrücklich speichern", exact=True).check()
    page.get_by_role("button", name="Änderung speichern", exact=True).click()
    expect(page.locator("main")).to_contain_text("Themen gespeichert", timeout=10000)
    assert [topic["id"] for topic in topics(mailhelp, "irrelevant_topics.yaml")] == ["werbung"]
