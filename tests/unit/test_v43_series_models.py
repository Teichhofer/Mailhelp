"""Series metadata never turns malformed model input into unchecked runtime errors."""
import pytest
from pydantic import ValidationError

from mailhelp.models import Proposal
from tests.fakes.shared_telegram_dialog import proposal


@pytest.mark.parametrize('field,value', [('title', 12), ('source_mail_id', 12), ('base_title', {})])
def test_invalid_series_facts_are_regular_validation_errors(field, value):
    record = proposal(kind='event', start='2027-01-23T19:00:00+01:00', end='2027-01-23T22:00:00+01:00').model_dump()
    record[field] = value
    with pytest.raises(ValidationError):
        Proposal.model_validate(record)


def test_series_normalization_and_missing_dates_do_not_change_occurrence_identity():
    from mailhelp.domain.event_series import dated_title, series_key
    from mailhelp.persistence.ledger import ActionLedgerService
    from tests.fakes.proposal_builder_fakes import builder, event
    assert series_key('a' * 24, ' SITZUNG  Nord ') == series_key('a' * 24, 'sitzung nord')
    assert series_key('a' * 24, 'Sitzung') != series_key('b' * 24, 'Sitzung')
    assert dated_title('Sitzung', None) == 'Sitzung'
    items = builder().build([], [event(date_text=None, time_requirement='required_unknown',
                                    evidence='Das Sitzungsdatum steht noch nicht fest.') for _ in range(2)])
    assert {item.title for item in items} == {'Gemeinderat'}
    original = proposal(kind='event', start='2027-01-23T19:00:00+01:00', end='2027-01-23T22:00:00+01:00')
    decorated = original.model_copy(update={'title': dated_title(original.title, original.start)})
    assert ActionLedgerService.action_key(original) == ActionLedgerService.action_key(decorated)


def test_old_current_snapshot_and_mail_projection_are_backfilled_without_a_revision(tmp_path):
    from mailhelp.models import MailState
    from mailhelp.storage import JsonStore
    from tests.fakes.shared_review import mail_state
    original = proposal(kind='event', start='2027-01-23T19:00:00+01:00', end='2027-01-23T22:00:00+01:00')
    record = original.model_dump(mode='json', exclude={'base_title', 'series_key'})
    with JsonStore(tmp_path) as store:
        store.save('old', record)
        loaded = store.load_model('old', Proposal)
        assert loaded.series_key == original.series_key and loaded.version == 1
        assert store.load('old')['base_title'] == original.title
        state = mail_state(proposals=[original]).model_dump(mode='json')
        state['proposals'] = [record]
        store.save('mail-old', state)
        assert store.load_model('mail-old', MailState).proposals[0].series_key == loaded.series_key
        assert store.load('mail-old')['proposals'][0]['series_key'] == loaded.series_key


@pytest.mark.parametrize('field,value', [('title', []), ('source_mail_id', []), ('base_title', 12)])
def test_invalid_legacy_metadata_is_quarantined_without_an_unchecked_migration_error(tmp_path, field, value):
    from mailhelp.storage import CorruptState, JsonStore
    record = proposal(kind='event', start='2027-01-23T19:00:00+01:00', end='2027-01-23T22:00:00+01:00').model_dump(
        mode='json', exclude={'base_title', 'series_key'})
    record[field] = value
    with JsonStore(tmp_path) as store:
        store.save('broken', record)
        with pytest.raises(CorruptState): store.load_model('broken', Proposal)
        assert (tmp_path / 'broken.invalid').exists()


@pytest.mark.parametrize('change', [
    {'members': ()}, {'members': ({'proposal_id': 'p0', 'version': 1},) * 2},
    {'proposal_id': 'other'}, {'version': 2}, {'endpoint': 'end', 'kind': 'series_confirm', 'text': None},
    {'kind': 'confirm', 'text': None},
])
def test_series_commands_require_an_exact_unique_list_and_matching_root(change):
    from mailhelp.review.commands import CommandKind, ReviewCommand
    from tests.fakes.series_fakes import batch, series
    record = batch(CommandKind.SERIES_ANSWER, series(), text='19 Uhr').model_dump(mode='json')
    record.update(change)
    with pytest.raises(ValidationError): ReviewCommand.model_validate(record)
