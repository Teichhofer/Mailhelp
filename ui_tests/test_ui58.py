"""5.8 usability: visible results, keyboard errors and consistent preparation."""
import json

import pytest
from playwright.sync_api import expect

from checks import SCREENSHOTS, audit
from conftest import sign_in
from tests.fakes import ui_learning, ui_topics

learning_server = ui_learning.learning_server
topic_catalog = ui_topics.topic_catalog


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_catalog58_results_are_near_the_search_and_have_no_overflow(page, mailhelp, topic_catalog, theme):
    page.emulate_media(color_scheme=theme)
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/themen")
    first = page.locator("[data-topic-row]:visible").first
    box = first.bounding_box()
    assert box["y"] < page.viewport_size["height"]
    assert audit(page, "topics58-" + theme + "-" + page.device, page.mobile) == []
    page.screenshot(path=str(SCREENSHOTS / f"topics58-{theme}-{page.device}.png"))
    # Record filter JS coverage before navigating away from this document.
    page.get_by_label("Themen durchsuchen", exact=True).fill("Schule")
    expect(page.locator("[data-topic-row]:visible")).to_have_count(1)


def test_editor58_error_summary_gets_focus_and_links_to_the_input(page, mailhelp):
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/themen/relevant/school")
    page.get_by_label("Beschreibung", exact=True).fill("")
    page.get_by_role("button", name="Änderung prüfen", exact=True).click()
    expect(page.locator("#form-errors")).to_be_focused()
    page.locator('#form-errors a[href="#topic-description"]').click()
    expect(page.locator("#topic-description")).to_be_focused()
    expect(page.locator("#topic-description")).to_have_attribute(
        "aria-describedby", "topic-description-help topic-description-error")
    assert audit(page, "topic-errors58-" + page.device, page.mobile) == []


@pytest.mark.parametrize("javascript", [True, False])
def test_estimate58_preserves_the_selected_values_without_starting(page, learning_server, javascript):
    h = learning_server
    if not javascript:
        page.cdp.send("Emulation.setScriptExecutionDisabled", {"value": True})
    page.goto(h.url + "/lernen/postfach")
    page.get_by_label("Code aus der Mailhelp-Konsole").fill(h.code)
    page.get_by_role("button", name="Gerät koppeln", exact=True).click()
    page.goto(h.url + "/lernen/postfach")
    page.get_by_label("Anzahl Mails", exact=True).fill("7")
    page.get_by_label("Weitere Ordner (ein Name je Zeile)", exact=True).fill("Archive")
    page.get_by_label("Preisobergrenze USD je Million Tokens", exact=True).fill("0.75")
    page.get_by_label("Budget USD", exact=True).fill("9")
    page.get_by_role("button", name="Schätzung anzeigen", exact=True).click()
    expect(page.get_by_label("Anzahl Mails", exact=True)).to_have_value("7")
    expect(page.get_by_label("Preisobergrenze USD je Million Tokens", exact=True)).to_have_value("0.75")
    expect(page.get_by_label("Budget USD", exact=True)).to_have_value("9")
    assert json.loads(page.locator('input[name="selection"]').input_value())["folders"] == ["INBOX", "Archive"]
    assert h.client.calls == [] and h.reader.reads == []
    if javascript:
        assert audit(page, "learning-setup58-" + page.device, page.mobile) == []
    else:
        # axe injects a script, which intentionally cannot execute in this case.
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_cards58_titles_and_actions_remain_reachable(page, mailhelp):
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/")
    cards = page.locator(".master-pane article.card").filter(has=page.locator("h3 a"))
    measurements = []
    for index in range(min(3, cards.count())):
        card = cards.nth(index)
        title = card.locator("h3 a")
        title.scroll_into_view_if_needed()
        expect(title).to_be_in_viewport()
        measurements.append({"height": card.bounding_box()["height"], "title": title.inner_text()})
    (SCREENSHOTS / f"cards58-{page.device}.json").write_text(json.dumps(measurements), encoding="utf-8")
    if page.device == "narrow":
        assert max(item["height"] for item in measurements) < 793  # Audit's largest initial card.
    assert audit(page, "cards58-" + page.device, page.mobile) == []


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_status58_starts_with_next_steps_and_keeps_technical_facts_accessible(page, mailhelp, theme):
    page.emulate_media(color_scheme=theme)
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/status")
    expect(page.locator(".status-summary")).to_contain_text("Browser und Mailhelp")
    expect(page.get_by_role("link", name="Verbindungen lesend prüfen", exact=True)).to_be_visible()
    expect(page.locator(".status-details")).not_to_have_attribute("open", "")
    assert audit(page, "status58-" + theme + "-" + page.device, page.mobile) == []
    page.get_by_text("Betriebsdetails und Zähler anzeigen", exact=True).click()
    expect(page.get_by_role("heading", name="Mailhelp", exact=True)).to_be_visible()
