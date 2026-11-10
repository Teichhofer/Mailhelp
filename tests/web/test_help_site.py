"""5.3 H7: the local reader of the packaged help sections."""
from mailhelp.helpdocs import HelpUnavailable
from tests.fakes.shared_web_actions import web as web  # noqa: F401 - the fixture
from tests.fakes.shared_web_auth import Browser


def test_the_index_and_a_section_are_readable_and_escaped(web):
    index = web.browser.request("GET", "/hilfe/dokumentation").body.decode()
    assert "<h1>Hilfe und Dokumentation</h1>" in index and 'href="/hilfe/dokumentation/betrieb/sicherung"' in index
    page = web.browser.request("GET", "/hilfe/dokumentation/web-einstellungen/postfach-briefings-49")
    assert page.status == 200 and page.cache == "no-store"
    text = page.body.decode()
    assert '<pre class="help-text">' in text and "Quelle: docs/Web-Einstellungen.md" in text
    escaped = web.browser.request("GET", "/hilfe/dokumentation/web-einstellungen/zugangsdaten-3311").body.decode()
    assert "IMAP_&lt;n&gt;_USERNAME" in escaped and "IMAP_<n>_USERNAME" not in escaped


def test_unknown_or_foreign_sections_are_not_found(web):
    assert web.browser.request("GET", "/hilfe/dokumentation/betrieb/gibt-es-nicht").status == 404
    assert web.browser.request("GET", "/hilfe/dokumentation/../../config.yaml").status in {400, 404}
    assert web.browser.request("GET", "/hilfe/dokumentation/BETRIEB/sicherung").status == 404


def test_the_reader_needs_a_session(web):
    assert Browser(web.app).request("GET", "/hilfe/dokumentation").status == 303


def test_an_unusable_resource_is_explained(web, monkeypatch):
    def broken():
        raise HelpUnavailable("kaputt")
    monkeypatch.setattr("mailhelp.web.help_site.load", broken)
    web.site.archive.help._base = None
    for path in ("/hilfe/dokumentation", "/hilfe/dokumentation/betrieb/sicherung"):
        page = web.browser.request("GET", path)
        assert page.status == 503 and "Einstellungen und Suche funktionieren weiterhin" in page.body.decode()
