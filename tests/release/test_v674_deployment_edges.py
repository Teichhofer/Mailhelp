"""Deployment acceptance for legacy records, provider races and revoked authorization."""
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from mailhelp.external.http_writer import HttpWriter
from mailhelp.models import ProposalStatus
from mailhelp.review import CommandKind, ResultStatus
from mailhelp.review.service import ReviewService, proposal_creation_time
from mailhelp.review.views import ReviewViews
from mailhelp.storage import JsonStore
from tests.fakes.calendar_fakes import FakeGoogleCalendar, timed
from tests.fakes.factories import build_proposal
from tests.fakes.shared_review import command, setup, web
from tests.fakes.shared_telegram_dialog import Writer, callback


def event(**extra):
    return build_proposal(**{
        'source_mail_id': 'a' * 24, 'id': 'p1', 'kind': 'event', 'target': 'calendar',
        'start': '2026-12-01T10:00:00+00:00', 'end': '2026-12-01T11:00:00+00:00',
        'status': 'created', 'external_id': 'ev-1', **extra})


def test_calendar_removal_needs_an_external_id_and_handles_disappearing_read(monkeypatch):
    fake = FakeGoogleCalendar(timed('ev-1', 'Synthetic', '2026-12-01T10:00:00+00:00',
                                   '2026-12-01T11:00:00+00:00'))
    writer = HttpWriter(service='google_calendar', token='synthetic', target='primary',
                        calendar_timezone='UTC', transport=httpx.MockTransport(fake))
    with pytest.raises(ValueError, match='externe ID'):
        writer.prepare_remove(event(external_id=None), 'remove-missing')
    with pytest.raises(ValueError, match='externe ID'):
        writer._prepare_remove_calendar(event(external_id=None), 'remove-missing')
    # An older target-bound representation has no new-event expected facts.
    legacy = event(target='primary', target_event_id='ev-1')
    assert writer.prepare_remove(legacy, 'remove-legacy').requires_write
    # The second, authoritative read may lose an entry after the first read saw it.
    monkeypatch.setattr(writer, '_read_calendar', lambda _: None)
    assert writer.prepare_remove(event(target='primary'), 'remove-race').kind == 'remove'
    assert fake.patches == []  # preparation itself never writes


def test_todoist_delete_race_missing_identity_and_failures(monkeypatch):
    requests = []
    def respond(request):
        requests.append(request.method)
        return httpx.Response(404)
    writer = HttpWriter(service='todoist', token='synthetic', target='project',
                        transport=httpx.MockTransport(respond))
    task = build_proposal(kind='task', status='created', external_id='task-1', target='project')
    with pytest.raises(ValueError, match='externe ID'):
        writer.prepare_remove(task.model_copy(update={'external_id': None}), 'missing-id')
    with pytest.raises(ValueError, match='externe ID'):
        writer._prepare_remove_todoist(task.model_copy(update={'external_id': None}), 'missing-id')
    assert writer.reconcile_remove(task.model_copy(update={'external_id': None}), 'missing-id') is None
    assert writer._reconcile_remove_todoist(task.model_copy(update={'external_id': None}), 'missing-id') is None
    monkeypatch.setattr(writer, '_read_todoist', lambda _: SimpleNamespace(completed=False, facts={}, link=None))
    assert writer.reconcile_remove(task, 'still-present') is None
    # The generic adapter also accepts a provider record without task-specific facts.
    assert writer._prepare_remove_todoist(event(), 'legacy-kind').requires_write
    assert writer._remove_todoist('task-1', 'race-key', task)['operation'] == 'already_removed'
    assert requests == ['DELETE']
    def denied(*_):
        raise OSError('Synthetic unavailable provider')
    monkeypatch.setattr(writer, '_delete', denied)
    with pytest.raises(OSError, match='Synthetic unavailable'):
        writer._remove_todoist('task-1', 'failure-key', task)


def test_review_legacy_writer_lookup_and_missing_timestamps(tmp_path):
    task = build_proposal(kind='task', target='project', status='created', external_id='task-1')
    writer = Writer()
    owner = SimpleNamespace(controller=SimpleNamespace(writers={'todoist': writer}))
    assert ReviewService._writer_for(owner, task) is writer
    owner.controller.writers = {}
    assert ReviewService._writer_for(owner, task) is None
    with JsonStore(tmp_path) as store:
        assert proposal_creation_time(store, task) is None
        controller = SimpleNamespace(store=store)
        service = ReviewService(controller)
        assert service._is_within_removal_window(task)
        assert ReviewViews(store, 'UTC')._is_within_removal_window(task)


def test_removal_rechecks_session_after_preparation(tmp_path, monkeypatch):
    writer = Writer()
    with JsonStore(tmp_path) as store:
        dialog, _, _ = setup(store, event(created_at=datetime.now(UTC)), writers={'google_calendar': writer})
        service = web(dialog)
        original = writer.prepare_remove
        def revoke(proposal, key):
            prepared = original(proposal, key)
            service.web_authorizer = lambda _: False
            return prepared
        monkeypatch.setattr(writer, 'prepare_remove', revoke)
        result = service.execute(command(CommandKind.REMOVE_CREATED))
        assert result.status == ResultStatus.UNAUTHORIZED and writer.removed == 0
        assert dialog.repository.load_current('a' * 24, 'p1').status == ProposalStatus.CREATED


def test_telegram_asks_about_legacy_created_record_without_timestamp(tmp_path):
    from mailhelp.telegram.callbacks import Decision, DecisionAction
    with JsonStore(tmp_path) as store:
        dialog, transport, _ = setup(store, event(), writers={'google_calendar': Writer()})
        from mailhelp import state_names
        legacy = event(created_at=None)
        store.save(state_names.proposal(legacy.source_mail_id, legacy.id), legacy.model_dump(mode='json'))
        store.save('action-ledger', None)
        assert proposal_creation_time(store, legacy) is None
        token = Decision(mail_id='a' * 24, proposal_id='p1', version=1,
                         action=DecisionAction.REMOVE_ASK).encode(store)
        from mailhelp.telegram import TelegramUpdate
        # Handle the legacy callback before the normal polling pass repairs its ledger.
        dialog._handle(TelegramUpdate.model_validate(callback(1, token)))
        assert 'Wirklich entfernen' in transport.sent[-1][1]
        assert transport.sent[-1][2]['inline_keyboard']


def test_verified_notification_omits_button_for_calendar_file():
    from mailhelp.domain.verification import VerificationState
    from mailhelp.external.verification import EntryReader
    from mailhelp.telegram.writes import ConfirmedWriteExecutor
    proposal = event()
    record = SimpleNamespace(state=VerificationState.VERIFIED, notified=None)
    checks = SimpleNamespace(check=lambda *_: (proposal, record), mark_notified=Mock())
    owner = SimpleNamespace(verification=checks, persistence=SimpleNamespace(persist=Mock()),
                            telegram=SimpleNamespace(send=Mock()), chat_id=2,
                            _verified_text=lambda *_: 'Synthetic verified',
                            _can_remove=lambda p, r: ConfirmedWriteExecutor._can_remove(
                                SimpleNamespace(test_mode=False), p, r), _remove_button=Mock())
    reader = Mock(spec=EntryReader)
    assert ConfirmedWriteExecutor._verify(owner, proposal, proposal, reader,
                                          {'operation': 'calendar_file'}) == proposal
    owner.telegram.send.assert_called_once_with(2, 'Synthetic verified')
    owner._remove_button.assert_not_called()
    assert not ConfirmedWriteExecutor._can_remove(SimpleNamespace(test_mode=False),
                                                  event(external_id=None), {})
    assert not ConfirmedWriteExecutor._can_remove(SimpleNamespace(test_mode=True), proposal, {})
    assert not ConfirmedWriteExecutor._can_remove(SimpleNamespace(test_mode=False), proposal, {'simulation': True})


def test_detached_confirmation_has_no_remove_link_if_proposal_disappeared():
    from mailhelp.review.inbox import CommandEntry, CommandStatus
    from mailhelp.review.results import ReviewResult
    from mailhelp.web.command_cards import CommandCards
    cmd = command(CommandKind.CONFIRM)
    entry = CommandEntry(id='a' * 32, command=cmd, received_at=datetime.now(UTC),
                         status=CommandStatus.DONE,
                         result=ReviewResult(status=ResultStatus.DONE, message='Synthetic'))
    cards = CommandCards([entry], 'csrf', '/', views=SimpleNamespace(proposal=lambda *_: None))
    assert cards._detached_actions(entry) == ''


def test_empty_groups_keep_proposal_swipe_hint(web):
    from mailhelp.web.review_pages import overview_page
    overview = web.site.views.overview()
    html = overview_page(overview, sections=[('Empty first', (), ())])
    assert 'Nach rechts wischen: anlegen' in html and 'Empty first' in html
