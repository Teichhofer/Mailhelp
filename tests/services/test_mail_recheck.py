"""Re-checking a mail filed as irrelevant (Planung 3.6, Schritt 0.2); synthetic data only."""
from __future__ import annotations

from datetime import timedelta
from threading import Event

from clock_fakes import step_back_wall_clock
from log_fakes import RecordingLogger
from shared_application import settings as app_settings
from shared_services import AnalyzerStub, Notify

from mailhelp.config import Topic
from mailhelp.mailbox.imap import FetchedMail
from mailhelp.mailbox.mailbox_run import MailboxRunService
from mailhelp.models import MailState
from mailhelp.processing.mail_recheck import RecheckOutcome, filed_as_irrelevant, recheck_round, request_recheck
from mailhelp.processing.orchestrator import Orchestrator, ProcessingOutcome
from mailhelp.storage import JsonStore

ACCOUNT = "c" * 24
RAW = (b"From: Amt <amt@example.test>\nSubject: Anmeldebestaetigung Onlinevortrag\nMessage-ID: <v1@example.test>\n\n"
       b"Beginn 12.11.2026, 18:30 Uhr")
MAIL = FetchedMail("INBOX", 7, 41, RAW, ACCOUNT)


def orchestrator(store, decision, logger=None):
    return Orchestrator(AnalyzerStub(decision), store, Notify(), 1, [Topic(id="t", name="T", enabled=True, description="t")],
                        100_000, logger=logger)


def state(store) -> MailState:
    loaded = store.load_model("mail-" + mail_id(store), MailState)
    assert isinstance(loaded, MailState)
    return loaded


def mail_id(store) -> str:
    (name,) = [name for name in store.names("mail-") if not name.startswith("mail-run-")]
    return name.removeprefix("mail-")


def test_a_mail_filed_as_irrelevant_is_analysed_again_with_the_current_configuration(tmp_path):
    logger = RecordingLogger()
    with JsonStore(tmp_path) as store:
        assert orchestrator(store, "irrelevant").process(MAIL).outcome is ProcessingOutcome.COMPLETED
        before = state(store)
        assert filed_as_irrelevant(before) and before.summary is None and before.analysis_round == 1
        assert recheck_round(store, before.id) == 1
        # A new topic now makes the mail relevant; its fingerprint differs from the stored one.
        current = orchestrator(store, "relevant", logger)
        current.config_fingerprint = "1" * 64
        # The web names the round it showed; another round is refused unchanged.
        assert request_recheck(current, before.id, expected_round=2) is RecheckOutcome.STALE
        assert state(store) == before
        assert request_recheck(current, before.id, expected_round=1) is RecheckOutcome.QUEUED
        queued = state(store)
        assert queued.steps.completion == queued.steps.preparation == queued.steps.relevance == "pending"
        assert queued.config_fingerprint == "1" * 64 and queued.mail is None and queued.relevance is None
        assert (queued.imap, queued.duplicate, queued.created_at) == (before.imap, before.duplicate, before.created_at)
        assert queued.llm_call_ids == before.llm_call_ids and queued.analysis_round == 2
        assert recheck_round(store, before.id) is None
        ((_, fields),) = [item for item in logger.events if item[0][2] == "recheck_requested"]
        assert fields == {"mail_id": before.id, "round": 2, "configuration_changed": True}
        # Repeating the request before the analysis ran changes nothing.
        assert request_recheck(current, before.id) is RecheckOutcome.ALREADY_PENDING
        assert request_recheck(current, before.id, expected_round=1) is RecheckOutcome.STALE
        assert state(store) == queued
        # The regular resumption fetches the mail again and runs the whole pipeline.
        assert current.process(MAIL).outcome is ProcessingOutcome.COMPLETED
        after = state(store)
        assert after.relevance is not None and after.relevance.decision == "relevant"
        assert after.summary is not None and after.steps.completion == "completed"
        assert after.duplicate == before.duplicate
        # A mail that is now relevant is not offered again.
        assert request_recheck(current, before.id) is RecheckOutcome.NOT_IRRELEVANT


def test_a_mail_scrubbed_by_retention_is_fetched_again_through_the_resumption(tmp_path):
    class Reader:
        account_id, last_uidvalidity = ACCOUNT, 7

        def __init__(self):
            self.fetches = []

        def fetch_uid(self, folder, uid, uidvalidity):
            self.fetches.append((folder, uid, uidvalidity))
            return MAIL

    with JsonStore(tmp_path / "state") as store:
        orchestrator(store, "irrelevant").process(MAIL)
        scrubbed = state(store)
        scrubbed.mail = scrubbed.relevance = None
        scrubbed.llm_call_ids = []
        store.save("mail-" + scrubbed.id, scrubbed.model_dump(mode="json"))
        current = orchestrator(store, "relevant")
        assert request_recheck(current, scrubbed.id) is RecheckOutcome.QUEUED
        reader = Reader()
        service = MailboxRunService(app_settings(tmp_path), store, RecordingLogger(), [], current, Event(),
                                    current.process, resume_readers={ACCOUNT: reader})
        (result,) = service.resume_pending()
        assert result.outcome is ProcessingOutcome.COMPLETED and reader.fetches == [("INBOX", 41, 7)]
        after = state(store)
        assert after.mail is not None and after.relevance is not None and after.relevance.decision == "relevant"


def test_only_known_mails_filed_as_irrelevant_can_be_rechecked(tmp_path):
    with JsonStore(tmp_path) as store:
        current = orchestrator(store, "relevant")
        assert request_recheck(current, "../config") is RecheckOutcome.NOT_FOUND
        assert request_recheck(current, "a" * 24) is RecheckOutcome.NOT_FOUND
        current.process(MAIL)
        relevant = state(store)
        assert relevant.proposals and request_recheck(current, relevant.id) is RecheckOutcome.NOT_IRRELEVANT
        # A mail with proposals is never reset, whatever its steps say.
        relevant.steps.summary = "skipped"
        store.save("mail-" + relevant.id, relevant.model_dump(mode="json"))
        assert request_recheck(current, relevant.id) is RecheckOutcome.NOT_IRRELEVANT
        # A duplicate skipped the relevance check; it mirrors another mail.
        relevant.steps.relevance, relevant.proposals, relevant.proposal_notifications = "skipped", [], []
        store.save("mail-" + relevant.id, relevant.model_dump(mode="json"))
        assert request_recheck(current, relevant.id) is RecheckOutcome.NOT_IRRELEVANT


def test_saving_after_the_clock_stepped_back_never_moves_updated_at_backwards(tmp_path, monkeypatch):
    """Regression (4.0.0): a backward clock correction produced updated_at before created_at."""
    with JsonStore(tmp_path) as store:
        service = orchestrator(store, "irrelevant")
        assert service.process(MAIL).outcome is ProcessingOutcome.COMPLETED
        before = state(store)
        step_back_wall_clock(monkeypatch, 0, timedelta(hours=1))
        service.save("mail-" + before.id, before)
        assert state(store).updated_at == before.updated_at


def test_a_recheck_after_the_clock_stepped_back_keeps_a_valid_state(tmp_path, monkeypatch):
    """Regression (4.0.0): the fresh state of a recheck failed validation after a clock step back."""
    with JsonStore(tmp_path) as store:
        assert orchestrator(store, "irrelevant").process(MAIL).outcome is ProcessingOutcome.COMPLETED
        before = state(store)
        current = orchestrator(store, "relevant")
        step_back_wall_clock(monkeypatch, 0, timedelta(hours=1))
        assert request_recheck(current, before.id, expected_round=1) is RecheckOutcome.QUEUED
        queued = state(store)
        assert queued.analysis_round == 2 and queued.created_at == before.created_at
        assert queued.updated_at >= before.updated_at and not list(tmp_path.glob("*.invalid"))
        assert current.process(MAIL).outcome is ProcessingOutcome.COMPLETED
