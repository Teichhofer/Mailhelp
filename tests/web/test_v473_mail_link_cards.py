"""4.7, step 18.4: "Original-Mail öffnen" on web cards and in Telegram."""
import pytest

from tests.scenarios.web_scenario import proposal, save_mail

APPLE = "message://%3Ca1@verein.example.test%3E"
GMAIL = "https://mail.google.com/mail/u/0/#search/rfc822msgid%3Aa1%40verein.example.test"


def prepared(web, link):
    item = proposal(60, "link", title="Unterlagen prüfen", mail_link=link)
    save_mail(web.store, 60, "verein@example.test", "Unterlagen", [item])
    return item


@pytest.mark.parametrize("link", [APPLE, GMAIL])
def test_the_web_card_links_the_original_mail(web, link):
    item = prepared(web, link)
    page = web.browser.request("GET", f"/vorschlag/{item.source_mail_id}/{item.id}").body.decode()
    assert f'<a href="{link}" rel="noopener noreferrer">📧 Original-Mail öffnen</a>' in page


def test_without_a_link_the_card_shows_none(web):
    item = prepared(web, None)
    page = web.browser.request("GET", f"/vorschlag/{item.source_mail_id}/{item.id}").body.decode()
    assert "Original-Mail öffnen" not in page


def buttons(markup):
    return [button for row in markup["inline_keyboard"] for button in row]


def test_telegram_offers_a_button_for_a_web_mail_link(web):
    web.dialog.delivery.deliver(prepared(web, GMAIL))
    text, markup = web.telegram.sent[-1][1], web.telegram.sent[-1][2]
    assert {"text": "📧 Original-Mail öffnen", "url": GMAIL} in buttons(markup)
    assert "Apple Mail" not in text


def test_telegram_shows_the_apple_mail_link_as_copyable_text(web):
    web.dialog.delivery.deliver(prepared(web, APPLE))
    text, markup = web.telegram.sent[-1][1], web.telegram.sent[-1][2]
    assert text.endswith(f"📧 Original-Mail (Apple Mail): {APPLE}")
    assert not any("url" in button for button in buttons(markup))  # Telegram opens only http(s) links


def test_telegram_without_a_link_adds_nothing(web):
    web.dialog.delivery.deliver(prepared(web, None))
    text, markup = web.telegram.sent[-1][1], web.telegram.sent[-1][2]
    assert "Original-Mail" not in text and not any("url" in button for button in buttons(markup))
