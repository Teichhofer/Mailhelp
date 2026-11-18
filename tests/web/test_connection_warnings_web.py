"""7.9.2: sign-in problems above the open decisions and the mail list (synthetic status only)."""
import json
from datetime import UTC, datetime

import pytest

from mailhelp.i18n import Locale, use_locale
from mailhelp.support.connection_health import STATE, ConnectionHealth, ConnectionProblem, digest
from mailhelp.web.connection_warnings import connection_warnings
from tests.fakes.shared_web_actions import web as web  # noqa: F401 - the fixture
from tests.fakes.shared_web_auth import Browser

WHEN = datetime(2026, 11, 18, 20, 18, tzinfo=UTC)


def problem(key, service, code="refresh_denied", number=None):
    return ConnectionProblem(key=key, service=service, number=number, code=code, first_seen=WHEN, last_seen=WHEN,
                             sequence=1)


def save(web, *problems):
    web.store.save(STATE, ConnectionHealth(sequence=len(problems),
                                           problems={item.key: item for item in problems}).model_dump(mode="json"))


@pytest.mark.parametrize("path", ["/", "/?filter=events&q=nichts-passt", "/mails", "/mails?filter=tasks"])
def test_a_refused_google_renewal_is_shown_above_every_list(web, path):
    save(web, problem("google_oauth", "google_oauth"))
    page = web.browser.request("GET", path).body.decode()
    assert '<section class="connection-warnings notice notice-warn"' in page
    assert "<strong>Google-Anmeldung: Anmeldung fehlgeschlagen.</strong>" in page
    assert "Zuletzt fehlgeschlagen: 18.11.2026, 21:18 Uhr." in page  # in the configured zone
    assert '<a href="/einstellungen/zielprofile">Verbindung prüfen</a>' in page
    assert "abgelaufen" not in page.split('connection-warnings', 1)[1].split("</section>", 1)[0]
    assert page.index("connection-warnings") < page.index("</main>")


def test_without_problems_there_is_no_warning_area(web):
    for path in ("/", "/mails"):
        assert "connection-warnings" not in web.browser.request("GET", path).body.decode()


def test_open_pages_notice_a_new_problem_and_its_repair(web):
    """The pages poll /api/stand every 15 seconds; the fingerprint changes with the warnings."""
    def fingerprint(query=""):
        return json.loads(web.browser.request("GET", "/api/stand" + query, accept="application/json").body)[
            "fingerprint"]

    before, mails = fingerprint(), fingerprint("?seite=verbindungen")
    page = web.browser.request("GET", "/mails").body.decode()
    assert 'data-state-url="/api/stand?seite=verbindungen"' in page and f'data-fingerprint="{mails}"' in page
    save(web, problem("imap:a1", "imap", "login_rejected", 2))
    assert fingerprint() != before and fingerprint("?seite=verbindungen") == digest([problem("imap:a1", "imap",
                                                                                            "login_rejected", 2)])
    save(web)
    assert fingerprint() == before and fingerprint("?seite=verbindungen") == mails


def test_warnings_need_the_web_sign_in(web):
    save(web, problem("google_oauth", "google_oauth"))
    stranger = Browser(web.app)
    for path in ("/", "/mails"):
        response = stranger.request("GET", path)
        assert response.status == 303 and b"Google-Anmeldung" not in response.body
    assert stranger.request("GET", "/api/stand?seite=verbindungen", accept="application/json").status == 401


def test_each_connection_names_its_effect_and_setup_page():
    problems = [problem("imap:a1", "imap", "login_rejected", 2), problem("imap:a2", "imap", "login_rejected"),
                problem("iserv:1", "iserv", "login_rejected", 1),
                problem("google_calendar", "google_calendar", "permission_denied", 2),
                problem("todoist", "todoist", "login_rejected", 1)]
    html = connection_warnings(problems, "Europe/Berlin")
    assert html.count('<li class="connection-warning">') == 5
    assert "<strong>Postfach 2: Anmeldung abgelehnt.</strong> Neue Mails dieses Postfachs" in html
    assert "<strong>Postfach: Anmeldung abgelehnt.</strong>" in html and 'href="/einstellungen/postfaecher"' in html
    assert "<strong>IServ-Konto 1: Anmeldung abgelehnt.</strong> Neue Elternbriefe" in html
    assert 'href="/einstellungen/iserv"' in html
    assert ("<strong>Google Kalender (Zielprofil 2): Zugriff verweigert – eine nötige Berechtigung fehlt.</strong> "
            "Kalenderabgleich und Kalenderänderungen") in html
    assert "<strong>Todoist: Anmeldung abgelehnt.</strong> Abgleich und Anlage von Aufgaben" in html
    with use_locale(Locale.EN):
        english = connection_warnings(problems[:1] + [problem("google_oauth", "google_oauth")], "Europe/Berlin")
    assert "<h2 id=\"verbindungsprobleme\">Connection problems</h2>" in english
    assert "<strong>Google sign-in: Sign-in failed.</strong>" in english and ">Check connection</a>" in english
    assert "Last failed: Nov 18, 2026, 21:18." in english
    assert connection_warnings([], "UTC") == ""
