"""Kontrollierte Polling-Schleife des Dienstes; der Aufbau steht in composition.py."""
from __future__ import annotations

import time
import traceback
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import Event
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from . import state_names
from .analysis import Analyzer
from .config import Settings
from .external.contracts import OAuthTokenError
from .external.http_writer import HttpWriter
from .imap import ImapReader
from .logging import JsonlLogger, NullLogger, log_and_continue
from .mailbox_run import MailboxRunService, _RunSummary
from .models import MailRunState, TelegramOffset
from .openrouter import OpenRouterClient
from .orchestrator import Orchestrator, ProcessingOutcome, ProcessingResult
from .retention import RetentionService
from .storage import JsonStore
from .telegram import TelegramChatNotFoundError, TelegramClient, TelegramDialogController
from .telegram.commands import STARTUP
from .telegram.receiver import TelegramInbox, TelegramReceiver
from .web import WebServer, WebServerError

if TYPE_CHECKING:
    from .experience import ExperienceRuntime
    from .imap import FetchedMail
    from .standalone import DisabledTelegram

_TELEGRAM_ERROR_BACKOFF_SECONDS = 5.0


@dataclass
class Application:
    settings: Settings
    store: JsonStore
    logger: JsonlLogger
    imap: ImapReader
    openrouter: OpenRouterClient
    analyzer: Analyzer
    telegram: TelegramClient | DisabledTelegram
    todoist: HttpWriter
    calendar: HttpWriter
    orchestrator: Orchestrator
    stop_event: Event
    dialog: TelegramDialogController | None = None
    sender_store: JsonStore | None = None
    _wait_for_user: bool = False
    _fatal_error: str | None = None
    _receiver: TelegramReceiver | None = None
    web: WebServer | None = None
    # Web stop handshake; its final state is set when the run loop ends.
    lifecycle: Any = None
    configuration: object | None = None
    experience: ExperienceRuntime | None = None

    mailbox: MailboxRunService = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.mailbox = MailboxRunService(
            self.settings, self.store, self.logger, self.imap, self.orchestrator,
            self.stop_event, self._process_mail,
        )

    def check_access(self) -> dict[str, str | None]:
        """Check every external credential and target without processing mail."""
        def check_imap() -> None:
            failures = []
            for folder in self.settings.imap.folders:
                try:
                    self.imap.check_access([folder])
                except Exception as exc:
                    failures.append(f"{folder}: {str(exc) or type(exc).__name__}")
                else:
                    getattr(self, "logger", NullLogger()).event(
                        "DEBUG", "access_check", "imap_folder_accessible", folder=folder)
            if failures:
                raise RuntimeError("IMAP: " + "; ".join(failures))

        checks = (
            ("IMAP", check_imap),
            (self.openrouter.service_name, self.openrouter.check_access),
            ("Telegram", lambda: Application._check_telegram_access(self)),
            ("Todoist", self.todoist.check_access),
            ("Google Kalender", self.calendar.check_access),
        )
        results: dict[str, str | None] = {}
        logger = getattr(self, "logger", NullLogger())
        for name, check in checks:
            logger.event("DEBUG", "access_check", "check_started", service=name)
            try:
                check()
            except Exception as exc:
                logger.event(
                    "ERROR", "access_check", "check_failed", service=name,
                    error=exc, stacktrace=traceback.format_exc(),
                )
                # Adapter diagnostics are already safe, service-specific user
                # messages.  Preserve them verbatim for the CLI rather than
                # replacing them with a generic access-check failure.
                message = str(exc)
                results[name] = message if message else type(exc).__name__
            else:
                results[name] = None
                logger.event("DEBUG", "access_check", "check_completed", service=name)
        return results

    def _check_telegram_access(self) -> None:
        """Validate the bot and visibly prove access to the configured chat."""
        self.telegram.check_access()
        now = datetime.now(ZoneInfo(self.settings.timezone))
        message = (
            f"Test – Datum: {now:%d.%m.%Y}, Uhrzeit: {now:%H:%M:%S} "
            f"({self.settings.timezone})"
        )
        try:
            self.telegram.send(self.settings.telegram.chat_id, message)
        except TelegramChatNotFoundError as exc:
            chats = self.telegram.started_chats(self.settings.telegram.user_id)
            configured = self.settings.telegram.chat_id
            if chats:
                found = ", ".join(str(chat_id) for chat_id in chats)
                raise TelegramChatNotFoundError(
                    f"{exc}. Für die konfigurierte telegram.user_id wurde /start "
                    f"in Chat {found} empfangen; konfiguriert ist telegram.chat_id "
                    f"{configured}. Bitte telegram.chat_id entsprechend korrigieren."
                ) from exc
            raise TelegramChatNotFoundError(
                f"{exc}. Von der konfigurierten telegram.user_id wurde kein /start "
                "bei diesem Bot empfangen. Bitte prüfen, ob /start an genau den Bot "
                "aus TELEGRAM_BOT_TOKEN gesendet wurde und telegram.user_id stimmt."
            ) from exc

    def apply_settings(self, settings: Settings) -> None:
        """Main-thread activation of the explicitly live configuration subset."""
        self.settings = settings
        self.mailbox.settings = settings
        metrics = self.logger.metrics
        assert metrics is not None  # attached together with the logger (_attach_metrics)
        metrics.settings = settings.metrics
        if metrics.comparison is not None:
            metrics.comparison.settings = settings.metrics

    def stop(self) -> None:
        self.stop_event.set()
        self.orchestrator.stop()
        if self._receiver is not None:
            self._receiver.stop()

    def _start_receiver(self) -> None:
        """Receive Telegram input in its own thread if the dialog has an inbox."""
        inbox = getattr(self.dialog, "inbox", None)
        if not isinstance(inbox, TelegramInbox):
            return
        assert self.dialog is not None
        self._receiver = TelegramReceiver(
            self.telegram, inbox, self.dialog.receive_offset(), self.logger,
            _TELEGRAM_ERROR_BACKOFF_SECONDS)
        self._receiver.start()

    def _stop_receiver(self) -> None:
        receiver, self._receiver = self._receiver, None
        if receiver is not None:
            receiver.stop()
            # A long-poll in flight ends with the Telegram client; never block exit.
            receiver.join(timeout=1)

    def _start_web(self) -> None:
        """Start the optional web interface; mail processing continues without it."""
        if self.web is None:
            return
        try:
            self.web.start()
            if self.experience is not None:
                self.experience.start()
        except WebServerError as exc:
            self.logger.event("ERROR", "web", "server_start_failed", error=str(exc))
            self.web = None
            try:
                self.telegram.send(self.settings.telegram.chat_id,
                                   f"⚠️ {exc}. Mailhelp läuft ohne Weboberfläche weiter.")
            except Exception as notification_error:
                log_and_continue(self.logger, "telegram", "web_start_notice_failed", notification_error)

    def _stop_web(self) -> None:
        if self.experience is not None:
            self.experience.stop()
        web, self.web = self.web, None
        if web is not None:
            web.stop()

    def _idle(self, delay: float) -> None:
        """Wait for the next mail cycle while handling Telegram input as it arrives."""
        getattr(self, "logger", NullLogger()).event("DEBUG", "application", "idle_started", delay_seconds=delay)
        if self._receiver is None:
            self.stop_event.wait(delay)
            return
        deadline = time.monotonic() + delay
        while not self.stop_event.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            if self._receiver.inbox.wait(remaining):
                self._poll_telegram(timeout=0)

    def _poll_imap(self, max_mails: int | None = None, *,
                   ignore_historical_start: bool = False) -> list[ProcessingResult]:
        return self.mailbox.poll(max_mails, ignore_historical_start=ignore_historical_start)


    def _poll_telegram(self, timeout: int | None = None) -> bool:
        """Poll Telegram once and report whether the request completed normally.

        With a receiver thread, wait up to *timeout* (default: the Telegram
        long-poll time) for its inbox and then process what arrived.
        """
        if self._receiver is not None:
            self._receiver.inbox.wait(self.settings.timeouts.telegram_poll_seconds
                                      if timeout is None else timeout)
        if self.dialog is not None:
            try:
                self.dialog.poll_once(timeout=timeout)
            except OAuthTokenError as exc:
                self._stop_after_fatal_oauth_error(exc)
                return False
            except Exception as exc:
                self.logger.event("ERROR", "telegram", "poll_failed", error=str(exc))
                return False
            return True
        state_model = self.store.load_model("telegram-offset", TelegramOffset, TelegramOffset())
        try:
            updates = self.telegram.poll(state_model.offset, timeout=timeout)
        except Exception as exc:
            self.logger.event("ERROR", "telegram", "poll_failed", error=str(exc))
            return False
        for update in updates:
            offset = int(update["update_id"]) + 1
            self.store.save("telegram-offset", TelegramOffset(offset=offset).model_dump())
            self.logger.event("INFO", "telegram", "update_received", update_id=update["update_id"])
        return True

    def _stop_after_fatal_oauth_error(self, exc: OAuthTokenError) -> None:
        """Stop permanently after Google rejected the configured OAuth grant."""
        self._fatal_error = str(exc)
        self.logger.event(
            "CRITICAL", "application", "fatal_google_oauth_error",
            error=self._fatal_error,
        )
        try:
            self.telegram.send(
                self.settings.telegram.chat_id,
                "Mailhelp wird beendet: Die Google-OAuth-Anmeldung wurde "
                "abgelehnt. Bitte Google-Zugangsdaten erneuern, danach "
                "'mailhelp --check-access' ausführen und Mailhelp neu starten.",
            )
        except Exception as notification_error:
            self.logger.event(
                "ERROR", "telegram", "fatal_error_notification_failed",
                error=str(notification_error),
            )
        self.stop_event.set()

    def _process_mail(self, mail: FetchedMail) -> ProcessingResult:
        """Wait only for relevance; proposals are independent of mail analysis."""
        if self._receiver is not None:
            # Button presses received during the previous mail come first.
            self._poll_telegram(timeout=0)
        while True:
            if (self._wait_for_user and self.dialog is not None
                    and self.dialog.awaiting_relevance_decision()
                    and not self._wait_for_telegram_decision()):
                return ProcessingResult(ProcessingOutcome.WAITING, {})
            result = self.orchestrator.process(mail)
            if (not self._wait_for_user or self.dialog is None
                    or not self.dialog.awaiting_relevance_decision()):
                return result
            resume_mail = result.outcome is ProcessingOutcome.WAITING
            if not self._wait_for_telegram_decision():
                return result
            if not resume_mail:
                return result
            # An unclear relevance answer interrupts analysis. Once Telegram
            # resolved it, resume this same mail before advancing the mailbox.

    def _wait_for_telegram_decision(self) -> bool:
        """Long-poll until the blocking relevance decision is resolved or stopped."""
        if self.dialog is None or not self.dialog.awaiting_relevance_decision():
            return False
        while (not self.stop_event.is_set()
               and self.dialog.awaiting_relevance_decision()):
            if not self._poll_telegram():
                self.stop_event.wait(min(
                    self.settings.poll_interval_seconds,
                    _TELEGRAM_ERROR_BACKOFF_SECONDS,
                ))
        return not self.stop_event.is_set()

    def run(self, max_mails: int | None = None, *,
            ignore_historical_start: bool = False) -> str | None:
        self._wait_for_user = True
        self._announce_start()
        self._start_receiver()
        self._start_web()
        try:
            while not self.stop_event.is_set():
                if not self._cycle(max_mails, ignore_historical_start):
                    break
        finally:
            self._finish(max_mails)
        return self._fatal_error

    def _announce_start(self) -> None:
        """Greeting, open decisions and held messages; no failure blocks the start."""
        try:
            self.telegram.send(self.settings.telegram.chat_id, STARTUP)
        except Exception as exc:
            # A failed greeting must not block recovery or disclose provider data.
            log_and_continue(self.logger, "telegram", "startup_help_failed", exc)
        else:
            self.logger.event("INFO", "telegram", "startup_help_sent")
        try:
            if self.dialog is not None and self.dialog.awaiting_decision():
                self.dialog.show_open_decisions()
        except Exception as exc:
            log_and_continue(self.logger, "telegram", "startup_decisions_failed", exc)
        try:
            if self.dialog is not None:
                # Held messages whose question was resolved before a restart.
                self.dialog.flush_outbox()
        except Exception as exc:
            log_and_continue(self.logger, "telegram", "startup_outbox_failed", exc)

    def _maintain(self) -> None:
        try:
            RetentionService(self.store, self.settings.retention, self.logger).run()
            metrics = getattr(self.logger, "metrics", None)
            if metrics is not None:
                metrics.maintain()
        except Exception as exc:
            # No state content is included in this operational event.
            log_and_continue(self.logger, "retention", "cleanup_failed", exc,
                             processed_at=datetime.now(UTC).isoformat(), failure_count=1)

    def _cycle(self, max_mails: int | None, ignore_historical_start: bool) -> bool:
        """One pass: maintenance, mail, Telegram input and idle time; ``False`` ends the run."""
        self._maintain()
        # Only an already open, durable relevance decision precedes mailbox
        # work.  An unconditional Telegram long-poll here used to make
        # every fresh start look stuck for up to telegram_poll_seconds.
        if self.dialog is not None and self.dialog.awaiting_relevance_decision():
            self._wait_for_telegram_decision()
        # A paused proposal revision is isolated to its source mail.
        # It must never prevent independent queued mail from being
        # analysed; the durable clarification remains available for an
        # operator retry without acting as a global circuit breaker.
        if not self.stop_event.is_set():
            if ignore_historical_start:
                self._poll_imap(
                    max_mails, ignore_historical_start=True
                )
            else:
                self._poll_imap(max_mails)
        if self.stop_event.is_set():
            return False
        if max_mails is not None:
            return False
        # The receiver already waited for input; only process what arrived.
        telegram_poll_succeeded = (self._poll_telegram(timeout=0)
                                   if self._receiver is not None
                                   else self._poll_telegram())
        if (not self.stop_event.is_set() and self.dialog is not None
                and self.dialog.awaiting_relevance_decision()):
            self._wait_for_telegram_decision()
        delay = (min(self.settings.poll_interval_seconds,
                     _TELEGRAM_ERROR_BACKOFF_SECONDS)
                 if not telegram_poll_succeeded
                 else self.settings.poll_interval_seconds)
        self._idle(delay)
        return True

    def _finish(self, max_mails: int | None) -> None:
        """Stop the helpers and report the run, unless a relevance question still blocks it."""
        self._stop_web()
        self._stop_receiver()
        if self.lifecycle is not None:
            self.lifecycle.finished()
        run_name = state_names.mail_run(self.imap.account_id)
        run = self.store.load_model(run_name, MailRunState)
        summary = _RunSummary.from_run(run)
        # Relevance still blocks analysis. Proposal buttons remain usable
        # independently of the run summary and of subsequent mail runs.
        if self.dialog is not None and self.dialog.awaiting_relevance_decision():
            self.logger.event("INFO", "telegram", "run_summary_deferred")
        elif summary.empty:
            self.logger.event("INFO", "telegram", "run_summary_skipped", reason="no_mail")
        else:
            try:
                self.telegram.send(
                    self.settings.telegram.chat_id,
                    summary.message(bounded=max_mails is not None),
                )
            except Exception as exc:
                self.logger.event("ERROR", "telegram", "run_summary_failed", error=str(exc))
            else:
                self.logger.event("INFO", "telegram", "run_summary_sent",
                                  discovered=summary.discovered, queued=summary.queued,
                                  processed=summary.processed, relevant=summary.relevant,
                                  irrelevant=summary.irrelevant,
                                  waiting_for_user=summary.waiting_for_user,
                                  failed=summary.failed, skipped=summary.skipped,
                                  run_complete=summary.run_complete)


# Construction lives in composition.py; these names stay importable from here.
from .composition import _state_directory, build_application, build_logger

__all__ = ["Application", "_state_directory", "build_application", "build_logger"]
