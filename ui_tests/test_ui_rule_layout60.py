"""6.0.1: the rule comparison on /lernen/entscheidungen keeps words whole and uses wide screens."""
from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect

from checks import audit
from conftest import sign_in
from tests.fakes.rule_learning import RuleHarness, record

# Rendered text lines of each node, padding ignored (as in 5.9.6).
LINES = """(nodes) => nodes.map((node) => {
  const range = document.createRange();
  range.selectNodeContents(node);
  return new Set(Array.from(range.getClientRects()).filter((rect) => rect.width > 0)
    .map((rect) => Math.round(rect.top))).size;
})"""


@pytest.fixture
def review(mailhelp, tmp_path):
    harness = RuleHarness(tmp_path, mailhelp.store,
                          lambda actor: actor.startswith("web:") and mailhelp.auth.active(actor[4:]))
    mailhelp.site.rule_learning.service = harness.service
    harness.log(record())
    return harness


def open_review(page, mailhelp, harness):
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/lernen/entscheidungen")
    page.get_by_label("Datenübertragung und kostenpflichtige Analyse ausdrücklich starten").check()
    page.get_by_role("button", name="Entscheidungen analysieren", exact=True).click()
    expect(page.get_by_text(re.compile("^Analysestand:"))).to_contain_text("Wartet")
    assert harness.service.tick()
    page.reload()
    expect(page.get_by_role("heading", name="Vorschläge prüfen", exact=True)).to_be_visible()


@pytest.mark.parametrize("width", [2560, 1920, 1366, 1024])
def test_regression_bisher_and_keine_are_not_broken_into_letters(page, mailhelp, review, width):
    """Regression 6.0.1: "Bisher" stood as "Bi/sh/er" and "Keine" as "K/ei/n/e" next to empty space."""
    if page.device != "desktop":
        return
    page.set_viewport_size({"width": width, "height": 1000})
    open_review(page, mailhelp, review)
    table = page.locator(".rule-review .compare-table").first
    assert table.locator("thead th").evaluate_all(LINES) == [1, 1, 1]
    keine = table.locator('td[data-label="Bisher"]', has_text="Keine").first
    assert keine.evaluate_all(LINES) == [1]
    assert all(box["width"] >= 100 for box in (cell.bounding_box() for cell in
                                               table.locator('td[data-label="Bisher"]').all()))
    card = page.locator(".rule-review").first.bounding_box()
    sides = page.locator(".rule-review .rule-diff > section")
    left, right = sides.nth(0).bounding_box(), sides.nth(1).bounding_box()
    if card["width"] >= 1000:
        assert right["x"] > left["x"] and abs(right["y"] - left["y"]) < 2  # side by side
    else:
        assert right["y"] > left["y"] + left["height"] - 1  # stacked inside a narrow card
    if width == 2560:
        assert card["width"] >= 1400 and page.locator("main").bounding_box()["width"] <= 1600 + 1
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert audit(page, f"rule-layout60-{width}", False) == []


def test_phones_stack_the_comparison_above_the_form(page, mailhelp, review):
    if page.device == "desktop":
        return
    open_review(page, mailhelp, review)
    sides = page.locator(".rule-review .rule-diff > section")
    assert sides.nth(1).bounding_box()["y"] > sides.nth(0).bounding_box()["y"]
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert audit(page, "rule-layout60-" + page.device, page.mobile) == []
