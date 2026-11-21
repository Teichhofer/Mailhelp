"""XOAUTH2 payloads stay in memory and are only sent to the bound TLS provider."""
import imaplib

import pytest

from mailhelp.config import ImapCredentials, MailboxSettings
from mailhelp.external.contracts import OAuthTokenError
from mailhelp.mailbox.imap import ImapLoginRejected, ImapReader, reader_arguments


class Tokens:
    def __init__(self, token="synthetic-access"):
        self.token, self.calls, self.closed = token, 0, 0

    def access_token(self):
        self.calls += 1
        return self.token

    def invalidate(self):
        self.token = ""

    def close(self):
        self.closed += 1


class Connection:
    def __init__(self, *_args, **_kwargs):
        self.debug, self.payload = 5, None

    def login(self, *_args):
        raise AssertionError("OAuth must not fall back to a password")

    def authenticate(self, mechanism, callback):
        assert mechanism == "XOAUTH2" and self.debug == 0
        self.payload = callback(b"")
        assert callback(b'{"status":"401"}') == b""
        return "OK", []

    def logout(self):
        return "OK", []


def test_authentication_reconnect_and_final_cleanup():
    tokens = Tokens()
    reader = ImapReader("imap.gmail.com", 993, "user@example.test", "", factory=Connection, token_provider=tokens)
    assert reader.connection.payload == b"user=user@example.test\x01auth=Bearer synthetic-access\x01\x01"
    reader._reconnect()
    assert tokens.calls == 2 and tokens.closed == 0
    reader.close()
    assert tokens.closed == 1


@pytest.mark.parametrize("token", ["", "bad\x01token", "bad\rtoken"])
def test_invalid_token_never_reaches_imap(token):
    tokens = Tokens(token)
    with pytest.raises(ImapLoginRejected):
        ImapReader("imap.gmail.com", 993, "user@example.test", "", factory=Connection, token_provider=tokens)
    assert tokens.closed == 1


@pytest.mark.parametrize("host,port,user", [("attacker.test", 993, "user"),
    ("imap.gmail.com", 143, "user"), ("imap.gmail.com", 993, "user\x01other")])
def test_unsafe_destination_or_user_is_refused_before_connect(host, port, user):
    tokens = Tokens()
    with pytest.raises(ValueError):
        ImapReader(host, port, user, "", factory=Connection, token_provider=tokens)
    assert tokens.calls == 0 and tokens.closed == 1


def test_refused_server_answer_is_redacted():
    class Refused(Connection):
        def authenticate(self, *_args):
            raise imaplib.IMAP4.error("must-not-expose-synthetic-access")
    with pytest.raises(ImapLoginRejected) as error:
        ImapReader("outlook.office365.com", 993, "user@example.test", "", factory=Refused, token_provider=Tokens())
    assert "must-not-expose" not in str(error.value) and error.value.__cause__ is None


def test_oauth_reader_arguments_require_the_configured_service():
    mailbox = MailboxSettings(id=1, host="imap.gmail.com", port=993, folders=["INBOX"],
                              auth_method="gmail", oauth_connection="a" * 32)
    with pytest.raises(ValueError):
        reader_arguments(mailbox, ImapCredentials(username="user", password=""))


def test_refused_refresh_becomes_an_imap_warning_without_token_details():
    class Refused(Tokens):
        def access_token(self):
            raise OAuthTokenError("secret-must-not-appear")
    with pytest.raises(ImapLoginRejected) as error:
        ImapReader("imap.gmail.com", 993, "user", "", factory=Connection, token_provider=Refused())
    assert "erneut verbinden" in str(error.value) and "secret-must-not" not in str(error.value)


def test_connection_failure_closes_the_owned_token_client():
    def failed(*_args, **_options):
        raise OSError("synthetic connection failure")
    tokens = Tokens()
    with pytest.raises(OSError):
        ImapReader("imap.gmail.com", 993, "user", "", factory=failed, token_provider=tokens)
    assert tokens.closed == 1


def test_logout_failure_never_logs_an_untrusted_server_response():
    from types import SimpleNamespace
    events = []
    class BrokenLogout(Connection):
        def logout(self):
            raise imaplib.IMAP4.abort("synthetic-access-must-not-be-logged")
    logger = SimpleNamespace(event=lambda *args, **fields: events.append((args, fields)))
    reader = ImapReader("imap.gmail.com", 993, "user", "", factory=BrokenLogout,
                        token_provider=Tokens(), logger=logger)
    reader.close()
    assert "synthetic-access-must-not-be-logged" not in repr(events)
    assert events[0][1]["error_class"] == "abort"


def test_hosted_reader_uses_a_mail_purpose_and_does_not_require_a_password(monkeypatch):
    from types import SimpleNamespace

    from mailhelp.config import ImapSettings, imap_secret_values
    from mailhelp.mailbox import imap as module
    from tests.fakes.hosted_google import settings
    calls = []
    client = SimpleNamespace(post=lambda path, data: calls.append((path, data)) or {
        "access_token": "synthetic", "expires_in": 3600}, close=lambda: calls.append("closed"))
    monkeypatch.setattr(module, "HostedAuthClient", lambda cfg: client)
    box = MailboxSettings(id=1, host="imap.gmail.com", port=993, folders=["INBOX"],
                         auth_method="gmail", oauth_connection="a" * 32)
    credentials, missing = imap_secret_values(ImapSettings(mailboxes=[box]), {"IMAP_1_USERNAME": "user"})
    assert not missing and credentials[1] == {"username": "user", "password": ""}
    _address, options = reader_arguments(box, ImapCredentials.model_validate(credentials[1]), settings())
    assert options["token_provider"].access_token() == "synthetic"
    assert calls[0][1] == {"connection": "a" * 32, "purpose": "gmail"}
    options["token_provider"].close()
    assert calls[-1] == "closed"
    with pytest.raises(ValueError):
        reader_arguments(box, ImapCredentials.model_validate(credentials[1]), settings().model_copy(
            update={"enabled": False}))


@pytest.mark.parametrize("changes", [{"host": "attacker.test"}, {"port": 143},
                                   {"connection_mode": "plain"}, {"oauth_connection": ""}])
def test_configuration_refuses_an_unsafe_oauth_destination(changes):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        MailboxSettings(id=1, folders=["INBOX"], **{
            "host": "imap.gmail.com", "port": 993, "auth_method": "gmail", "oauth_connection": "a" * 32, **changes})
