"""6.2.9: fewer settings tiles without overlaps; the status page starts with one verdict line."""
import re
from types import SimpleNamespace

import pytest

from mailhelp.web.status_pages import _verdict
from tests.fakes.shared_web_actions import web  # noqa: F401  (fixture)


def test_the_overview_has_one_tile_per_purpose(web):
    """Regression 6.2.9: 22 tiles with four ways to check connections and devices listed twice."""
    page = web.browser.request("GET", "/einstellungen").body.decode()
    tiles = re.findall(r'<a class="settings-tile[^"]*" href="([^"]+)"><strong>([^<]+)</strong>', page)
    titles = [title for _href, title in tiles]
    assert len(tiles) == 18
    for gone in ("Diagnose", "Lesender Selbsttest", "Benachrichtigungsprofil", "Zustellhistorie", "Geräte"):
        assert gone not in titles
    assert ("/diagnose", "Verbindungen prüfen") in tiles
    assert len(set(href for href, _title in tiles)) == len(tiles)


@pytest.mark.parametrize("path", ["/diagnose", "/einstellungen/benachrichtigungen",
                                  "/benachrichtigungen", "/geraete"])
def test_every_former_tile_keeps_its_address(web, path):
    assert web.browser.request("GET", path).status != 404


def test_the_notification_area_leads_to_profile_and_history(web):
    page = web.browser.request("GET", "/einstellungen?bereich=benachrichtigungen").body.decode()
    assert 'href="/einstellungen/benachrichtigungen">Benachrichtigungsprofil: Ruhezeiten und Kanäle</a>' in page
    assert 'href="/benachrichtigungen">Zustellhistorie</a>' in page


def status(failed=0, damaged=0, imap=0):
    return (SimpleNamespace(damaged=damaged), SimpleNamespace(mails_failed=failed),
            SimpleNamespace(runtime={"imap_errors": [{}] * imap} if imap else None))


def test_the_verdict_says_all_is_well_or_names_each_problem_with_a_way_to_it():
    assert "<strong>Alles in Ordnung.</strong>" in _verdict(*status())
    warn = _verdict(*status(failed=1, imap=2))
    assert warn.startswith('<p class="notice notice-warn status-verdict" role="alert"><strong>Handlungsbedarf:</strong>')
    assert '<a href="/mails?state=failed">1 Mail mit Fehler</a> · <a href="#imap-fehler">2 Abruffehler</a>' in warn
    damaged = _verdict(*status(damaged=3))
    assert 'notice-error' in damaged and "3 beschädigte Datensätze – bitte Protokolle prüfen" in damaged


def test_the_status_page_shows_the_verdict_before_the_figures(web):
    page = web.browser.request("GET", "/status").body.decode()
    assert page.index("status-verdict") < page.index('class="stats') < page.index("status-summary")
