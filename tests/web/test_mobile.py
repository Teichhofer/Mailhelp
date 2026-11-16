"""6.2.8: "Offen" on phones – search and sort fold under one control; the phone bar shows the reconciliation."""
from mailhelp.web.open_toolbar import OpenView, toolbar
from mailhelp.web.pages import layout


def test_search_and_sort_sit_in_a_foldable_control_that_names_what_is_set():
    plain = toolbar("/", OpenView("", "", "neu", False))
    assert '<details class="open-more" open data-open-more><summary>Suchen und sortieren</summary>' in plain
    narrowed = toolbar("/", OpenView("", "<b>x</b>", "alt", True))
    assert ('<details class="open-more" open data-open-more data-set><summary>Suchen und sortieren '
            '<span class="open-more-state">(„&lt;b&gt;x&lt;/b&gt;“, Älteste Mail zuerst, gruppiert)</span>') in narrowed


def test_the_phone_bar_shows_the_reconciliation_with_a_short_label():
    html = layout("Offen", "<h1>Offen</h1>", active="/abgleich")
    bar = html[html.index('<nav class="tab-bar"'):]
    tabs = bar[:bar.index("<details")]
    assert '<span class="nav-label">Abgleich</span>' in tabs and 'href="/status"' not in tabs
    assert 'href="/status"' in bar  # under "Mehr"
    sidebar = html[html.index('<nav class="nav"'):html.index('<nav class="tab-bar"')]
    assert '<span class="nav-label">Vorschlagsabgleich</span>' in sidebar
