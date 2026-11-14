"""6.2.5: one tool row for history, mails and evaluation; further filters under „Mehr Filter“."""
import re

from mailhelp.review.archive import record_event
from mailhelp.web.toolbar import date_field, search_field, toolbar
from tests.fakes.shared_web_actions import web  # noqa: F401  (fixture)
from tests.fakes.shared_web_v12 import configure
from tests.scenarios.web_scenario import proposal


def test_the_row_holds_the_main_fields_and_one_primary_button():
    html = toolbar("/x?a=1", ["<label>A<input name=a></label>"], submit="Filtern")
    assert html == ('<form method="get" action="/x?a=1" class="toolbar" role="search"><div class="toolbar-row">'
                    '<label>A<input name=a></label><button class="button primary" type="submit">Filtern</button>'
                    '</div></form>')


def test_further_filters_name_how_many_are_active_and_stay_open_then():
    closed = toolbar("/x", [], submit="Los", more=["<label>B</label>"])
    assert '<details class="toolbar-more"><summary>Mehr Filter</summary>' in closed and "Zurücksetzen" not in closed
    opened = toolbar("/x", [], submit="Los", more=["<label>B</label>"], active=2, reset="/x", hidden="<i>h</i>",
                     below="<p>Hinweis</p>")
    assert '<details class="toolbar-more" open><summary>Mehr Filter (2 aktiv)</summary>' in opened
    assert '<a class="button link" href="/x">Zurücksetzen</a></div><p>Hinweis</p>' in opened
    assert 'role="search"><i>h</i><div' in opened


def test_fields_escape_their_values():
    assert 'value="&quot;x&quot;"' in search_field("q", "Suche", '"x"', hint_id="h", placeholder="Titel")
    assert 'aria-describedby="h"' in search_field("q", "Suche", "", hint_id="h")
    assert date_field("since", "Von", None) == '<label>Von<input type="date" name="since" value=""></label>'


def test_the_history_filters_are_choices_with_german_names(web):
    """Regression 6.2.5: six free text fields, among them „Aufgabe (task) oder Termin (event)“."""
    item = proposal(1, "formular")
    record_event(web.store, item, "reject", "web", "key-1")
    html = web.browser.request("GET", "/verlauf?status=rejected&proposal_kind=task&filter=tasks").body.decode()
    assert "(task)" not in html and 'name="kind" value' not in html
    assert '<option value="rejected" selected>Verworfen</option>' in html
    assert '<option value="task" selected>Aufgabe</option>' in html
    assert '<input type="hidden" name="filter" value="tasks">' in html  # the quick filter stays
    assert '<details class="toolbar-more"><summary>Mehr Filter</summary>' in html
    assert '<a class="button link" href="/verlauf">Zurücksetzen</a>' in html
    more = web.browser.request("GET", "/verlauf?kind=reject&since=2026-01-01").body.decode()
    assert '<summary>Mehr Filter (2 aktiv)</summary>' in more and '<option value="reject" selected>Verworfen</option>' in more
    assert 'type="date" name="since" value="2026-01-01"' in more
    plain = web.browser.request("GET", "/verlauf").body.decode()
    assert "Zurücksetzen" not in plain
    assert web.browser.request("GET", "/verlauf?proposal_kind=termin").status == 422


def test_every_list_form_has_exactly_one_primary_action(web, tmp_path):
    configure(web, tmp_path)
    for path in ("/verlauf", "/mails", "/", "/auswertung"):
        html = web.browser.request("GET", path).body.decode()
        forms = re.findall(r'<form method="get".*?</form>', html, re.S)
        assert forms and all(form.count("button primary") <= 1 for form in forms), path
        assert "button primary" in html, path


def test_the_evaluation_counts_its_narrowing_filters(web, tmp_path):
    configure(web, tmp_path)
    html = web.browser.request("GET", "/auswertung?days=7&stage=relevance").body.decode()
    assert '<details class="toolbar-more" open><summary>Mehr Filter (1 aktiv)</summary>' in html
    assert '<a class="button link" href="/auswertung">Zurücksetzen</a>' in html
    assert "Zurücksetzen" not in web.browser.request("GET", "/auswertung?days=7").body.decode()
