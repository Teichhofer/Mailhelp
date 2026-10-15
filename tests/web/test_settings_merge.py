"""Both credential forms retain their own checks after merging the web settings."""
from mailhelp.config import _dotenv


def test_draft_credentials_save_through_their_own_confirmed_handler(profiled):
    web = profiled.web
    form = web.form("/einstellungen/zugangsdaten", action="/einstellungen/zugangsdaten/speichern",
                    name="IMAP_1_PASSWORD")
    response = web.browser.request("POST", "/einstellungen/zugangsdaten/speichern",
                                   {**form, "value": "synthetic-draft-secret", "confirm": "yes"})
    assert response.status == 303
    assert _dotenv(profiled.tmp_path / ".env")["IMAP_1_PASSWORD"] == "synthetic-draft-secret"
    assert web.commands.queued() == []


def test_credential_save_routes_are_unique(profiled):
    routes = profiled.web.site.app._routes
    signatures = [(method, pattern.pattern) for method, pattern, _ in routes]
    assert len(signatures) == len(set(signatures))


def test_settings_link_to_credentials_for_unapproved_iserv_accounts(profiled):
    web, runtime = profiled.web, profiled.runtime
    before = (profiled.tmp_path / "config.yaml").read_bytes()
    runtime.setup.save("web:" + web.auth.sessions()[0].id, runtime.setup.state().version,
                       "merge-iserv-draft", 6,
                       {"iserv.accounts": [{"id": 1, "server": "https://schule.example", "mailbox": 1}]})
    page = web.browser.request("GET", "/einstellungen").body.decode()
    assert 'href="/einstellungen/zugangsdaten">Alle Zugangsdaten und neue Konten</a>' in page
    form = web.form("/einstellungen/zugangsdaten", action="/einstellungen/zugangsdaten/speichern",
                    name="ISERV_1_PASSWORD")
    response = web.browser.request("POST", "/einstellungen/zugangsdaten/speichern",
                                   {**form, "value": "synthetic-parent-secret", "confirm": "yes"})
    assert response.status == 303
    assert _dotenv(profiled.tmp_path / ".env")["ISERV_1_PASSWORD"] == "synthetic-parent-secret"
    assert (profiled.tmp_path / "config.yaml").read_bytes() == before
    assert web.commands.queued() == []
