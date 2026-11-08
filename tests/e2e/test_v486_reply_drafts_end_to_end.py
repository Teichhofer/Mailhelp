"""4.8 acceptance: synthetic incoming mail, real pipeline and durable offline IMAP drafts."""
import hashlib
import imaplib
from contextlib import nullcontext
from email import message_from_bytes, policy

import pytest

from mailhelp import state_names
from mailhelp.config import Topic
from mailhelp.mailbox.imap import FetchedMail
from mailhelp.models import ActionRoute, MailState
from mailhelp.notifications.drafts import DraftService, ReplyDraft
from mailhelp.processing.orchestrator import Orchestrator
from mailhelp.storage import JsonStore
from tests.fakes.shared_services import AnalyzerStub, Notify

pytestmark = pytest.mark.e2e

RAW = ("From: Kundin <kundin@example.test>\r\nReply-To: antwort@example.test\r\n"
       "Subject: AW: Besuch\r\nMessage-ID: <source@example.test>\r\n"
       "References: <earlier@example.test>\r\nDate: Sun, 8 Nov 2026 10:00:00 +0100\r\n"
       "Content-Type: text/plain; charset=utf-8\r\n\r\n"
       "Bitte nennen Sie mir einen Termin für den Besuch.").encode()
FETCHED = FetchedMail("INBOX", 1, 81, RAW)
MAIL = hashlib.sha256(f"{FETCHED.account_id}:INBOX:1:81".encode()).hexdigest()[:24]
TEXT = "Vielen Dank für Ihre Anfrage. [Termin vorschlagen]\n\nFreundliche Grüße\nAlex Beispiel"


class Model(AnalyzerStub):
    def __init__(self):
        super().__init__("relevant")
        self.drafted = []

    def action_route(self, mail):
        return "router", ActionRoute(action_state="none", task_count=0, event_count=0, reason="Nur Antwort",
                                      reply_needed=True, reply_reason="Termin vorschlagen")

    def draft_reply(self, mail, intent, personal_info, reason=None):
        self.drafted.append((intent, personal_info, reason))
        return "draft-call", ReplyDraft(text=TEXT)


class OfflineImap:
    def __init__(self, outcome="OK"):
        self.outcome, self.messages, self.attempts = outcome, {}, 0

    def select(self, folder, readonly):
        assert readonly
        if self.outcome == "disconnect":
            raise imaplib.IMAP4.abort("synthetic disconnect before APPEND")
        return "OK", []

    def uid(self, *args):
        return "OK", [b"81" if args[-1] in self.messages else b""]

    def append(self, folder, flags, internaldate, content):
        assert folder == "Drafts" and flags == r"(\Draft \Seen)"
        self.attempts += 1
        if self.outcome == "quota":
            return "NO", [b"[OVERQUOTA] synthetic full mailbox"]
        if self.outcome == "lost_before":
            raise OSError("synthetic connection loss before acceptance")
        self.messages[str(message_from_bytes(content, policy=policy.default)["Message-ID"])] = content
        if self.outcome == "lost_after":
            raise imaplib.IMAP4.abort("synthetic connection loss after acceptance")
        return "OK", []


def compose(store, server, model):
    drafts = DraftService(store, lambda actor: actor == "reviewer", lambda: nullcontext(server),
                          "me@example.test", analyzer=model, personal_info=lambda: "Alex Beispiel")
    drafts.auto_policy = lambda account: True
    orchestrator = Orchestrator(model, store, Notify(), 1,
                                [Topic(id="schule", name="Beruf", description="Beruf", enabled=True)], 50_000)
    orchestrator.drafts = drafts
    return orchestrator, drafts


def test_reply_only_mail_becomes_one_threaded_draft_and_survives_restart(tmp_path, monkeypatch):
    import smtplib

    monkeypatch.setattr(smtplib, "SMTP", lambda *a, **k: pytest.fail("Mailhelp must never send mail"))
    server, model = OfflineImap(), Model()
    with JsonStore(tmp_path / "data") as store:
        app, drafts = compose(store, server, model)
        result = app.process(FETCHED)
        assert result.state["steps"]["completion"] == "completed" and result.state["proposals"] == []
        assert result.state["steps"]["auto_draft"] == "completed" and drafts.get(MAIL)["status"] == "saved"
        assert result.state["write_attempts"] == []  # no calendar or task write authorization
    with JsonStore(tmp_path / "data") as store:
        app, drafts = compose(store, server, model)
        app.process(FETCHED)
        assert drafts.auto_draft(MAIL, "Wiederholung") == "skipped"
    assert server.attempts == 1 and len(server.messages) == 1
    assert model.drafted == [("reply", "Alex Beispiel", "Termin vorschlagen")]
    message = message_from_bytes(next(iter(server.messages.values())), policy=policy.default)
    assert message["Subject"] == "Re: Besuch" and message["To"] == "antwort@example.test"
    assert message["From"] == "me@example.test" and message["In-Reply-To"] == "<source@example.test>"
    assert str(message["References"]) == "<earlier@example.test> <source@example.test>"
    assert message.get_content().replace("\r\n", "\n").strip() == TEXT


@pytest.mark.parametrize("outcome,status,step", [("quota", "editing", "completed"),
                                                 ("disconnect", "editing", "failed"),
                                                 ("lost_before", "uncertain", "completed"),
                                                 ("lost_after", "uncertain", "completed")])
def test_imap_failures_keep_text_and_never_abort_the_mail_or_blindly_repeat(tmp_path, outcome, status, step):
    server, model = OfflineImap(outcome), Model()
    with JsonStore(tmp_path / "data") as store:
        app, drafts = compose(store, server, model)
        result = app.process(FETCHED)
        assert result.state["steps"]["completion"] == "completed"
        assert result.state["steps"]["auto_draft"] == step
        assert drafts.get(MAIL)["status"] == status and drafts.get(MAIL)["text"] == TEXT
        attempts = server.attempts
    server.outcome = "OK"
    with JsonStore(tmp_path / "data") as store:
        app, drafts = compose(store, server, model)
        app.process(FETCHED)
        assert server.attempts == attempts  # a finished mail is never blindly rerun
        if status == "uncertain":
            drafts.auto_draft(MAIL, "Abgleichen")
        else:
            drafts.act("reviewer", MAIL, 1, "retry-0001", TEXT)
        assert drafts.get(MAIL)["status"] == "saved" and len(server.messages) == 1
        assert len(model.drafted) == 1


def test_restart_after_append_before_commit_reconciles_the_durable_message_id(tmp_path, monkeypatch):
    server, model = OfflineImap(), Model()
    with JsonStore(tmp_path / "data") as store:
        app, drafts = compose(store, server, model)
        save = drafts._save
        def crash_after_append(mail_id, draft):
            if draft["status"] == "saved":
                raise SystemExit("synthetic process exit after APPEND")
            save(mail_id, draft)
        monkeypatch.setattr(drafts, "_save", crash_after_append)
        with pytest.raises(SystemExit):
            app.process(FETCHED)
        assert drafts.get(MAIL)["status"] == "uncertain" and len(server.messages) == 1
        assert store.load_model(state_names.mail(MAIL), MailState).steps.auto_draft == "pending"
    with JsonStore(tmp_path / "data") as store:
        app, drafts = compose(store, server, model)
        assert app.process(FETCHED).state["steps"]["completion"] == "completed"
        assert drafts.get(MAIL)["status"] == "saved"
    assert server.attempts == 1 and len(model.drafted) == 1
