"""6.3.2: retained terminal mail cannot retry with scrubbed analysis results."""
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from mailhelp.config import RetentionSettings
from mailhelp.domain.mail import MailState
from mailhelp.domain.processing import ProcessingStage
from mailhelp.mailbox.imap import FetchedMail
from mailhelp.mailbox.mailbox_run import _MailBudget
from mailhelp.persistence.storage import JsonStore
from mailhelp.processing.mail_pipeline import AnalysisDataUnavailable, MailPipeline, ProcessingOutcome, ProcessingRun
from mailhelp.review.views import ReviewViews
from mailhelp.runtime.retention import RetentionService
from tests.fakes.shared_application import Imap, Log, Orch, Telegram, app


def terminal():
    state = MailState(id="a" * 24, config_fingerprint="0" * 64,
                      imap={"account_id": "0" * 24, "folder": "INBOX", "uidvalidity": 7, "uid": 1},
                      mail={"text": "Synthetic"},
                      relevance={"decision": "relevant", "topic_ids": ["test"], "reason": "Synthetic"},
                      summary={"sentences": ["Synthetic"]})
    for name in ("preparation", "relevance", "summary", "completion"):
        setattr(state.steps, name, "completed")
    state.steps.action_detection = "failed"
    return state


def test_scrubbed_completed_mail_is_abandoned_once_without_fetch_or_budget_even_after_restart(tmp_path):
    state = terminal()
    state.relevance = None
    with JsonStore(tmp_path / "data") as store:
        store.save("mail-a", state.model_dump(mode="json"))
        service = app(tmp_path, Imap([]), Telegram([]), Orch(), store=store)
        budget = _MailBudget(1)
        assert service.mailbox.resume_pending(budget) == []
        assert budget.remaining == 1 and service.imap.uid_calls == service.orchestrator.seen == []
        saved = store.load("mail-a")
        assert saved["steps"]["completion"] == "completed"
        assert saved["steps"]["action_detection"] == "skipped"
        assert saved["error"]["code"] == "analysis_data_removed" and saved["error"]["retryable"] is False
        assert [event[0][2] for event in service.logger.events] == ["resume_abandoned"]
        assert service.mailbox.resume_pending() == [] and store.load("mail-a") == saved
    with JsonStore(tmp_path / "data") as store:
        restarted = app(tmp_path, Imap([]), Telegram([]), Orch(), store=store)
        assert restarted.mailbox.resume_pending() == []
        assert store.load("mail-a") == saved and restarted.logger.events == []


def test_retention_then_resume_stops_the_retry_and_present_results_remain_resumable(tmp_path):
    with JsonStore(tmp_path / "data") as store:
        state = terminal()
        store.save("mail-a", state.model_dump(mode="json"))
        log = Log()
        result = RetentionService(store, RetentionSettings(debug_llm_days="disabled", full_mail_days="unlimited"),
                                  log, lambda: datetime.now(UTC)).run()
        assert result.debug_scrubbed == 1
        service = app(tmp_path, Imap([]), Telegram([]), Orch(), store=store)
        assert service.mailbox.resume_pending() == [] and service.imap.uid_calls == []
        state = terminal()
        store.save("mail-b", state.model_dump(mode="json"))
        assert len(service.mailbox.resume_pending()) == 1
        assert service.imap.uid_calls == [("INBOX", 1, 7)]


def test_pipeline_names_missing_completed_relevance_instead_of_asserting():
    state = terminal()
    state.relevance = None
    owner = SimpleNamespace(duplicates=SimpleNamespace(check=lambda *_: False), vision=None)
    pipeline = MailPipeline(owner)
    pipeline._prepare = lambda *_: None
    run = ProcessingRun("mail-a", state, ProcessingStage.PREPARATION, 0)
    with pytest.raises(ValueError, match="Analyse-Daten fehlen"):
        pipeline.advance(run, FetchedMail("INBOX", 7, 1, b"Subject: Synthetic\n\nSynthetic"))


@pytest.mark.parametrize("field", ["mail", "summary"])
def test_missing_other_completed_prerequisites_do_not_spend_the_budget(tmp_path, field):
    state = terminal()
    setattr(state, field, None)
    with JsonStore(tmp_path / "data") as store:
        store.save("mail-a", state.model_dump(mode="json"))
        available = terminal()
        available.id = "b" * 24
        store.save("mail-b", available.model_dump(mode="json"))
        service = app(tmp_path, Imap([]), Telegram([]), Orch(), store=store)
        assert len(service.mailbox.resume_pending(_MailBudget(1))) == 1
        assert service.imap.uid_calls == [("INBOX", 1, 7)]
        assert store.load("mail-a")["error"]["retryable"] is False


def test_pipeline_defensively_records_a_permanent_missing_result():
    state = terminal()
    state.relevance = None
    state.steps.relevance = "pending"
    calls = []
    owner = SimpleNamespace(duplicates=SimpleNamespace(check=lambda *_: False), vision=None,
                            failure=lambda *args: calls.append(args), logger=Log())
    pipeline = MailPipeline(owner)
    pipeline._prepare = lambda *_: None
    pipeline._relevance = lambda run: setattr(run, "stage", ProcessingStage.RELEVANCE)
    run = ProcessingRun("mail-a", state, ProcessingStage.PREPARATION, 0)
    with pytest.raises(AnalysisDataUnavailable) as caught:
        pipeline.advance(run, FetchedMail("INBOX", 7, 1, b"Subject: Synthetic\n\nSynthetic"))
    assert pipeline.handle_failure(run, caught.value) is ProcessingOutcome.FAILED
    assert calls[0][2].value == "analysis_data_removed" and calls[0][-1] is False
    assert owner.logger.events[0][0][2] == "analysis_data_unavailable"


def test_abandoned_mail_remains_completed_and_visible_with_its_named_error(tmp_path):
    state = terminal()
    state.mail = state.relevance = state.summary = None
    with JsonStore(tmp_path / "data") as store:
        store.save("mail-" + state.id, state.model_dump(mode="json"))
        service = app(tmp_path, Imap([]), Telegram([]), Orch(), store=store)
        assert service.mailbox.resume_pending() == []
        overview = ReviewViews(store, "UTC").system()
        assert overview.mails_failed == 1
        assert overview.errors[0].cause_code == "analysis_data_removed"
        assert overview.errors[0].cause == (
            "Aktionserkennung nicht nachholbar – Analyse-Daten nach Aufbewahrung entfernt")
        assert store.load("mail-" + state.id)["steps"]["completion"] == "completed"
