"""Settings overview, dedicated areas and word-based search (3.5)."""
from urllib.parse import quote

import pytest
import yaml
from shared_web_v12 import configure

from mailhelp.configuration import SETTINGS_FIELDS
from mailhelp.web.settings_pages import AREA_KEYS, AREAS, _names, settings_page


def test_overview_links_counts_and_pending_badges(profiled):
    ctx = profiled
    page = ctx.web.browser.request("GET", "/einstellungen").body.decode()
    for title in ("Konten und Verbindungen", "Allgemeine Einstellungen", "Inhalte und Benachrichtigungen", "System"):
        assert f"<h2>{title}</h2>" in page
    assert "2 eingerichtet" in page and "0 eingerichtet" in page
    assert 'name="suche"' in page and "/einstellungen/speichern" not in page
    path = ctx.tmp_path / "config.yaml"
    raw = yaml.safe_load(path.read_text())
    raw["poll_interval_seconds"] = 33
    raw["metrics"]["usd_per_eur"] = 1.5
    raw["metrics"]["enabled"] = False
    path.write_text(yaml.safe_dump(raw))
    page = ctx.web.browser.request("GET", "/einstellungen").body.decode()
    assert "1 Änderung ausstehend" in page and "2 Änderungen ausstehend" in page


@pytest.mark.parametrize("area", sorted(AREA_KEYS))
def test_areas_have_current_navigation_and_only_their_own_controls(web, tmp_path, area):
    configure(web, tmp_path)
    page = web.browser.request("GET", "/einstellungen?bereich=" + area).body.decode()
    assert f'href="/einstellungen?bereich={area}" aria-current="page"' in page
    assert page.count('aria-current="page"') == 2  # Main navigation and area navigation.
    if area == "zugangsdaten":
        assert 'id="settings-credentials"' in page and "/einstellungen/speichern" not in page
        return
    groups = next(groups for key, _, _, groups in AREAS if key == area)
    names = {name for group in groups for name in _names(group)}
    for name in SETTINGS_FIELDS:
        assert (f'name="name" value="{name}"' in page) == (name in names)
    assert ('id="push-controls"' in page) == (area == "benachrichtigungen")
    assert ("Modelle (nur lesend)" in page) == (area == "ki")


@pytest.mark.parametrize(("query", "found", "absent"), [
    ("ZEITzone", "timezone", "poll_interval_seconds"),
    ("Mailabruf Intervall", "poll_interval_seconds", "timezone"),
    ("timeouts.imap.retries", "timeouts.imap.retries", "timeouts.todoist.retries"),
    ("niemandkenntdieseoption", "", "timezone"),
    ('<script>alert("x")</script>', "", "timezone"),
])
def test_search_matches_every_word_and_escapes_input(web, tmp_path, query, found, absent):
    configure(web, tmp_path)
    page = web.browser.request("GET", "/einstellungen?suche=" + quote(query)).body.decode()
    if found:
        assert f'name="name" value="{found}"' in page and 'Bereich <a href="/einstellungen?bereich=' in page
    else:
        assert "Keine Einstellung zu" in page
    assert f'name="name" value="{absent}"' not in page and "<script>alert" not in page


def test_unknown_area_is_not_found_and_empty_search_returns_overview(web):
    assert web.browser.request("GET", "/einstellungen?bereich=unbekannt").status == 404
    assert "Konten und Verbindungen" in web.browser.request("GET", "/einstellungen?suche=%20").body.decode()


def test_unavailable_configuration_keeps_navigation_and_reports_problem(web):
    page = web.browser.request("GET", "/einstellungen").body.decode()
    assert "hinzufügen, prüfen und anpassen" in page and "eingerichtet ·" not in page
    for area in ("abruf", "ki"):
        page = web.browser.request("GET", "/einstellungen?bereich=" + area).body.decode()
        assert "Konfigurationsdienst nicht verfügbar" in page
    page = web.browser.request("GET", "/einstellungen?suche=Zeitzone").body.decode()
    assert "Konfigurationsdienst nicht verfügbar" in page
    assert "1 eingerichtet" in settings_page([], {}, {}, "", "")  # Former single-mailbox format.
