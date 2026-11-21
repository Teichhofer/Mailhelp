"""Mailbox consent, folder selection and replacement in real browsers, with synthetic providers."""
from html import escape
from urllib.parse import parse_qs, urlencode

import httpx
import pytest
from playwright.sync_api import expect

from inboxstride_auth.google import Client, GoogleTokens
from inboxstride_auth.http_api import public
from inboxstride_auth.microsoft import CALLBACK, MicrosoftTokens
from inboxstride_auth.models import MAIL_SCOPES
from mailhelp.app import mailbox_accounts
from mailhelp.external.hosted_oauth import HostedRefused
from mailhelp.web.http import Response
from tests.fakes.hosted_google import Central
from tests.fakes.initial_harness import InitialHarness
from tests.fakes.shared_web_auth import SECRET


@pytest.mark.parametrize("purpose", ["gmail", "microsoft"])
@pytest.mark.parametrize("locale", ["de", "en"])
@pytest.mark.parametrize("width", [1366, 390, 320])
def test_mailbox_first_connection_and_replacement(https_browser, tmp_path, monkeypatch, purpose, locale, width):
    transport = https_browser(width)
    page = transport.page
    (tmp_path / "hub").mkdir()
    central = Central(tmp_path / "hub")
    tokens_class = MicrosoftTokens if purpose == "microsoft" else GoogleTokens
    client = Client("synthetic", "synthetic", CALLBACK) if purpose == "microsoft" else Client("synthetic", "synthetic")
    tokens = tokens_class(client, transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={
        "access_token": "synthetic-mail", "refresh_token": "synthetic-refresh", "expires_in": 3600,
        "token_type": "Bearer", "scope": " ".join(MAIL_SCOPES[purpose])})))
    central.service.mail_providers[purpose] = tokens
    monkeypatch.setattr("mailhelp.external.hosted_oauth.mtls_transport", lambda _settings: central.transport("anna"))
    monkeypatch.setattr(mailbox_accounts, "probe", lambda *_: [("INBOX", "inbox"), ("Drafts", "drafts")])
    for key, value in {"URL": "https://auth-intern.inboxstride.example:8443", "INSTANCE": "anna",
                       "CERT": "synthetic.pem", "KEY": "synthetic.key", "CA": "synthetic-ca.pem"}.items():
        monkeypatch.setenv("MAILHELP_HOSTED_AUTH_" + key, value)
    monkeypatch.setenv("MAILHELP_WEB_SECRET", SECRET)
    harness = InitialHarness(tmp_path / "anna")
    origin = "https://anna.inboxstride.example"
    harness.app.allowed_hosts = frozenset({"anna.inboxstride.example"})
    harness.setup.save(harness.actor, harness.form(1, password="synthetic-browser-password"))
    page.context.add_cookies([
        {"name": "mh_session", "value": harness.token, "url": origin, "sameSite": "Strict"},
        {"name": "mailhelp_lang", "value": locale, "url": origin, "sameSite": "Lax"}])

    def bridge(request):
        if request.host in {"accounts.google.com", "login.microsoftonline.com"}:
            if request.path == "/favicon.ico":
                return Response(204)
            query = parse_qs(request.query)
            callback = query["redirect_uri"][0] + "?" + urlencode({"state": query["state"][0], "code": "good"})
            return Response.html(200,
                '<html><title>Synthetic consent</title><a href="' + escape(callback, quote=True)
                + '">Synthetic consent</a></html>')
        if request.host == "auth.inboxstride.de":
            result = public(central.service, request.method, request.path + "?" + request.query, lambda *_: None)
            return Response(result.status, result.body, headers=result.headers)
        if request.host == "anna.inboxstride.example":
            return harness.app(request)
        return Response.text(404, "Synthetic host missing")

    transport.dispatch = bridge
    try:
        previous = None
        for _ in range(2):
            page.goto(origin + f"/postfach/oauth?provider={purpose}&mailbox=1")
            page.get_by_role("textbox").fill("user@example.test")
            page.get_by_role("button", name="Sign in with provider" if locale == "en" else
                             "Beim Anbieter anmelden").click()
            page.get_by_role("link", name="Synthetic consent").click()
            page.wait_for_url(origin + "/einrichtung/postfach/abschluss?*")
            page.get_by_role("link", name="Check mailbox" if locale == "en" else "Postfach prüfen").click()
            page.get_by_role("button", name="Check mailbox" if locale == "en" else "Postfach prüfen").click()
            expect(page.get_by_role("combobox", name="Inbox" if locale == "en" else "Posteingang",
                                    exact=True)).to_be_visible()
            if previous:
                assert central.service.state.read().connections[previous].status == "active"
            page.get_by_role("button", name="Adopt mailbox connection" if locale == "en" else
                             "Postfachverbindung übernehmen").click()
            expect(page.page).to_have_url(origin + "/einrichtung/start")
            current = harness.setup.state().config["imap"]["oauth_connection"]
            assert central.service.state.read().connections[current].status == "active"
            if previous:
                assert current != previous
                assert central.service.state.read().connections[previous].status == "disconnected"
            previous = current
        assert harness.setup.environment()["IMAP_USERNAME"] == "user@example.test"
        assert not (harness.directory / "config.yaml").exists()
        other = central.client("bert")
        try:
            with pytest.raises(HostedRefused):
                other.post("/intern/token", {"connection": current, "purpose": purpose})
        finally:
            other.close()
        assert harness.store.load("action-ledger", {"entries": []})["entries"] == []
    finally:
        harness.close()
        tokens.close()
        central.close()
