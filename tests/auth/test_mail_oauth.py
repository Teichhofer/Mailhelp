"""Mailbox authorizations cannot replace or supply calendar authorizations."""
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from pydantic import ValidationError

from inboxstride_auth.google import Client, GoogleTokens
from inboxstride_auth.http_api import public
from inboxstride_auth.microsoft import CALLBACK, MicrosoftTokens
from inboxstride_auth.models import MAIL_SCOPES, AuthJob, Connection
from inboxstride_auth.service import Refused
from tests.fakes.auth_service import ANNA, BERT, T0, service  # noqa: F401


@pytest.mark.parametrize("purpose", ["gmail", "microsoft"])
def test_separate_mail_grant_end_to_end_refresh_and_cross_purpose_refusal(service, purpose):
    requests = []

    def endpoint(request):
        requests.append(request)
        return httpx.Response(200, json={"access_token": "synthetic-mail-token", "token_type": "Bearer",
            "expires_in": 3600, "scope": " ".join(MAIL_SCOPES[purpose]), "refresh_token": "rotated-mail-refresh"})

    client = Client("synthetic-mail-client", "synthetic-mail-secret", CALLBACK) if purpose == "microsoft" else Client(
        "synthetic-google", "synthetic-secret")
    kind = MicrosoftTokens if purpose == "microsoft" else GoogleTokens
    tokens = kind(client, transport=httpx.MockTransport(endpoint))
    service.mail_providers[purpose] = tokens
    try:
        job, url = service.start("anna", ANNA, "mailbox:1", "connect", "mail-1", purpose)
        params = parse_qs(urlsplit(url).query)
        assert set(params["scope"][0].split()) == set(MAIL_SCOPES[purpose]) | (
            {"offline_access"} if purpose == "microsoft" else set())
        assert params["code_challenge_method"] == ["S256"]
        with pytest.raises(Refused, match="wrong_provider"):
            service.callback(params["state"][0], "good", None,
                             "google" if purpose == "microsoft" else "microsoft")
        route = "/auth/microsoft/callback" if purpose == "microsoft" else "/auth/google/callback"
        returned = public(service, "GET", route + "?state=" + params["state"][0] + "&code=good", lambda *_: None)
        assert returned.status == 303
        back = urlsplit(returned.headers["Location"])
        assert back.hostname == "anna.inboxstride.example" and back.path == "/einrichtung/postfach/abschluss"
        receipt = parse_qs(back.query)["beleg"][0]
        with pytest.raises(Refused):
            service.redeem("bert", BERT, receipt)
        ready = service.redeem("anna", ANNA, receipt)
        connection = service.activate("anna", ANNA, ready.id, ready.version)
        assert connection.purpose == purpose and connection.target == "mailbox:1"
        with pytest.raises(Refused, match="wrong_purpose"):
            service.access_token("anna", connection.id)
        assert service.access_token("anna", connection.id, purpose)[0] == "synthetic-mail-token"
        service.clock_.tick += 4000
        assert service.access_token("anna", connection.id, purpose)[0] == "synthetic-mail-token"
        assert len(requests) == 2
        assert service.store.get(connection.secret) == "rotated-mail-refresh"
        with pytest.raises(Refused, match="key_reused"):
            service.start("anna", ANNA, "profile:1", "connect", "mail-1")
    finally:
        tokens.close()


def test_unconfigured_mail_provider_fails_before_creating_a_job(service):
    before = service.state.read()
    with pytest.raises(Refused, match="provider_not_configured"):
        service.start("anna", ANNA, "mailbox:1", "connect", "mail", "gmail")
    assert service.state.read() == before


def test_microsoft_configuration_rejects_other_authorities_and_callbacks():
    with pytest.raises(ValueError):
        MicrosoftTokens(Client("id", "secret", CALLBACK), "../attacker")
    with pytest.raises(ValueError):
        MicrosoftTokens(Client("id", "secret", "https://other.test/callback"))


def test_purpose_is_bound_to_target_and_required_permissions():
    with pytest.raises(ValidationError):
        AuthJob(id="a" * 32, instance="anna", session="b" * 64, target="profile:1", purpose="gmail",
                operation="connect", client_revision=1, created=T0, expires=T0)
    with pytest.raises(ValidationError):
        Connection(id="a" * 32, instance="anna", target="profile:1", purpose="gmail", status="candidate",
                   generation=1, scopes=MAIL_SCOPES["gmail"], secret="refresh:" + "a" * 32,
                   client_revision=1, created=T0)


def test_operator_import_and_separate_provider_enablement(tmp_path, capsys):
    import json

    from inboxstride_auth import __main__ as cli
    env = {"INBOXSTRIDE_AUTH_STATE": str(tmp_path / "state"), "INBOXSTRIDE_AUTH_KEY": str(tmp_path / "key")}
    assert cli.main(["create-key"], env) == 0
    private = tmp_path / "client.json"
    for invalid in ([], {}, {"client_id": 3, "client_secret": "synthetic"}):
        private.write_text(json.dumps(invalid), encoding="utf-8")
        with pytest.raises(ValueError, match="Missing Microsoft"):
            cli.set_mail_client(env, private)
    private.write_text(json.dumps({"client_id": "synthetic-microsoft", "client_secret": "synthetic-secret"}),
                       encoding="utf-8")
    assert cli.main(["set-mail-client", str(private)], env) == 0
    assert "synthetic-secret" not in capsys.readouterr().out
    only_microsoft = cli.build(env)
    assert set(only_microsoft.mail_providers) == {"microsoft"}
    with pytest.raises(Refused, match="provider_not_configured"):
        only_microsoft._provider("calendar")
    with pytest.raises(SystemExit, match="Google-Client fehlt"):
        cli.build({**env, "INBOXSTRIDE_AUTH_GMAIL_ENABLED": "1"})
    private.write_text(json.dumps({"web": {"client_id": "synthetic-google", "client_secret": "synthetic-secret"}}),
                       encoding="utf-8")
    cli.set_client(env, private)
    both = cli.build({**env, "INBOXSTRIDE_AUTH_GMAIL_ENABLED": "1"})
    assert set(both.mail_providers) == {"gmail", "microsoft"}
    assert both.state.read().client_revision == 3
    for instance in (only_microsoft, both):
        for provider in {instance.google, *instance.mail_providers.values()}:
            provider.close()


@pytest.mark.parametrize("origin,valid", [
    ("https://auth.own.example", True), ("http://localhost:8780", True),
    ("http://external.example", False), ("https://auth.example/path", False),
    ("https://user:password@auth.example", False), ("https://auth.example?secret=x", False),
    ("https://auth.example#fragment", False), ("invalid", False),
])
def test_operator_callback_origin_validation(origin, valid):
    from inboxstride_auth.__main__ import public_origin
    if valid:
        assert public_origin({"INBOXSTRIDE_AUTH_PUBLIC_URL": origin}) == origin
    else:
        with pytest.raises(ValueError):
            public_origin({"INBOXSTRIDE_AUTH_PUBLIC_URL": origin})


def test_calendar_state_migrates_without_inventing_mail_permissions(service):
    import json

    from tests.fakes.auth_service import sign_in
    sign_in(service)
    old = service.state.read().model_dump(mode="json")
    old["schema_version"] = 1
    for item in [*old["jobs"].values(), *old["connections"].values()]:
        del item["purpose"]
    service.state.path.write_text(json.dumps(old), encoding="utf-8")
    migrated = service.state.read()
    assert migrated.schema_version == 2
    assert {item.purpose for item in migrated.connections.values()} == {"calendar"}
    assert json.loads(service.state.path.read_text())["schema_version"] == 1
    service.state.update(lambda state: state)
    assert json.loads(service.state.path.read_text())["schema_version"] == 2


def test_refresh_cannot_silently_lose_required_scopes(service):
    from tests.fakes.auth_service import sign_in
    sign_in(service)
    connection, = service.state.read().connections.values()
    service._tokens.clear()
    service.store.put(connection.secret, "narrow-refresh")
    with pytest.raises(Refused, match="missing_scopes"):
        service.access_token("anna", connection.id)
    assert service.state.read().connections[connection.id].status == "reconnect_required"
