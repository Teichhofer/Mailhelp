"""Navigation for every width (Planung 5.0, 21.2): sidebar, phone bar with "Mehr" and open count."""
import re
from pathlib import Path

from mailhelp.web import pages
from mailhelp.web.pages import NAVIGATION, OPEN_DECISIONS, TAB_BAR, layout


def bar(html):
    return html[html.index('<nav class="tab-bar"'):html.index('</nav>', html.index('<nav class="tab-bar"'))]


def test_the_phone_bar_holds_four_routes_and_the_rest_under_more():
    html = layout("Verlauf", "<h1>Verlauf</h1>", active="/verlauf")
    tabs = bar(html)
    assert 'aria-label="Schnellnavigation"' in tabs
    menu = tabs[tabs.index('<details class="tab-more">'):]
    assert re.findall(r'href="([^"]+)"', tabs[:tabs.index('<details')]) == list(TAB_BAR)
    assert re.findall(r'href="([^"]+)"', menu) == [href for href, _ in NAVIGATION if href not in TAB_BAR]
    assert '<summary>' in menu and '<span class="nav-label">Mehr</span>' in menu
    assert html.count('aria-current="page"') == 2  # sidebar and phone bar
    # Without open decisions there is neither a count nor a description.
    assert 'nav-count' not in html and 'offen-zahl' not in html


def test_a_current_page_under_more_marks_the_more_menu():
    html = layout("Lernen", "<h1>Lernen</h1>", active="/lernen")
    assert '<details class="tab-more has-current">' in bar(html)
    assert '<details class="tab-more">' in bar(layout("Ohne", "<h1>x</h1>"))


def test_the_open_count_is_shown_and_described_for_screen_readers():
    token = OPEN_DECISIONS.set(1)
    try:
        single = layout("Offen", "<h1>Offen</h1>", active="/")
    finally:
        OPEN_DECISIONS.reset(token)
    assert '<span id="offen-zahl" hidden>1 offene Entscheidung</span>' in single
    assert single.count('<a href="/" aria-current="page" aria-describedby="offen-zahl">') == 2
    assert single.count('<span class="nav-count" aria-hidden="true">1</span>') == 2
    token = OPEN_DECISIONS.set(12)
    try:
        several = layout("Mails", "<h1>Mails</h1>", active="/mails")
    finally:
        OPEN_DECISIONS.reset(token)
    assert '<span id="offen-zahl" hidden>12 offene Entscheidungen</span>' in several
    assert several.count('<a href="/" aria-describedby="offen-zahl">') == 2


def test_signed_in_pages_count_the_open_decisions_of_the_overview(web):
    overview = web.site.overview()
    expected = len(overview.open) + len(overview.relevance)
    assert expected > 1
    for path in ("/", "/mails", "/einstellungen"):
        page = web.browser.request("GET", path).body.decode()
        assert f'<span id="offen-zahl" hidden>{expected} offene Entscheidungen</span>' in page
        assert f'<span class="nav-count" aria-hidden="true">{expected}</span>' in page
    # The count belongs to one request only.
    assert OPEN_DECISIONS.get() == 0
    assert 'nav-count' not in layout("Danach", "<h1>x</h1>")


def test_the_phone_bar_keeps_scrolled_controls_above_it():
    # Regression: buttons at the end of a page were scrolled under the fixed bar.
    css = Path(pages.__file__).with_name("static").joinpath("app.css").read_text(encoding="utf-8")
    phone = css[css.index('@media (max-width: 899px) {'):]
    assert 'html:has(.app-shell) { scroll-padding-bottom: calc(76px + env(safe-area-inset-bottom)); }' in phone[:400]
