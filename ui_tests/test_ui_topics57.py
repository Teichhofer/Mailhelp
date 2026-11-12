"""Compact topic browsing works with local filtering and without application scripts."""
from playwright.sync_api import expect

from checks import audit
from conftest import sign_in
from tests.fakes import ui_topics

topic_catalog = ui_topics.topic_catalog

def test_topics57_compact_list_filters_immediately_and_edits_on_its_own_page(page, mailhelp, topic_catalog):
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/themen")
    expect(page.get_by_role("link", name="Relevante Themen (48)", exact=True)).to_be_visible()
    expect(page.locator('[data-topic-row]:visible')).to_have_count(48)
    expect(page.locator('input[name="description"]')).to_have_count(0)
    assert audit(page, "topics57-catalog-" + page.device, page.mobile) == []
    query = page.get_by_label("Themen durchsuchen", exact=True)
    query.fill("Rechnung")
    expect(page.locator('[data-topic-row]:visible')).to_have_count(1)
    query.fill("unbekannt")
    expect(page.get_by_text("Keine passenden Themen.", exact=True)).to_be_visible()
    query.fill("")
    page.get_by_label("Status filtern", exact=True).select_option("deaktiviert")
    expect(page.locator('[data-topic-row]:visible')).to_have_count(1)
    page.get_by_label("Status filtern", exact=True).select_option("aktiv")
    expect(page.locator('[data-topic-row]:visible')).to_have_count(47)
    page.get_by_label("Status filtern", exact=True).select_option("alle")
    expect(page.locator('[data-topic-row]:visible')).to_have_count(48)
    # 5.7.5 regression: the coverage of the filter was lost with the document on the link click.
    page.collect()
    page.get_by_role("link", name="Schule bearbeiten", exact=True).click()
    expect(page.get_by_role("heading", name="Schule", exact=True)).to_be_visible()
    expect(page.locator('textarea[name="examples"]')).to_have_value("Rechnung; verbindlich")


def test_topics57_links_server_search_and_filters_work_without_javascript(page, mailhelp, topic_catalog):
    page.cdp.send("Emulation.setScriptExecutionDisabled", {"value": True})
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/themen")
    page.get_by_label("Themen durchsuchen", exact=True).fill("Rechnung")
    page.get_by_role("button", name="Themen suchen", exact=True).click()
    expect(page.locator('[data-topic-row]:visible')).to_have_count(1)
    page.get_by_label("Themen durchsuchen", exact=True).fill("")
    page.get_by_label("Status filtern", exact=True).select_option("deaktiviert")
    page.get_by_role("button", name="Themen suchen", exact=True).click()
    expect(page.locator('[data-topic-row]:visible')).to_have_count(1)
    page.get_by_role("link", name="Ausschlussthemen (0)", exact=True).click()
    expect(page.get_by_text("Keine passenden Themen.", exact=True)).to_be_visible()
    page.get_by_role("link", name="Neues Thema", exact=True).click()
    expect(page.get_by_role("heading", name="Neues Thema", exact=True)).to_be_visible()
