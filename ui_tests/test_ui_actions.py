"""Deciding in the browser: confirm, answer, quick answers, relevance (desktop and iPhone)."""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from checks import audit
from conftest import act, item, sign_in
from tests.scenarios.web_scenario import mail_id


def card(page, number, pid):
    return item(page, f"#v-{mail_id(number)}-{pid}")


@pytest.mark.smoke
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


@pytest.mark.smoke
def test_confirm_in_the_browser_creates_the_entry_once(page, mailhelp):
    sign_in(page, mailhelp)
    act(page, card(page, 1, "elternabend").get_by_role("button", name="Im Kalender anlegen"), "Angelegt.")
    assert audit(page, f"aktion-ergebnis-{page.device}", page.mobile) == []
    # 4.4: the decided card is replaced by its durable result ("Deine Aktion") without actions.
    decided = page.locator(f"#v-{mail_id(1)}-elternabend")
    expect(decided).to_contain_text("Deine Aktion")
    expect(decided.get_by_role("button", name="Im Kalender anlegen")).to_have_count(0)
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
    from tests.scenarios.web_scenario import Revisions  # noqa: F401  (documents the simulated revision)

    class Handler:
        def __init__(self, store):
            self.store = store

        def resolve_relevance(self, mail, version, decision, offset):
            from tests.fakes.shared_telegram_dialog import RelevanceHandler
            return RelevanceHandler(self.store).resolve_relevance(mail, version, decision, offset)

        def resume_mail(self, state):
            pass

    mailhelp.dialog.relevance_handler = Handler(mailhelp.store)
    sign_in(page, mailhelp)
    act(page, card(page, 3, "fest").get_by_role("button", name="Ja", exact=True), "Antwort übernommen")
    expect(card(page, 3, "fest").get_by_role("button", name="Im Kalender anlegen")).to_be_visible()
    act(page, item(page, f"#r-{mail_id(7)}").get_by_role("button", name="Irrelevant"),
        "Mail als irrelevant eingestuft.")
    answered = page.locator(f"#r-{mail_id(7)}")
    expect(answered).to_contain_text("Deine Aktion")
    expect(answered.get_by_role("button", name="Irrelevant")).to_have_count(0)
    assert "🌐 Im Web: Mail als irrelevant eingestuft." in mailhelp.telegram.sent
    assert page.errors == []


def test_an_outdated_form_is_explained(page, mailhelp):
    sign_in(page, mailhelp)
    formular = card(page, 1, "formular")
    # Decided elsewhere (e.g. in Telegram) while this page was open.
    page.evaluate("""document.querySelectorAll('input[name="version"]').forEach(
        (input) => { input.value = '9'; })""")
    formular.get_by_role("button", name="Verwerfen").click()
    # 4.4: an unknown newer version is accepted at once; the operator refuses it and the
    # refusal stays on the card until it is acknowledged.
    expect(page.get_by_role("heading", name="Offene Entscheidungen")).to_be_visible(timeout=10000)
    refused = card(page, 1, "formular").get_by_role("alert").first
    expect(refused).to_be_visible(timeout=15000)
    expect(refused.get_by_role("button", name="Zur Kenntnis genommen")).to_be_visible()
    assert audit(page, f"aktion-veraltet-{page.device}", page.mobile) == []
    assert mailhelp.store.load(f"proposal-{mail_id(1)}-formular")["status"] == "pending_confirmation"
    refused.get_by_role("button", name="Zur Kenntnis genommen").click()
    expect(page.locator(f'[id$="v-{mail_id(1)}-formular"]').get_by_role("alert")).to_have_count(0)
    assert page.errors == []
