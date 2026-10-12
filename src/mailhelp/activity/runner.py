"""Background run of activity reports: counting, reading, judging and extracting dates.

At most one report reads the mailbox at a time.  Network and model calls never
run under the service lock; every result is stored per mail, so a restart
repeats at most the one call that was in flight.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from threading import Event, Thread
from typing import Any

from ..imap import FolderNotReadable
from ..logging import log_and_continue
from ..openrouter import RateLimitExceeded
from .llm import ActivityAnalyzer
from .models import ActivityReport, FolderProgress, ReportMail, ReportStatus
from .scan import default_folders, list_folder, period, read_mail, received_day, sent_folders
from .service import ActivityService

BATCH = 25
MAX_FAILURES = 3


class ActivityRunner:
    def __init__(self, service: ActivityService, analyzer: ActivityAnalyzer,
                 open_reader: Callable[[], AbstractContextManager[Any]], settings: Any, logger: Any,
                 llm_calls_per_minute: Callable[[], int] = lambda: 60,
                 clock: Callable[[], float] = time.monotonic):
        self.service, self.analyzer, self.open_reader = service, analyzer, open_reader
        self.settings, self.logger = settings, logger
        self.llm_calls_per_minute, self.clock = llm_calls_per_minute, clock
        self.stop_event = Event()
        self.thread: Thread | None = None
        self._calls: list[float] = []
        self._failures = 0

    # --- lifecycle -------------------------------------------------------------------

    def recover(self) -> None:
        """A report that was reading when Mailhelp stopped waits for the user again."""
        with self.service.lock:
            for report in self.service.store.reports():
                if report.status == ReportStatus.RUNNING:
                    report.status = ReportStatus.PAUSED
                    report.message = "Nach einem Neustart pausiert. Fortsetzen setzt an der letzten Mail an."
                    self.service.store.save(report)

    def start(self) -> None:
        self.recover()
        self.thread = Thread(target=self.run, name="mailhelp-activity", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=15)

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                worked = self.tick()
            except Exception as exc:
                log_and_continue(self.logger, "activity", "background_failed", exc)
                worked = False
            if not worked:
                self.stop_event.wait(5)

    def tick(self) -> bool:
        """One unit of work; ``False`` when nothing is to be done."""
        reports = self.service.store.reports()
        for report in reports:
            if report.status == ReportStatus.COUNTING:
                self.count(report.id)
                return True
        for report in reports:
            if report.status == ReportStatus.RUNNING:
                self.process(report.id)
                return True
        for report in reports:
            if report.pending_extractions:
                self.extract_requested(report.id)
                return True
        return False

    # --- counting --------------------------------------------------------------------

    def count(self, report_id: str) -> None:
        """List the mail identities of the period; no content is read."""
        report = self.service.store.load(report_id)
        assert report is not None
        start, end = period(report, self.settings.timezone)
        progress, missing = [], []
        with self.open_reader() as reader:
            listed = reader.list_folders()
            folders = [(folder, False) for folder in report.definition.folders]
            if report.definition.include_sent:
                folders += [(folder, True) for folder in sent_folders(listed)
                            if folder not in report.definition.folders]
            for folder, sent in folders:
                try:
                    progress.append(list_folder(reader, folder, sent, start, end))
                except FolderNotReadable:
                    missing.append(folder)
        with self.service.lock:
            current = self.service.store.load(report_id)
            if current is None or current.status != ReportStatus.COUNTING:
                return
            current.folders = progress
            current.counters.listed = current.total
            current.status = ReportStatus.READY
            current.message = (f"Nicht lesbar und übersprungen: {', '.join(missing)}." if missing else "")
            self.service.store.save(current)

    # --- reading -----------------------------------------------------------------------

    def _next(self, report: ActivityReport) -> tuple[FolderProgress, int] | None:
        for progress in report.folders:
            if progress.done < len(progress.uids):
                return progress, progress.uids[progress.done]
        return None

    def _limit_reached(self, report: ActivityReport) -> str | None:
        limits = self.settings.activity_report
        if report.counters.read >= limits.max_mails:
            return f"Höchstzahl von {limits.max_mails} Mails erreicht; Fortsetzen erhöht sie nicht."
        if report.counters.llm_calls >= limits.max_llm_calls:
            return f"Höchstzahl von {limits.max_llm_calls} KI-Aufrufen erreicht."
        return None

    def _settle(self, report_id: str, update: Callable[[ActivityReport], None]) -> ActivityReport | None:
        with self.service.lock:
            report = self.service.store.load(report_id)
            if report is None:
                return None
            update(report)
            self.service.store.save(report)
            return report

    def process(self, report_id: str) -> None:
        """Read and judge up to one batch of mail with one IMAP connection."""
        with self.open_reader() as reader:
            for _ in range(BATCH):
                if self.stop_event.is_set() or not self._process_one(report_id, reader):
                    return

    def _process_one(self, report_id: str, reader: Any) -> bool:
        report = self.service.store.load(report_id)
        if report is None or report.status != ReportStatus.RUNNING:
            return False
        reason = self._limit_reached(report)
        following = self._next(report)
        if reason is not None or following is None:
            def finish(current: ActivityReport) -> None:
                if current.status == ReportStatus.RUNNING:
                    current.status = ReportStatus.PAUSED if reason else ReportStatus.DONE
                    current.message = reason or ""
                    current.finished_at = None if reason else datetime.now(UTC)
            self._settle(report_id, finish)
            return False
        progress, uid = following
        try:
            fetched = reader.fetch_uid(progress.folder, uid, progress.uidvalidity)
        except Exception as exc:
            return self._fetch_failed(report_id, progress, exc)
        self._failures = 0
        mail = self._judge(report, progress, fetched)
        self._record(report_id, progress.folder, mail)
        return True

    def _fetch_failed(self, report_id: str, progress: FolderProgress, exc: Exception) -> bool:
        """A failing mailbox stops the batch; after repeated failures the report fails."""
        self._failures += 1
        log_and_continue(self.logger, "activity", "fetch_failed", exc)
        if self._failures >= MAX_FAILURES:
            def fail(current: ActivityReport) -> None:
                current.status = ReportStatus.FAILED
                current.message = ("Das Postfach war wiederholt nicht lesbar "
                                   f"({type(exc).__name__}); Ordner {progress.folder}.")
            self._settle(report_id, fail)
            self._failures = 0
        return False

    def _judge(self, report: ActivityReport, progress: FolderProgress, fetched: Any) -> ReportMail:
        """Prepare one mail and ask the model, reusing every result already stored."""
        stored = self.service.store.mail(report.id, f"{progress.folder}:{progress.uidvalidity}:{fetched.uid}")
        if stored is not None and stored.relevant is not None:
            mail = stored
        else:
            mail, prepared = read_mail(report, progress, fetched, self.settings.limits, self.settings.timezone,
                                       self.settings.activity_report.max_fulltext_chars)
            if mail.skipped is None and mail.message_id and any(
                    other.message_id == mail.message_id and other.key != mail.key and other.skipped is None
                    for other in self.service.store.mails(report.id)):
                mail.skipped, mail.text = "duplicate", ""
            if mail.skipped is None and self.analyzer.suspicious(mail):
                mail.skipped, mail.text = "suspicious", ""
            if mail.skipped is not None:
                return mail
            call, verdict = self._call(lambda: self.analyzer.relevance(
                report, mail, received_day(mail, self.settings.timezone)))
            mail.relevant, mail.confidence, mail.reason = verdict.relevant, verdict.confidence, verdict.reason
            mail.relevance_call_id = call
            # Durable before the second call: a restart repeats only the date extraction.
            self._record_partial(report.id, mail)
        if mail.relevant and not mail.events_extracted:
            self._extract(report, mail)
        return mail

    def _extract(self, report: ActivityReport, mail: ReportMail) -> None:
        call, events = self._call(lambda: self.analyzer.events(
            report, mail, received_day(mail, self.settings.timezone), self.logger))
        mail.events, mail.events_call_id, mail.events_extracted = events, call, True

    def _record_partial(self, report_id: str, mail: ReportMail) -> None:
        def count(report: ActivityReport) -> None:
            report.counters.llm_calls += 1
            self.service.store.save_mail(report_id, mail)
        self._settle(report_id, count)

    def _record(self, report_id: str, folder: str, mail: ReportMail) -> None:
        def advance(report: ActivityReport) -> None:
            # The run is the only writer of progress; the mail is the folder's next one.
            progress = next(item for item in report.folders if item.folder == folder)
            progress.done += 1
            counters = report.counters
            counters.read += 1
            if mail.skipped == "sender":
                counters.skipped_sender += 1
            elif mail.skipped == "duplicate":
                counters.duplicates += 1
            elif mail.skipped is not None:
                counters.skipped_other += 1
            else:
                counters.evaluated += 1
            if mail.relevant:
                counters.relevant += 1
                counters.events += len(mail.events)
                counters.llm_calls += 1
            self.service.store.save_mail(report_id, mail)
        self._settle(report_id, advance)

    # --- dates on request ----------------------------------------------------------------

    def extract_requested(self, report_id: str) -> None:
        """Extract the dates of a mail the user marked relevant after the model's 'no'."""
        report = self.service.store.load(report_id)
        assert report is not None and report.pending_extractions
        key = report.pending_extractions[0]
        mail = self.service.store.mail(report_id, key)
        if mail is not None and not mail.events_extracted and not mail.text_removed:
            self._extract(report, mail)

        def done(current: ActivityReport) -> None:
            current.pending_extractions = [item for item in current.pending_extractions if item != key]
            if mail is not None and mail.events_extracted:
                current.counters.llm_calls += 1
                current.counters.events += len(mail.events)
                self.service.store.save_mail(report_id, mail)
        self._settle(report_id, done)

    # --- language-model budget -----------------------------------------------------------

    def _wait_for_budget(self) -> None:
        """Use at most the configured share of the per-minute budget."""
        share = self.settings.activity_report.max_share_of_llm_budget
        allowed = max(1, int(self.llm_calls_per_minute() * share))
        while True:
            now = self.clock()
            self._calls = [stamp for stamp in self._calls if now - stamp < 60]
            if len(self._calls) < allowed or self.stop_event.is_set():
                self._calls.append(now)
                return
            self.stop_event.wait(min(5.0, 60 - (now - self._calls[0])))

    def _call(self, call: Callable[[], Any]) -> Any:
        """Wait for the report's budget share; the shared budget defers, it never fails a mail."""
        while True:
            self._wait_for_budget()
            try:
                return call()
            except RateLimitExceeded as exc:
                self.stop_event.wait(max(1.0, min(60.0, exc.next_allowed_at - time.time())))
                if self.stop_event.is_set():
                    raise


def default_report_folders(open_reader: Callable[[], AbstractContextManager[Any]],
                           configured: list[str]) -> list[str]:
    """The configured folders a new report suggests, read from the server's roles."""
    with open_reader() as reader:
        return default_folders(reader.list_folders(), configured)


__all__ = ["BATCH", "MAX_FAILURES", "ActivityRunner", "default_report_folders"]
