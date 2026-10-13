"""Deciding in the browser: confirm, answer, quick answers, relevance (desktop and iPhone)."""
from __future__ import annotations

from playwright.sync_api import expect
from web_scenario import mail_id

from checks import audit
from conftest import act, item, sign_in


def card(page, number, pid):
    return item(page, f"#v-{mail_id(number)}-{pid}")


def test_overview_with_actions_is_easy_to_operate(page, mailhelp):
    sign_in(page, mailhelp)
    current = card(page, 1, "elternabend")
    expect(current.get_by_role("button", name="Im Kalender anlegen")).to_be_visible()
    expect(card(page, 2, "zahnarzt").get_by_label("Wann beginnt der Termin?")).to_be_visible()
    expect(card(page, 3, "fest").get_by_role("button", name="Ja", exact=True)).to_be_visible()
    assert audit(page, f"aktionen-uebersicht-{page.device}", page.mobile) == []
    formular = card(page, 1, "formular")
    formular.get_by_text("Ändern", exact=True).click()
    expect(formular.get_by_label("Was soll geändert werden?")).to_be_visible()
    assert audit(page, f"aktionen-aendern-{page.device}", page.mobile) == []
    assert page.errors == []


def test_confirm_in_the_browser_creates_the_entry_once(page, mailhelp):
    sign_in(page, mailhelp)
    act(page, card(page, 1, "elternabend").get_by_role("button", name="Im Kalender anlegen"), "Angelegt.")
    assert audit(page, f"aktion-ergebnis-{page.device}", page.mobile) == []
    expect(page.locator(f"#v-{mail_id(1)}-elternabend")).to_have_count(0)
    expect(page.locator(".recent")).to_contain_text("Elternabend Klasse 4b")
    assert mailhelp.writer.created == ["Elternabend Klasse 4b"]
    assert any("Angelegt im Kalender" in text for text in mailhelp.telegram.sent)
    assert page.errors == []


def test_answering_questions_until_the_proposal_can_be_confirmed(page, mailhelp):
    sign_in(page, mailhelp)
    dentist = card(page, 2, "zahnarzt")
    dentist.get_by_label("Wann beginnt der Termin?").fill("10 Uhr")
    act(page, dentist.get_by_role("button", name="Antwort senden"), "Antwort übernommen")
    dentist = card(page, 2, "zahnarzt")
    expect(dentist.get_by_label("Wann endet der Termin?")).to_be_visible()
    assert audit(page, f"aktion-folgefrage-{page.device}", page.mobile) == []
    dentist.get_by_label("Wann endet der Termin?").fill("10:30")
    act(page, dentist.get_by_role("button", name="Antwort senden"), "Antwort übernommen")
    dentist = card(page, 2, "zahnarzt")
    expect(dentist).to_contain_text("23.10.2026, 10:00–10:30 Uhr")
    act(page, dentist.get_by_role("button", name="Im Kalender anlegen"), "Angelegt.")
    assert mailhelp.writer.created == ["Zahnarzt Kontrolle"]
    assert page.errors == []


def test_quick_answer_and_relevance_buttons(page, mailhelp):
    from web_scenario import Revisions  # noqa: F401  (documents the simulated revision)

    class Handler:
        def __init__(self, store):
            self.store = store

        def resolve_relevance(self, mail, version, decision, offset):
            from shared_telegram_dialog import RelevanceHandler
            return RelevanceHandler(self.store).resolve_relevance(mail, version, decision, offset)

        def resume_mail(self, state):
            pass

    mailhelp.dialog.relevance_handler = Handler(mailhelp.store)
    sign_in(page, mailhelp)
    act(page, card(page, 3, "fest").get_by_role("button", name="Ja", exact=True), "Antwort übernommen")
    expect(card(page, 3, "fest").get_by_role("button", name="Im Kalender anlegen")).to_be_visible()
    act(page, item(page, f"#r-{mail_id(7)}").get_by_role("button", name="Irrelevant"),
        "Mail als irrelevant eingestuft.")
    expect(page.locator(f"#r-{mail_id(7)}")).to_have_count(0)
    assert "🌐 Im Web: Mail als irrelevant eingestuft." in mailhelp.telegram.sent
    assert page.errors == []


def test_an_outdated_form_is_explained(page, mailhelp):
    sign_in(page, mailhelp)
    formular = card(page, 1, "formular")
    # Decided elsewhere (e.g. in Telegram) while this page was open.
    page.evaluate("""document.querySelectorAll('input[name="version"]').forEach(
        (input) => { input.value = '9'; })""")
    formular.get_by_role("button", name="Verwerfen").click()
    expect(page.get_by_role("heading", name="Nicht mehr aktuell")).to_be_visible(timeout=15000)
    assert audit(page, f"aktion-veraltet-{page.device}", page.mobile) == []
    page.errors[:] = [error for error in page.errors if "409" not in error]
    assert page.errors == []
