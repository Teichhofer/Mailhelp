"""8.0: the instance's client of the central service and its token provider (synthetic only)."""
from types import SimpleNamespace

import httpx
import pytest

from inboxstride_auth.ca import create_ca, issue
from mailhelp.external.contracts import OAuthTokenError
from mailhelp.external.hosted_oauth import (
    HostedAuthClient,
    HostedRefused,
    HostedTokenProvider,
    HostedUnavailable,
    cached_client,
    mtls_transport,
)
from tests.fakes.hosted_google import settings


def answering(*responses):
    calls = []

    def handle(request):
        calls.append(request)
        response = responses[min(len(calls), len(responses)) - 1]
        if isinstance(response, Exception):
            raise response
        return response
    return httpx.MockTransport(handle), calls


class Events:
    def __init__(self):
        self.items = []

    def event(self, level, module, event, **context):
        self.items.append((module, event, context))


def test_the_client_separates_refusals_from_outages():
    transport, calls = answering(httpx.Response(200, json={"ok": True}),
                                 httpx.Response(409, json={"error": "job_changed"}),
                                 httpx.Response(403, json={"error": "unknown_certificate"}),
                                 httpx.Response(500, json={"error": "x"}), httpx.Response(200, text="kein json"),
                                 httpx.Response(200, json=["liste"]), httpx.Response(409, json={"error": 5}),
                                 httpx.ConnectError("weg"))
    client = HostedAuthClient(settings(), transport)
    assert client.post("/intern/token", {"connection": "c"}) == {"ok": True}
    assert calls[0].url == "https://auth-intern.inboxstride.example:8443/intern/token"
    for code in ("job_changed", "unknown_certificate"):
        with pytest.raises(HostedRefused) as refused:
            client.post("/intern/token", {})
        assert refused.value.code == code
    for _ in range(5):
        with pytest.raises(HostedUnavailable):
            client.post("/intern/token", {})
    client.close()


def test_tokens_are_cached_and_a_refusal_raises_the_7_9_warning():
    transport, calls = answering(httpx.Response(200, json={"access_token": "a1", "expires_in": 3600}),
                                 httpx.Response(409, json={"error": "reconnect_required"}),
                                 httpx.Response(200, json={"access_token": "", "expires_in": 3600}),
                                 httpx.Response(200, json={"access_token": "a2", "expires_in": 0}))
    events, now = Events(), [0.0]
    provider = HostedTokenProvider(HostedAuthClient(settings(), transport), "c" * 32, events, lambda: now[0])
    assert provider.access_token() == "a1" and provider.access_token() == "a1" and len(calls) == 1
    assert events.items[-1] == ("google_oauth", "token_credentials_accepted", {"mode": "hosted"})
    now[0] = 3571  # 30 seconds before expiry the cache ends
    with pytest.raises(OAuthTokenError, match="erneut verbinden"):
        provider.access_token()
    assert ("google_oauth", "token_refresh_denied", {"mode": "hosted", "reason": "reconnect_required"}) in events.items
    for _ in range(2):
        with pytest.raises(HostedUnavailable):
            provider.access_token()
    provider.invalidate()
    provider.close()


def test_one_client_serves_unchanged_settings_and_a_change_replaces_it():
    current = {"value": settings()}
    closed = []
    factory = cached_client(lambda: current["value"], httpx.MockTransport(lambda request: httpx.Response(200)))
    first = factory()
    assert first is factory()
    first.close = lambda: closed.append(True)
    current["value"] = settings("bert")
    assert factory() is not first and closed == [True]
    current["value"] = SimpleNamespace(enabled=False)
    assert factory() is None


def test_the_mtls_transport_uses_the_instance_certificate(tmp_path):
    create_ca(tmp_path / "ca")
    issue(tmp_path / "ca", tmp_path / "certs", "anna", server=False)
    configured = settings().model_copy(update={"certificate": str(tmp_path / "certs" / "anna.pem"),
                                               "key": str(tmp_path / "certs" / "anna.key"),
                                               "ca": str(tmp_path / "ca" / "ca.pem")})
    transport = mtls_transport(configured)
    assert isinstance(transport, httpx.HTTPTransport)
    transport.close()
