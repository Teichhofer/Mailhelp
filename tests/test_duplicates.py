from email.message import EmailMessage

from mailhelp.config import Topic
from mailhelp.imap import FetchedMail
from mailhelp.models import DuplicateIndex, MailState, ProposalStatus
from mailhelp.orchestrator import Orchestrator, ProcessingOutcome
from mailhelp.storage import JsonStore


class CountingAnalyzer:
    def __init__(self):
        self.calls = 0

    def relevance(self, mail, topics):
        from mailhelp.models import Relevance
        self.calls += 1
        return "r", Relevance(decision="irrelevant", topic_ids=[], reason="test")


class Notify:
    def send(self, chat_id, text): pass
    def send_proposal(self, proposal): pass
    def send_relevance(self, dialog): pass


class Log:
    def __init__(self): self.events = []
    def event(self, *args, **kwargs): self.events.append((args, kwargs))


TOPICS = [Topic(id="x", name="X", enabled=True, description="X")]


def raw(message_id="<same@example.test>", body="Body", subject="Subject"):
    if isinstance(message_id, list):
        headers = "".join(f"Message-ID: {value}\n" for value in message_id)
        return (f"From: Alice <alice@example.test>\nSubject: {subject}\n"
                f"Date: Thu, 17 Sep 2026 10:00:00 +0000\n{headers}\n{body}\n").encode()
    message = EmailMessage()
    message["From"] = "Alice <alice@example.test>"
    message["Subject"] = subject
    message["Date"] = "Thu, 17 Sep 2026 10:00:00 +0000"
    if message_id is not None:
        message["Message-ID"] = message_id
    message.set_content(body)
    return message.as_bytes()


def process(store, analyzer, uid, payload, folder="INBOX", validity=1, logger=None):
    return Orchestrator(analyzer, store, Notify(), 1, TOPICS, 10000, logger=logger).process(
        FetchedMail(folder, validity, uid, payload)
    )


def test_same_message_across_folder_uidvalidity_and_restart_is_skipped(tmp_path):
    data = tmp_path / "data"
    first_analyzer = CountingAnalyzer()
    with JsonStore(data) as store:
        first = process(store, first_analyzer, 1, raw())
        assert first_analyzer.calls == 1
    second_analyzer, log = CountingAnalyzer(), Log()
    with JsonStore(data) as restarted:
        second = process(restarted, second_analyzer, 77, raw(), "Archive", 9, log)
        assert second.outcome is ProcessingOutcome.COMPLETED
        assert second["duplicate"] == {"outcome": "duplicate", "reason": "same_message",
                                       "previous_mail_id": first["id"]}
        assert second_analyzer.calls == 0
        assert second["steps"]["relevance"] == "skipped"
        index = restarted.load_model("duplicate-index", DuplicateIndex)
        assert len(index.entries) == 2
    assert any(event[0][2] == "duplicate_skipped" for event in log.events)
    assert "Body" not in str(log.events) and "Alice" not in str(log.events)


def test_durable_index_skips_same_identity_after_mail_state_is_removed(tmp_path):
    """Content cleanup must not make a stable processed identity new again."""
    with JsonStore(tmp_path) as store:
        first = process(store, CountingAnalyzer(), 1, raw())
        (tmp_path / f"mail-{first['id']}.json").unlink()
        analyzer = CountingAnalyzer()

        repeated = process(store, analyzer, 1, raw())

        assert repeated["duplicate"] == {
            "outcome": "duplicate", "reason": "same_message",
            "previous_mail_id": first["id"],
        }
        assert analyzer.calls == 0

        (tmp_path / f"mail-{first['id']}.json").unlink()
        changed = process(store, analyzer, 1, raw(body="Changed"))
        assert changed["duplicate"]["outcome"] == "ambiguous"
        assert changed["duplicate"]["reason"] == "message_id_reused"
        assert analyzer.calls == 1

        (tmp_path / f"mail-{first['id']}.json").unlink()
        changed_id = process(store, analyzer, 1, raw("<changed@example.test>"))
        assert changed_id["duplicate"]["outcome"] == "ambiguous"
        assert changed_id["duplicate"]["reason"] == "fingerprint_collision"
        assert analyzer.calls == 2


def test_reused_or_multiple_message_id_and_fingerprint_collision_are_not_skipped(tmp_path):
    with JsonStore(tmp_path) as store:
        analyzer = CountingAnalyzer()
        first = process(store, analyzer, 1, raw())
        reused = process(store, analyzer, 2, raw(body="Different"))
        assert reused["duplicate"]["reason"] == "message_id_reused"
        missing = process(store, analyzer, 3, raw(None))
        missing_copy = process(store, analyzer, 4, raw(None), "Archive")
        assert missing["duplicate"]["outcome"] == "ambiguous"
        assert missing["duplicate"]["reason"] == "missing_message_id"
        assert missing_copy["duplicate"]["reason"] == "missing_message_id"
        collision = process(store, analyzer, 5, raw("<other@example.test>"))
        assert collision["duplicate"]["reason"] == "fingerprint_collision"
        multiple = process(store, analyzer, 6, raw(["<one@example.test>", "<two@example.test>"]))
        multiple_copy = process(store, analyzer, 7, raw(["<one@example.test>", "<two@example.test>"]), "Sent")
        assert multiple["duplicate"]["outcome"] == "ambiguous"
        assert multiple["duplicate"]["reason"] == "multiple_message_ids"
        assert multiple_copy["duplicate"]["reason"] == "multiple_message_ids"
        assert analyzer.calls == 7
        assert all(item["steps"]["completion"] == "completed"
                   for item in (first, reused, missing, missing_copy, collision, multiple, multiple_copy))


def test_incomplete_candidate_and_identifier_normalization_are_conservative(tmp_path):
    with JsonStore(tmp_path) as store:
        waiting_analyzer = CountingAnalyzer()
        first = process(store, waiting_analyzer, 1, raw("<Case@Example.Test>"))
        state = store.load_model("mail-" + first["id"], MailState)
        state.steps.completion = "pending"
        store.save("mail-" + first["id"], state.model_dump(mode="json"))
        second = process(store, CountingAnalyzer(), 2, raw(" <CASE@example.test> "), "Archive")
        assert second["duplicate"]["reason"] == "candidate_incomplete"

        prepared = {"headers": {"from": "", "subject": "", "date": "", "message_id": ""},
                    "text": "", "message_ids": ["bad", "<x@example.test>", "<X@EXAMPLE.TEST>", "<" + "x" * 999 + ">@x>"]}
        identifiers, fingerprint, count = Orchestrator._duplicate_identity(prepared)
        assert identifiers == ["<x@example.test>"] and len(fingerprint) == 64 and count == 4


def test_duplicate_of_mail_with_external_action_keeps_original_action(tmp_path):
    with JsonStore(tmp_path) as store:
        first = process(store, CountingAnalyzer(), 1, raw())
        original = store.load_model("mail-" + first["id"], MailState)
        # A terminal external result is intentionally retained on the earlier state.
        from test_core import proposal
        original.proposals = [proposal(id="p1", source_mail_id=original.id,
                                       status=ProposalStatus.CREATED, external_id="external-1")]
        store.save("mail-" + first["id"], original.model_dump(mode="json"))
        duplicate = process(store, CountingAnalyzer(), 2, raw(), "Archive")
        persisted = store.load_model("mail-" + first["id"], MailState)
        assert duplicate["duplicate"]["previous_mail_id"] == first["id"]
        assert duplicate["proposals"] == []
        assert persisted.proposals[0].external_id == "external-1"
