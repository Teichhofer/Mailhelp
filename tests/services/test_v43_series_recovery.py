"""Restart, races, partial failures and authorization for series operations."""
from dataclasses import replace

import pytest

from mailhelp.models import ProposalStatus
from mailhelp.proposals.proposal_reconciliation import ProposalReconciliationService
from mailhelp.review.commands import CommandKind
from mailhelp.review.results import ResultStatus
from mailhelp.review.series import SeriesService
from mailhelp.storage import JsonStore
from tests.fakes.series_fakes import batch, series
from tests.fakes.shared_review import setup, web
from tests.fakes.shared_telegram_dialog import Writer, proposal


def configured(store, items, writer=None):
    writer = writer or Writer()
    dialog, _, _ = setup(store, *items, writers={"google_calendar": writer})
    review = web(dialog)
    return dialog, review, writer


@pytest.mark.parametrize('change', ['missing', 'version', 'closed'])
def test_answer_skips_stale_terms_and_names_them(tmp_path, change):
    with JsonStore(tmp_path) as store:
        items = series()
        dialog, review, writer = configured(store, items)
        last = items[-1]
        if change == 'missing':
            store.delete(f'proposal-{last.source_mail_id}-{last.id}')
        else:
            dialog.persist(last.model_copy(update={'version': 2} if change == 'version' else {'status': ProposalStatus.REJECTED}))
        result = review.execute(batch(CommandKind.SERIES_ANSWER, items, text='19 Uhr'))
        assert result.status == ResultStatus.DONE and last.id in result.message
        assert '2 Serientermine' in result.message
        assert dialog.repository.load_current(items[0].source_mail_id, items[0].id).version == 2
        assert writer.created == 0


@pytest.mark.parametrize('change', ['task', 'different_series', 'missing_key'])
def test_mixed_or_unbound_series_never_creates_anything(tmp_path, change):
    with JsonStore(tmp_path) as store:
        items = series(complete=True)
        if change == 'task':
            items[-1] = proposal(id=items[-1].id)
        elif change == 'different_series':
            items[-1] = proposal(id=items[-1].id, kind='event', title='Andere Sitzung',
                start=items[-1].start, end=items[-1].end)
        dialog, review, writer = configured(store, items)
        if change == 'missing_key':
            original = dialog.repository.load_current
            def load(mail, pid):
                item = original(mail, pid)
                return item.model_copy(update={'series_key': None}) if pid == items[-1].id else item
            dialog.repository.load_current = load
        assert review.execute(batch(CommandKind.SERIES_CONFIRM, items)).status == ResultStatus.INVALID
        assert writer.created == 0


@pytest.mark.parametrize('reason', ['profile', 'candidate', 'prior_action'])
def test_confirmation_preflight_stops_before_the_first_write(tmp_path, monkeypatch, reason):
    with JsonStore(tmp_path) as store:
        items = series(complete=True)
        dialog, review, writer = configured(store, items)
        if reason == 'profile':
            dialog.decision_service.profile_available = lambda item: item.id != items[-1].id
        elif reason == 'candidate':
            monkeypatch.setattr(ProposalReconciliationService, 'confirmation_candidates',
                                lambda self, item: [object()] if item.id == items[-1].id else [])
        else:
            dialog.ledger.prior_actions = lambda item: [object()] if item.id == items[-1].id else []
        result = review.execute(batch(CommandKind.SERIES_CONFIRM, items))
        assert result.status in {ResultStatus.STALE, ResultStatus.NEEDS_ANSWER}
        assert writer.created == 0


def test_precheck_network_port_runs_outside_the_shared_store_lock(tmp_path):
    with JsonStore(tmp_path) as store:
        items = series(complete=True)
        dialog, review, writer = configured(store, items)
        class Precheck:
            def check_proposal(self, item):
                assert not store._thread_lock._is_owned()
                return item
        dialog.decision_service.precheck = Precheck()
        assert review.execute(batch(CommandKind.SERIES_CONFIRM, items)).status == ResultStatus.DONE
        assert writer.created == 3


def test_a_change_during_preflight_rejects_the_whole_batch(tmp_path, monkeypatch):
    with JsonStore(tmp_path) as store:
        items = series(complete=True)
        dialog, review, writer = configured(store, items)
        check = SeriesService._preflight
        def preflight(service, receipt):
            check(service, receipt)
            dialog.persist(items[-1].model_copy(update={'version': 2}))
        monkeypatch.setattr(SeriesService, '_preflight', preflight)
        assert review.execute(batch(CommandKind.SERIES_CONFIRM, items)).status == ResultStatus.STALE
        assert writer.created == 0


def test_unparseable_time_and_receipt_key_reuse_cannot_overwrite_versions(tmp_path):
    with JsonStore(tmp_path) as store:
        items = series()
        dialog, review, writer = configured(store, items)
        cmd = batch(CommandKind.SERIES_ANSWER, items, text='irgendwann')
        assert review.execute(cmd).status == ResultStatus.NEEDS_ANSWER
        cmd = cmd.model_copy(update={'text': '19 Uhr'})
        assert review.execute(cmd).status == ResultStatus.DONE
        assert review.execute(cmd.model_copy(update={'text': '20 Uhr'})).status == ResultStatus.INVALID
        assert dialog.repository.load_current(items[0].source_mail_id, items[0].id).version == 2
        assert writer.created == 0


def test_restart_after_a_revision_commit_does_not_create_a_second_version(tmp_path, monkeypatch):
    with JsonStore(tmp_path) as store:
        items = series()
        dialog, review, _ = configured(store, items)
        persist = dialog.persist
        def interrupted(item):
            persist(item)
            raise KeyboardInterrupt('synthetic crash after durable revision')
        monkeypatch.setattr(dialog, 'persist', interrupted)
        cmd = batch(CommandKind.SERIES_ANSWER, items, text='19 Uhr')
        with pytest.raises(KeyboardInterrupt):
            review.execute(cmd)
        monkeypatch.setattr(dialog, 'persist', persist)
        assert review.reconcile(cmd).status == ResultStatus.DONE
        assert all(dialog.repository.load_current(item.source_mail_id, item.id).version == 2 for item in items)


def test_restart_after_external_success_reconciles_before_continuing(tmp_path):
    class DurableCalendar:
        def __init__(self):
            self.entries, self.creates, self.lookups = {}, [], []
            self.interrupt = True
        def create(self, item, key):
            self.creates.append(key)
            self.entries[key] = {'id': f'event-{item.id}', 'url': 'https://example.test/event'}
            if self.interrupt:
                self.interrupt = False
                raise KeyboardInterrupt('synthetic crash after server accepted create')
            return self.entries[key]
        def reconcile(self, key):
            self.lookups.append(key)
            return self.entries.get(key)
    calendar = DurableCalendar()
    items = series(complete=True)
    cmd = batch(CommandKind.SERIES_CONFIRM, items)
    with JsonStore(tmp_path) as store:
        dialog, review, _ = configured(store, items, calendar)
        with pytest.raises(KeyboardInterrupt):
            review.execute(cmd)
    with JsonStore(tmp_path) as store:
        # Restart without seeding the authoritative state again.
        from tests.fakes.shared_telegram_dialog import controller
        dialog, _, _ = controller(store, writers={'google_calendar': calendar})
        review = web(dialog)
        assert review.reconcile(cmd).status == ResultStatus.DONE
        assert len(calendar.creates) == 3 and len(set(calendar.creates)) == 3
        assert calendar.creates[0] in calendar.lookups
        assert review.reconcile(cmd).status == ResultStatus.DONE
        assert len(calendar.creates) == 3


def test_revoked_session_stops_remaining_members_after_an_individual_result(tmp_path):
    allowed = True
    class Calendar(Writer):
        def create(self, item, key):
            nonlocal allowed
            result = super().create(item, key)
            allowed = False
            return result
    with JsonStore(tmp_path) as store:
        items = series(complete=True)
        dialog, review, writer = configured(store, items, Calendar())
        review.web_authorizer = lambda actor: allowed
        result = review.execute(batch(CommandKind.SERIES_CONFIRM, items))
        assert result.status == ResultStatus.UNAUTHORIZED and writer.created == 1
        assert dialog.repository.load_current(items[-1].source_mail_id, items[-1].id).status == ProposalStatus.PENDING_CONFIRMATION


def test_a_mid_batch_version_change_stops_all_remaining_creates(tmp_path):
    with JsonStore(tmp_path) as store:
        items = series(complete=True)
        dialog, review, writer = configured(store, items)
        create = writer.create
        def changed(item, key):
            result = create(item, key)
            dialog.persist(items[1].model_copy(update={'version': 2}))
            return result
        writer.create = changed
        assert review.execute(batch(CommandKind.SERIES_CONFIRM, items)).status == ResultStatus.STALE
        assert writer.created == 1


def test_restart_after_success_before_receipt_does_not_repeat_the_create(tmp_path, monkeypatch):
    with JsonStore(tmp_path) as store:
        items = series(complete=True)
        dialog, review, writer = configured(store, items)
        save = store.save
        def interrupted(name, value):
            if name.startswith('series-receipt-') and value['completed']:
                raise KeyboardInterrupt('synthetic crash before progress receipt')
            save(name, value)
        monkeypatch.setattr(store, 'save', interrupted)
        cmd = batch(CommandKind.SERIES_CONFIRM, items)
        with pytest.raises(KeyboardInterrupt): review.execute(cmd)
        assert writer.created == 1
        monkeypatch.setattr(store, 'save', save)
        assert review.reconcile(cmd).status == ResultStatus.DONE
        assert writer.created == 3


def test_a_change_during_answer_application_is_skipped_and_reported(tmp_path):
    with JsonStore(tmp_path) as store:
        items = series()
        dialog, review, writer = configured(store, items)
        persist = dialog.persist
        def changed(item):
            persist(item)
            if item.id == items[0].id:
                persist(items[1].model_copy(update={'version': 2}))
        dialog.persist = changed
        result = review.execute(batch(CommandKind.SERIES_ANSWER, items, text='19 Uhr'))
        assert result.status == ResultStatus.DONE and '2 Serientermine' in result.message
        assert items[1].id in result.message and writer.created == 0
        assert dialog.repository.load_current(items[1].source_mail_id, items[1].id).start is None


def test_active_configuration_controls_series_default_duration(tmp_path):
    from types import SimpleNamespace

    from tests.fakes.factories import minimal_settings
    with JsonStore(tmp_path / 'data') as store:
        items = series()
        dialog, review, _ = configured(store, items)
        cfg = minimal_settings(tmp_path, event_defaults={'in_person_duration_minutes': 120})
        review.configuration = SimpleNamespace(active=cfg)
        assert review.execute(batch(CommandKind.SERIES_ANSWER, items, text='19 Uhr')).status == ResultStatus.DONE
        current = dialog.repository.load_current(items[0].source_mail_id, items[0].id)
        assert current.end.hour == 21 and current.default_duration_minutes == 120


def test_shared_end_answer_respects_the_known_start_and_protects_manual_facts(tmp_path):
    from mailhelp.models import KnownTemporalFacts
    with JsonStore(tmp_path) as store:
        items = [item.model_copy(update={'start': None, 'end': None, 'status': ProposalStatus.NEEDS_CLARIFICATION,
            'known_temporal_facts': KnownTemporalFacts(start=item.start), 'open_questions': ['Wann endet der Termin?']})
            for item in series(complete=True)]
        dialog, review, writer = configured(store, items)
        assert review.execute(batch(CommandKind.SERIES_ANSWER, items, text='22:30 Uhr', endpoint='end')).status == ResultStatus.DONE
        for item in items:
            current = dialog.repository.load_current(item.source_mail_id, item.id)
            assert current.start.hour == 19 and (current.end.hour, current.end.minute) == (22, 30)
            assert 'end' in current.protected_fields and current.end_origin == 'manual'
        assert writer.created == 0
