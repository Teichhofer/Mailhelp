"""5.1 R3: durable re-analysis jobs, bound to the original mail, bounded and restartable."""
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

import pytest

from mailhelp.config import ReanalysisSettings
from mailhelp.domain.extraction import ActionRoute, EventExtraction, ExtractedTask, TaskExtraction
from mailhelp.domain.mail import MailState
from mailhelp.domain.reanalysis import ReanalysisError, ReanalysisJob, ReanalysisStatus
from mailhelp.mailbox.imap import FetchedMail, FolderNotReadable, UIDValidityChanged
from mailhelp.processing.reanalysis import HINT_KEY, ReanalysisJobs, ReanalysisRefused, ReanalysisRunner
from mailhelp.storage import JsonStore
from tests.fakes.log_fakes import RecordingLogger
from tests.scenarios.web_scenario import mail_id, proposal

NOW = datetime(2026, 11, 10, 9, tzinfo=UTC)
MAIL = mail_id(7)
DONE = dict(preparation="completed", relevance="completed", summary="completed", action_detection="completed",
            action_router="completed", task_extraction="completed", event_extraction="skipped",
            normalization="completed", proposal_building="completed", duplicate_precheck="completed",
            completion="completed")
TASK = ExtractedTask(title="Unterlagen abgeben", description="", evidence="Bitte bis Freitag abgeben.",
                     responsibility="user", certainty="certain", classification="new")


def raw_mail():
    message = EmailMessage()
    message["From"] = "Schule <schule@example.test>"
    message["To"] = "ich@example.test"
    message["Subject"] = "Unterlagen"
    message["Date"] = "Mon, 09 Nov 2026 08:00:00 +0100"
    message["Message-ID"] = "<synthetisch@example.test>"
    message.set_content("Bitte die Unterlagen bis Freitag abgeben.")
    return message.as_bytes()


class Clock:
    def __init__(self): self.now = NOW
    def __call__(self): return self.now


class Analyzer:
    def __init__(self, route=None, fail=()):
        self.route = route or ActionRoute(action_state="task", task_count=1, event_count=0, reason="synthetisch")
        self.fail, self.calls, self.inputs = list(fail), [], []

    def _call(self, name, value, mail):
        self.calls.append(name)
        self.inputs.append(mail)
        if name in self.fail:
            self.fail.remove(name)
            raise RuntimeError("synthetischer Modellfehler")
        return f"{name}-{len(self.calls)}", value

    def action_route(self, mail):
        return self._call("route", self.route, mail)

    def extract_tasks(self, mail, *, expected_count):
        return self._call("tasks", TaskExtraction(tasks=[TASK] * expected_count), mail)

    def extract_events(self, mail, *, expected_count):
        return self._call("events", EventExtraction(events=[]), mail)


class Engine:
    max_bytes, user_timezone = 1_000_000, "Europe/Berlin"

    def __init__(self, analyzer):
        self.analyzer, self.built = analyzer, []

    def own_addresses(self, account_id):
        return frozenset({"ich@example.test"})

    def build_proposals(self, state):
        from tests.scenarios.web_scenario import proposal
        self.built.append(state)
        tasks = state.task_extraction.tasks if state.task_extraction else []
        return [proposal(7, f"neu{index}", title=task.title, evidence=task.evidence) for index, task in enumerate(tasks)]


class Reader:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, []

    def fetch_uid(self, folder, uid, expected_uidvalidity):
        self.calls.append((folder, uid, expected_uidvalidity))
        if self.error is not None:
            raise self.error
        return self.result


def mail_state(**fields):
    return MailState(id=MAIL, config_fingerprint="f" * 64, created_at=NOW - timedelta(days=1),
                     imap={"account_id": "0" * 24, "folder": "INBOX", "uidvalidity": 3, "uid": 42},
                     steps=fields.pop("steps", DONE), mail=fields.pop("mail", {"text": "Bitte die Unterlagen bis Freitag abgeben.",
                                                          "headers": {}}), **fields)


@pytest.fixture
def setup(tmp_path):
    store, clock, logger = JsonStore(tmp_path), Clock(), RecordingLogger()
    jobs = ReanalysisJobs(store, ReanalysisSettings(max_jobs_per_day=3), logger, clock)
    store.save(f"mail-{MAIL}", mail_state().model_dump(mode="json"))
    return store, jobs, clock, logger


def start(jobs, store, key="k1", hint=None, expected_round=1):
    state = store.load_model(f"mail-{MAIL}", MailState)
    return jobs.start(state, expected_round=expected_round, hint=hint, key=key)


def test_a_job_runs_all_paid_steps_once_and_never_changes_the_mail(setup):
    store, jobs, clock, logger = setup
    before = store.load(f"mail-{MAIL}")
    job, created = start(jobs, store, hint="  Bitte die Rückmeldefrist prüfen  ")
    assert created and job.status == ReanalysisStatus.QUEUED and job.hint == "Bitte die Rückmeldefrist prüfen"
    analyzer = Analyzer()
    done = ReanalysisRunner(jobs, Engine(analyzer), lambda account: None).run_next()
    assert (done.status, done.stage, done.llm_calls, done.error) == (ReanalysisStatus.COMPLETED, "done", 2, None)
    assert analyzer.calls == ["route", "tasks"] and done.call_ids == ["route-1", "tasks-2"]
    assert [item.title for item in done.proposals] == ["Unterlagen abgeben"]
    # The hint is passed as marked, untrusted input next to the mail; nothing else changes.
    assert analyzer.inputs[0][HINT_KEY] == "Bitte die Rückmeldefrist prüfen"
    assert store.load(f"mail-{MAIL}") == before
    assert jobs.get(job.id) == done and jobs.for_mail(MAIL) == [done]
    assert [event for (_, _, event), _ in logger.events] == ["reanalysis_queued", "reanalysis_finished"]
    assert ReanalysisRunner(jobs, Engine(analyzer), lambda account: None).run_next() is None


def test_repeated_and_parallel_starts_give_one_job(setup):
    store, jobs, clock, _ = setup
    first, _ = start(jobs, store, key="a")
    again, created = start(jobs, store, key="a")
    parallel, parallel_created = start(jobs, store, key="b")
    assert (again, created) == (first, False) and (parallel.id, parallel_created) == (first.id, False)
    assert len(jobs.all()) == 1
    other = mail_state().model_copy(update={"id": mail_id(8)})
    with pytest.raises(ReanalysisRefused, match="key_conflict"):
        jobs.start(other, expected_round=1, hint=None, key="a")


@pytest.mark.parametrize(("change", "reason"), [
    (dict(expected_round=2), "stale"),
])
def test_a_start_for_another_round_is_refused(setup, change, reason):
    store, jobs, _, _ = setup
    with pytest.raises(ReanalysisRefused, match=reason):
        start(jobs, store, **change)


def test_running_mails_disabled_settings_and_the_daily_limit_refuse_a_start(setup):
    store, jobs, clock, _ = setup
    store.save(f"mail-{MAIL}", mail_state(steps={**DONE, "completion": "pending"}).model_dump(mode="json"))
    with pytest.raises(ReanalysisRefused, match="processing"):
        start(jobs, store)
    store.save(f"mail-{MAIL}", mail_state().model_dump(mode="json"))
    for index in range(3):
        job, _ = start(jobs, store, key=f"tag-{index}")
        jobs.cancel(job.id)
    with pytest.raises(ReanalysisRefused, match="daily_limit"):
        start(jobs, store, key="zu-viel")
    clock.now = NOW + timedelta(days=1)
    assert start(jobs, store, key="morgen")[1] is True
    off = ReanalysisJobs(store, ReanalysisSettings(enabled=False), RecordingLogger(), clock)
    with pytest.raises(ReanalysisRefused, match="disabled"):
        start(off, store, key="aus")


def test_a_restart_continues_after_the_last_stored_step_without_repeating_paid_calls(setup):
    store, jobs, _, logger = setup
    job, _ = start(jobs, store)
    analyzer = Analyzer(fail=["tasks"])
    runner = ReanalysisRunner(jobs, Engine(analyzer), lambda account: None)
    retried = runner.run(job)
    assert (retried.status, retried.stage, retried.attempts, retried.llm_calls) == (
        ReanalysisStatus.QUEUED, "tasks", 1, 2)
    # A crash while the next call runs leaves the job "running"; recovery counts the attempt.
    crashed = jobs.get(job.id).model_copy(update={"status": ReanalysisStatus.RUNNING})
    jobs.save(crashed)
    assert jobs.recover() == 1
    failed = jobs.get(job.id)
    assert (failed.status, failed.error) == (ReanalysisStatus.FAILED, ReanalysisError.MODEL_FAILED)
    assert analyzer.calls == ["route", "tasks"]
    assert jobs.recover() == 0


def test_a_recovered_job_resumes_at_its_stage(setup):
    store, jobs, _, _ = setup
    jobs.settings = ReanalysisSettings(max_attempts=3)
    job, _ = start(jobs, store)
    analyzer = Analyzer()
    stored = job.model_copy(update={"status": ReanalysisStatus.RUNNING, "stage": "tasks", "llm_calls": 1,
                                    "action_route": analyzer.route, "call_ids": ["route-0"]})
    jobs.save(stored)
    jobs.recover()
    done = ReanalysisRunner(jobs, Engine(analyzer), lambda account: None).run_next()
    assert done.status == ReanalysisStatus.COMPLETED and analyzer.calls == ["tasks"] and done.llm_calls == 2


def test_the_call_budget_ends_a_job_instead_of_looping(setup):
    store, jobs, _, _ = setup
    jobs.settings = ReanalysisSettings(max_llm_calls_per_job=1, max_attempts=5)
    job, _ = start(jobs, store)
    analyzer = Analyzer(fail=["route"])
    runner = ReanalysisRunner(jobs, Engine(analyzer), lambda account: None)
    assert runner.run(job).status == ReanalysisStatus.QUEUED
    failed = runner.run_next()
    assert (failed.status, failed.error, failed.llm_calls) == (
        ReanalysisStatus.FAILED, ReanalysisError.BUDGET_EXHAUSTED, 1)
    assert analyzer.calls == ["route"]


def test_no_action_needs_no_extraction_and_events_are_extracted_when_counted(setup):
    store, jobs, _, _ = setup
    none = Analyzer(route=ActionRoute(action_state="none", task_count=0, event_count=0, reason="x"))
    done = ReanalysisRunner(jobs, Engine(none), lambda account: None).run(start(jobs, store)[0])
    assert none.calls == ["route"] and done.proposals == [] and done.llm_calls == 1
    store.save(f"mail-{MAIL}", mail_state(analysis_round=2).model_dump(mode="json"))
    events = Analyzer(route=ActionRoute(action_state="event", task_count=0, event_count=1, reason="x"))
    job, _ = start(jobs, store, key="k2", expected_round=2)
    assert ReanalysisRunner(jobs, Engine(events), lambda account: None).run(job).status == ReanalysisStatus.COMPLETED
    assert events.calls == ["route", "events"]


def test_removed_content_is_read_again_only_through_the_bound_identity(setup):
    store, jobs, _, _ = setup
    store.save(f"mail-{MAIL}", mail_state(mail=None).model_dump(mode="json"))
    reader = Reader(FetchedMail("INBOX", 3, 42, raw_mail(), "0" * 24, NOW - timedelta(days=1)))
    analyzer = Analyzer()
    done = ReanalysisRunner(jobs, Engine(analyzer), {"0" * 24: reader}.get).run(start(jobs, store)[0])
    assert done.status == ReanalysisStatus.COMPLETED and reader.calls == [("INBOX", 42, 3)]
    assert "Unterlagen bis Freitag" in analyzer.inputs[0]["text"]
    # The original receive time is kept, so relative dates refer to the mail, not to today.
    assert analyzer.inputs[0]["imap_received_at"].startswith("2026-11-09")
    assert store.load_model(f"mail-{MAIL}", MailState).mail is None


@pytest.mark.parametrize(("reader", "error"), [
    (None, ReanalysisError.MAILBOX_UNAVAILABLE),
    (Reader(error=UIDValidityChanged("INBOX", 3, 4)), ReanalysisError.UIDVALIDITY_CHANGED),
    (Reader(error=FolderNotReadable("INBOX")), ReanalysisError.MAILBOX_UNAVAILABLE),
    (Reader(FetchedMail("INBOX", 3, 42, b"", "0" * 24)), ReanalysisError.MAIL_MISSING),
])
def test_an_unreachable_original_ends_with_an_explained_error(setup, reader, error):
    store, jobs, _, _ = setup
    store.save(f"mail-{MAIL}", mail_state(mail=None).model_dump(mode="json"))
    analyzer = Analyzer()
    done = ReanalysisRunner(jobs, Engine(analyzer), lambda account: reader).run(start(jobs, store)[0])
    assert (done.status, done.error) == (ReanalysisStatus.FAILED, error) and analyzer.calls == []


def test_a_fetch_error_is_retried_and_then_reported_as_missing(setup):
    store, jobs, _, logger = setup
    store.save(f"mail-{MAIL}", mail_state(mail=None).model_dump(mode="json"))
    reader = Reader(error=RuntimeError("IMAP-Abruf fehlgeschlagen: UID 42"))
    runner = ReanalysisRunner(jobs, Engine(Analyzer()), lambda account: reader)
    job, _ = start(jobs, store)
    assert runner.run(job).status == ReanalysisStatus.QUEUED
    done = runner.run_next()
    assert (done.status, done.error, done.attempts) == (ReanalysisStatus.FAILED, ReanalysisError.MAIL_MISSING, 2)
    warnings = [fields for (level, _, event), fields in logger.events if event == "reanalysis_attempt_failed"]
    assert warnings[0]["error"] == "RuntimeError" and "UID" not in str(warnings)


def test_a_newer_round_or_a_deleted_mail_makes_the_job_stale(setup):
    store, jobs, _, _ = setup
    job, _ = start(jobs, store)
    store.save(f"mail-{MAIL}", mail_state(analysis_round=2).model_dump(mode="json"))
    runner = ReanalysisRunner(jobs, Engine(Analyzer()), lambda account: None)
    assert runner.run(job).error == ReanalysisError.STALE_ROUND
    second, _ = start(jobs, store, key="k2", expected_round=2)
    store.delete(f"mail-{MAIL}")
    assert runner.run(second).error == ReanalysisError.MAIL_MISSING


def test_a_cancelled_job_is_not_run_and_a_late_result_is_discarded(setup):
    store, jobs, _, _ = setup
    job, _ = start(jobs, store)
    assert jobs.cancel(job.id).status == ReanalysisStatus.CANCELLED
    assert jobs.cancel(job.id).status == ReanalysisStatus.CANCELLED and jobs.cancel("0" * 32) is None
    analyzer = Analyzer()
    assert ReanalysisRunner(jobs, Engine(analyzer), lambda account: None).run(job).status == ReanalysisStatus.CANCELLED
    assert analyzer.calls == []
    # Cancelled while a call runs: the result arriving afterwards does not complete the job.
    second, _ = start(jobs, store, key="k2")

    class Cancelling(Analyzer):
        def action_route(inner, mail):
            jobs.cancel(second.id)
            return super().action_route(mail)
    late = ReanalysisRunner(jobs, Engine(Cancelling(route=ActionRoute(
        action_state="none", task_count=0, event_count=0, reason="x"))), lambda account: None).run(second)
    assert late.status == ReanalysisStatus.CANCELLED and jobs.get(second.id).proposals == []


def test_the_job_file_is_readable_json_and_rejects_inconsistent_states(setup):
    store, jobs, _, _ = setup
    job, _ = start(jobs, store)
    stored = store.load(f"reanalysis-{job.id}")
    assert stored["status"] == "queued" and stored["imap"]["uidvalidity"] == 3 and "mail" not in stored
    for broken in ({"status": "failed"}, {"status": "completed"}, {"llm_calls": 9},
                   {"created_at": "2026-11-10T09:00:00"},
                   {"proposals": [proposal(8, "fremd").model_dump(mode="json")]}):
        with pytest.raises(ValueError):
            ReanalysisJob.model_validate({**stored, **broken})


def test_a_job_interrupted_after_its_last_call_only_builds_the_proposals(setup):
    store, jobs, _, _ = setup
    job, _ = start(jobs, store)
    analyzer = Analyzer()
    stored = job.model_copy(update={"stage": "build", "llm_calls": 2, "action_route": analyzer.route,
                                    "task_extraction": TaskExtraction(tasks=[TASK])})
    jobs.save(stored)
    done = ReanalysisRunner(jobs, Engine(analyzer), lambda account: None).run(stored)
    assert done.status == ReanalysisStatus.COMPLETED and analyzer.calls == [] and len(done.proposals) == 1


def test_a_cancellation_while_proposals_are_built_wins(setup):
    store, jobs, _, _ = setup
    job, _ = start(jobs, store)

    class Cancelling(Engine):
        def build_proposals(inner, state):
            jobs.cancel(job.id)
            return super().build_proposals(state)
    done = ReanalysisRunner(jobs, Cancelling(Analyzer()), lambda account: None).run(job)
    assert done.status == ReanalysisStatus.CANCELLED and jobs.get(job.id).proposals == []
