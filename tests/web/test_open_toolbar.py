"""6.0.6: count, quick filters, search, sort and grouping of the open decisions in one tool row."""
import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from mailhelp.review.commands import CommandKind
from mailhelp.review.views import ReviewViews
from mailhelp.web import open_toolbar as tools
from tests.scenarios.web_scenario import mail_id


def page(web, query=""):
    web.site.refresh_overview()
    response = web.browser.request("GET", "/" + (f"?{query}" if query else ""))
    return response.status, response.body.decode()


def cards(html):
    return re.findall(r'<article class="card[^"]*" id="([vr]-[^"]+)"', html)


def test_regression_filters_and_heading_form_one_tool_row_with_search_sort_and_grouping(web):
    """Regression 6.0.6: heading, quick filters and the list stood apart; there was no search or sort."""
    status, html = page(web)
    assert status == 200
    toolbar = html[html.index('<div class="open-toolbar">'):html.index("</form></div>")]
    assert 'aria-label="Schnellfilter"' in toolbar and 'id="open-q"' in toolbar and 'id="open-sort"' in toolbar
    assert "Nach Bearbeitungsbedarf gruppieren" in toolbar and ">Zurücksetzen</a>" in toolbar
    assert '<span class="count">6</span>' in html  # five proposals and one relevance question


def test_search_covers_title_subject_and_sender_and_combines_with_a_quick_filter(web):
    _status, html = page(web, "q=zahnarzt")
    assert cards(html) == [f"v-{mail_id(2)}-zahnarzt"] and '<span class="count">1 von 6</span>' in html
    assert cards(page(web, "q=Vereinsnachrichten")[1]) == [f"r-{mail_id(7)}"]  # relevance: subject
    assert cards(page(web, "q=sv.test")[1]) == []  # the sender is the display name only
    assert cards(page(web, "q=Sportverein")[1]) == [f"r-{mail_id(7)}"]  # relevance: sender
    assert set(cards(page(web, "q=klassenleitung")[1])) == {f"v-{mail_id(1)}-elternabend", f"v-{mail_id(1)}-formular"}
    combined = page(web, "filter=tasks&q=klassenleitung")[1]
    assert cards(combined) == [f"v-{mail_id(1)}-formular"]
    # Quick filters keep the search; the form keeps the quick filter.
    assert 'href="/offen?filter=events&amp;q=klassenleitung"' in combined
    assert '<input type="hidden" name="filter" value="tasks">' in combined


def test_no_match_keeps_the_tool_row_and_a_way_back(web):
    _status, html = page(web, "q=gibtsnicht")
    assert cards(html) == [] and "Keine passenden Entscheidungen." in html and 'id="open-q"' in html
    assert '<span class="count">0 von 6</span>' in html and 'value="gibtsnicht"' in html
    assert "Heute" not in html.split("Keine passenden")[1][:200]  # not the "all done" summary


def test_the_search_is_escaped_and_bounded():
    view = tools.parse("q=" + "%3Cb%3E" + "x" * 200 + "&sort=unbekannt&gruppe=ja")
    assert view.q == "<b>" + "x" * 77 and view.sort == "neu" and not view.group
    assert 'value="&lt;b&gt;' in tools.toolbar("/", view)
    assert tools.parse("q=+a++b+&gruppe=bedarf&sort=datum") == tools.OpenView("", "a b", "datum", True)
    assert tools.OpenView(sort="alt", group=True).params(filter="tasks") == {"filter": "tasks", "sort": "alt",
                                                                               "gruppe": "bedarf"}


def test_an_unknown_quick_filter_is_still_rejected(web):
    assert page(web, "filter=unbekannt")[0] == 422


def test_sorting_by_arrival_and_by_date_is_stable_and_undated_items_go_last(web):
    overview = ReviewViews(web.store, "Europe/Berlin").overview()
    base = datetime(2026, 11, 1, tzinfo=UTC)
    views = [replace(view, arrived_at=base + timedelta(hours=index)) for index, view in enumerate(overview.open)]
    newest = tools.ordered(views, "neu")
    assert [view.arrived_at for view in newest] == sorted((view.arrived_at for view in views), reverse=True)
    assert tools.ordered(views, "alt") == tuple(reversed(newest))
    by_date = [view.proposal_id for view in tools.ordered(overview.open, "datum")]
    assert by_date[:3] == ["formular", "elternabend", "fest"]  # 17.10. (due), 21.10., 25.10.
    assert set(by_date[3:]) == {"zahnarzt", "boese"}  # no date: last, in their previous order
    assert by_date[3:] == [view.proposal_id for view in overview.open if view.proposal_id in {"zahnarzt", "boese"}]
    unknown = [replace(view, arrived_at=None) for view in views[:2]]
    assert tools.ordered(unknown, "neu") == tuple(unknown) and tools.ordered(unknown, "alt") == tuple(unknown)
    people = ReviewViews(web.store, "Europe/Berlin").overview().relevance
    assert tools.ordered(people, "datum") == tuple(people)


def test_grouping_puts_every_decision_exactly_once_and_only_confirmable_ones_under_ready(web):
    _status, html = page(web, "gruppe=bedarf")
    headings = re.findall(r'<h2>([^<]+) <span class="count">(\d+)</span></h2>', html)
    assert [name for name, _ in headings] == ["Rückfrage nötig", "Bereit zum Bestätigen"]
    assert sum(int(number) for _, number in headings) == 6 and len(cards(html)) == len(set(cards(html))) == 6
    overview = ReviewViews(web.store, "Europe/Berlin").overview()
    sections = tools.groups(overview.relevance, overview.open)
    asking, ready = sections[0], sections[1]
    assert [view.proposal_id for view in asking[2]] == ["zahnarzt", "fest"] and len(asking[1]) == 1
    assert all(CommandKind.CONFIRM in view.actions for view in ready[2])
    blocked = replace(overview.open[0], actions=frozenset())
    assert tools.groups((), [blocked]) == [("Weitere Prüfung nötig", (), (blocked,))]
    conflict = replace(overview.open[0], conflicts=("x",))
    assert tools.groups((), [conflict])[0][0] == "Rückfrage nötig"


def test_the_tool_row_only_reads(web):
    page(web, "q=zahnarzt&sort=datum&gruppe=bedarf&filter=events")
    web.run()
    assert web.writer.created == 0 and web.commands.queued() == []


def test_regression_sort_order_is_preserved_for_multiple_proposals_from_one_mail(web):
    from mailhelp.web.review_pages import overview_page

    overview = ReviewViews(web.store, "Europe/Berlin").overview()
    first, last = [view for view in overview.open if view.mail_id == mail_id(1)]
    first, last = replace(first, series_key=None), replace(last, series_key=None)
    middle = next(view for view in overview.open if view.mail_id != mail_id(1))
    html = overview_page(replace(overview, relevance=(), open=(first, middle, last)))
    assert cards(html) == [f"v-{view.mail_id}-{view.proposal_id}" for view in (first, middle, last)]
