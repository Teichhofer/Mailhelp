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

from ..analysis import TechnicalRevisionError
from ..imap import FolderNotReadable, UIDValidityChanged
from ..logging import log_and_continue
from .budget import ReportCalls, ReportPaused
from .llm import ActivityAnalyzer
from .models import ActivityReport, FolderProgress, ReportMail, ReportStatus
from .scan import default_folders, list_folder, period, read_mail, received_day, sent_folders
from .service import ActivityService

BATCH = 25
MAX_FAILURES = 3


class ActivityRunner:
    def __init__(self, service: ActivityService, analyzer: ActivityAnalyzer,
                 open_reader: Callable[[int], AbstractContextManager[Any]], settings: Any, logger: Any,
                 llm_calls_per_minute: Callable[[], int] = lambda: 60,
                 clock: Callable[[], float] = time.monotonic):
        self.service, self.analyzer, self.open_reader = service, analyzer, open_reader
        self.settings, self.logger = settings, logger
        self.llm_calls_per_minute, self.clock = llm_calls_per_minute, clock
        self.stop_event = Event()
        self.thread: Thread | None = None
        self.calls = ReportCalls(service, analyzer.client, self.stop_event, lambda: self.settings,
                                 llm_calls_per_minute, clock)
        self._failures = 0
        self._model_failures = 0

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
        reports = list(reversed(self.service.store.reports()))
        for report in reports:
            if report.status == ReportStatus.COUNTING:
                try:
                    self.count(report.id)
                except Exception as exc:
                    log_and_continue(self.logger, "activity", "count_failed", exc)
                    error_name = type(exc).__name__
                    def failed(current: ActivityReport, error_name: str = error_name) -> None:
                        if current.status == ReportStatus.COUNTING:
                            current.counting_failures += 1
                            if current.counting_failures >= MAX_FAILURES:
                                current.status = ReportStatus.FAILED
                                current.message = f"Postfach wiederholt nicht lesbar ({error_name})."
                                current.finished_at = datetime.now(UTC)
                    self._settle(report.id, failed)
                return True
        for report in reports:
            if report.status == ReportStatus.RUNNING:
                self.process(report.id, report.definition.mailbox)
                return True
        for report in reports:
            if report.pending_extractions and report.status not in {ReportStatus.PAUSED, ReportStatus.CANCELLED}:
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
        with self.open_reader(report.definition.mailbox) as reader:
            listed = reader.list_folders()
            sent_names = sent_folders(listed)
            folders = [(folder, folder in sent_names) for folder in report.definition.folders]
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
            current.counting_failures = 0
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

    def process(self, report_id: str, mailbox: int) -> None:
        """Read and judge up to one batch of mail with one IMAP connection to the report's mailbox."""
        with self.open_reader(mailbox) as reader:
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
            cached = self.service.store.mail(report_id, f"{progress.folder}:{progress.uidvalidity}:{uid}")
            fetched = (cached if cached is not None and cached.cached_input
                       else reader.fetch_uid(progress.folder, uid, progress.uidvalidity))
        except UIDValidityChanged:
            start, end = period(report, self.settings.timezone)
            renewed = list_folder(reader, progress.folder, progress.sent, start, end)
            def renew(current: ActivityReport) -> None:
                current.folders = [renewed if item.folder == progress.folder else item for item in current.folders]
                current.counters.listed = current.total
            self._settle(report_id, renew)
            return False
        except Exception as exc:
            return self._fetch_failed(report_id, progress, exc)
        self._failures = 0
        try:
            mail = self._judge(report, progress, fetched)
        except ReportPaused:
            return False
        except Exception as exc:
            return self._model_unavailable(report_id, exc)
        self._model_failures = 0
        self._record(report_id, progress.folder, mail)
        return True

    def _model_unavailable(self, report_id: str, exc: Exception) -> bool:
        """An unreachable model stops the batch; after repeated failures the report pauses."""
        self._model_failures += 1
        log_and_continue(self.logger, "activity", "model_unavailable", exc)
        if self._model_failures >= MAX_FAILURES:
            def pause(current: ActivityReport) -> None:
                if current.status == ReportStatus.RUNNING:
                    current.status = ReportStatus.PAUSED
                    current.message = (f"Der KI-Dienst war wiederholt nicht erreichbar ({type(exc).__name__}). "
                                       "Fortsetzen versucht die Mail erneut.")
            self._settle(report_id, pause)
            self._model_failures = 0
        return False

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
            if stored is not None and stored.cached_input:
                mail = stored
            else:
                mail, _prepared = read_mail(report, progress, fetched, self.settings.limits, self.settings.timezone,
                                            self.settings.activity_report.max_fulltext_chars)
            with self.service.lock:
                mail = self.service.store.reidentify(report.id, mail)
            if mail.relevant is not None or mail.failed_step is not None:
                if mail.relevant and not mail.events_extracted:
                    self._extract(report, mail)
                return mail
            if mail.skipped is None and mail.message_id and any(
                    other.message_id == mail.message_id and other.key != mail.key and other.skipped is None
                    for other in self.service.store.mails(report.id)):
                mail.skipped, mail.text = "duplicate", ""
            if mail.skipped is None and self.analyzer.suspicious(mail):
                mail.skipped, mail.text = "suspicious", ""
            if mail.skipped is not None:
                return mail
            try:
                call, verdict = self.calls.call(lambda: self.analyzer.relevance(
                    report, mail, received_day(mail, self.settings.timezone)), report.id)
            except TechnicalRevisionError as exc:
                log_and_continue(self.logger, "activity", "model_answer_unusable", exc)
                mail.failed_step = "relevance"
                return mail
            mail.relevant, mail.confidence, mail.reason = verdict.relevant, verdict.confidence, verdict.reason
            mail.relevance_call_id = call
            # Durable before the second call: a restart repeats only the date extraction.
            self._record_partial(report.id, mail)
        if mail.relevant and not mail.events_extracted:
            self._extract(report, mail)
        return mail

    def _extract(self, report: ActivityReport, mail: ReportMail) -> None:
        try:
            call, events = self.calls.call(lambda: self.analyzer.events(
                report, mail, received_day(mail, self.settings.timezone), self.logger), report.id)
        except TechnicalRevisionError as exc:
            # The user adds the dates by hand; a repetition would cost again.
            log_and_continue(self.logger, "activity", "model_answer_unusable", exc)
            mail.failed_step, mail.events_extracted = "events", True
            return
        mail.events, mail.events_call_id, mail.events_extracted = events, call, True
        mail.failed_step = None

    def _record_partial(self, report_id: str, mail: ReportMail) -> None:
        def count(report: ActivityReport) -> None:
            self.service.store.save_analysis(report_id, mail)
        self._settle(report_id, count)

    def _record(self, report_id: str, folder: str, mail: ReportMail) -> None:
        def advance(report: ActivityReport) -> None:
            # The run is the only writer of progress; the mail is the folder's next one.
            progress = next(item for item in report.folders if item.folder == folder)
            progress.done += 1
            if mail.accounted:
                self.service.store.save_analysis(report_id, mail)
                return
            mail.accounted = True
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
            if mail.failed_step is not None:
                counters.failed += 1
            if mail.relevant:
                counters.relevant += 1
                counters.events += len(mail.events)
            self.service.store.save_analysis(report_id, mail)
        self._settle(report_id, advance)

    # --- dates on request ----------------------------------------------------------------

    def extract_requested(self, report_id: str) -> None:
        """Extract the dates of a mail the user marked relevant after the model's 'no'."""
        report = self.service.store.load(report_id)
        assert report is not None and report.pending_extractions
        key = report.pending_extractions[0]
        mail = self.service.store.mail(report_id, key)
        if mail is not None and not mail.events_extracted and not mail.text_removed:
            try:
                self._extract(report, mail)
            except ReportPaused:
                # Keep the request, but do not spin while the limit is unchanged.
                return
            except Exception as exc:
                # The request is dropped, not repeated every few seconds; the user may ask again.
                log_and_continue(self.logger, "activity", "model_unavailable", exc)

        def done(current: ActivityReport) -> None:
            current.pending_extractions = [item for item in current.pending_extractions if item != key]
            if mail is not None and mail.events_extracted:
                current.counters.events += len(mail.events)
                current.counters.failed += mail.failed_step == "events"
                self.service.store.save_analysis(report_id, mail)
        self._settle(report_id, done)


def default_report_folders(open_reader: Callable[[], AbstractContextManager[Any]],
                           configured: list[str]) -> list[str]:
    """The configured folders a new report suggests, read from the server's roles."""
    with open_reader() as reader:
        return default_folders(reader.list_folders(), configured)


def available_report_folders(open_reader: Callable[[], AbstractContextManager[Any]]) -> list[str]:
    with open_reader() as reader:
        return [folder.name for folder in reader.list_folders()]


__all__ = ["BATCH", "MAX_FAILURES", "ActivityRunner", "default_report_folders", "available_report_folders"]
