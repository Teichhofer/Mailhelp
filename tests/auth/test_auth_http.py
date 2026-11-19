"""8.0: public callback, internal mTLS API, own CA and operator commands (synthetic hosts only)."""
import json
import runpy
import ssl
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from inboxstride_auth import __main__ as cli
from inboxstride_auth.ca import create_ca, fingerprint, issue
from inboxstride_auth.google import Client, GoogleTokens
from inboxstride_auth.http_api import SECURITY, internal, public, serve, server_context
from inboxstride_auth.models import Instance
from inboxstride_auth.secret_store import SecretStore, create_key
from inboxstride_auth.service import AuthService
from inboxstride_auth.state_file import StateFile
from tests.fakes.google_oauth import FakeGoogle

SESSION = "a" * 64


@pytest.fixture
def pki(tmp_path_factory):
    root = tmp_path_factory.mktemp("pki")
    create_ca(root / "ca")
    issue(root / "ca", root / "certs", "localhost", server=True)
    anna = issue(root / "ca", root / "certs", "anna", server=False)
    create_ca(root / "other")
    issue(root / "other", root / "foreign", "anna", server=False)
    return root, anna


@pytest.fixture
def service(tmp_path, pki):
    key = tmp_path / "auth.key"
    create_key(key)
    google = FakeGoogle()
    tokens = GoogleTokens(Client("synthetic-client", "synthetic-client-secret"), transport=httpx.MockTransport(google))
    auth = AuthService(StateFile(tmp_path / "state"), SecretStore(tmp_path / "state", key), tokens)
    auth.register(Instance(id="anna", host="anna.inboxstride.example", certificate=pki[1]))
    auth.register(Instance(id="bert", host="bert.inboxstride.example", certificate="2" * 64))
    yield auth
    tokens.close()


def collect():
    events = []
    return events, lambda event, context: events.append((event, context))


def test_the_internal_api_acts_only_for_the_instance_of_the_certificate(service, pki):
    events, log = collect()
    started = internal(service, "POST", "/intern/start", json.dumps(
        {"session": SESSION, "target": "profile:1", "operation": "connect", "key": "k1"}).encode(), pki[1], log)
    assert started.status == 200
    url = json.loads(started.body)["url"]
    state = parse_qs(urlsplit(url).query)["state"][0]
    answer = public(service, "GET", f"/auth/google/callback?state={state}&code=good", log)
    assert answer.status == 303 and answer.headers["Location"].startswith("https://anna.inboxstride.example/")
    receipt = parse_qs(urlsplit(answer.headers["Location"]).query)["beleg"][0]
    redeemed = json.loads(internal(service, "POST", "/intern/redeem", json.dumps(
        {"session": SESSION, "receipt": receipt}).encode(), pki[1], log).body)
    assert redeemed["target"] == "profile:1" and redeemed["operation"] == "connect"
    token = json.loads(internal(service, "POST", "/intern/token", json.dumps(
        {"connection": redeemed["connection"]}).encode(), pki[1], log).body)
    assert token["access_token"] == "access-1"
    activated = json.loads(internal(service, "POST", "/intern/activate", json.dumps(
        {"session": SESSION, "job": redeemed["job"], "version": redeemed["version"]}).encode(), pki[1], log).body)
    assert activated["generation"] == 1
    status = internal(service, "POST", "/intern/connection", json.dumps(
        {"connection": redeemed["connection"]}).encode(), pki[1], log)
    assert json.loads(status.body) == {"status": "active", "generation": 1, "target": "profile:1"}
    assert internal(service, "POST", "/intern/connection", json.dumps({"connection": "x" * 32}).encode(),
                    pki[1], log).status == 409
    gone = internal(service, "POST", "/intern/disconnect", json.dumps(
        {"connection": redeemed["connection"]}).encode(), pki[1], log)
    assert json.loads(gone.body) == {"status": "disconnected"}
    # Another registered instance with its own certificate sees nothing of it.
    foreign = internal(service, "POST", "/intern/connection", json.dumps(
        {"connection": redeemed["connection"]}).encode(), "2" * 64, log)
    assert foreign.status == 409 and json.loads(foreign.body) == {"error": "unknown_connection"}
    text = json.dumps(events)
    assert "good" not in text and receipt not in text and state not in text and "access-1" not in text


@pytest.mark.parametrize(("method", "path", "body", "peer", "status", "error"), [
    ("POST", "/intern/start", b"{}", None, 403, "unknown_certificate"),
    ("POST", "/intern/start", b"{}", "f" * 64, 403, "unknown_certificate"),
    ("GET", "/intern/start", b"", "P", 404, "not_found"),
    ("POST", "/intern/raus", b"{}", "P", 404, "not_found"),
    ("POST", "/intern/start", b"x" * 20000, "P", 413, "too_large"),
    ("POST", "/intern/start", b"[1]", "P", 400, "invalid_request"),
    ("POST", "/intern/start", b"{", "P", 400, "invalid_request"),
    ("POST", "/intern/activate", b'{"session": "s", "job": "j", "version": "x"}', "P", 400, "invalid_request"),
    ("POST", "/intern/redeem", b'{"session": "s", "receipt": "r"}', "P", 409, "unknown_receipt"),
])
def test_unusable_internal_requests_change_nothing(service, pki, method, path, body, peer, status, error):
    answer = internal(service, method, path, body, pki[1] if peer == "P" else peer, collect()[1])
    assert answer.status == status and json.loads(answer.body) == {"error": error}


def test_disabled_instances_are_revoked_at_once(service, pki):
    def disable(state):
        item = state.instances["anna"].model_copy(update={"enabled": False})
        return state.model_copy(update={"instances": {**state.instances, "anna": item}})
    service.state.update(disable)
    assert internal(service, "POST", "/intern/token", b"{}", pki[1], collect()[1]).status == 403


@pytest.mark.parametrize(("target", "status"), [
    ("/auth/google/callback?state=a&state=b&code=c", 400), ("/auth/google/callback?code=c", 400),
    ("/auth/google/callback?state=erfunden&code=c", 400), ("/sonstwo", 404),
])
def test_the_public_side_offers_nothing_beyond_the_callback(service, target, status):
    events, log = collect()
    answer = public(service, "GET", target, log)
    assert answer.status == status and b"<h1>" in answer.body and answer.headers["Content-Type"].startswith("text/html")
    assert public(service, "POST", "/auth/google/callback", log).status == 404
    assert json.loads(public(service, "GET", "/health", log).body) == {"status": "ok"}
    assert "erfunden" not in json.dumps(events)


def test_the_servers_require_a_client_certificate_of_the_own_ca(service, pki):
    root, _anna = pki
    events, log = collect()
    context = server_context(str(root / "certs" / "localhost.pem"), str(root / "certs" / "localhost.key"),
                             str(root / "ca" / "ca.pem"))
    inner = serve(service, ("127.0.0.1", 0), log, context)
    outer = serve(service, ("127.0.0.1", 0), log)
    try:
        port = inner.server_address[1]
        # Explicit transports: only this test's own loopback servers are contacted.
        own = httpx.Client(transport=httpx.HTTPTransport(
            verify=ssl.create_default_context(cafile=str(root / "ca" / "ca.pem")),
            cert=(str(root / "certs" / "anna.pem"), str(root / "certs" / "anna.key"))))
        answer = own.post(f"https://localhost:{port}/intern/connection", json={"connection": "x" * 32})
        assert answer.status_code == 409 and answer.json() == {"error": "unknown_connection"}
        for name, value in SECURITY.items():
            assert answer.headers[name] == value
        assert own.get(f"https://localhost:{port}/health").status_code == 404  # health is public only
        own.close()
        for cert in (None, (str(root / "foreign" / "anna.pem"), str(root / "foreign" / "anna.key"))):
            stranger = httpx.Client(transport=httpx.HTTPTransport(
                verify=ssl.create_default_context(cafile=str(root / "ca" / "ca.pem")), cert=cert))
            with pytest.raises(httpx.HTTPError):
                stranger.post(f"https://localhost:{port}/intern/token", json={})
            stranger.close()
        plain = httpx.Client(transport=httpx.HTTPTransport())
        public_port = outer.server_address[1]
        assert plain.get(f"http://127.0.0.1:{public_port}/health").json() == {"status": "ok"}
        assert plain.post(f"http://127.0.0.1:{public_port}/intern/token").status_code == 404
        assert plain.get(f"http://127.0.0.1:{public_port}/auth/google/callback?state=x&code=geheim").status_code == 400
        plain.close()
    finally:
        inner.shutdown()
        outer.shutdown()
    assert "geheim" not in json.dumps(events)


def test_certificates_carry_their_role_and_fingerprint(pki):
    root, anna = pki
    assert fingerprint((root / "certs" / "anna.pem").read_bytes()) == anna
    with pytest.raises(FileExistsError):
        create_ca(root / "ca")  # never overwritten
    (root / "ec").mkdir()
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    (root / "ec" / "ca.key").write_bytes(rsa_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    (root / "ec" / "ca.pem").write_bytes((root / "ca" / "ca.pem").read_bytes())
    with pytest.raises(ValueError, match="CA-Schlüssel"):
        issue(root / "ec", root / "x", "y", server=False, now=datetime(2026, 11, 19, tzinfo=UTC))


def test_operator_commands_build_a_working_service(tmp_path, pki, monkeypatch, capsys):
    root, anna = pki
    env = {"INBOXSTRIDE_AUTH_STATE": str(tmp_path / "state"), "INBOXSTRIDE_AUTH_KEY": str(tmp_path / "k.key"),
           "INBOXSTRIDE_AUTH_LOG": str(tmp_path / "auth.jsonl"), "INBOXSTRIDE_AUTH_PUBLIC": "127.0.0.1:0",
           "INBOXSTRIDE_AUTH_INTERNAL": "127.0.0.1:0", "INBOXSTRIDE_AUTH_TLS_CERT": str(root / "certs" / "localhost.pem"),
           "INBOXSTRIDE_AUTH_TLS_KEY": str(root / "certs" / "localhost.key"),
           "INBOXSTRIDE_AUTH_TLS_CA": str(root / "ca" / "ca.pem")}
    assert cli.main(["create-key"], env) == 0
    with pytest.raises(SystemExit, match="Google-Client fehlt"):
        cli.main(["sweep"], env)
    client = tmp_path / "client.json"
    client.write_text(json.dumps({"web": {"client_id": "id", "client_secret": "synthetic-client-secret"}}), "utf-8")
    assert cli.main(["set-client", str(client)], env) == 0 and "Clientrevision 2" in capsys.readouterr().out
    client.write_text(json.dumps({"installed": {}}), "utf-8")
    with pytest.raises(SystemExit, match="Webanwendungsclient"):
        cli.main(["set-client", str(client)], env)
    assert cli.main(["register", "anna", "anna.inboxstride.example", str(root / "certs" / "anna.pem")], env) == 0
    assert StateFile(tmp_path / "state").read().instances["anna"].certificate == anna
    assert cli.main(["disable", "anna"], env) == 0
    assert not StateFile(tmp_path / "state").read().instances["anna"].enabled
    assert cli.main(["sweep"], env) == 0 and capsys.readouterr().out.strip() == "0"
    assert cli.main(["ca-init", str(tmp_path / "ca2")], env) == 0
    assert cli.main(["issue", str(tmp_path / "ca2"), str(tmp_path / "c2"), "bert"], env) == 0
    assert len(capsys.readouterr().out.strip().splitlines()[-1]) == 64
    assert cli.main(["serve"], env, wait=lambda: None) == 0
    events = [json.loads(line)["event"] for line in (tmp_path / "auth.jsonl").read_text("utf-8").splitlines()]
    assert events == ["service_started", "service_stopped"]
    with pytest.raises(SystemExit, match="INBOXSTRIDE_AUTH_STATE fehlt"):
        cli.main(["sweep"], {})
    monkeypatch.setattr("sys.argv", ["inboxstride_auth", "create-key"])
    monkeypatch.setenv("INBOXSTRIDE_AUTH_KEY", str(tmp_path / "second.key"))
    with pytest.raises(SystemExit) as finished:
        runpy.run_module("inboxstride_auth", run_name="__main__")
    assert finished.value.code == 0 and (tmp_path / "second.key").exists()
