"""6.2.8: "Offen" on phones – the first decision on the first screen, measured in the real window."""
from __future__ import annotations

from playwright.sync_api import expect

from checks import audit
from conftest import sign_in

# Positions in the visible window (not a full-page screenshot): where the first decision starts and how
# much the phone bar and the sticky decision row of that card cover.
WINDOW = """() => {
  const card = document.querySelector('.open-items .card'), bar = document.querySelector('nav.tab-bar');
  const actions = card.querySelector('.actions');
  const title = card.querySelector('h2, h3');
  return {top: card.getBoundingClientRect().top, height: innerHeight,
          bar: bar.getBoundingClientRect().height, actions: actions ? actions.getBoundingClientRect().height : 0,
          title: title.getBoundingClientRect().bottom};
}"""


def test_open628_first_decision_on_the_first_screen(page, mailhelp):
    if page.device == "desktop":
        return
    sign_in(page, mailhelp)
    tools = page.locator("details[data-open-more]")
    expect(tools).not_to_have_attribute("open", "")
    window = page.evaluate(WINDOW)
    assert window["top"] < 0.6 * window["height"], window
    assert window["bar"] + window["actions"] <= 0.35 * window["height"], window
    assert window["title"] < window["height"] - window["bar"], window  # the card title is not covered
    # The quick filters stay one line that scrolls sideways, never the page.
    chips = page.locator(".open-toolbar .filter-chips .button")
    tops = {round(box["y"]) for box in chips.evaluate_all("(nodes) => nodes.map((n) => n.getBoundingClientRect())")}
    assert len(tops) == 1
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert audit(page, "open628-" + page.device, page.mobile) == []
    # The phone bar holds the daily work: Offen, Mails, Abgleich, Verlauf; Status is under "Mehr".
    bar = page.locator("nav.tab-bar")
    expect(bar.get_by_role("link", name="Abgleich", exact=True)).to_be_visible()
    expect(bar.get_by_role("link", name="Status", exact=True)).to_be_hidden()
    # Something set: the controls start open and the summary names it.
    page.goto(mailhelp.url + "/?q=zahnarzt&sort=alt")
    expect(tools).to_have_attribute("open", "")
    expect(tools.locator("summary")).to_contain_text("(„zahnarzt“, Älteste Mail zuerst)")
    assert page.errors == []


def test_open628_wider_window_shows_the_controls_again(page, mailhelp):
    if page.device != "mobile":
        return
    sign_in(page, mailhelp)
    expect(page.locator("details[data-open-more]")).not_to_have_attribute("open", "")
    page.set_viewport_size({"width": 1366, "height": 900})
    expect(page.locator("#open-q")).to_be_visible()
    expect(page.locator(".open-more > summary")).to_be_hidden()


def test_open628_detail_card_has_no_gap_below_the_decisions(page, mailhelp):
    """B14: the gap seen in full-page screenshots is the sticky decision row, not empty space."""
    if page.device != "desktop":
        return
    sign_in(page, mailhelp)
    page.locator('.open-items article.card[id^="v-"]').first.click()  # a proposal, not a relevance question
    bar = page.locator(".detail-pane .decision-bar")
    expect(bar).to_be_visible()
    help_box = page.locator(".detail-pane .decision-help")
    # While its place is below the window the row sticks to the bottom edge (5.0.8); a full-page
    # screenshot shows that offset as a gap. Scrolled to the explanation, the row sits right above it.
    help_box.scroll_into_view_if_needed()
    page.evaluate("window.scrollBy(0, 200)")
    gap = help_box.bounding_box()["y"] - (bar.bounding_box()["y"] + bar.bounding_box()["height"])
    assert 0 <= gap < 40, gap
