"""The split view loads the details of a card with an "Original-Mail öffnen" link (5.0.4).

Regression: the pane fetched the first link of the card, which was the original mail
(message://… or https://mail.google.com/…), and reported "Details nicht geladen".
"""
import pytest
from playwright.sync_api import expect

from conftest import sign_in
from pages import MASTER, PANE, Overview
from tests.scenarios.web_scenario import mail_id, proposal, save_mail

APPLE = "message://%3Ca1@verein.example.test%3E"
GMAIL = "https://mail.google.com/mail/u/0/#search/rfc822msgid%3Aa1%40verein.example.test"


@pytest.mark.parametrize("link", [APPLE, GMAIL])
def test_a_card_with_an_original_mail_link_shows_its_details(page, mailhelp, link):
    if page.device != "desktop":
        return
    save_mail(mailhelp.store, 60, "verein@example.test", "Unterlagen",
              [proposal(60, "link", title="Unterlagen prüfen", mail_link=link)])
    sign_in(page, mailhelp)
    page.locator(f"{MASTER} #v-{mail_id(60)}-link").click(position={"x": 12, "y": 12})
    expect(Overview(page).selected).to_have_attribute("id", f"v-{mail_id(60)}-link")
    expect(page.locator(f"{PANE} #detail-v-{mail_id(60)}-link")).to_be_visible()
    expect(page.locator(PANE)).not_to_have_attribute("aria-busy", "true")
    expect(Overview(page).toast).not_to_contain_text("Details nicht geladen")
    assert page.errors == []
