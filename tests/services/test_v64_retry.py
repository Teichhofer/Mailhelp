"""Bounded processing, including persisted restarts and admission before IMAP."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from mailhelp.models import MailState, ProcessingErrorCode, ProcessingStage
from mailhelp.processing.orchestrator import Orchestrator
from mailhelp.processing.retry import blocked, failed, succeeded
from tests.fakes.processing_retry import errored, terminal



def test_five_attempts_survive_restart_and_never_fetch_during_delay(tmp_path):
    from mailhelp.mailbox.mailbox_run import _MailBudget
    from mailhelp.storage import JsonStore
    from tests.fakes.shared_application import Imap, Orch, Telegram, app

    state = errored()
    now = datetime.now(UTC)
    for attempt, delay in enumerate((60, 300, 1800, 7200, None), 1):
        failed(state, 'config', now)
        state = MailState.model_validate_json(state.model_dump_json())
        assert state.processing_retry.attempts == attempt
        assert state.processing_retry.first_failed_at <= now
        assert state.processing_retry.last_failed_at == now
        assert blocked(state, 'config', now)
        if delay is None:
            assert state.processing_retry.abandoned and state.deferred_until is None
        else:
            assert state.deferred_until == now + timedelta(seconds=delay)
            assert not blocked(state, 'config', state.deferred_until)
        now += timedelta(days=1)
    with JsonStore(tmp_path / 'data') as store:
        state.processing_retry.fingerprint = f'{state.config_fingerprint}:relevance:internal_error'
        store.save('mail-a', state.model_dump(mode='json'))
        application = app(tmp_path, Imap([]), Telegram([]), Orch(), store=store)
        budget = _MailBudget(1)
        assert application.mailbox.resume_pending(budget) == []
        assert budget.remaining == 1 and application.imap.uid_calls == []
        assert application.mailbox.resume_pending() == []


def test_changed_error_configuration_success_permanent_and_rate_limit():
    state = errored(); now = datetime.now(UTC)
    failed(state, 'one', now)
    assert not blocked(state, 'two', now)
    assert state.processing_retry is None and state.deferred_until is None
    failed(state, 'two', now)
    state.error.stage = ProcessingStage.SUMMARY
    failed(state, 'two', now)
    assert state.processing_retry.attempts == 1
    state.error.retryable = False
    failed(state, 'two', now)
    assert state.processing_retry.abandoned
    state.processing_filed = True
    assert blocked(state, 'two', now)
    state.processing_filed = False
    succeeded(state)
    assert state.processing_retry is None and state.deferred_until is None
    state.error.code = ProcessingErrorCode.LLM_RATE_LIMITED
    state.deferred_until = now + timedelta(hours=1)
    failed(state, 'two', now)
    assert state.processing_retry is None and blocked(state, 'two', now)


def test_operator_receives_one_notification_only_when_abandoned():
    state = terminal(); saves=[]; messages=[]
    owner = SimpleNamespace(fingerprint_for=lambda _: 'config', save=lambda *_: saves.append(1),
                            notifier=SimpleNamespace(send=lambda *args: messages.append(args)), chat_id=1)
    for attempt in range(7):
        Orchestrator.failure(owner, 'mail-a', state, ProcessingErrorCode.INTERNAL_ERROR,
                             ProcessingStage.RELEVANCE, 'Synthetic')
        assert len(messages) == (0 if attempt < 4 else 1)
    assert len(saves) == 7 and state.processing_retry.attempts == 5


def test_legacy_and_empty_retry_are_compatible():
    state = terminal()
    raw=state.model_dump(); raw.pop('processing_retry'); raw.pop('processing_filed')
    assert MailState.model_validate(raw).processing_retry is None
    assert not blocked(state, 'config', datetime.now(UTC))


def test_rate_limit_failure_notification_suppression_and_web_link(tmp_path):
    from tests.fakes.factories import minimal_settings
    state = terminal()
    saves = []
    messages = []
    settings = minimal_settings(tmp_path, web={"enabled": True, "port": 8080})
    owner = SimpleNamespace(
        fingerprint_for=lambda _: 'config',
        save=lambda *_: saves.append(1),
        notifier=SimpleNamespace(send=lambda *args: messages.append(args)),
        chat_id=1,
        mailbox_settings=settings,
    )
    for attempt in range(5):
        Orchestrator.failure(owner, 'mail-a', state, ProcessingErrorCode.INTERNAL_ERROR,
                             ProcessingStage.RELEVANCE, 'Synthetic')
    assert len(messages) == 1
    assert f"/mail/{state.id}" in messages[0][1]

    state_rl = errored()
    state_rl.processing_retry = None
    state_rl.error.code = ProcessingErrorCode.LLM_RATE_LIMITED
    state_rl.error.notification_marked_at = datetime.now(UTC)
    messages.clear()
    Orchestrator.failure(owner, 'mail-b', state_rl, ProcessingErrorCode.LLM_RATE_LIMITED,
                         ProcessingStage.RELEVANCE, 'Rate limited')
    assert len(messages) == 0


def test_resume_pending_fetch_error_calls_failure(tmp_path):
    from mailhelp.mailbox.mailbox_run import _MailBudget
    from mailhelp.storage import JsonStore
    from tests.fakes.shared_application import Imap, Orch, Telegram, app

    state = errored()
    state.steps.completion = "pending"
    state.steps.action_detection = "pending"
    state.awaiting_relevance = False
    state.processing_retry = None
    state.deferred_until = None

    class FailingImap(Imap):
        def fetch_uid(self, *args):
            raise RuntimeError("IMAP fetch failed during resume")

    failures = []
    class FailingOrch(Orch):
        def failure(self, *args):
            failures.append(args)

    with JsonStore(tmp_path / 'data') as store:
        state.config_fingerprint = "0" * 64
        store.save('mail-state-000000000000000000000001', state.model_dump(mode='json'))
        application = app(tmp_path, FailingImap([]), Telegram([]), FailingOrch(), store=store)
        results = application.mailbox.resume_pending(_MailBudget(1))
        assert results == []
        assert len(failures) == 1
        assert failures[0][0] == 'mail-state-000000000000000000000001'
        assert failures[0][2] == ProcessingErrorCode.INTERNAL_ERROR


def test_telegram_status_reports_abandoned_mails(tmp_path):
    from mailhelp.domain.retry import ProcessingRetry
    from mailhelp.storage import JsonStore
    from mailhelp.telegram.commands import TelegramCommands
    from tests.fakes.shared_application import Imap, Orch, Telegram, app

    state = errored()
    state.processing_retry = ProcessingRetry(
        fingerprint="test", attempts=5, abandoned=True,
        first_failed_at=datetime.now(UTC), last_failed_at=datetime.now(UTC),
    )
    state.processing_filed = False

    with JsonStore(tmp_path / 'data') as store:
        store.save('mail-state-000000000000000000000001', state.model_dump(mode='json'))
        telegram = Telegram([])
        commands = TelegramCommands(
            store=store,
            repository=SimpleNamespace(open_proposals=lambda: []),
            presenter=SimpleNamespace(profiles_status=lambda: None),
            telegram=telegram,
            chat_id=1,
            relevance=SimpleNamespace(open=lambda: []),
            outbox=None,
        )
        commands.overview(counted=True)
        assert any("1 aufgegebene Mails – Handlungsbedarf im Webstatus." in text for _, text in telegram.sent)

