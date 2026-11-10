"""5.1 (R6): runs queued re-analysis jobs in the background, one at a time.

Each job opens its own IMAP session for the mailbox it is bound to, and only when
the mail's content has to be read again. After a restart, interrupted jobs are
recovered first; nothing runs while the service is stopped.
"""
from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager, ExitStack
from threading import Event, Thread
from typing import Any

from ..mailbox.imap import mailbox_account_id
from ..processing.reanalysis import ReanalysisJobs, ReanalysisRunner
from ..processing.reanalysis_adoption import AdoptionRefused, ReanalysisAdoption

IDLE_SECONDS = 5.0


class ReanalysisWorker:
    def __init__(self, store: Any, settings: Any, engine: Any, logger: Any,
                 open_reader: Callable[[str], AbstractContextManager[Any] | None],
                 send_proposal: Callable[[Any], None], authorized: Callable[[str], bool]):
        self.jobs = ReanalysisJobs(store, settings, logger)
        self.engine, self.open_reader, self.authorized = engine, open_reader, authorized
        self.adoption = ReanalysisAdoption(self.jobs, engine, send_proposal)
        self.stopped, self.woken = Event(), Event()
        self.thread: Thread | None = None

    def wake(self) -> None:
        self.woken.set()

    def adopt_once(self) -> bool:
        """Run the next requested adoption; the requesting session is checked again first."""
        job = self.jobs.pending_adoption()
        if job is None:
            return False
        assert job.adoption_round is not None and job.adoption_versions is not None
        assert job.adoption_actor is not None
        try:
            if not self.authorized(job.adoption_actor):
                raise AdoptionRefused("session_ended")
            self.adoption.adopt(job.id, expected_round=job.adoption_round, expected_versions=job.adoption_versions)
        except AdoptionRefused as refused:
            with self.jobs.lock:
                current = self.jobs.get(job.id)
                assert current is not None
                current.adoption_error = refused.reason
                self.jobs.save(current)
        return True

    def run_once(self) -> bool:
        """Run the next requested adoption or queued job; ``False`` when there is none."""
        if self.adopt_once():
            return True
        job = self.jobs.next_queued()
        if job is None:
            return False
        with ExitStack() as stack:
            # A job reads only its own mailbox, once; the session closes with the job.
            def reader_for(account_id: str) -> Any:
                opened = self.open_reader(account_id)
                return None if opened is None else stack.enter_context(opened)
            ReanalysisRunner(self.jobs, self.engine, reader_for, self.authorized).run(job)
        return True

    def run(self) -> None:
        while not self.stopped.is_set():
            try:
                busy = self.run_once()
            except Exception as exc:  # a damaged job file must not stop the service
                self.jobs.logger.event("ERROR", "reanalysis", "reanalysis_worker_failed",
                                       error=type(exc).__name__)
                busy = False
            if not busy:
                self.woken.wait(IDLE_SECONDS)
                self.woken.clear()

    def start(self) -> None:
        self.jobs.recover()
        self.stopped.clear()
        self.thread = Thread(target=self.run, name="mailhelp-reanalysis", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stopped.set()
        self.woken.set()
        if self.thread is not None:
            self.thread.join()


def mailbox_readers(settings: Any, secrets: Any, reader: Callable[..., Any]) -> Callable[[str], Any]:
    """An IMAP session factory per account id of the enabled mailboxes; unknown accounts get none."""
    def open_reader(account_id: str) -> Any:
        for mailbox in settings.imap.enabled_mailboxes():
            if mailbox_account_id(mailbox, secrets.imap_credentials(mailbox.id)) == account_id:
                return reader(settings, secrets, mailbox)
        return None
    return open_reader
