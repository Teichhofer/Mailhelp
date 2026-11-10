"""5.1 R9: retention, damaged and old job files, parallel starts and restarts of re-analysis jobs."""
import threading
from datetime import UTC, datetime, timedelta

import pytest

from mailhelp.config import ReanalysisSettings, RetentionSettings
from mailhelp.domain.mail import MailState
from mailhelp.domain.reanalysis import ReanalysisJob, ReanalysisStatus
from mailhelp.processing.reanalysis import ReanalysisJobs
from mailhelp.runtime.retention import RetentionService
from mailhelp.storage import JsonStore
from tests.fakes.log_fakes import RecordingLogger
from tests.fakes.reanalysis_fakes import DONE_STEPS
from tests.scenarios.web_scenario import mail_id, proposal

NOW = datetime(2026, 11, 10, 9, tzinfo=UTC)
MAIL = mail_id(11)


def job(number, status, updated, **fields):
    completed = status == ReanalysisStatus.COMPLETED
    return ReanalysisJob(id=f"{number:032x}", mail_id=MAIL, source_round=1, config_fingerprint="f" * 64,
                         imap={"account_id": "0" * 24, "folder": "INBOX", "uidvalidity": 1, "uid": 11},
                         key_hash=f"{number:064x}", status=status, stage="done" if completed else "route",
                         max_attempts=2, max_llm_calls=5, error="model_failed" if status == "failed" else None,
                         proposals=[proposal(11, "neu", evidence="Beleg aus der Mail")] if completed else [],
                         hint="Bitte die Frist prüfen", created_at=updated, updated_at=updated, **fields)


@pytest.fixture
def store(tmp_path):
    return JsonStore(tmp_path)


def save(store, *jobs):
    for item in jobs:
        store.save(f"reanalysis-{item.id}", item.model_dump(mode="json"))


def test_retention_removes_finished_jobs_and_old_results_but_keeps_active_ones(store):
    old, recent = NOW - timedelta(days=40), NOW - timedelta(days=2)
    save(store, job(1, "failed", recent), job(2, "cancelled", recent), job(3, "completed", recent, adopted_at=recent),
         job(4, "completed", recent), job(5, "completed", old), job(6, "queued", old), job(7, "running", old))
    result = RetentionService(store, RetentionSettings(), RecordingLogger(), lambda: NOW).run()
    # Default analysis retention is "disabled": finished jobs go at once; an unadopted result
    # follows the 30 days of full mail content; active jobs are never removed.
    assert result.reanalysis_removed == 4
    assert sorted(name[-1] for name in store.names("reanalysis-")) == ["4", "6", "7"]


def test_unlimited_retention_keeps_every_job(store):
    save(store, job(1, "failed", NOW - timedelta(days=400)))
    settings = RetentionSettings(debug_llm_days="unlimited", full_mail_days="unlimited")
    assert RetentionService(store, settings, RecordingLogger(), lambda: NOW).run().reanalysis_removed == 0


def test_a_damaged_job_file_is_isolated_and_the_others_stay_usable(store):
    save(store, job(1, "queued", NOW))
    (store.directory / f"reanalysis-{2:032x}.json").write_text("{kaputt", encoding="utf-8")
    logger = RecordingLogger()
    jobs = ReanalysisJobs(store, ReanalysisSettings(), logger, lambda: NOW)
    assert [item.id for item in jobs.all()] == [f"{1:032x}"]
    assert [fields for (_, _, event), fields in logger.events if event == "reanalysis_job_damaged"] == [
        {"state_name": f"reanalysis-{2:032x}"}]
    assert [item.id for item in jobs.all()] == [f"{1:032x}"] and len(logger.events) == 1


def test_a_job_file_written_before_5_1_5_still_loads(store):
    stored = job(1, "completed", NOW).model_dump(mode="json")
    for field in ("actor", "adopted_at", "adoption_round", "adoption_versions", "adoption_actor", "adoption_error"):
        del stored[field]
    store.save(f"reanalysis-{1:032x}", stored)
    loaded = ReanalysisJobs(store, ReanalysisSettings(), RecordingLogger()).get(f"{1:032x}")
    assert loaded.actor is None and loaded.adoption_round is None and loaded.status == ReanalysisStatus.COMPLETED


def test_parallel_starts_for_one_mail_create_a_single_job(store):
    state = MailState(id=MAIL, config_fingerprint="f" * 64, created_at=NOW, steps=DONE_STEPS,
                      imap={"account_id": "0" * 24, "folder": "INBOX", "uidvalidity": 1, "uid": 11})
    jobs = ReanalysisJobs(store, ReanalysisSettings(), RecordingLogger(), lambda: NOW)
    barrier, results = threading.Barrier(8), []

    def click(number):
        barrier.wait()
        results.append(jobs.start(state, expected_round=1, hint=None, key=f"klick-{number}"))
    threads = [threading.Thread(target=click, args=(number,)) for number in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(jobs.all()) == 1 and sum(created for _, created in results) == 1
    assert {item.id for item, _ in results} == {jobs.all()[0].id}
