"""Series use real review services, synthetic writers, and durable storage."""

from datetime import date, datetime

import pytest

from mailhelp.models import KnownTemporalFacts, ProposalStatus
from mailhelp.review.commands import CommandKind
from mailhelp.review.results import ResultStatus
from mailhelp.review.series import SeriesService, members
from mailhelp.storage import JsonStore
from tests.fakes.proposal_builder_fakes import builder, event
from tests.fakes.series_fakes import batch, series
from tests.fakes.shared_review import EVENT, command, setup, web
from tests.fakes.shared_telegram_dialog import Writer, proposal


def test_dated_series_titles_preserve_base_identity_and_separate_another_title():
    items = builder().build([], [event(title="Sitzung", date_text=f"23.{month:02d}.2027",
                                      evidence=f"Sitzung am 23.{month:02d}.2027") for month in range(1, 11)]
                              + [event(title="Klausur")])
    assert len({item.title for item in items}) == 11
    assert {item.base_title for item in items[:10]} == {"Sitzung"}
    assert len({item.series_key for item in items[:10]}) == 1
    assert items[-1].series_key != items[0].series_key
    assert items[-1].title == "Klausur"


def test_one_time_answer_creates_one_revision_per_date_and_no_external_write(tmp_path):
    with JsonStore(tmp_path) as store:
        items = series()
        writer = Writer()
        dialog, _, _ = setup(store, *items, writers={"google_calendar": writer})
        review = web(dialog)
        cmd = batch(CommandKind.SERIES_ANSWER, items, text="19 Uhr")
        assert review.execute(cmd).status == ResultStatus.DONE
        for item in items:
            current = dialog.repository.load_current(item.source_mail_id, item.id)
            assert current.version == 2 and current.status == ProposalStatus.PENDING_CONFIRMATION
            assert current.start.date() == item.known_temporal_facts.date
            assert current.start.hour == 19 and current.end.hour == 22
            assert 'start' in current.protected_fields and current.end_origin == 'standard'
            assert current.series_key == item.series_key
        assert writer.created == 0
        assert review.execute(cmd).status == ResultStatus.DONE
        assert review.reconcile(cmd).status == ResultStatus.DONE
        assert all(dialog.repository.load_current(item.source_mail_id, item.id).version == 2 for item in items)


def test_confirmation_checks_the_whole_version_list_before_any_write(tmp_path):
    with JsonStore(tmp_path) as store:
        items = series(complete=True)
        writer = Writer()
        dialog, _, _ = setup(store, *items, writers={"google_calendar": writer})
        cmd = batch(CommandKind.SERIES_CONFIRM, items)
        dialog.persist(items[-1].model_copy(update={"version": 2}))
        result = web(dialog).execute(cmd)
        assert result.status == ResultStatus.STALE
        assert writer.created == 0


def test_series_confirmation_is_idempotent_and_rechecks_authorization(tmp_path):
    with JsonStore(tmp_path) as store:
        items = series(complete=True)
        writer = Writer()
        dialog, _, _ = setup(store, *items, writers={"google_calendar": writer})
        review = web(dialog)
        dialog.write_executor.web_authorizer = lambda actor: actor == "web:session"
        cmd = batch(CommandKind.SERIES_CONFIRM, items)
        assert review.execute(cmd).status == ResultStatus.DONE
        assert writer.created == len(items)
        assert review.reconcile(cmd).status == ResultStatus.DONE
        assert writer.created == len(items)
        web(dialog, allowed=False)
        assert review.execute(cmd).status == ResultStatus.UNAUTHORIZED


def test_a_late_incomplete_member_prevents_the_entire_batch(tmp_path):
    with JsonStore(tmp_path) as store:
        items = series(complete=True)
        items[-1] = series()[2]
        writer = Writer()
        dialog, _, _ = setup(store, *items, writers={"google_calendar": writer})
        assert web(dialog).execute(batch(CommandKind.SERIES_CONFIRM, items)).status == ResultStatus.NEEDS_ANSWER
        assert writer.created == 0


def test_preflight_checks_every_calendar_candidate_before_the_first_create(tmp_path):
    with JsonStore(tmp_path) as store:
        items = series(complete=True)
        writer = Writer()
        dialog, _, _ = setup(store, *items, writers={"google_calendar": writer})
        class ChangedPrecheck:
            def check_proposal(self, item):
                return item.model_copy(update={"duplicate_check_failed": True}) if item.id == items[-1].id else item
        dialog.decision_service.precheck = ChangedPrecheck()
        result = web(dialog).execute(batch(CommandKind.SERIES_CONFIRM, items))
        assert result.status == ResultStatus.STALE
        assert writer.created == 0
