"""Synthetic token exchanges; no browser login or external calendar writes."""
import io
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from pydantic import SecretStr
from shared_decision_test import secrets

from mailhelp.external.contracts import OAuthTokenError
from mailhelp.google_login import login, receive_code


def test_google_profiles_get_distinct_refresh_tokens_and_keep_other_env(tmp_path):
    path = tmp_path / ".env"
    path.write_text('# retained\nGOOGLE_OAUTH_2_REFRESH_TOKEN="old"\nOTHER=value\n', encoding="utf-8")
    requests = []
    def receiver(builder):
        query = parse_qs(urlsplit(builder("http://127.0.0.1:1234/oauth/callback", "state", "challenge")).query)
        assert query["code_challenge_method"] == ["S256"] and query["state"] == ["state"]
        assert query["access_type"] == ["offline"]
        return "synthetic-code", "http://127.0.0.1:1234/oauth/callback", "verifier"
    def transport(request):
        requests.append(parse_qs(request.content.decode()))
        return httpx.Response(200, json={"refresh_token": 'synthetic\\"token'})
    login(secrets(), tmp_path, 2, receiver=receiver, transport=httpx.MockTransport(transport))
    text = path.read_text()
    assert text.startswith("# retained\nOTHER=value\n") and text.count("GOOGLE_OAUTH_2_REFRESH_TOKEN") == 1
    assert requests[0]["code_verifier"] == ["verifier"]
    login(secrets(), tmp_path, receiver=receiver, transport=httpx.MockTransport(transport))
    assert "GOOGLE_OAUTH_REFRESH_TOKEN=" in path.read_text()


@pytest.mark.parametrize("response", [httpx.Response(400), httpx.Response(200, text="bad"),
    httpx.Response(200, json={}), httpx.Response(200, json={"refresh_token": None}),
    httpx.Response(200, json={"refresh_token": ""}), httpx.Response(200, json={"refresh_token": "x" * 16385})])
def test_invalid_token_response_does_not_overwrite_credentials(tmp_path, response):
    path = tmp_path / ".env"
    path.write_text("OTHER=keep\n")
    with pytest.raises(OAuthTokenError, match="kein Refresh-Token"):
        login(secrets(), tmp_path, receiver=lambda _: ("code", "redirect", "verifier"),
              transport=httpx.MockTransport(lambda _: response))
    assert path.read_text() == "OTHER=keep\n"


def test_login_handles_network_failure_and_missing_clients(tmp_path):
    with pytest.raises(OAuthTokenError, match="Client"):
        login(secrets().model_copy(update={"google_oauth_client_id": SecretStr("")}), tmp_path)
    def fail(_):
        raise httpx.ConnectError("private response")
    with pytest.raises(OAuthTokenError) as error:
        login(secrets(), tmp_path, receiver=lambda _: ("c", "r", "v"), transport=httpx.MockTransport(fail))
    assert "private" not in str(error.value)


class Server:
    """Drive the real callback handler with synthetic requests, without opening a socket."""
    instances = []
    def __init__(self, address, handler):
        assert address == ("127.0.0.1", 0)
        self.handler, self.server_port, self.paths, self.responses = handler, 1234, [], []
        self.instances.append(self)
    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.closed = True
    def handle_request(self):
        instance = object.__new__(self.handler)
        instance.path = self.paths.pop(0)
        instance.wfile = io.BytesIO()
        instance.send_response = self.responses.append
        instance.send_header = lambda *args: None
        instance.end_headers = lambda: None
        instance.log_message("never log codes")
        instance.do_GET()
        assert b"secret" not in instance.wfile.getvalue()


def test_loopback_requires_correct_state_path_and_single_nonempty_code():
    def opener(url):
        state = parse_qs(urlsplit(url).query)["state"][0]
        Server.instances[-1].paths = ["/wrong?state=" + state + "&code=secret", "/oauth/callback?state=wrong&code=secret",
            "/oauth/callback?state=" + state + "&code=", "/oauth/callback?state=" + state + "&code=a&code=b",
            "/oauth/callback?state=" + state + "&code=secret"]
        return True
    code, redirect, verifier = receive_code(lambda r, s, c: "https://example.test?state=" + s,
        opener=opener, server_factory=Server, clock=lambda: 0)
    assert code == "secret" and redirect.startswith("http://127.0.0.1:") and 43 <= len(verifier) <= 128
    assert Server.instances[-1].responses == [400, 400, 400, 400, 200] and Server.instances[-1].closed


def test_loopback_browser_failure_and_timeout_close_server():
    with pytest.raises(OAuthTokenError, match="Browser"):
        receive_code(lambda *args: "url", opener=lambda _: False, server_factory=Server)
    clock = iter([0, 301])
    with pytest.raises(OAuthTokenError, match="abgelaufen"):
        receive_code(lambda *args: "url", opener=lambda _: True, server_factory=Server, clock=lambda: next(clock))
    assert Server.instances[-1].closed
