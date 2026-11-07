"""Date suffixes are presentation; every matching provider receives the base title."""
from types import SimpleNamespace

import httpx
import pytest

from mailhelp.proposals.integrations import HttpWriter
from mailhelp.proposals.precheck import DuplicatePreCheckService
from mailhelp.proposals.proposal_reconciliation import ProposalReconciliationService
from mailhelp.storage import JsonStore
from tests.fakes.series_fakes import series


def test_reconciliation_matcher_receives_undecorated_titles(tmp_path):
    original = series(complete=True)[0]
    decorated = original.model_copy(update={'title': 'Sitzung – 23.01.2027'})
    def matcher(incoming, candidates):
        assert incoming.title == original.base_title and candidates[0].title == original.base_title
        return 'synthetic-match', {'relation': 'different', 'reason': 'Andere Quelle'}
    with JsonStore(tmp_path) as store:
        service = ProposalReconciliationService(store, matcher)
        assert service.compare(decorated, [decorated]).relation == 'different'
    assert decorated.title.endswith('2027')


@pytest.mark.parametrize('use_matcher', [False, True])
def test_calendar_precheck_keeps_using_the_base_title(use_matcher):
    item = series(complete=True)[0]
    def matcher(incoming, existing):
        assert incoming.title == item.base_title
        return 'synthetic-calendar-match', SimpleNamespace(same_event=True)
    def response(request):
        return httpx.Response(200, json={'items': [{'id': 'existing', 'summary': 'Sitzung',
            'start': {'dateTime': item.start.isoformat()}, 'end': {'dateTime': item.end.isoformat()}}]})
    writer = HttpWriter(service='google_calendar', token='synthetic', target='calendar',
                        calendar_timezone='Europe/Berlin', transport=httpx.MockTransport(response),
                        calendar_matcher=matcher if use_matcher else None)
    decorated = item.model_copy(update={'title': 'Sitzung – 23.01.2027'})
    result = DuplicatePreCheckService(writer=writer).check_proposal(decorated)
    assert result.status.value == 'already_exists' and result.duplicate_match.external_id == 'existing'
