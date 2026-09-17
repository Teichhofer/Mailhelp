from datetime import datetime, timedelta, timezone

import pytest

from mailhelp.imap import ImapReader
from mailhelp.mime import prepare
from mailhelp.models import MailState, Proposal, ProposalStatus
from mailhelp.orchestrator import Orchestrator
from mailhelp.config import TargetSettings


class Connection:
    def __init__(self, response):
        self.response_value = response
        self.commands = []

    def login(self, *_args): pass
    def logout(self): pass
    def select(self, *_args, **_kwargs): return "OK", []
    def response(self, _key): return "UIDVALIDITY", [b"8"]
    def uid(self, command, *args):
        self.commands.append((command, args))
        if command == "search": return "OK", [b"12"]
        return self.response_value


@pytest.mark.parametrize("targeted", [False, True])
def test_combined_peek_fetch_transports_internaldate(targeted):
    connection = Connection(("OK", [None, (b'12 (INTERNALDATE "27-Oct-2024 02:30:00 +0200" BODY[] {3})', b"raw"), b")"]))
    reader = ImapReader("host", 993, "user", "password", factory=lambda *_a, **_k: connection)
    mail = reader.fetch_uid("INBOX", 12, 8) if targeted else reader.fetch_since("INBOX", 0, 8)[0]
    assert mail.raw == b"raw"
    assert mail.received_at.isoformat() == "2024-10-27T02:30:00+02:00"
    assert any(args[-1] == "(BODY.PEEK[] INTERNALDATE)" for command, args in connection.commands if command == "fetch")


@pytest.mark.parametrize("response", [
    ("OK", None), ("OK", [b"not a tuple"]), ("OK", [("text", b"raw")]),
    ("OK", [(b"metadata", b"raw")]),
    ("OK", [(b'1 (INTERNALDATE "not-a-date")', b"raw")]),
])
def test_malformed_combined_fetch_is_rejected(response):
    reader = ImapReader("host", 993, "user", "password", factory=lambda *_a, **_k: Connection(response))
    with pytest.raises(RuntimeError, match="IMAP"):
        reader.fetch_uid("INBOX", 12, 8)


def test_mail_date_context_valid_invalid_naive_conflicting_and_dst():
    received = datetime(2024, 10, 27, 2, 45, tzinfo=timezone(timedelta(hours=1)))
    valid = prepare(b"Date: Sun, 27 Oct 2024 02:30:00 +0100\r\n\r\nx", 10000, received, "Europe/Berlin")
    assert valid["date_context_status"] == "valid"
    assert valid["date_header_original"].endswith("+0100")
    assert valid["date_header_parsed"] == "2024-10-27T02:30:00+01:00"
    assert valid["imap_received_at"] == received.isoformat()
    assert valid["user_timezone"] == "Europe/Berlin"
    for header, status in ((b"", "missing"), (b"Date: nonsense\r\n", "invalid"),
                           (b"Date: Sun, 27 Oct 2024 02:30:00\r\n", "naive"),
                           (b"Date: Mon, 01 Jan 2024 10:00:00 +0000\r\n", "conflicting")):
        assert prepare(header + b"\r\nx", 10000, received, "Europe/Berlin")["date_context_status"] == status
    with pytest.raises(ValueError, match="zeitzonenbehaftet"):
        prepare(b"\r\nx", 10000, received.replace(tzinfo=None))


def test_unsafe_context_forces_event_clarification():
    class Dummy: pass
    orchestrator = Orchestrator(Dummy(), Dummy(), Dummy(), 1, [], 1000,
                                targets=TargetSettings(todoist_project="p", google_calendar="c"))
    state = MailState(id="a" * 24, config_fingerprint="0" * 64,
                      imap={"account_id":"0" * 24, "folder":"INBOX", "uidvalidity":1, "uid":1},
                      mail={"date_context_status":"conflicting"})
    start = datetime(2026, 1, 1, 10, tzinfo=timezone.utc)
    event = Proposal(id="e", version=1, kind="event", responsibility="user", certainty="certain", classification="new", title="x", evidence="x",
                     source_mail_id=state.id, target="untrusted", start=start, end=start + timedelta(hours=1))
    normalized = orchestrator._normalize_proposals(state, [event])[0]
    assert normalized.status == ProposalStatus.NEEDS_CLARIFICATION
    assert normalized.open_questions
    # Repeating normalization remains idempotent with respect to the fixed question.
    assert len(orchestrator._normalize_proposals(state, [normalized])[0].open_questions) == 1
