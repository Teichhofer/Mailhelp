"""6.1.3: the mailbox check against a real local IMAP server – each failure gets its own message."""
import pytest

from mailhelp.config import Settings
from mailhelp.runtime import setup_checks as module
from mailhelp.runtime.setup_checks import SetupChecks
from mailhelp.runtime.setup_messages import SetupProblem
from tests.fakes.imap_server import Behaviour, SyntheticImapServer, closed_port
from tests.fakes.initial_harness import initial  # noqa: F401  (fixture)


def settings(initial, **imap):
    initial.advance()
    raw = initial.setup.state().config
    raw["imap"].update({"host": "127.0.0.1", "connection_mode": "plain", **imap})
    raw["imap"]["folders"] = [raw["imap"]["primary_folder"]]
    return Settings.model_validate(raw)


def run(initial, password="richtig", **imap):
    env = {"IMAP_USERNAME": "user@example.test", "IMAP_PASSWORD": password}
    return SetupChecks(initial.directory).imap(settings(initial, **imap), env)


def code(initial, **arguments):
    with pytest.raises(SetupProblem) as raised:
        run(initial, **arguments)
    return raised.value


def test_a_reachable_mailbox_lists_its_folders_and_closes_the_connection(initial):
    with SyntheticImapServer() as server:
        result = run(initial, port=server.port, drafts_folder="Entwürfe")
    assert result["folders"] == ["INBOX", "Entwürfe"] and result["drafts"] == "Entwürfe"
    assert not result["drafts_missing"] and server.behaviour.commands[-1] == "LOGOUT"


def test_a_wrong_password_is_reported_as_a_rejected_login(initial):
    with SyntheticImapServer() as server:
        problem = code(initial, password="falsch", port=server.port)
    assert problem.code == "imap.auth_failed" and "falsch" not in str(problem)


def test_a_missing_inbox_names_the_folders_found(initial):
    with SyntheticImapServer() as server:
        problem = code(initial, port=server.port, primary_folder="Archiv")
    assert problem.code == "imap.folder_missing" and problem.detail == "INBOX, Entwürfe"


@pytest.mark.parametrize(("behaviour", "mode", "expected"), [
    (Behaviour(), "ssl", "imap.tls_mismatch"),               # TLS handshake against a plain server
    (Behaviour(starttls="refuse"), "starttls", "imap.tls_mismatch"),
    (Behaviour(starttls="absent"), "starttls", "imap.tls_mismatch"),
])
def test_encryption_that_does_not_match_the_server(initial, behaviour, mode, expected):
    with SyntheticImapServer(behaviour) as server:
        assert code(initial, port=server.port, connection_mode=mode).code == expected


def test_a_closed_port_a_silent_server_and_an_unknown_host(initial, monkeypatch):
    assert code(initial, port=closed_port()).code == "imap.unreachable"
    monkeypatch.setattr(module, "TIMEOUT", 1)
    with SyntheticImapServer(Behaviour(silent=True)) as server:
        assert code(initial, port=server.port).code == "imap.unreachable"
    assert code(initial, host="unbekannt.invalid").code == "imap.host_unknown"
