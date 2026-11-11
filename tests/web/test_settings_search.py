"""5.3 H3: the shared settings catalog, its normalisation, ranking and the form search built on it."""
from urllib.parse import quote

from mailhelp.configuration import SETTINGS_FIELDS
from mailhelp.web import settings_search
from mailhelp.web.settings_pages import AREAS, _names
from mailhelp.web.settings_search import Entry, anchor, bounded, catalog, normalize, search
from tests.fakes.shared_web_actions import web as web  # noqa: F401 - the fixture
from tests.fakes.shared_web_v12 import configure


def ids(query):
    return [entry.id for entry in search(query)]


def test_normalisation_folds_case_umlauts_and_space():
    assert normalize("  Größe   ÄNDERN übernehmen Öl ") == "groesse aendern uebernehmen oel"
    assert bounded("  " + "x" * 100) == "x" * 80


def test_the_catalog_covers_every_area_setting_and_the_special_pages():
    entries = catalog()
    assert len({entry.id for entry in entries}) == len(entries)
    shown = {name for _key, _title, _text, groups in AREAS for group in groups for name in _names(group)}
    assert {entry.key for entry in entries if entry.path == "Weboberfläche"} == shown and shown <= SETTINGS_FIELDS
    from devtools.inventory import settings_rows
    assert {entry.key for entry in entries if entry.key} == {row.key for row in settings_rows("")}
    timezone = next(entry for entry in entries if entry.key == "timezone")
    assert timezone.href == "/einstellungen?bereich=abruf#einstellung-timezone" and timezone.path == "Weboberfläche"
    assert {"page:postfaecher", "page:iserv", "page:zielprofile", "page:themen", "page:zugangsdaten"} <= {
        entry.id for entry in entries}
    assert anchor("timeouts.imap.retries") == "einstellung-timeouts-imap-retries"
    assert all(len(entry.summary) <= 160 for entry in entries)


def test_exact_keys_and_labels_come_first_then_word_starts_then_the_rest():
    assert ids("timezone")[0] == "setting:timezone"
    assert ids("Zeitzone")[0] == "setting:timezone"
    assert ids("timeouts.imap.retries") == ["setting:timeouts.imap.retries"]
    found = search("Abruf")
    assert found[0].label.casefold().startswith("abruf")
    ranks = [settings_search._rank(entry, "abruf", ["abruf"]) for entry in found]
    assert ranks == sorted(ranks)
    same = [entry for entry, rank in zip(found, ranks, strict=True) if rank == ranks[-1]]
    assert [normalize(entry.label) for entry in same] == sorted(normalize(entry.label) for entry in same)


def test_umlauts_spellings_synonyms_and_help_texts_are_found():
    assert ids("Aufbewahrung") == ids("aufbewahrung") == ids("AUFBEWAHRUNG")
    assert "page:postfaecher" in ids("Postfächer") and "page:postfaecher" in ids("postfaecher")
    assert "page:postfaecher" in ids("Konto")              # synonym of Postfach
    assert any(entry.key and entry.key.startswith("vision.") for entry in search("KI"))
    assert "setting:poll_interval_seconds" in ids("Mailserver")  # only in its help text
    assert ids("") == ids("   ") == [] and ids("niemandkenntdieseoption") == []


def test_every_word_must_match_and_no_value_is_searched():
    assert ids("Telegram Benutzer") and set(ids("Telegram Benutzer")) < set(ids("Telegram"))
    entry = Entry(id="x", label="A", area="B", summary="C", href="/")
    assert entry.text == "a b c"


def test_the_form_search_lists_settings_with_anchors_and_pages(web, tmp_path):
    configure(web, tmp_path)
    page = web.browser.request("GET", "/einstellungen?suche=" + quote("Zeitzone")).body.decode()
    assert '<div class="setting-row" id="einstellung-timezone">' in page and "Treffer für „Zeitzone“" in page
    assert 'Bereich <a href="/einstellungen?bereich=abruf">Mailabruf</a>' in page
    page = web.browser.request("GET", "/einstellungen?suche=" + quote("Postfach")).body.decode()
    assert '<h2>Seiten</h2>' in page and '<a href="/einstellungen/postfaecher">Postfächer</a>' in page
    page = web.browser.request("GET", "/einstellungen?suche=Elternbriefe").body.decode()
    assert '<a href="/einstellungen/iserv">IServ-Konten</a>' in page and "<h2>Einstellungen</h2>" not in page
    area = web.browser.request("GET", "/einstellungen?bereich=abruf").body.decode()
    assert 'id="einstellung-poll-interval-seconds"' in area


def test_the_result_page_without_configuration_service(web):
    page = web.browser.request("GET", "/einstellungen?suche=" + quote("Postfach")).body.decode()
    assert "Konfigurationsdienst nicht verfügbar" in page


def test_file_and_setup_settings_are_searchable_with_their_actual_editing_path(web, tmp_path):
    configure(web, tmp_path)
    for name in ("web.port", "logging.llm.filename", "reanalysis.max_jobs_per_day", "imap.mailboxes[].host"):
        found = search(name)
        assert found and found[0].key == name
        assert found[0].path != "Weboberfläche"
        assert found[0].href.startswith("/hilfe/dokumentation/")
        page = web.browser.request("GET", "/einstellungen?suche=" + quote(name)).body.decode()
        assert found[0].href in page and found[0].path in page
        assert 'name="value"' not in page


def test_a_missing_or_broken_extra_catalog_keeps_the_general_settings_search(tmp_path, monkeypatch):
    import json

    monkeypatch.setattr(settings_search, "EXTRA_CATALOG", tmp_path / "settings.json")
    assert settings_search.extra_catalog() == ()
    for content in ("invalid", json.dumps([{}]), json.dumps([{"label": "x", "help": "y"}])):
        settings_search.EXTRA_CATALOG.write_text(content, encoding="utf-8")
        assert settings_search.extra_catalog() == ()
