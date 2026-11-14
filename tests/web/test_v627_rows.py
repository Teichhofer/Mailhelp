"""6.2.7: dense row lists for mails, history and reconciliation; the same status badge everywhere."""
from mailhelp.review.archive import record_event
from mailhelp.web.archive_pages import history_meta
from mailhelp.web.labels import status_badge
from mailhelp.web.reconciliation_site import grouped
from mailhelp.web.rows import row
from tests.fakes.shared_web_actions import web  # noqa: F401  (fixture)
from tests.scenarios.web_scenario import proposal


def test_a_row_has_a_title_link_one_meta_line_and_badges():
    assert row("/mail/a?b=1&c", "<Titel>", "Absender · Zeit", '<span class="badge">x</span>', "<p>d</p>") == (
        '<li class="row-item"><div class="row-main"><a class="row-title" href="/mail/a?b=1&amp;c">&lt;Titel&gt;</a>'
        '<span class="row-meta">Absender · Zeit</span></div><div class="row-badges"><span class="badge">x</span>'
        '</div><p>d</p></li>')


def test_the_badge_names_the_status_and_colour_only_repeats_it():
    assert status_badge("needs_clarification") == '<span class="badge warn">Klärung nötig</span>'
    assert status_badge("failed", "2 × ") == '<span class="badge danger">2 × Anlage fehlgeschlagen</span>'
    assert status_badge("rejected") == '<span class="badge">Verworfen</span>'
    assert status_badge("<neu>") == '<span class="badge">unbekannt (&lt;neu&gt;)</span>'


def test_history_meta_names_time_event_source_and_version():
    entry = {"at": "2026-10-02T10:00:00+00:00", "kind": "edit", "status": "pending_confirmation",
             "source": "web", "version": 3}
    assert history_meta(entry, "Europe/Berlin") == "02.10.2026, 12:00 Uhr · Felder bearbeitet · Weboberfläche · Version 3"
    legacy = {**entry, "kind": "legacy", "status": "legacy", "source": "unknown", "version": ""}
    assert history_meta(legacy, "UTC") == "02.10.2026, 10:00 Uhr · unbekannt"


def test_rows_share_a_list_and_cards_keep_their_place():
    assert grouped(["<li>a</li>", "<li>b</li>", "<section>c</section>", "<li>d</li>"]) == (
        '<ul class="row-list"><li>a</li><li>b</li></ul><section>c</section><ul class="row-list"><li>d</li></ul>')
    assert grouped(["<section>c</section>"]) == "<section>c</section>" and grouped([]) == ""


def test_mails_history_and_reconciliation_render_rows(web):
    """Regression 6.2.7: every entry was a tall card; about five fitted on a 1080 px screen."""
    record_event(web.store, proposal(1, "formular"), "reject", "web", "key-1")
    for path in ("/mails", "/verlauf", "/abgleich"):
        html = web.browser.request("GET", path).body.decode()
        assert '<ul class="row-list"><li class="row-item">' in html, path
        assert 'class="archive-list"' not in html, path
    abgleich = web.browser.request("GET", "/abgleich").body.decode()
    assert '<a class="button" href="/vorschlag/' not in abgleich  # titles are links, not buttons
