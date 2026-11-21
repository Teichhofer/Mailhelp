"""Real browser redirects/cookies across Google, central callback and two synthetic tenants."""
from html import escape
from urllib.parse import parse_qs, urlencode

import pytest
from playwright.sync_api import expect

from inboxstride_auth.http_api import public
from mailhelp.app import bootstrap
from mailhelp.external.hosted_oauth import HostedRefused
from mailhelp.web.hosted_google_site import HostedGoogleSite
from mailhelp.web.http import Response
from tests.fakes.hosted_google import Central
from tests.fakes.initial_harness import InitialHarness
from tests.fakes.shared_web_auth import SECRET


@pytest.mark.parametrize("replace_connection", [False, True])
@pytest.mark.parametrize("width", [1366, 390, 320])
def test_initial_google_connection_and_replacement_across_tenants(https_browser, tmp_path, monkeypatch,
                                                                replace_connection, width):
    transport = https_browser(width)
    page = transport.page
    (tmp_path / "hub").mkdir()
    central = Central(tmp_path / "hub")
    monkeypatch.setattr("mailhelp.external.hosted_oauth.mtls_transport",
                        lambda settings: central.transport(settings.instance_id))
    monkeypatch.setattr(bootstrap, "HostedGoogleSite", lambda *args, **kwargs:
        HostedGoogleSite(*args, **kwargs, transport=central.transport("anna")))
    for key, value in {"URL": "https://auth-intern.inboxstride.example:8443", "CERT": "synthetic.pem",
                       "KEY": "synthetic.key", "CA": "synthetic-ca.pem"}.items():
        monkeypatch.setenv("MAILHELP_HOSTED_AUTH_" + key, value)
    monkeypatch.setenv("MAILHELP_WEB_SECRET", SECRET)
    harnesses = {}
    try:
        for name in ("anna", "bert"):
            monkeypatch.setenv("MAILHELP_HOSTED_AUTH_INSTANCE", name)
            harness = InitialHarness(tmp_path / name)
            harnesses[name + ".inboxstride.example"] = harness
            harness.app.allowed_hosts = frozenset({name + ".inboxstride.example"})
            harness.setup.save(harness.actor, harness.form(1, password="synthetic-browser-password"))
            harness.setup.save(harness.actor, harness.form(2, **{
                "imap.host": "imap.example.test", "IMAP_USERNAME": "user@example.test",
                "IMAP_PASSWORD": "synthetic-imap-password"}))
            harness.setup.save(harness.actor, harness.form(3, OPENROUTER_API_KEY="synthetic-key"))
            page.context.add_cookies([{"name": "mh_session", "value": harness.token,
                                      "url": "https://" + name + ".inboxstride.example", "sameSite": "Strict"}])

        def bridge(request):
            if request.host == "accounts.google.com":
                if request.path == "/favicon.ico":
                    return Response(204)
                query = parse_qs(request.query)
                callback = query["redirect_uri"][0] + "?" + urlencode({"state": query["state"][0], "code": "good"})
                return Response.html(200,
                    '<html><title>Synthetic Google consent</title><a href="' + escape(callback, quote=True)
                    + '">Synthetic consent</a></html>')
            if request.host == "auth.inboxstride.de":
                answer = public(central.service, request.method, request.path + "?" + request.query, lambda *_: None)
                return Response(answer.status, answer.body, headers=answer.headers)
            if request.host in harnesses:
                return harnesses[request.host].app(request)
            return Response.text(404, "Synthetic host missing")

        transport.dispatch = bridge
        origin = "https://anna.inboxstride.example"

        def connect():
            page.goto(origin + "/google/verbinden?profile=1")
            page.get_by_role("button", name="Weiter zu Google", exact=True).click()
            expect(page.get_by_role("link", name="Synthetic consent")).to_be_visible()
            page.get_by_role("link", name="Synthetic consent").click()
            page.wait_for_url(origin + "/einrichtung/google/abschluss?*")
            expect(page.locator("h1")).to_be_visible()
            if page.get_by_role("link", name="Fortsetzen", exact=True).count():
                page.get_by_role("link", name="Fortsetzen", exact=True).click()
            expect(page.get_by_role("button", name="Kalender auswählen", exact=True)).to_be_visible()
            page.get_by_role("button", name="Kalender auswählen", exact=True).click()
            expect(page.get_by_role("combobox", name="Google-Kalender", exact=True)).to_be_visible()

        anna = harnesses["anna.inboxstride.example"]
        connect()
        assert not (anna.directory / "config.yaml").exists()
        assert anna.setup.state().config["targets"].get("google_connection", "") == ""
        page.get_by_role("button", name="Verbindung übernehmen", exact=True).click()
        expect(page.page).to_have_url(origin + "/einrichtung/start")
        previous = anna.setup.state().config["targets"]["google_connection"]
        assert central.service.state.read().connections[previous].status == "active"
        bert = harnesses["bert.inboxstride.example"]
        assert bert.setup.state().config["targets"].get("google_connection", "") == ""
        # A different host/session cannot retrieve the other instance's token even in the same browser context.
        response = central.client("bert")
        try:
            with pytest.raises(HostedRefused):
                response.post("/intern/token", {"connection": previous})
        finally:
            response.close()
        if replace_connection:
            connect()
            assert central.service.state.read().connections[previous].status == "active"
            page.get_by_role("button", name="Verbindung übernehmen", exact=True).click()
            expect(page.page).to_have_url(origin + "/einrichtung/start")
            current = anna.setup.state().config["targets"]["google_connection"]
            assert current != previous and central.service.state.read().connections[previous].status == "disconnected"
        assert anna.store.load("action-ledger", {"entries": []})["entries"] == []
    finally:
        for harness in harnesses.values():
            harness.close()
        central.close()
