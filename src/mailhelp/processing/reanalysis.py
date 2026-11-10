"""5.1 (R3): durable re-analysis jobs and their bounded, restartable execution.

A job reads the mail again only through its bound mailbox identity; another mail
with the same subject is never a substitute. Every paid call is counted before it
is made, so a crash cannot hide a spent call, and each result is stored before the
next step starts, so a restart never repeats a finished call. A job never changes
the mail state and never writes to a calendar or task list.
"""
from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from .. import state_names
from ..config import ReanalysisSettings
from ..domain.mail import MailState
from ..domain.reanalysis import ACTIVE, ReanalysisError, ReanalysisJob, ReanalysisStatus
from ..mailbox.imap import FetchedMail, FolderNotReadable, UIDValidityChanged
from ..mailbox.mime import prepare
from .perspective import Perspective, read_perspective

PREFIX = "reanalysis-"
HINT_KEY = "user_review_hint"


class ReanalysisRefused(ValueError):
    """A start that is not possible now; ``reason`` names why for the user."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class _Cancelled(Exception):
    """The job was cancelled while it ran; nothing more is stored."""


class _Failed(Exception):
    def __init__(self, error: ReanalysisError):
        super().__init__(str(error))
        self.error = error


class Reader(Protocol):
    def fetch_uid(self, folder: str, uid: int, expected_uidvalidity: int) -> FetchedMail: ...


class Engine(Protocol):
    """The parts of the orchestrator a re-analysis uses: analyzer, preparation and proposal building."""

    analyzer: Any
    max_bytes: int
    user_timezone: str

    def own_addresses(self, account_id: str) -> frozenset[str]: ...

    def build_proposals(self, state: MailState) -> list[Any]: ...


def key_hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


class ReanalysisJobs:
    """The durable jobs; at most one active job per mail and analysis round."""

    def __init__(self, store: Any, settings: ReanalysisSettings, logger: Any,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self.store, self.settings, self.logger, self.clock = store, settings, logger, clock
        self.lock = threading.Lock()

    def all(self) -> list[ReanalysisJob]:
        jobs = [self.store.load_model(name, ReanalysisJob) for name in self.store.names(PREFIX)]
        return sorted((job for job in jobs if isinstance(job, ReanalysisJob)), key=lambda job: job.created_at)

    def for_mail(self, mail_id: str) -> list[ReanalysisJob]:
        return [job for job in self.all() if job.mail_id == mail_id]

    def get(self, job_id: str) -> ReanalysisJob | None:
        job = self.store.load_model(PREFIX + job_id, ReanalysisJob)
        return job if isinstance(job, ReanalysisJob) else None

    def save(self, job: ReanalysisJob) -> None:
        job.updated_at = max(self.clock(), job.updated_at)
        self.store.save(PREFIX + job.id, job.model_dump(mode="json"))

    def start(self, state: MailState, *, expected_round: int, hint: str | None,
              key: str) -> tuple[ReanalysisJob, bool]:
        """A job for *state*; repeating the request returns the same job instead of a second one."""
        if not self.settings.enabled:
            raise ReanalysisRefused("disabled")
        digest = key_hash(key)
        with self.lock:
            jobs = self.all()
            known = next((job for job in jobs if job.key_hash == digest), None)
            if known is not None:
                if known.mail_id != state.id:
                    raise ReanalysisRefused("key_conflict")
                return known, False
            if expected_round != state.analysis_round:
                raise ReanalysisRefused("stale")
            if state.steps.completion != "completed":
                raise ReanalysisRefused("processing")
            active = next((job for job in jobs if job.mail_id == state.id and job.status in ACTIVE
                           and job.source_round == state.analysis_round), None)
            if active is not None:
                return active, False
            now = self.clock()
            if sum(job.created_at.date() == now.date() for job in jobs) >= self.settings.max_jobs_per_day:
                raise ReanalysisRefused("daily_limit")
            job = ReanalysisJob(id=digest[:32], mail_id=state.id, source_round=state.analysis_round,
                                config_fingerprint=state.config_fingerprint, imap=state.imap,
                                hint=(hint or "").strip()[:500] or None, key_hash=digest,
                                max_attempts=self.settings.max_attempts,
                                max_llm_calls=self.settings.max_llm_calls_per_job, created_at=now, updated_at=now)
            self.save(job)
        self.logger.event("INFO", "reanalysis", "reanalysis_queued", job_id=job.id, mail_id=job.mail_id,
                          round=job.source_round)
        return job, True

    def cancel(self, job_id: str) -> ReanalysisJob | None:
        with self.lock:
            job = self.get(job_id)
            if job is None or job.status not in ACTIVE:
                return job
            job.status = ReanalysisStatus.CANCELLED
            self.save(job)
        self.logger.event("INFO", "reanalysis", "reanalysis_cancelled", job_id=job.id, mail_id=job.mail_id)
        return job

    def recover(self) -> int:
        """After a restart: an interrupted job counts one attempt and is queued again."""
        recovered = 0
        with self.lock:
            for job in self.all():
                if job.status != ReanalysisStatus.RUNNING:
                    continue
                job.attempts += 1
                job.status = ReanalysisStatus.QUEUED
                if job.attempts >= job.max_attempts:
                    job.status, job.error = ReanalysisStatus.FAILED, ReanalysisError.MODEL_FAILED
                self.save(job)
                recovered += 1
        if recovered:
            self.logger.event("INFO", "reanalysis", "reanalysis_recovered", jobs=recovered)
        return recovered

    def next_queued(self) -> ReanalysisJob | None:
        return next((job for job in self.all() if job.status == ReanalysisStatus.QUEUED), None)


class ReanalysisRunner:
    """Executes queued jobs step by step within their call budget and attempt limit."""

    def __init__(self, jobs: ReanalysisJobs, engine: Engine, reader_for: Callable[[str], Reader | None]):
        self.jobs, self.engine, self.reader_for = jobs, engine, reader_for

    def run_next(self) -> ReanalysisJob | None:
        job = self.jobs.next_queued()
        return None if job is None else self.run(job)

    def run(self, job: ReanalysisJob) -> ReanalysisJob:
        with self.jobs.lock:
            current = self.jobs.get(job.id)
            if current is None or current.status != ReanalysisStatus.QUEUED:
                return current or job
            job = current
            job.status = ReanalysisStatus.RUNNING
            self.jobs.save(job)
        try:
            state = self._source(job)
            self._steps(job, state)
        except _Cancelled:
            return self.jobs.get(job.id) or job
        except _Failed as failure:
            return self._finish(job, ReanalysisStatus.FAILED, failure.error)
        except Exception as exc:
            return self._retry(job, exc)
        return self._finish(job, ReanalysisStatus.COMPLETED, None)

    def _source(self, job: ReanalysisJob) -> MailState:
        """The mail of the job with content: retained, or read again through its bound identity."""
        state = self.jobs.store.load_model(state_names.mail(job.mail_id), MailState)
        if not isinstance(state, MailState):
            raise _Failed(ReanalysisError.MAIL_MISSING)
        if state.analysis_round != job.source_round:
            raise _Failed(ReanalysisError.STALE_ROUND)
        if state.mail is not None:
            return state
        reader = self.reader_for(job.imap.account_id)
        if reader is None:
            raise _Failed(ReanalysisError.MAILBOX_UNAVAILABLE)
        try:
            fetched = reader.fetch_uid(job.imap.folder, job.imap.uid, job.imap.uidvalidity)
        except UIDValidityChanged:
            raise _Failed(ReanalysisError.UIDVALIDITY_CHANGED) from None
        except FolderNotReadable:
            raise _Failed(ReanalysisError.MAILBOX_UNAVAILABLE) from None
        if not fetched.raw:
            raise _Failed(ReanalysisError.MAIL_MISSING)
        # The original receive time keeps relative dates bound to the mail, not to today.
        mail = prepare(fetched.raw, self.engine.max_bytes, fetched.received_at, self.engine.user_timezone)
        mail["internal_id"] = state.id
        seen = read_perspective(mail, self.engine.own_addresses(job.imap.account_id))
        return state.model_copy(update={"mail": mail, "self_mail": seen.self_mail, "user_note": seen.user_note,
                                        "is_forwarding": seen.is_forwarding,
                                        "forwarded_headers": seen.forwarded_headers})

    def _content(self, job: ReanalysisJob, state: MailState) -> dict[str, Any]:
        assert state.mail is not None
        content = Perspective(state.self_mail, state.user_note, state.is_forwarding,
                              state.forwarded_headers).model_input(state.mail)
        return {**content, HINT_KEY: job.hint} if job.hint else content

    def _progress(self, job: ReanalysisJob) -> None:
        """Store an intermediate state unless the job was cancelled meanwhile."""
        with self.jobs.lock:
            current = self.jobs.get(job.id)
            if current is not None and current.status == ReanalysisStatus.CANCELLED:
                raise _Cancelled()
            self.jobs.save(job)

    def _paid(self, job: ReanalysisJob, call: Callable[[], tuple[str, Any]]) -> Any:
        """One counted model call; the count is saved before the call is made."""
        if job.llm_calls >= job.max_llm_calls:
            raise _Failed(ReanalysisError.BUDGET_EXHAUSTED)
        job.llm_calls += 1
        self._progress(job)
        call_id, result = call()
        job.call_ids.append(call_id)
        return result

    def _steps(self, job: ReanalysisJob, state: MailState) -> None:
        analyzer = self.engine.analyzer
        content = self._content(job, state)
        if job.stage == "route":
            job.action_route = self._paid(job, lambda: analyzer.action_route(content))
            job.stage = "tasks"
            self._progress(job)
        route = job.action_route
        assert route is not None
        if job.stage == "tasks":
            if route.action_state in {"task", "task_and_event"} or route.task_count > 0:
                job.task_extraction = self._paid(
                    job, lambda: analyzer.extract_tasks(content, expected_count=route.task_count))
            job.stage = "events"
            self._progress(job)
        if job.stage == "events":
            if route.action_state in {"event", "task_and_event"} or route.event_count > 0:
                job.event_extraction = self._paid(
                    job, lambda: analyzer.extract_events(content, expected_count=route.event_count))
            job.stage = "build"
            self._progress(job)
        candidate = state.model_copy(update={"action_route": route, "task_extraction": job.task_extraction,
                                             "event_extraction": job.event_extraction,
                                             "extraction_count_conflicts": []})
        job.proposals = list(self.engine.build_proposals(candidate))
        job.stage = "done"

    def _retry(self, job: ReanalysisJob, exc: Exception) -> ReanalysisJob:
        job.attempts += 1
        self.jobs.logger.event("WARNING", "reanalysis", "reanalysis_attempt_failed", job_id=job.id,
                               mail_id=job.mail_id, stage=job.stage, error=type(exc).__name__)
        if job.attempts >= job.max_attempts:
            error = ReanalysisError.MODEL_FAILED if job.llm_calls else ReanalysisError.MAIL_MISSING
            return self._finish(job, ReanalysisStatus.FAILED, error)
        with self.jobs.lock:
            job.status = ReanalysisStatus.QUEUED
            self.jobs.save(job)
        return job

    def _finish(self, job: ReanalysisJob, status: ReanalysisStatus,
                error: ReanalysisError | None) -> ReanalysisJob:
        with self.jobs.lock:
            current = self.jobs.get(job.id)
            if current is not None and current.status == ReanalysisStatus.CANCELLED:
                return current  # cancelled while running: the late result is discarded
            job.status, job.error = status, error
            self.jobs.save(job)
        self.jobs.logger.event("INFO" if error is None else "WARNING", "reanalysis", "reanalysis_finished",
                               job_id=job.id, mail_id=job.mail_id, status=status.value,
                               error=error.value if error else None, llm_calls=job.llm_calls)
        return job
