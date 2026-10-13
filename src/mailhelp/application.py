"""Composition Root und kontrollierte Polling-Schleife des Dienstes."""
from __future__ import annotations

import imaplib
import time
import traceback
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Lock
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from . import state_names
from .adapter import RetryPolicy
from .analysis import Analyzer
from .config import PromptConfig, Secrets, Settings, Topic
from .decisions import (
    DecisionAnalyzer,
    DecisionClient,
    JevRelevanceAnalyzer,
    load_relevance_prompts,
    relevance_fingerprint,
)
from .external.contracts import OAuthTokenError
from .external.http_writer import HttpWriter
from .external.oauth import GoogleOAuthTokenProvider
from .imap import ImapReader
from .logging import JsonlLogger, NullLogger, log_and_continue
from .mailbox_run import MailboxRunService, _RunSummary
from .models import MailRunState, TelegramOffset
from .ollama import LocalLlm, OllamaClient
from .openrouter import OpenRouterClient
from .orchestrator import Orchestrator, ProcessingOutcome, ProcessingResult
from .paths import runtime_path
from .retention import RetentionService
from .review.inbox import CommandInbox
from .storage import JsonStore
from .telegram import TelegramChatNotFoundError, TelegramClient, TelegramDialogController
from .telegram.commands import STARTUP
from .telegram.receiver import TelegramInbox, TelegramReceiver
from .vision import VisionExtractor
from .web import WebServer, WebServerError
from .web.factory import create_web

if TYPE_CHECKING:
    from .experience import ExperienceRuntime
    from .imap import FetchedMail
    from .standalone import DisabledTelegram

_TELEGRAM_ERROR_BACKOFF_SECONDS = 5.0


class _FailedAccessAdapter:
    """Expose an adapter construction failure to the aggregated access check."""

    def __init__(self, error: Exception):
        self.error = error

    def check_access(self, *_args: object) -> None:
        raise self.error


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


def _state_directory(settings: Settings, base_directory: Path) -> Path:
    """Return the fully isolated state namespace for the selected mode."""
    root = runtime_path(settings.data_directory, base_directory)
    return root / ("test" if settings.test_mode else "production")


def build_logger(
    settings: Settings,
    secrets: Secrets,
    base_directory: Path = Path("."),
    *,
    access_diagnostics: bool = False,
    log_directory: Path | None = None,
) -> JsonlLogger:
    """Construct the configured logger with every known secret redacted."""
    log_dir = log_directory if log_directory is not None else settings.logging.directory
    log_dir = runtime_path(log_dir, base_directory)
    known_secrets = tuple(value.get_secret_value() for value in (
        secrets.imap_password, secrets.openrouter_api_key, secrets.telegram_bot_token,
        secrets.todoist_token, secrets.todoist_client_id, secrets.todoist_client_secret,
        secrets.google_oauth_client_id, secrets.google_oauth_client_secret,
        secrets.google_oauth_refresh_token,
    ) if value is not None)
    log = settings.logging
    return JsonlLogger(
        log_dir, log.llm.include_requests, log.llm.include_responses,
        "DEBUG" if access_diagnostics else log.file.level,
        {} if access_diagnostics else log.modules,
        known_secrets,
        file_enabled=access_diagnostics or log.file.enabled, file_name=log.file.filename,
        file_format=log.file.format, file_max_bytes=log.file.max_bytes,
        file_backup_count=log.file.backup_count, file_retention_days=log.file.retention_days,
        console_enabled=access_diagnostics or log.console.enabled,
        console_level="DEBUG" if access_diagnostics else log.console.level,
        console_format=log.console.format,
        llm_enabled=log.llm.enabled, llm_level=log.llm.level,
        llm_name=log.llm.filename, llm_format=log.llm.format,
        llm_max_bytes=log.llm.max_bytes, llm_backup_count=log.llm.backup_count,
        llm_retention_days=log.llm.retention_days,
        telegram_enabled=log.telegram.enabled,
        telegram_level=log.telegram.level,
        telegram_name=log.telegram.filename,
        telegram_format=log.telegram.format,
        telegram_max_bytes=log.telegram.max_bytes,
        telegram_backup_count=log.telegram.backup_count,
        telegram_retention_days=log.telegram.retention_days,
    )


def _attach_metrics(logger: JsonlLogger, settings: Settings, base_directory: Path, data: Path,
                    store: JsonStore, local_llm: LocalLlm | None) -> None:
    from .metrics import DECISION_TEST_FILE, PRODUCTION_FILE, MetricsRecorder, adopt_legacy, metrics_directory
    metrics_root = metrics_directory(runtime_path(settings.logging.directory, base_directory))
    production = metrics_root / PRODUCTION_FILE
    comparison = metrics_root / DECISION_TEST_FILE
    adopt_legacy(data / "metrics" / "llm.jsonl", production)
    adopt_legacy(data.parent / "decision-tests" / "metrics" / "llm.jsonl", comparison)
    recorder = MetricsRecorder(production, settings.metrics, "local" if local_llm else "standard")
    recorder.comparison = MetricsRecorder(comparison, settings.metrics, "decision_test")
    recorder.changed = store.touch
    logger.metrics = recorder


def _build_imap(settings: Settings, secrets: Secrets, policy: Callable[[str], RetryPolicy],
                logger: JsonlLogger, access_diagnostics: bool, stack: ExitStack) -> Any:
    imap_cfg = settings.timeouts.imap
    factory = imaplib.IMAP4_SSL if settings.imap.connection_mode == "ssl" else imaplib.IMAP4
    try:
        imap = ImapReader(settings.imap.host, settings.imap.port, secrets.imap_username,
                          secrets.imap_password.get_secret_value(), imap_cfg.timeout_seconds, factory=factory,
                          policy=policy("imap"), logger=logger, starttls=settings.imap.connection_mode == "starttls",
                          batch_size=settings.imap.batch_size)
    except Exception as exc:
        if not access_diagnostics:
            raise
        # IMAP connects and authenticates in its constructor, unlike the
        # HTTP adapters. Preserve that failure as one diagnostic result so
        # constructing the application cannot prevent the other checks.
        return _FailedAccessAdapter(exc)
    stack.callback(imap.close)
    return imap


def _build_llm(settings: Settings, secrets: Secrets, local_llm: LocalLlm | None, llm_budget: dict[str, Any],
               logger: JsonlLogger, stack: ExitStack) -> OpenRouterClient:
    openrouter: OpenRouterClient
    if local_llm is None:
        llm_cfg = settings.timeouts.openrouter
        openrouter = OpenRouterClient(secrets.openrouter_api_key.get_secret_value(), llm_cfg.timeout_seconds,
                                      llm_cfg.retries, settings.limits.llm_calls_per_minute,
                                      initial_backoff=llm_cfg.initial_backoff_seconds,
                                      max_backoff=llm_cfg.max_backoff_seconds, **llm_budget)
    else:
        # Experimental: every LLM stage runs on the local Ollama model.
        llm_cfg = settings.timeouts.ollama
        openrouter = OllamaClient(local_llm, llm_cfg.timeout_seconds, llm_cfg.retries,
                                  settings.limits.llm_calls_per_minute, initial_backoff=llm_cfg.initial_backoff_seconds,
                                  max_backoff=llm_cfg.max_backoff_seconds, **llm_budget)
        logger.event("WARNING", "application", "local_llm_experimental",
                     host=local_llm.host, port=local_llm.port, model=local_llm.model,
                     num_ctx=local_llm.num_ctx)
    stack.callback(openrouter.close)
    return openrouter


def _build_telegram(settings: Settings, secrets: Secrets, policy: Callable[[str], RetryPolicy],
                    logger: JsonlLogger, stack: ExitStack) -> Any:
    if settings.telegram.enabled:
        telegram: TelegramClient | DisabledTelegram = TelegramClient(
            secrets.telegram_bot_token.get_secret_value(), settings.timeouts.telegram.timeout_seconds,
            poll_timeout=settings.timeouts.telegram_poll_seconds, policy=policy("telegram"), logger=logger)
    else:
        from .standalone import DisabledTelegram
        telegram = DisabledTelegram()
    stack.callback(telegram.close)
    return telegram


def _build_analyzer(settings: Settings, secrets: Secrets, prompts: PromptConfig, openrouter: OpenRouterClient,
                    jev_prompts: Any, llm_budget: dict[str, Any], stop_event: Event, stack: ExitStack) -> Analyzer:
    analyzer_options: dict[str, Any] = {}
    analyzer_type: Callable[..., Analyzer] = Analyzer
    if jev_prompts is not None:
        llm_cfg = settings.timeouts.openrouter
        decision_client = DecisionClient(
            secrets.openrouter_api_key.get_secret_value(), llm_cfg.timeout_seconds,
            llm_cfg.retries, settings.limits.llm_calls_per_minute,
            initial_backoff=llm_cfg.initial_backoff_seconds,
            max_backoff=llm_cfg.max_backoff_seconds, stopped=stop_event.wait, **llm_budget)
        stack.callback(decision_client.close)
        # Both adapters charge the same durable budget atomically.
        shared_lock = Lock()
        openrouter._state_lock = decision_client._state_lock = shared_lock
        analyzer_options["decisions"] = DecisionAnalyzer(
            decision_client, jev_prompts, settings.limits.max_llm_payload_bytes)
        analyzer_type = JevRelevanceAnalyzer
    return analyzer_type(
        openrouter, prompts,
        provider_retries=settings.retries.provider_retry,
        json_repair_retries=settings.retries.json_repair,
        schema_repair_retries=settings.retries.schema_repair,
        **analyzer_options,
    )


def _build_dialog(settings: Settings, store: JsonStore, telegram: Any, logger: JsonlLogger, writers: dict[str, Any],
                  analyzer: Analyzer, web_enabled: bool) -> TelegramDialogController:
    telegram_inbox = TelegramInbox(store)
    return TelegramDialogController(
        store, telegram, settings.telegram.user_id, settings.telegram.chat_id, logger,
        writers, settings.test_mode,
        settings.timezone,
        analyzer,
        interpretation_attempts=settings.retries.interpretation_attempts,
        interpretation_backoff_seconds=settings.retries.interpretation_backoff_seconds,
        revision_attempts=settings.retries.revision_attempts,
        revision_backoff_seconds=settings.retries.revision_backoff_seconds,
        sequential_questions=settings.telegram.sequential_questions,
        inbox=telegram_inbox,
        commands=CommandInbox(store, wake=telegram_inbox.wake) if web_enabled else None,
    )


def _build_orchestrator(settings: Settings, prompts: PromptConfig, topics: list[Topic], fingerprint: str,
                        jev_prompts: Any, store: JsonStore, sender_store: JsonStore, logger: JsonlLogger,
                        analyzer: Analyzer, dialog: TelegramDialogController, writers: dict[str, Any],
                        access_diagnostics: bool) -> Orchestrator:
    from .precheck import DuplicatePreCheckService
    precheck = DuplicatePreCheckService(
        writers={"google_calendar": writers["google_calendar"], "todoist": writers["todoist"]},
        ledger=dialog.ledger,
        logger=logger,
    )
    vision = None
    if settings.vision.enabled and "vision_ocr" in prompts.prompts:
        vision = VisionExtractor(analyzer, settings.vision)
    elif settings.vision.enabled:
        # A prompts.yaml from before 1.4: no image is sent anywhere.
        logger.event("WARNING", "application", "vision_prompt_missing")
    orchestrator = Orchestrator(analyzer, store, dialog, settings.telegram.chat_id, topics,
                                settings.limits.max_mail_bytes, logger, mime_limits=settings.limits,
                                config_fingerprint=fingerprint, targets=settings.targets,
                                user_timezone=settings.timezone, sender_store=sender_store, precheck=precheck,
                                vision=vision)
    from .fingerprints import adopt_legacy_configuration, legacy_fingerprints, legacy_policies, topic_policy
    orchestrator.topic_policy = topic_policy(settings, prompts)
    if not access_diagnostics:
        legacy = legacy_fingerprints(settings, prompts, topics)
        if jev_prompts is not None:
            legacy = {relevance_fingerprint(item, jev_prompts) for item in legacy}
        # Mails started under 1.1 or the 1.2 beta with this same configuration continue.
        adopt_legacy_configuration(store, fingerprint, legacy, orchestrator.topic_policy,
                                   legacy_policies(settings, prompts), topics)
    return orchestrator


def _attach_web(application: Application, settings: Settings, secrets: Secrets, prompts: PromptConfig,
                jev_prompts: Any, local_llm: LocalLlm | None, base_directory: Path, sender_store: JsonStore) -> None:
    store, logger, dialog = application.store, application.logger, application.dialog
    # build_application always creates the dialog and its command inbox before the web interface.
    assert dialog is not None and dialog.commands is not None
    telegram, orchestrator, stop_event = application.telegram, application.orchestrator, application.stop_event
    secret = secrets.mailhelp_web_secret
    if settings.telegram.enabled:
        def notify(text):
            telegram.send(settings.telegram.chat_id, text)
    else:
        # Standalone: pairing codes appear only in the console of the PC, never in a log file.
        def notify(text):
            print(text, flush=True)
    components = create_web(
        settings, secret.get_secret_value() if secret is not None else None, store,
        notify, logger, dialog.commands)
    if not settings.telegram.enabled:
        components.auth.channel = "console"
    dialog.review.web_authorizer = components.authorize
    dialog.web_logout = components.auth.revoke_all
    dialog.web_invite = components.invite
    application.web = components.server
    from .configuration import ConfigurationService
    from .lifecycle import Lifecycle
    configuration = ConfigurationService(base_directory, store, settings, components.authorize,
                                          application.apply_settings, orchestrator.change_topics,
                                          senders=sender_store)
    application.configuration = configuration
    dialog.review.configuration = configuration
    components.site.lifecycle = Lifecycle(
        application.stop, components.authorize,
        lambda state, process: logger.event("INFO", "lifecycle", state, process=process))
    application.lifecycle = components.site.lifecycle
    components.site.archive.lifecycle = components.site.lifecycle
    dialog.stop_requested = lambda: components.site.lifecycle.state != "running" or stop_event.is_set()
    components.site.archive.configuration = configuration
    components.site.archive.metrics = logger.metrics
    from .configuration import effective_models
    components.site.archive.models = effective_models(
        prompts, jev_prompts.model if jev_prompts else None, local_llm.model if local_llm else None)
    from .experience import ExperienceRuntime
    application.experience = ExperienceRuntime(application, components, secrets)
    if not settings.telegram.enabled:
        print(components.invite())


@contextmanager
def build_application(
    settings: Settings,
    secrets: Secrets,
    topics: list[Topic],
    prompts: PromptConfig,
    fingerprint: str,
    base_directory: Path = Path("."),
    *,
    access_diagnostics: bool = False,
    logger: JsonlLogger | None = None,
    local_llm: LocalLlm | None = None,
    use_jev_relevance: bool = True,
) -> Iterator[Application]:
    """Construct adapters and close every successfully constructed resource."""
    jev_prompts = None
    if use_jev_relevance and local_llm is None and not access_diagnostics:
        jev_prompts = load_relevance_prompts(base_directory)
        fingerprint = relevance_fingerprint(fingerprint, jev_prompts)
    with ExitStack() as stack:
        data = _state_directory(settings, base_directory)
        store = stack.enter_context(JsonStore(data))
        sender_store = JsonStore(base_directory)
        if logger is None or access_diagnostics:
            logger = build_logger(
                settings, secrets, base_directory,
                access_diagnostics=access_diagnostics,
            )
        _attach_metrics(logger, settings, base_directory, data, store, local_llm)
        stop_event = Event()
        def policy(name: str) -> RetryPolicy:
            item = getattr(settings.timeouts, name)
            return RetryPolicy(item.retries, item.initial_backoff_seconds, item.max_backoff_seconds, stop_event.wait)
        imap = _build_imap(settings, secrets, policy, logger, access_diagnostics, stack)
        llm_budget: dict[str, Any] = dict(
            load_calls=lambda: store.load("llm-budget", {}).get("calls", []),
            save_calls=lambda calls: store.save("llm-budget", {"calls": calls}), logger=logger)
        openrouter = _build_llm(settings, secrets, local_llm, llm_budget, logger, stack)
        telegram = _build_telegram(settings, secrets, policy, logger, stack)
        todoist = HttpWriter("todoist", secrets.todoist_token.get_secret_value(), settings.targets.todoist_project,
                             settings.timeouts.todoist.timeout_seconds, policy=policy("todoist"), logger=logger)
        stack.callback(todoist.close)
        google_cfg = settings.timeouts.google_calendar
        oauth = GoogleOAuthTokenProvider(
            secrets.google_oauth_client_id.get_secret_value(),
            secrets.google_oauth_client_secret.get_secret_value(),
            secrets.google_oauth_refresh_token.get_secret_value(),
            google_cfg.timeout_seconds,
            logger=logger,
        )
        stack.callback(oauth.close)
        analyzer = _build_analyzer(settings, secrets, prompts, openrouter, jev_prompts, llm_budget, stop_event, stack)
        calendar = HttpWriter(
            "google_calendar", oauth, settings.targets.google_calendar,
            google_cfg.timeout_seconds, policy=policy("google_calendar"), logger=logger,
            calendar_timezone=settings.timezone,
            calendar_matcher=analyzer.calendar_duplicate,
        )
        stack.callback(calendar.close)
        writers = {"todoist": todoist, "google_calendar": calendar}
        web_enabled = settings.web.enabled and not access_diagnostics
        dialog = _build_dialog(settings, store, telegram, logger, writers, analyzer, web_enabled)
        orchestrator = _build_orchestrator(settings, prompts, topics, fingerprint, jev_prompts, store, sender_store,
                                           logger, analyzer, dialog, writers, access_diagnostics)
        dialog.relevance_handler = orchestrator
        orchestrator.stop_event = stop_event
        application = Application(settings, store, logger, imap, openrouter, analyzer, telegram, todoist, calendar,
                                  orchestrator, stop_event, dialog, sender_store)
        if web_enabled:
            _attach_web(application, settings, secrets, prompts, jev_prompts, local_llm, base_directory, sender_store)
        yield application
