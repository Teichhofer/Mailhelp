"""A partial external failure must remain visible until acknowledged."""
from mailhelp.llm.adapter import UncertainWriteError
from mailhelp.review.commands import CommandKind
from mailhelp.review.results import ResultStatus
from mailhelp.storage import JsonStore
from tests.fakes.series_fakes import batch, series
from tests.fakes.shared_review import setup, web
from tests.fakes.shared_telegram_dialog import Writer


def test_failed_series_members_never_report_an_unqualified_success(tmp_path):
    class Calendar(Writer):
        def create(self, item, key):
            raise UncertainWriteError('synthetic lost provider response')
    with JsonStore(tmp_path) as store:
        items = series(complete=True)
        dialog, _, _ = setup(store, *items, writers={'google_calendar': Calendar()})
        review = web(dialog)
        dialog.write_executor.web_authorizer = lambda actor: actor == 'web:session'
        result = review.execute(batch(CommandKind.SERIES_CONFIRM, items))
        assert result.status in {ResultStatus.WRITE_UNCERTAIN, ResultStatus.WRITE_FAILED}
        assert 'separat prüfen' in result.message
