"""Read-only review pages: content, escaping, links, status and refresh state."""
from __future__ import annotations

import json
from datetime import UTC

import pytest
from shared_web_auth import Browser, signed_in, site  # noqa: F401  (fixture)
from web_scenario import mail_id, populate, proposal, save_mail

from mailhelp.review.views import ReviewViews
from mailhelp.storage import JsonStore
from mailhelp.web.review_pages import https_link, overview_page, proposal_card


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
    assert "<dt>Gestartet</dt><dd>11.10.2026, 11:30 Uhr</dd>" in html
    assert "läuft noch · 7 von 9 Mails analysiert" in html
    assert '<progress class="run-progress" max="9" value="7"' in html
    assert '<strong>6</strong><span>Relevant und ausgewertet</span>' in html
    assert '<strong>1</strong><span>Irrelevant</span>' in html
    from mailhelp import __version__
    assert f"<dt>Version</dt><dd>{__version__}</dd>" in html and "<dt>Modus</dt><dd>Produktiv</dd>" in html
    assert "<dt>Weboberfläche</dt><dd>http://127.0.0.1:8765</dd>" in html
    assert "<dt>Gekoppelte Geräte</dt><dd>1</dd>" in html and "<dt>Gespeichert</dt><dd>7</dd>" in html
    assert '<strong>2</strong><span>Klärung nötig</span>' in html and "Angelegt</span>" in html
    assert "Keine Fehler bei gespeicherten Mails." in html
    assert "<dd>0 wartend, 0 laufend, 0 erledigt, 0 abgelehnt, 0 fehlgeschlagen</dd>" in html
    assert "<dt>KI-Aufrufe in der letzten Minute</dt><dd>0</dd>" in html


def test_status_page_lists_errors_and_operating_figures(tmp_path):
    from datetime import datetime, timedelta

    from shared_review import command
    from shared_web_auth import SECRET, Logger, code_from

    from mailhelp.config import WebSettings
    from mailhelp.models import MailState, ProcessingError
    from mailhelp.review.commands import CommandKind
    from mailhelp.review.inbox import CommandInbox
    from mailhelp.web import WebApp
    from mailhelp.web.auth import WebAuth
    from mailhelp.web.site import MailhelpSite

    now = datetime(2026, 10, 13, 14, 0, tzinfo=UTC)
    clock = iter([now - timedelta(days=2, hours=3)] + [now] * 20)
    with JsonStore(tmp_path) as store:
        populate(store)
        for number, stage, code, retry, minutes in ((1, "event_extraction", "invalid_json", True, 5),
                                                    (2, "relevance", "llm_rate_limited", None, 1)):
            state = store.load_model(f"mail-{mail_id(number)}", MailState)
            store.save(f"mail-{mail_id(number)}", state.model_copy(update={
                "error": ProcessingError(code=code, stage=stage, retryable=retry,
                                         occurred_at=now - timedelta(minutes=minutes)),
                "deferred_until": now + timedelta(hours=1) if number == 1 else None,
                "display_headers": None if number == 2 else state.display_headers,
            }).model_dump(mode="json"))
        store.save("llm-budget", {"calls": [now.timestamp() - 5, now.timestamp() - 120, "x"]})
        store.save("telegram-inbox", {"entries": [{}, {}]})
        commands = CommandInbox(store)
        entry, _ = commands.submit(command(CommandKind.REJECT, mail_id=mail_id(1), proposal_id="formular"))
        messages = []
        auth = WebAuth(store, SECRET, 30, messages.append)
        app = WebApp(["127.0.0.1:8765"])
        MailhelpSite(app, auth, WebSettings(), "Europe/Berlin", Logger(),
                     ReviewViews(store, "Europe/Berlin", test_mode=True), commands,
                     link_base=lambda: "http://192.168.1.144:8765", llm_calls_per_minute=20,
                     clock=lambda: next(clock))
        browser = Browser(app)
        csrf = browser.csrf()
        browser.request("POST", "/anmelden/code", {"csrf": csrf})
        browser.request("POST", "/anmelden", {"csrf": csrf, "code": code_from(messages)})
        html = page(browser, "/status")
    assert "<dd>Testmodus – Einträge werden nur simuliert</dd>" in html
    assert "(2 T 3 Std.)" in html and "<dd>http://192.168.1.144:8765</dd>" in html
    assert '<strong>2</strong><span>Mails mit Fehler</span>' in html
    assert '<strong>1</strong><span>Wartende Web-Aktionen</span>' in html
    assert "<dd>1 wartend, 0 laufend" in html
    assert html.index("Mail ohne Betreff") < html.index("Elternabend und Klassenfahrt")
    assert "KI-Aufruflimit erreicht · Relevanzprüfung" in html
    assert "KI-Antwort war kein gültiges JSON · Terminerkennung" in html
    assert html.count("wird automatisch wiederholt") == 1
    assert f'href="/mail/{mail_id(1)}"' in html
    assert "<dt>Zurückgestellt (neuer Versuch später)</dt><dd>1</dd>" in html
    assert "<dd>1 von höchstens 20</dd>" in html
    assert "<dt>Unverarbeitete Telegram-Eingänge</dt><dd>2</dd>" in html
    assert "<dt>Zurückgehaltene Telegram-Nachrichten</dt><dd>1</dd>" in html
    assert entry.id


def test_status_page_without_any_run_or_proposal(site):
    client, _ = signed_in(site)
    html = page(client, "/status")
    assert "Keine Mails im aktuellen Durchlauf" in html and "<progress" not in html
    assert "Noch keine Vorschläge gespeichert." in html and "Ergebnis der Analyse" not in html
    assert "<dt>Zuletzt verarbeitet</dt><dd>—</dd>" in html


def test_operating_figures_tolerate_damaged_counters(tmp_path):
    from mailhelp.review.views import ReviewViews as Views
    with JsonStore(tmp_path) as store:
        (tmp_path / "telegram-inbox.json").write_text("{", encoding="utf-8")
        store.save("llm-budget", ["kein", "objekt"])
        system = Views(store, "UTC").system()
    assert (system.telegram_unprocessed, system.llm_calls_last_minute) == (0, 0)
    with JsonStore(tmp_path / "b") as store:
        store.save("llm-budget", {"calls": "kaputt"})
        store.save("telegram-inbox", {"entries": "kaputt"})
        system = Views(store, "UTC").system()
    assert (system.telegram_unprocessed, system.llm_calls_last_minute) == (0, 0)


def test_durations_on_the_status_page():
    from mailhelp.web.status_pages import _duration
    assert _duration(59) == "0 Min." and _duration(3 * 3600 + 5 * 60) == "3 Std. 5 Min."
    assert _duration(2 * 86400 + 3600) == "2 T 1 Std."


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
    assert "Alles erledigt! Keine offenen Entscheidungen" in html and "Zuletzt erledigt" not in html
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


def test_manual_warning_only_without_open_questions(tmp_path):
    with JsonStore(tmp_path) as store:
        save_mail(store, 1, "A <a@x.test>", "Absage", [
            proposal(1, "manual", classification="cancellation", status="needs_clarification"),
            proposal(1, "asked", responsibility="unclear",
                     open_questions=["Ist die Nutzerin oder der Nutzer für diesen Eintrag zuständig?"]),
        ])
        views = {view.proposal_id: view for view in ReviewViews(store, "UTC").overview().open}
    assert "manuell prüfen" in proposal_card(views["manual"])
    assert "manuell prüfen" not in proposal_card(views["asked"])
