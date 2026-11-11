"""5.4 regressions: the chat stays above settings across real document replacements."""
from playwright.sync_api import expect

from checks import audit
from conftest import sign_in
from tests.fakes.help_window54 import chat_service


def test_window54_opens_without_navigation_and_survives_search_and_reload(page, mailhelp):
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/einstellungen")
    page.get_by_label("Hilfschat öffnen", exact=True).click()
    expect(page.page).to_have_url(mailhelp.url + "/einstellungen")
    window = page.get_by_role("region", name="Hilfe zu Einstellungen", exact=True)
    expect(window).to_be_visible()
    page.get_by_label("Deine Frage zu Einstellungen und Bedienung").fill("Mein noch nicht gesendeter Entwurf")
    page.get_by_role("searchbox", name="Einstellung suchen").fill("Zeitzone")
    page.get_by_role("button", name="Suchen", exact=True).click()
    expect(window).to_be_visible()
    expect(page.get_by_label("Deine Frage zu Einstellungen und Bedienung")).to_have_value(
        "Mein noch nicht gesendeter Entwurf")
    page.reload()
    expect(window).to_be_visible()
    page.keyboard.press("Escape")
    expect(window).to_be_visible()
    page.get_by_role("button", name="Hilfschat schließen", exact=True).click()
    expect(window).to_be_hidden()
    page.reload()
    expect(window).to_be_hidden()
    page.get_by_label("Hilfschat öffnen", exact=True).click()
    expect(page.get_by_label("Deine Frage zu Einstellungen und Bedienung")).to_have_value(
        "Mein noch nicht gesendeter Entwurf")
    assert page.errors == []


def test_window54_survives_real_edit_confirmation_and_saving(page, mailhelp):
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/einstellungen?bereich=abruf")
    page.get_by_label("Hilfschat öffnen", exact=True).click()
    window = page.get_by_role("region", name="Hilfe zu Einstellungen", exact=True)
    page.get_by_label("Deine Frage zu Einstellungen und Bedienung").fill("Was bedeutet 75 Sekunden?")
    row = page.locator("#einstellung-poll-interval-seconds")
    row.locator("summary").click()
    row.get_by_label("Neuer Wert", exact=True).fill("75")
    row.get_by_role("button", name="Prüfen", exact=True).click()
    expect(page.get_by_role("heading", name="Änderung bestätigen")).to_be_visible()
    expect(window).to_be_visible()
    expect(page.get_by_label("Deine Frage zu Einstellungen und Bedienung")).to_have_value("Was bedeutet 75 Sekunden?")
    page.get_by_role("button", name="Änderung ausdrücklich speichern", exact=True).click()
    expect(page.get_by_text("Gespeichert. Pollintervall", exact=False)).to_be_visible(timeout=15000)
    expect(window).to_be_visible()
    expect(page.get_by_label("Deine Frage zu Einstellungen und Bedienung")).to_have_value("Was bedeutet 75 Sekunden?")
    assert mailhelp.site.archive.configuration.active.poll_interval_seconds == 75
    assert mailhelp.writer.created == [] and page.errors == []


def test_window54_answer_preserves_the_background_form_and_sources_open_inside(page, mailhelp):
    service = chat_service(mailhelp)
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/einstellungen?bereich=abruf")
    row = page.locator("#einstellung-poll-interval-seconds")
    row.locator("a.ask-help").click()
    page.get_by_label("Deine Frage zu Einstellungen und Bedienung").fill("Was bedeutet das Abrufintervall?")
    page.get_by_role("button", name="Frage senden", exact=True).click()
    expect(page.get_by_text("Antwort wird vorbereitet", exact=False)).to_be_visible()
    row.locator("summary").click()
    value = row.get_by_label("Neuer Wert", exact=True)
    value.fill("88")
    value.focus()
    service.run_once()
    expect(page.locator(".help-answer")).to_have_text("Das Intervall steuert den Mailabruf.", timeout=10000)
    expect(value).to_have_value("88")
    expect(value).to_be_focused()
    page.get_by_label("Deine Frage zu Einstellungen und Bedienung").fill("Und pro Postfach?")
    page.locator(".help-sources a").first.click()
    expect(page.locator("#help-document")).to_be_visible()
    expect(page.page).to_have_url(mailhelp.url + "/einstellungen?bereich=abruf")
    page.get_by_role("button", name="Zurück zum Gespräch", exact=True).click()
    expect(page.get_by_label("Deine Frage zu Einstellungen und Bedienung")).to_have_value("Und pro Postfach?")
    assert audit(page, "help-window54-answer-" + page.device, page.mobile) == []
    page.get_by_role("button", name="Chat leeren", exact=True).click()
    expect(page.locator(".help-turn")).to_have_count(0)
    expect(page.get_by_label("Deine Frage zu Einstellungen und Bedienung")).to_have_value("")
    assert page.errors == []


def test_window54_no_javascript_open_draft_search_and_close(page, mailhelp):
    page.cdp.send("Emulation.setScriptExecutionDisabled", {"value": True})
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/einstellungen")
    page.get_by_role("button", name="Hilfschat öffnen", exact=True).click()
    window = page.get_by_role("region", name="Hilfe zu Einstellungen", exact=True)
    expect(window).to_be_visible()
    page.get_by_label("Deine Frage zu Einstellungen und Bedienung").fill("Entwurf ohne JavaScript")
    page.get_by_role("button", name="Entwurf behalten", exact=True).click()
    expect(window).to_be_visible()
    if page.mobile:
        page.get_by_role("button", name="Chatfenster nach oben", exact=True).click()
    page.get_by_role("searchbox", name="Einstellung suchen").fill("Zeitzone")
    page.get_by_role("button", name="Suchen", exact=True).click()
    expect(window).to_be_visible()
    expect(page.get_by_label("Deine Frage zu Einstellungen und Bedienung")).to_have_value("Entwurf ohne JavaScript")
    page.get_by_role("button", name="Hilfschat schließen", exact=True).click()
    expect(window).to_be_hidden()


def test_window54_blocked_storage_keeps_state_and_draft_across_navigation(page, mailhelp):
    page.add_init_script("""Object.defineProperty(window, 'sessionStorage', {
        get() { throw new Error('synthetic blocked storage'); }
    });""")
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/einstellungen")
    page.get_by_label("Hilfschat öffnen", exact=True).click()
    page.get_by_label("Deine Frage zu Einstellungen und Bedienung").fill("Entwurf bei gesperrtem Speicher")
    page.get_by_role("searchbox", name="Einstellung suchen").fill("Zeitzone")
    page.get_by_role("button", name="Suchen", exact=True).click()
    expect(page.get_by_role("region", name="Hilfe zu Einstellungen", exact=True)).to_be_visible()
    expect(page.get_by_label("Deine Frage zu Einstellungen und Bedienung")).to_have_value(
        "Entwurf bei gesperrtem Speicher")
    page.get_by_role("button", name="Hilfschat schließen", exact=True).click()
    expect(page.get_by_role("region", name="Hilfe zu Einstellungen", exact=True)).to_be_hidden()
    assert page.errors == []


def test_window54_keyboard_position_and_drag_are_restored(page, mailhelp):
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/einstellungen")
    page.get_by_label("Hilfschat öffnen", exact=True).click()
    panel = page.locator("#help-window")
    page.get_by_role("button", name="Chatfenster nach links", exact=True).click()
    page.get_by_role("button", name="Chatfenster nach oben", exact=True).click()
    page.get_by_role("button", name="Chatfenster nach rechts", exact=True).click()
    page.get_by_role("button", name="Chatfenster nach unten", exact=True).click()
    head = page.locator(".help-window-head h2").bounding_box()
    page.mouse.move(head["x"] + 10, head["y"] + 10)
    page.mouse.down()
    page.mouse.move(20, 20, steps=3)
    page.mouse.up()
    box = panel.bounding_box()
    page.reload()
    expect(panel).to_be_visible()
    restored = panel.bounding_box()
    assert abs(restored["x"] - box["x"]) <= 2
    assert abs(restored["y"] - box["y"]) <= 2
    assert audit(page, "help-window54-position-" + page.device, page.mobile) == []
    assert page.errors == []
