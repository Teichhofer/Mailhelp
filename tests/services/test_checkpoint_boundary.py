"""IMAP's reversed UID ranges must not reopen a durable start boundary."""
import pytest
from shared_application import Imap, Orch, Telegram, _persisted_run, app
from shared_core import FakeImap

from mailhelp.imap import ImapReader
from mailhelp.mailbox_run import _checkpoint_name
from mailhelp.models import ImapCheckpoint, MailRunEntry, MailRunState, MailState
from mailhelp.orchestrator import ProcessingOutcome, ProcessingResult
from mailhelp.storage import JsonStore


class ReversedRangeImap(FakeImap):
    """An IMAP server may return its highest UID for SEARCH UID highest+1:*."""

    def __init__(self):
        super().__init__()
        self.uids = [5]
        self.fetches = []

    def uid(self, action, *args):
        if action == "search":
            return "OK", [b" ".join(str(uid).encode() for uid in self.uids)]
        self.fetches.append(args)
        tokens = args[0].split(b",")
        metadata = [b'1 (UID ' + token + b' INTERNALDATE "14-Oct-2026 10:00:00 +0000")'
                    for token in tokens]
        if args[1] == "(UID INTERNALDATE)":
            return "OK", metadata
        return "OK", [(metadata[0], b"Subject: Synthetic\r\n\r\nTest")]


class DurableReader(Imap):
    def discover_since(self, *_args):
        self.last_uidvalidity = 7
        return []


@pytest.mark.parametrize("method", ["discover_since", "fetch_since"])
@pytest.mark.parametrize("returned", [[5], [4, 5]])
def test_search_excludes_boundary_before_any_metadata_or_body_fetch(method, returned):
    server = ReversedRangeImap()
    server.uids = returned
    reader = ImapReader("synthetic", 993, "user", "password", factory=lambda *a, **k: server)
    poll = getattr(reader, method)
    for _ in range(2):
        assert poll("INBOX", 5, 7) == []
    assert server.fetches == []
    server.uids = [4, 5, 6]
    assert [mail.uid for mail in poll("INBOX", 5, 7)] == [6]
    assert len(server.fetches) == 1 and server.fetches[0][0] == b"6"
    server.uids = []
    assert poll("INBOX", 6, 7) == []
    reader.close()


def test_empty_highest_uid_poll_then_new_mail_and_restart(tmp_path):
    server = ReversedRangeImap()
    reader = ImapReader("synthetic", 993, "user", "password", factory=lambda *a, **k: server)
    name = _checkpoint_name(reader.account_id, "INBOX")
    store = JsonStore(tmp_path / "state")
    store.save(name, ImapCheckpoint(uidvalidity=7, uid=5, start_uid=5).model_dump())
    application = app(tmp_path, reader, Telegram([]), Orch(), store=store, global_newest_first=True)
    assert application.mailbox.poll(max_mails=1) == []
    assert application.orchestrator.seen == [] and server.fetches == []
    server.uids = [5, 6]
    assert len(application.mailbox.poll(max_mails=1)) == 1
    assert application.orchestrator.seen == [6]
    assert store.load_model(name, ImapCheckpoint).completed_uid_ranges == [(6, 6)]
    server.uids = [6]
    restarted = app(tmp_path, reader, Telegram([]), Orch(), store=JsonStore(tmp_path / "state"),
                    global_newest_first=True)
    assert restarted.mailbox.poll(max_mails=1) == []
    assert restarted.orchestrator.seen == []
    assert len(server.fetches) == 2  # one metadata request and one BODY.PEEK for UID 6
    reader.close()


@pytest.mark.parametrize("uid", [4, 5])
@pytest.mark.parametrize("resumed", [False, True])
def test_old_durable_queue_completion_preserves_boundary_after_restart(tmp_path, uid, resumed):
    account = "0" * 24
    name = _checkpoint_name(account, "INBOX")
    run_name = f"mail-run-{account}"
    store = JsonStore(tmp_path / "state")
    original = ImapCheckpoint(uidvalidity=7, uid=8, start_uid=5,
                              completed_uid_ranges=[(8, 8)])
    store.save(name, original.model_dump())
    entry = MailRunEntry(account_id=account, folder="INBOX", uidvalidity=7, uid=uid,
                         status="processing" if resumed else "queued")
    store.save(run_name, _persisted_run([entry]).model_dump(mode="json"))
    application = app(tmp_path, DurableReader([]), Telegram([]), Orch(), store=store,
                      global_newest_first=True)
    if resumed:
        state = MailState(id="a" * 24, config_fingerprint="0" * 64,
                          imap={"account_id": account, "folder": "INBOX", "uidvalidity": 7, "uid": uid})
        application.mailbox.complete_resumed_entry(state, ProcessingResult(ProcessingOutcome.COMPLETED, {}))
    else:
        assert len(application.mailbox.poll(max_mails=1)) == 1
        assert application.orchestrator.seen == [uid]
    restarted_store = JsonStore(tmp_path / "state")
    assert restarted_store.load_model(name, ImapCheckpoint) == original
    assert restarted_store.load_model(run_name, MailRunState).entries[0].analysis_terminal == "completed"
    restarted = app(tmp_path, DurableReader([]), Telegram([]), Orch(), store=restarted_store,
                    global_newest_first=True)
    assert restarted.mailbox.poll(max_mails=1) == []
    assert restarted.orchestrator.seen == []
    assert restarted_store.load_model(name, ImapCheckpoint) == original
