"""8.0: wiring of the hosted Google sign-in into the initial setup, the running app and the writers."""
import os
from types import SimpleNamespace

import pytest
import yaml
from pydantic import SecretStr, ValidationError

from inboxstride_auth.ca import create_ca, issue
from mailhelp.app import bootstrap, browser_accounts
from mailhelp.config import Settings, TargetProfileSettings, TargetSettings, WebSettings
from mailhelp.config.loader import provider_secret_names
from mailhelp.config.target_settings import HostedAuthSettings
from mailhelp.external.hosted_oauth import HostedAuthClient, HostedTokenProvider
from mailhelp.external.oauth import GoogleOAuthTokenProvider
from mailhelp.external.providers import google_tokens
from mailhelp.logging import NullLogger
from mailhelp.runtime.initial_setup import HOSTED_ENV, hosted_auth_from_env
from mailhelp.support.connection_health import ConnectionProblem
from mailhelp.web.connection_warnings import connection_warnings
from mailhelp.web.initial_pages import hosted_google_box, initial_page
from tests.fakes.hosted_google import settings as hosted_settings
from tests.fakes.initial_harness import InitialHarness

CONNECTION = "c" * 32
ENV = {name: value for name, value in zip(HOSTED_ENV.values(), (
    "https://auth-intern.inboxstride.example:8443", "anna", "/tls/a.pem", "/tls/a.key", "/tls/ca.pem"), strict=True)}


def tls(directory):
    """Real synthetic certificate files, so the mTLS transport can load them."""
    create_ca(directory / "ca")
    issue(directory / "ca", directory / "certs", "anna", server=False)
    return {"certificate": str(directory / "certs" / "anna.pem"), "key": str(directory / "certs" / "anna.key"),
            "ca": str(directory / "ca" / "ca.pem")}


@pytest.fixture
def hosted_initial(tmp_path, monkeypatch):
    for name in list(os.environ):
        if name.startswith(("GOOGLE_", "MICROSOFT_", "IMAP_", "OPENROUTER_", "TODOIST_", "MAILHELP_")):
            monkeypatch.delenv(name)
    files = tls(tmp_path / "tls")
    for name, value in {**ENV, "MAILHELP_HOSTED_AUTH_CERT": files["certificate"],
                        "MAILHELP_HOSTED_AUTH_KEY": files["key"], "MAILHELP_HOSTED_AUTH_CA": files["ca"]}.items():
        monkeypatch.setenv(name, value)
    harness = InitialHarness(tmp_path)
    yield harness
    harness.close()


def test_the_operator_environment_enables_the_hosted_sign_in():
    assert hosted_auth_from_env({}) is None
    assert hosted_auth_from_env(ENV) == {"enabled": True, "service_url": ENV["MAILHELP_HOSTED_AUTH_URL"],
                                         "instance_id": "anna", "certificate": "/tls/a.pem", "key": "/tls/a.key",
                                         "ca": "/tls/ca.pem"}


def test_the_initial_setup_offers_google_without_any_client_data(hosted_initial, monkeypatch):
    h = hosted_initial
    state = h.setup.state()
    assert state.config["hosted_auth"]["enabled"] is True
    page = initial_page(state, "csrf", 4)
    assert "Mit Google verbinden" in page and 'href="/google/verbinden?profile=1"' in page
    assert "GOOGLE_OAUTH_CLIENT_ID" not in page and "TODOIST_TOKEN" in page and "google_connection" not in page
    captured = {}
    monkeypatch.setattr(bootstrap, "HostedGoogleSite", lambda site, store, client, profiles, path, **kw:
                        captured.update(client=client, profiles=profiles, path=path, kw=kw))
    bootstrap.create_initial(h.directory, h.store, WebSettings(enabled=True), h.stopped, NullLogger())
    profiles = captured["profiles"]
    assert captured["path"] == "/einrichtung/start" and captured["kw"] == {"navigation": False}
    assert profiles.draft(1) == ("", h.setup.state().version)
    with pytest.raises(LookupError):
        profiles.target(2)
    assert profiles.target(1).startswith("draft:") and len(profiles.target(1)) == 38
    h.advance()
    profiles.save(h.actor, 1, {"calendar_provider": "google", "google_calendar": "familie",
                               "google_connection": CONNECTION}, h.setup.state().version, "d" * 32)
    targets = h.setup.state().config["targets"]
    assert (targets["google_calendar"], targets["google_connection"]) == ("familie", CONNECTION)
    assert "über Inboxstride verbunden (Kalender familie)" in initial_page(h.setup.state(), "csrf", 4)
    client = captured["client"]()
    assert isinstance(client, HostedAuthClient)
    client.close()


def test_the_running_app_binds_target_profiles_and_offers_the_connection(configured, monkeypatch):
    c = configured
    c.cfg.target_profiles = [TargetProfileSettings(id=2, label="Work", google_calendar="primary",
                                                   todoist_project="inbox")]
    (c.tmp_path / "config.yaml").write_text(yaml.safe_dump(c.cfg.model_dump(mode="json")), encoding="utf-8")
    c.app.services = SimpleNamespace()
    captured = {}
    monkeypatch.setattr(browser_accounts, "HostedGoogleSite", lambda site, store, client, profiles, path:
                        captured.update(client=client, profiles=profiles, path=path))
    browser_accounts.attach_accounts(c.app, c.web.site, c.tmp_path)
    profiles = captured["profiles"]
    assert captured["path"] == "/einrichtung" and captured["client"]() is None  # not hosted
    assert profiles.draft(2)[0] == "" and profiles.target(2) == "profile:2"
    with pytest.raises(LookupError):
        profiles.target(5)
    hosted = c.cfg.model_copy(update={"hosted_auth": hosted_settings().model_copy(update=tls(c.tmp_path / "tls"))})
    (c.tmp_path / "config.yaml").write_text(yaml.safe_dump(hosted.model_dump(mode="json")), encoding="utf-8")
    client = captured["client"]()
    assert isinstance(client, HostedAuthClient)
    client.close()
    page = c.web.browser.request("GET", "/einstellungen/zielprofile").body.decode()
    assert page.count('href="/google/verbinden?profile=') == 2
    # Bugfix 7.9.8: the adoption saves through the real settings draft; google_connection was refused there
    # as "Nicht angebotene Einstellung" after the central service had already activated the access.
    actor = "web:" + c.web.auth.authenticate(c.web.browser.cookies["mh_session"]).id
    setup = c.web.site.setup_page.runtime.setup
    for number, key in ((1, "a" * 32), (2, "b" * 32)):
        profiles.save(actor, number, {"calendar_provider": "google", "google_calendar": "familie",
                                      "google_connection": CONNECTION}, setup.state().version, key)
        assert profiles.draft(number) == (CONNECTION, setup.state().version)


def test_a_hosted_connection_needs_the_service_and_the_calendar_only(tmp_path):
    from tests.fakes.shared_profiles import settings
    base = settings(tmp_path).model_dump(mode="json")
    base["targets"]["google_connection"] = CONNECTION
    with pytest.raises(ValidationError, match="hosted_auth.enabled"):
        Settings.model_validate(base)
    base["hosted_auth"] = hosted_settings().model_dump()
    assert Settings.model_validate(base).targets.google_connection == CONNECTION
    with pytest.raises(ValidationError, match="nicht für Google Tasks"):
        TargetSettings(google_calendar="primary", google_connection=CONNECTION, task_provider="google_tasks")
    with pytest.raises(ValidationError, match="hosted_auth benötigt"):
        HostedAuthSettings(enabled=True, service_url="https://x.example")
    targets = TargetSettings(google_calendar="primary", todoist_project="inbox", google_connection=CONNECTION)
    assert provider_secret_names(targets) == ["TODOIST_TOKEN"]  # no Google secret in the instance


def test_the_writers_obtain_google_access_by_mode(tmp_path):
    secrets = SimpleNamespace(google_oauth_client_id=SecretStr("i"), google_oauth_client_secret=SecretStr("s"),
                              google_oauth_refresh_token=SecretStr("r"))
    hosted = SimpleNamespace(targets=SimpleNamespace(google_connection=CONNECTION, uses_google=True),
                             hosted_auth=hosted_settings().model_copy(update=tls(tmp_path)))
    provider = google_tokens(hosted, secrets, 15, None, None)
    assert isinstance(provider, HostedTokenProvider) and provider.connection == CONNECTION
    provider.close()
    direct = SimpleNamespace(targets=SimpleNamespace(google_connection="", uses_google=True))
    token = google_tokens(direct, secrets, 15, None, None)
    assert isinstance(token, GoogleOAuthTokenProvider)
    token.close()
    none = SimpleNamespace(targets=SimpleNamespace(google_connection="", uses_google=False))
    assert google_tokens(none, secrets, 15, None, None) is None


def test_hosted_google_warnings_lead_to_reconnecting(web):
    from datetime import UTC, datetime
    when = datetime(2026, 11, 19, 8, tzinfo=UTC)
    problems = [ConnectionProblem(key="google_oauth", service="google_oauth", code="refresh_denied",
                                  first_seen=when, last_seen=when, sequence=1),
                ConnectionProblem(key="google_calendar", service="google_calendar", code="login_rejected", number=2,
                                  first_seen=when, last_seen=when, sequence=2),
                ConnectionProblem(key="todoist", service="todoist", code="login_rejected", first_seen=when,
                                  last_seen=when, sequence=3)]
    html = connection_warnings(problems, "UTC", hosted_google=True)
    assert 'href="/google/verbinden?profile=1">Google erneut verbinden' in html
    assert 'href="/google/verbinden?profile=2">Google erneut verbinden' in html
    assert 'href="/einstellungen/zielprofile">Verbindung prüfen' in html
    web.site.archive.configuration = SimpleNamespace(active=SimpleNamespace(hosted_auth=hosted_settings()))
    from mailhelp.support.connection_health import STATE, ConnectionHealth
    web.store.save(STATE, ConnectionHealth(sequence=1, problems={"google_oauth": problems[0]}).model_dump(mode="json"))
    assert "Google erneut verbinden" in web.site.connection_state()[0]
    assert hosted_google_box({"google_connection": ""}, 3).count("profile=3") == 1
