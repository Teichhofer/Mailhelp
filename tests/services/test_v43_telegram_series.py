"""Real Telegram message and opaque callback paths, including restarts and replay."""
import pytest

from mailhelp.models import ProposalStatus, TelegramDialogState
from mailhelp.review.commands import CommandKind
from mailhelp.review.series_offers import SeriesOffer, create_offer
from mailhelp.storage import JsonStore
from mailhelp.telegram.models import TelegramUpdate
from mailhelp.telegram.series import execute_callback, offer_answer, offer_confirmation
from tests.fakes.series_fakes import series
from tests.fakes.shared_review import setup
from tests.fakes.shared_telegram_dialog import callback, message, proposal


def choice(telegram, label):
    return next(button['callback_data'] for _, _, markup in reversed(telegram.sent) if markup
                for row in markup['inline_keyboard'] for button in row if button['text'] == label)


@pytest.mark.parametrize('label,expected', [('Alle', 3), ('Nur diesen', 1)])
def test_time_answer_asks_before_applying_and_never_creates_without_confirmation(tmp_path, label, expected):
    with JsonStore(tmp_path) as store:
        items = series()
        dialog, telegram, _ = setup(store, *items)
        pointer = TelegramDialogState(mail_id=items[0].source_mail_id, proposal_id=items[0].id, version=1)
        store.save('telegram-dialog', pointer.model_dump(mode='json'))
        dialog.updates.handle(TelegramUpdate.model_validate(message(1, '19 Uhr')))
        assert all(dialog.repository.load_current(item.source_mail_id, item.id).version == 1 for item in items)
        assert all('datetime.date' not in text for _, text, _ in telegram.sent)
        data = choice(telegram, label)
        assert len(data.encode()) <= 64
        dialog.updates.handle(TelegramUpdate.model_validate(callback(2, data)))
        assert sum(dialog.repository.load_current(item.source_mail_id, item.id).version == 2 for item in items) == expected
        dialog.updates.handle(TelegramUpdate.model_validate(callback(3, data)))
        assert sum(dialog.repository.load_current(item.source_mail_id, item.id).version == 2 for item in items) == expected
        if expected == 3:
            assert choice(telegram, 'Alle 3 Termine anlegen').startswith('series:')


def test_ready_series_confirmation_is_visible_once_and_uses_the_exact_versions(tmp_path):
    with JsonStore(tmp_path) as store:
        from tests.fakes.shared_telegram_dialog import Writer
        items = series(complete=True)
        writer = Writer()
        dialog, telegram, _ = setup(store, *items, writers={'google_calendar': writer})
        offer_confirmation(dialog, items[0])
        count = len(telegram.sent)
        offer_confirmation(dialog, items[-1])
        assert len(telegram.sent) == count
        data = choice(telegram, 'Alle 3 Termine anlegen')
        dialog.updates.handle(TelegramUpdate.model_validate(callback(1, data, user=8)))
        assert writer.created == 0
        dialog.updates.handle(TelegramUpdate.model_validate(callback(2, data)))
        assert writer.created == 3
        dialog.updates.handle(TelegramUpdate.model_validate(callback(3, data)))
        assert writer.created == 3


@pytest.mark.parametrize('reason', ['no_pointer', 'empty_pointer', 'missing', 'stale', 'task',
                                   'no_question', 'other_question', 'not_time', 'date', 'singleton', 'retry'])
def test_only_an_unambiguous_series_clock_answer_is_offered(tmp_path, reason):
    with JsonStore(tmp_path) as store:
        items = series()
        dialog, telegram, _ = setup(store, *items)
        pointer = TelegramDialogState(mail_id=items[0].source_mail_id, proposal_id=items[0].id, version=1)
        text = '19 Uhr'
        if reason == 'no_pointer': pointer = None
        elif reason == 'empty_pointer': pointer = TelegramDialogState()
        elif reason == 'missing': store.delete(f'proposal-{items[0].source_mail_id}-{items[0].id}')
        elif reason == 'stale': pointer = pointer.model_copy(update={'version': 8})
        elif reason == 'retry':
            pointer = pointer.model_copy(update={'retry_required': True, 'question': 'Wann?', 'normalized_answer': '19 Uhr'})
        elif reason == 'task': dialog.persist(proposal(id=items[0].id))
        elif reason == 'no_question': dialog.persist(series(complete=True)[0])
        elif reason == 'other_question': dialog.persist(items[0].model_copy(update={'open_questions': ['Wer nimmt teil?']}))
        elif reason == 'not_time': text = 'irgendwann'
        elif reason == 'date': text = '23.01.2027 um 19 Uhr'
        elif reason == 'singleton':
            for item in items[1:]: store.delete(f'proposal-{item.source_mail_id}-{item.id}')
        assert offer_answer(dialog, pointer, text) is False
        assert telegram.sent == []


@pytest.mark.parametrize('data', ['series:invalid:all', 'series:' + '0' * 32 + ':all'])
def test_invalid_or_unknown_series_callback_never_changes_state(tmp_path, data):
    with JsonStore(tmp_path) as store:
        dialog, _, _ = setup(store, *series())
        with pytest.raises(ValueError):
            execute_callback(dialog, data)


def test_another_actor_and_changed_versions_cannot_reuse_a_telegram_offer(tmp_path):
    with JsonStore(tmp_path) as store:
        items = series(complete=True)
        dialog, telegram, _ = setup(store, *items)
        token = create_offer(store, SeriesOffer(actor='telegram:77:2', items=items))
        with pytest.raises(ValueError):
            execute_callback(dialog, f'series:{token}:confirm')
        offer_confirmation(dialog, items[0])
        data = choice(telegram, 'Alle 3 Termine anlegen')
        dialog.persist(items[-1].model_copy(update={'version': 2}))
        assert 'geändert' in execute_callback(dialog, data)


def test_an_old_series_answer_does_not_cancel_another_open_dialog(tmp_path):
    with JsonStore(tmp_path) as store:
        items = series()
        dialog, telegram, _ = setup(store, *items)
        pointer = TelegramDialogState(mail_id=items[0].source_mail_id, proposal_id=items[0].id, version=1)
        assert offer_answer(dialog, pointer, '19 Uhr')
        other = TelegramDialogState(mail_id='b' * 24, proposal_id='other', version=7)
        store.save('telegram-dialog', other.model_dump(mode='json'))
        execute_callback(dialog, choice(telegram, 'Alle'))
        assert store.load_model('telegram-dialog', TelegramDialogState) == other


def test_a_deleted_series_is_reported_without_cancelling_an_unrelated_dialog(tmp_path):
    with JsonStore(tmp_path) as store:
        items = series()
        dialog, telegram, _ = setup(store, *items)
        pointer = TelegramDialogState(mail_id=items[0].source_mail_id, proposal_id=items[0].id, version=1)
        assert offer_answer(dialog, pointer, '19 Uhr')
        for item in items: store.delete(f'proposal-{item.source_mail_id}-{item.id}')
        assert '0 Serientermine' in execute_callback(dialog, choice(telegram, 'Alle'))
        assert store.load('telegram-dialog') is None


def test_long_confirmation_lists_are_split_and_tasks_get_no_series_button(tmp_path):
    with JsonStore(tmp_path) as store:
        items = [item.model_copy(update={'title': 'Sitzung ' + 'x' * 480}) for item in series(10, complete=True)]
        dialog, telegram, _ = setup(store, *items)
        offer_confirmation(dialog, proposal())
        assert telegram.sent == []
        offer_confirmation(dialog, items[0])
        assert len(telegram.sent) > 1
        assert choice(telegram, 'Alle 10 Termine anlegen')


def test_an_end_time_is_offered_as_an_end_not_as_a_new_beginning(tmp_path):
    from mailhelp.models import KnownTemporalFacts
    with JsonStore(tmp_path) as store:
        items = [item.model_copy(update={'start': None, 'end': None, 'status': ProposalStatus.NEEDS_CLARIFICATION,
            'known_temporal_facts': KnownTemporalFacts(start=item.start), 'open_questions': ['Wann endet der Termin?']})
            for item in series(complete=True)]
        # Validate the copied enum value before passing to persistence.
        from mailhelp.models import Proposal
        items = [Proposal.model_validate(item.model_dump()) for item in items]
        dialog, telegram, _ = setup(store, *items)
        pointer = TelegramDialogState(mail_id=items[0].source_mail_id, proposal_id=items[0].id, version=1)
        assert offer_answer(dialog, pointer, '22:30 Uhr')
        assert 'gespeichert' in execute_callback(dialog, choice(telegram, 'Alle'))
        current = dialog.repository.load_current(items[0].source_mail_id, items[0].id)
        assert current.start.hour == 19 and current.end.minute == 30
