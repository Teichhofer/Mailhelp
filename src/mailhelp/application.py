"""Composition Root und kontrollierte Polling-Schleife des Dienstes."""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
import imaplib
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from typing import Iterator
from zoneinfo import ZoneInfo

from .analysis import Analyzer
from .config import PromptConfig, Secrets, Settings, Topic
from .imap import ImapReader
from .integrations import CalendarFileWriter, HttpWriter
from .logging import JsonlLogger, NullLogger
from .models import ImapCheckpoint, MailState, TelegramOffset
from .openrouter import OpenRouterClient
from .orchestrator import Orchestrator, ProcessingOutcome, ProcessingResult
from .storage import JsonStore
from .telegram import (TelegramChatNotFoundError, TelegramClient,
                       TelegramDialogController)
from .adapter import RetryPolicy
from .retention import RetentionService

_BLOCKED_STATE_SCAN_LIMIT = 1000


@dataclass
class _MailBudget:
    """Independent per-run budgets for actionable and blocked mail states."""

    remaining: int | None
    blocked_remaining: int | None = None

    def __post_init__(self) -> None:
        # A bounded run may report at most as many configuration-blocked states
        # as it can actually process.  Keeping this counter separate prevents a
        # stale backlog from starving newly arrived mail.
        if self.blocked_remaining is None:
            self.blocked_remaining = (self.remaining if self.remaining is not None
                                      else _BLOCKED_STATE_SCAN_LIMIT)

    def take(self) -> None:
        assert self.remaining is not None
        self.remaining -= 1

    def take_blocked(self) -> None:
        assert self.blocked_remaining is not None
        self.blocked_remaining -= 1


@dataclass
class _RunSummary:
    """Outcome counters for the lifetime of one application run."""

    completed: int = 0
    waiting: int = 0
    failed: int = 0

    def add(self, results: list[ProcessingResult]) -> None:
        counts = {
            ProcessingOutcome.COMPLETED: self.completed,
            ProcessingOutcome.WAITING: self.waiting,
            ProcessingOutcome.FAILED: self.failed,
        }
        for result in results:
            counts[result.outcome] += 1
        self.completed = counts[ProcessingOutcome.COMPLETED]
        self.waiting = counts[ProcessingOutcome.WAITING]
        self.failed = counts[ProcessingOutcome.FAILED]

    def message(self) -> str:
        total = self.completed + self.waiting + self.failed
        return "\n".join((
            "Mailhelp-Lauf beendet.",
            f"Bearbeitet: {total}",
            f"Erfolgreich abgeschlossen: {self.completed}",
            f"Warten auf Eingabe oder Wiederholung: {self.waiting}",
            f"Fehlgeschlagen: {self.failed}",
        ))


@dataclass
class Application:
    settings: Settings
    store: JsonStore
    logger: JsonlLogger
    imap: ImapReader
    openrouter: OpenRouterClient
    analyzer: Analyzer
    telegram: TelegramClient
    todoist: HttpWriter
    calendar: CalendarFileWriter
    orchestrator: Orchestrator
    stop_event: Event
    dialog: TelegramDialogController | None = None

    def check_access(self) -> dict[str, str | None]:
        """Check every external credential and target without processing mail."""
        checks = (
            ("IMAP", lambda: self.imap.check_access(self.settings.imap.folders)),
            ("OpenRouter", self.openrouter.check_access),
            ("Telegram", lambda: Application._check_telegram_access(self)),
            ("Todoist", self.todoist.check_access),
            ("Kalenderdatei", self.calendar.check_access),
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

    def stop(self) -> None:
        self.stop_event.set()
        self.orchestrator.stop()

    def _poll_imap(self, max_mails: int | None = None) -> list[ProcessingResult]:
        """Resume durable work and process new mail, returning every outcome."""
        budget = _MailBudget(max_mails)
        results = self._resume_pending(budget)
        for folder in self.settings.imap.folders:
            if self.stop_event.is_set() or budget.remaining == 0:
                break
            checkpoint_name = _checkpoint_name(self.imap.account_id, folder)
            checkpoint_model = self.store.load_model(checkpoint_name, ImapCheckpoint, ImapCheckpoint()) if hasattr(self.store, "load_model") else ImapCheckpoint.model_validate(self.store.load(checkpoint_name, {}))
            checkpoint = checkpoint_model.model_dump(exclude={"schema_version"})
            try:
                if checkpoint["start_uid"] is None:
                    if self.settings.imap.historical_start is not None:
                        start_uid = self.imap.determine_start_uid(folder, self.settings.imap.historical_start)
                        initial_uidvalidity = self.imap.last_uidvalidity
                    else:
                        start_uid = checkpoint["uid"]
                        initial_uidvalidity = checkpoint["uidvalidity"]
                    checkpoint_model = ImapCheckpoint(uidvalidity=initial_uidvalidity, uid=start_uid, start_uid=start_uid)
                    self.store.save(checkpoint_name, checkpoint_model.model_dump())
                    checkpoint = checkpoint_model.model_dump(exclude={"schema_version"})
                mails = self.imap.fetch_since(
                    folder,
                    checkpoint.get("uid", 0),
                    checkpoint.get("uidvalidity"),
                    budget.remaining if budget is not None else None,
                )
            except Exception as exc:
                self.logger.event("ERROR", "imap", "poll_failed", folder=folder, error=str(exc))
                continue
            if (checkpoint.get("uidvalidity") is not None and self.imap.last_uidvalidity is not None
                    and checkpoint.get("uidvalidity") != self.imap.last_uidvalidity):
                self.logger.event("WARNING", "imap", "uidvalidity_changed", account_id=self.imap.account_id, folder=folder,
                                  previous_uidvalidity=checkpoint.get("uidvalidity"), uidvalidity=self.imap.last_uidvalidity)
            checkpoint_reachable = True
            for mail in mails:
                if self.stop_event.is_set() or budget.remaining == 0:
                    break
                if budget.remaining is not None:
                    budget.take()
                try:
                    result = self.orchestrator.process(mail)
                except Exception as exc:
                    self.logger.event("ERROR", "orchestrator", "mail_failed", folder=folder, uid=mail.uid, error=str(exc))
                    checkpoint_reachable = False
                    continue
                results.append(result)
                # Every regular result has a durable mail state, including failed
                # and deliberately waiting work.  It is therefore safe to move the
                # discovery checkpoint and let _resume_pending own unfinished work.
                if checkpoint_reachable:
                    self.store.save(checkpoint_name, ImapCheckpoint(uidvalidity=mail.uidvalidity, uid=mail.uid, start_uid=checkpoint["start_uid"]).model_dump())
                if result.outcome is ProcessingOutcome.FAILED:
                    self.logger.event("ERROR", "orchestrator", "mail_failed", folder=folder, uid=mail.uid,
                                      error=result.state.get("error"))
            if not mails and self.imap.last_uidvalidity is not None:
                uid = checkpoint.get("uid", 0) if checkpoint.get("uidvalidity") == self.imap.last_uidvalidity else 0
                self.store.save(checkpoint_name, ImapCheckpoint(uidvalidity=self.imap.last_uidvalidity, uid=uid, start_uid=checkpoint["start_uid"]).model_dump())
        return results

    def _resume_pending(self, budget: _MailBudget | None = None) -> list[ProcessingResult]:
        """Resume due durable mail states, independently of IMAP checkpoints."""
        results: list[ProcessingResult] = []
        if not hasattr(self.store, "names"):
            return results
        budget = budget or _MailBudget(None)
        now = datetime.now(timezone.utc)
        for name in self.store.names("mail-"):
            if self.stop_event.is_set() or budget.remaining == 0:
                break
            try:
                state = self.store.load_model(name, MailState)
                if state is None or state.steps.completion != "pending":
                    continue
                if state.imap.account_id != self.imap.account_id:
                    continue
                if state.config_fingerprint != self.orchestrator.config_fingerprint:
                    if budget.blocked_remaining == 0:
                        break
                    budget.take_blocked()
                    self.logger.event(
                        "WARNING", "orchestrator", "configuration_changed",
                        mail_id=state.id,
                    )
                    results.append(ProcessingResult(
                        ProcessingOutcome.WAITING, state.model_dump(mode="json")
                    ))
                    continue
                if state.deferred_until is not None and state.deferred_until > now:
                    continue
                if budget.remaining is not None:
                    budget.take()
                mail = self.imap.fetch_uid(state.imap.folder, state.imap.uid, state.imap.uidvalidity)
                result = self.orchestrator.process(mail)
                results.append(result)
                if result.outcome is ProcessingOutcome.FAILED:
                    self.logger.event("ERROR", "orchestrator", "resume_failed", state_name=name,
                                      error=result.state.get("error"))
            except Exception as exc:
                self.logger.event("ERROR", "orchestrator", "resume_failed", state_name=name, error=str(exc))
        return results

    def _poll_telegram(self) -> None:
        if self.dialog is not None:
            try:
                self.dialog.poll_once()
            except Exception as exc:
                self.logger.event("ERROR", "telegram", "poll_failed", error=str(exc))
            return
        state_model = self.store.load_model("telegram-offset", TelegramOffset, TelegramOffset()) if hasattr(self.store, "load_model") else TelegramOffset.model_validate(self.store.load("telegram-offset", {}))
        try:
            updates = self.telegram.poll(state_model.offset)
        except Exception as exc:
            self.logger.event("ERROR", "telegram", "poll_failed", error=str(exc))
            return
        for update in updates:
            offset = int(update["update_id"]) + 1
            self.store.save("telegram-offset", TelegramOffset(offset=offset).model_dump())
            self.logger.event("INFO", "telegram", "update_received", update_id=update["update_id"])

    def run(self, max_mails: int | None = None) -> None:
        summary = _RunSummary()
        try:
            while not self.stop_event.is_set():
                try:
                    RetentionService(self.store, self.settings.retention, self.logger).run()
                except Exception:
                    # No state content is included in this operational event.
                    self.logger.event("ERROR", "retention", "cleanup_failed",
                                      processed_at=datetime.now(timezone.utc).isoformat(), failure_count=1)
                summary.add(self._poll_imap(max_mails))
                if not self.stop_event.is_set():
                    self._poll_telegram()
                if max_mails is not None:
                    break
                self.stop_event.wait(self.settings.poll_interval_seconds)
        finally:
            try:
                self.telegram.send(self.settings.telegram.chat_id, summary.message())
            except Exception as exc:
                self.logger.event("ERROR", "telegram", "run_summary_failed", error=str(exc))
            else:
                self.logger.event("INFO", "telegram", "run_summary_sent",
                                  completed=summary.completed, waiting=summary.waiting,
                                  failed=summary.failed)


def _safe_name(folder: str) -> str:
    return folder.encode("utf-8").hex()


def _checkpoint_name(account: str, folder: str) -> str:
    return f"imap-{account}-{_safe_name(folder)}"


def _state_directory(settings: Settings, base_directory: Path) -> Path:
    """Return the fully isolated state namespace for the selected mode."""
    root = settings.data_directory if settings.data_directory.is_absolute() else base_directory / settings.data_directory
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
    if not log_dir.is_absolute():
        log_dir = base_directory / log_dir
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
    )


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
) -> Iterator[Application]:
    """Construct adapters and close every successfully constructed resource."""
    with ExitStack() as stack:
        data = _state_directory(settings, base_directory)
        store = stack.enter_context(JsonStore(data))
        if logger is None or access_diagnostics:
            logger = build_logger(
                settings, secrets, base_directory,
                access_diagnostics=access_diagnostics,
            )
        stop_event = Event()
        def policy(name: str) -> RetryPolicy:
            item = getattr(settings.timeouts, name)
            return RetryPolicy(item.retries, item.initial_backoff_seconds, item.max_backoff_seconds, stop_event.wait)
        imap_cfg = settings.timeouts.imap
        factory = imaplib.IMAP4_SSL if settings.imap.connection_mode == "ssl" else imaplib.IMAP4
        imap = ImapReader(settings.imap.host, settings.imap.port, secrets.imap_username, secrets.imap_password.get_secret_value(), imap_cfg.timeout_seconds, factory=factory, policy=policy("imap"), logger=logger, starttls=settings.imap.connection_mode == "starttls", batch_size=settings.imap.batch_size)
        stack.callback(imap.close)
        llm_cfg = settings.timeouts.openrouter
        openrouter = OpenRouterClient(secrets.openrouter_api_key.get_secret_value(), llm_cfg.timeout_seconds, llm_cfg.retries, settings.limits.llm_calls_per_minute, initial_backoff=llm_cfg.initial_backoff_seconds, max_backoff=llm_cfg.max_backoff_seconds, load_calls=lambda: store.load("llm-budget", {}).get("calls", []), save_calls=lambda calls: store.save("llm-budget", {"calls": calls}), logger=logger)
        stack.callback(openrouter.close)
        telegram = TelegramClient(secrets.telegram_bot_token.get_secret_value(), settings.timeouts.telegram.timeout_seconds, poll_timeout=settings.timeouts.telegram_poll_seconds, policy=policy("telegram"), logger=logger)
        stack.callback(telegram.close)
        todoist = HttpWriter("todoist", secrets.todoist_token.get_secret_value(), settings.targets.todoist_project, settings.timeouts.todoist.timeout_seconds, policy=policy("todoist"), logger=logger)
        stack.callback(todoist.close)
        calendar = CalendarFileWriter(telegram, settings.telegram.chat_id, logger)
        analyzer = Analyzer(openrouter, prompts, settings.retries.validation)
        dialog = TelegramDialogController(
            store, telegram, settings.telegram.user_id, settings.telegram.chat_id, logger,
            {"todoist": todoist, "google_calendar": calendar}, settings.test_mode,
            settings.timezone,
            analyzer,
        )
        orchestrator = Orchestrator(analyzer, store, dialog, settings.telegram.chat_id, topics, settings.limits.max_mail_bytes, logger, mime_limits=settings.limits, config_fingerprint=fingerprint, targets=settings.targets, user_timezone=settings.timezone)
        dialog.relevance_handler = orchestrator
        orchestrator.stop_event = stop_event
        yield Application(settings, store, logger, imap, openrouter, analyzer, telegram, todoist, calendar, orchestrator, stop_event, dialog)
