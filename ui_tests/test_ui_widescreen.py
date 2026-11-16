"""6.0.2: every core page on very wide screens (2560 × 1440 and 1920 × 1080, light and dark).

The regular device matrix (desktop, mobile, narrow) stays as it is; this module adds its own wide
viewports. A guard test keeps the page list in step with the main navigation, so a new page is
checked automatically or the guard fails.
"""
from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect

from checks import CORE_PAGES, audit
from conftest import sign_in
from mailhelp.web.pages import NAVIGATION
from tests.fakes.rule_learning import RuleHarness, record

WIDE = {"qhd": {"width": 2560, "height": 1440}, "full_hd": {"width": 1920, "height": 1080}}
PAGES = CORE_PAGES

# Words in headers, badges and buttons must never be split over lines (counted on the text itself).
SPLIT_WORDS = """() => Array.from(document.querySelectorAll(
    'main thead th, main .badge, main .button, main button, main .chip, main .stat span'))
  .filter((node) => node.offsetParent !== null && node.textContent.trim())
  .filter((node) => {
    const range = document.createRange();
    range.selectNodeContents(node);
    const tops = new Set(Array.from(range.getClientRects()).filter((rect) => rect.width > 0)
      .map((rect) => Math.round(rect.top)));
    return tops.size > 1;
  }).map((node) => node.textContent.trim().slice(0, 40))"""

# main must use the room next to the sidebar (at least 60 %) or reach its own maximum width.
BALANCE = """() => {
  const main = document.querySelector('main'), box = main.getBoundingClientRect();
  const sidebar = document.querySelector('.app-shell nav, .sidebar');
  const room = window.innerWidth - (sidebar ? sidebar.getBoundingClientRect().width : 0);
  const limit = parseFloat(getComputedStyle(main).maxWidth) || Infinity;
  return {width: box.width, room: room, limit: limit};
}"""


def test_the_page_list_covers_the_main_navigation():
    assert {path for path, _label in NAVIGATION} <= set(PAGES)


@pytest.fixture
def review(mailhelp, tmp_path):
    harness = RuleHarness(tmp_path, mailhelp.store,
                          lambda actor: actor.startswith("web:") and mailhelp.auth.active(actor[4:]))
    mailhelp.site.rule_learning.service = harness.service
    harness.log(record())
    return harness


def prepare_review(page, mailhelp, harness):
    """/lernen/entscheidungen is checked with an open review, its widest content."""
    page.goto(mailhelp.url + "/lernen/entscheidungen")
    page.get_by_label("Datenübertragung und kostenpflichtige Analyse ausdrücklich starten").check()
    page.get_by_role("button", name="Entscheidungen analysieren", exact=True).click()
    expect(page.get_by_text(re.compile("^Analysestand:"))).to_contain_text("Wartet")
    assert harness.service.tick()


@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("size", list(WIDE))
def test_core_pages_on_wide_screens(page, mailhelp, review, size, scheme):
    if page.device != "desktop":
        return
    page.set_viewport_size(WIDE[size])
    page.emulate_media(color_scheme=scheme)
    sign_in(page, mailhelp)
    prepare_review(page, mailhelp, review)
    problems = []
    for path in PAGES:
        page.goto(mailhelp.url + path)
        expect(page.locator("main")).to_be_visible()
        split = page.evaluate(SPLIT_WORDS)
        if split:
            problems.append(f"{path}: Wörter umbrochen {split}")
        if not page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"):
            problems.append(f"{path}: waagerechter Überlauf")
        balance = page.evaluate(BALANCE)
        if balance["width"] < 0.6 * balance["room"] and balance["width"] < balance["limit"] - 1:
            problems.append(f"{path}: main nur {balance['width']:.0f} von {balance['room']:.0f} px")
        name = path.strip("/").replace("/", "-") or "offen"
        problems += [f"{path}: {item}" for item in audit(page, f"wide60-{name}-{size}-{scheme}", False)]
    assert problems == []
    assert page.errors == []


def test_the_checks_detect_split_words_and_overflow(page, mailhelp):
    """The detectors above are not vacuous: a squeezed header and a too wide block are reported."""
    if page.device != "desktop":
        return
    page.set_viewport_size(WIDE["full_hd"])
    sign_in(page, mailhelp)
    # A static page: the overview replaces its content during background refreshes.
    page.goto(mailhelp.url + "/geraete")
    page.evaluate("""() => {
      const table = document.createElement('table'), head = table.createTHead().insertRow();
      const cell = document.createElement('th');
      cell.textContent = 'Geltungsbereich';
      cell.style.width = '1px';
      cell.style.maxWidth = '1px';
      cell.style.overflowWrap = 'anywhere';
      table.style.width = '1px';  // app.css gives tables the full width
      head.appendChild(cell);
      const wide = document.createElement('div');
      wide.style.width = '4000px';
      wide.textContent = 'breit';
      document.querySelector('main').append(table, wide);
    }""")
    assert page.evaluate(SPLIT_WORDS) == ["Geltungsbereich"]
    assert not page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
