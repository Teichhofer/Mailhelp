"""Read-only review pages: content, escaping, links, status and refresh state."""
from __future__ import annotations

import json

import pytest

from mailhelp.review.views import ReviewViews
from mailhelp.storage import JsonStore
from mailhelp.web.review_pages import https_link, overview_page, proposal_card
from test_web_auth import Browser, signed_in, site  # noqa: F401  (fixture)
from web_scenario import mail_id, populate, proposal, save_mail


@pytest.fixture
def browser(site):
    populate(site.auth.store)
    client, _ = signed_in(site)
    return client


def page(browser, path):
    response = browser.request("GET", path)
    assert response.status == 200, response.status
    return response.body.decode()


def test_overview_lists_relevance_current_queue_and_recent(browser):
    html = page(browser, "/")
    assert '<span class="count">6</span>' in html
    assert "Folgt in Telegram" in html
    assert html.index("Relevanz klären") < html.index("Vorschläge") < html.index("Zuletzt erledigt")
    assert html.index("Elternabend Klasse 4b") < html.index("Zahnarzt Kontrolle")
    assert "Aktuell in Telegram" in html and "Vereinsnachrichten Oktober" in html
    assert "21.10.2026, 19:00–20:30 Uhr" in html and "Fällig: 17.10.2026" in html
    assert "Grundschule am Park, Raum 12" in html
    assert "Bist du dafür zuständig?" in html and "Zuständig: Noch unklar" in html
    assert "Kinderturnen" in html and "Verworfen" in html
    assert "Beleg vollständig anzeigen" in html
    assert 'data-fingerprint="' in html


def test_mail_content_is_escaped_and_mail_links_are_text(browser):
    html = page(browser, "/")
    assert "<script>alert" not in html and "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;" in html
    assert "<b>dringend</b>" not in html and "&lt;b&gt;dringend&lt;/b&gt;" in html
    assert 'href="https://evil.test' not in html and "https://evil.test/login?token=1" in html
    assert "&lt;a href=&quot;https://evil.test&quot;&gt;" in html


def test_detail_page_shows_full_texts_and_unknown_ids_are_not_found(browser):
    html = page(browser, f"/vorschlag/{mail_id(1)}/elternabend")
    assert "Termin</h1>" in html and "Beschreibung vollständig anzeigen" not in html
    assert "Bitte bringen Sie die unterschriebene Einverständniserklärung mit." in html
    created = page(browser, f"/vorschlag/{mail_id(5)}/turnen")
    assert 'href="https://calendar.google.com/event?eid=1"' in created and "Im Kalender öffnen" in created
    missing = browser.request("GET", f"/vorschlag/{mail_id(1)}/gibtsnicht")
    assert missing.status == 404 and "nicht (mehr) vorhanden" in missing.body.decode()
    assert browser.request("GET", "/vorschlag/kurz/x").status == 404


def test_status_page_counts_the_run(browser):
    html = page(browser, "/status")
    assert '<strong>4</strong><span>Warten auf dich</span>' in html
    assert '<strong>1</strong><span>In Bearbeitung</span>' in html
    assert '<strong>5</strong><span>Offene Vorschläge</span>' in html
    assert '<strong>0</strong><span>Wartende Web-Aktionen</span>' in html
    assert "11.10.2026, 11:30 Uhr" in html and "Analyse läuft noch" in html


def test_refresh_state_needs_a_session_and_changes_with_the_data(site, browser):
    state = json.loads(browser.request("GET", "/api/stand", accept="application/json").body)
    assert state == {"fingerprint": ReviewViews(site.auth.store, "UTC").overview().fingerprint}
    stranger = Browser(site)
    assert stranger.request("GET", "/api/stand", accept="application/json").status == 401
    save_mail(site.auth.store, 9, "Neu <neu@x.test>", "Neu", [proposal(9, "neu", title="Neu")])
    changed = json.loads(browser.request("GET", "/api/stand", accept="application/json").body)
    assert changed["fingerprint"] != state["fingerprint"]


def test_empty_and_damaged_states_are_explained(site, tmp_path):
    client, _ = signed_in(site)
    html = page(client, "/")
    assert "Nichts zu entscheiden" in html and "Zuletzt erledigt" not in html
    (site.auth.store.directory / f"proposal-{mail_id(1)}-x.json").write_text("{", encoding="utf-8")
    assert "beschädigt" in page(client, "/") and "beschädigte" in page(client, "/status")


def test_links_and_card_variants(tmp_path):
    assert https_link("https://meet.test/a") == "https://meet.test/a"
    for value in (None, "", "http://meet.test/a", "javascript:alert(1)", "https:///x"):
        assert https_link(value) is None
    with JsonStore(tmp_path) as store:
        save_mail(store, 1, "A <a@x.test>", "Video", [
            proposal(1, "secure", kind="event", start="2026-10-21T10:00:00+02:00",
                     end="2026-10-21T11:00:00+02:00", video_link="https://meet.test/a"),
            proposal(1, "plain", kind="event", start="2026-10-21T10:00:00+02:00",
                     end="2026-10-21T11:00:00+02:00", video_link="http://meet.test/b", version=2),
            proposal(1, "done", status="created", external_link="http://todoist.test/1"),
        ])
        views = {view.proposal_id: view for view in
                 ReviewViews(store, "Europe/Berlin", test_mode=True).overview().open
                 + ReviewViews(store, "Europe/Berlin", test_mode=True).overview().recent}
    secure = proposal_card(views["secure"])
    assert '<a href="https://meet.test/a" rel="noopener noreferrer"' in secure
    assert "Testmodus" in secure
    plain = proposal_card(views["plain"], detail_link=False)
    assert "http://meet.test/b" in plain and 'href="http://meet.test/b"' not in plain
    assert "Version 2" in plain and "/vorschlag/" not in plain
    overview = ReviewViews(store, "Europe/Berlin").overview()
    assert '<p class="notice notice-ok" role="status">Gespeichert &amp; erledigt</p>' in overview_page(
        overview, message="Gespeichert & erledigt")
    done = proposal_card(views["done"], actions=lambda view: "<form>aktion</form>")
    assert "In Todoist öffnen" not in done and "<form>aktion</form>" in done
