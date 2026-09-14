"""Composition Root und kontrollierte Polling-Schleife des Dienstes."""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Iterator

from .analysis import Analyzer
from .config import PromptConfig, Secrets, Settings, Topic
from .imap import ImapReader
from .integrations import HttpWriter
from .logging import JsonlLogger
from .models import ImapCheckpoint, TelegramOffset
from .openrouter import OpenRouterClient
from .orchestrator import Orchestrator
from .storage import JsonStore
from .telegram import TelegramClient, TelegramDialogController
from .adapter import RetryPolicy


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
    calendar: HttpWriter
    orchestrator: Orchestrator
    stop_event: Event
    dialog: TelegramDialogController | None = None

    def stop(self) -> None:
        self.stop_event.set()
        self.orchestrator.stop()

    def _poll_imap(self) -> None:
        for folder in self.settings.imap.folders:
            if self.stop_event.is_set():
                break
            checkpoint_model = self.store.load_model(f"imap-{_safe_name(folder)}", ImapCheckpoint, ImapCheckpoint()) if hasattr(self.store, "load_model") else ImapCheckpoint.model_validate(self.store.load(f"imap-{_safe_name(folder)}", {}))
            checkpoint = checkpoint_model.model_dump(exclude={"schema_version"})
            try:
                mails = self.imap.fetch_since(folder, checkpoint.get("uid", 0), checkpoint.get("uidvalidity"))
            except Exception as exc:
                self.logger.event("ERROR", "imap", "poll_failed", folder=folder, error=str(exc))
                continue
            for mail in mails:
                if self.stop_event.is_set():
                    break
                try:
                    self.orchestrator.process(mail)
                except Exception as exc:
                    self.logger.event("ERROR", "orchestrator", "mail_failed", folder=folder, uid=mail.uid, error=str(exc))
                self.store.save(f"imap-{_safe_name(folder)}", ImapCheckpoint(uidvalidity=mail.uidvalidity, uid=mail.uid).model_dump())
            if not mails and self.imap.last_uidvalidity is not None:
                uid = checkpoint.get("uid", 0) if checkpoint.get("uidvalidity") == self.imap.last_uidvalidity else 0
                self.store.save(f"imap-{_safe_name(folder)}", ImapCheckpoint(uidvalidity=self.imap.last_uidvalidity, uid=uid).model_dump())

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

    def run(self) -> None:
        while not self.stop_event.is_set():
            self._poll_imap()
            if not self.stop_event.is_set():
                self._poll_telegram()
            self.stop_event.wait(self.settings.poll_interval_seconds)


def _safe_name(folder: str) -> str:
    return folder.encode("utf-8").hex()


@contextmanager
def build_application(settings: Settings, secrets: Secrets, topics: list[Topic], prompts: PromptConfig, base_directory: Path = Path(".")) -> Iterator[Application]:
    """Construct adapters and close every successfully constructed resource."""
    with ExitStack() as stack:
        data = settings.data_directory if settings.data_directory.is_absolute() else base_directory / settings.data_directory
        log_dir = settings.logging.directory
        if not log_dir.is_absolute():
            log_dir = base_directory / log_dir
        store = stack.enter_context(JsonStore(data))
        known_secrets = tuple(value.get_secret_value() for value in (
            secrets.imap_password, secrets.openrouter_api_key, secrets.telegram_bot_token,
            secrets.todoist_token, secrets.google_access_token,
        ))
        logger = JsonlLogger(log_dir, settings.logging.include_llm_requests, settings.logging.include_llm_responses,
                             settings.logging.level, settings.logging.module_levels, known_secrets)
        stop_event = Event()
        def policy(name: str) -> RetryPolicy:
            item = getattr(settings.timeouts, name)
            return RetryPolicy(item.retries, item.initial_backoff_seconds, item.max_backoff_seconds, stop_event.wait)
        imap_cfg = settings.timeouts.imap
        imap = ImapReader(settings.imap.host, settings.imap.port, secrets.imap_username, secrets.imap_password.get_secret_value(), imap_cfg.timeout_seconds, policy=policy("imap"), logger=logger)
        stack.callback(imap.close)
        llm_cfg = settings.timeouts.openrouter
        openrouter = OpenRouterClient(secrets.openrouter_api_key.get_secret_value(), llm_cfg.timeout_seconds, llm_cfg.retries, settings.limits.llm_calls_per_minute, initial_backoff=llm_cfg.initial_backoff_seconds, max_backoff=llm_cfg.max_backoff_seconds, load_calls=lambda: store.load("llm-budget", {}).get("calls", []), save_calls=lambda calls: store.save("llm-budget", {"calls": calls}), logger=logger)
        stack.callback(openrouter.close)
        telegram = TelegramClient(secrets.telegram_bot_token.get_secret_value(), settings.timeouts.telegram.timeout_seconds, poll_timeout=settings.timeouts.telegram_poll_seconds, policy=policy("telegram"), logger=logger)
        stack.callback(telegram.close)
        todoist = HttpWriter("todoist", secrets.todoist_token.get_secret_value(), settings.targets.todoist_project, settings.timeouts.todoist.timeout_seconds, policy=policy("todoist"), logger=logger)
        stack.callback(todoist.close)
        calendar = HttpWriter("google_calendar", secrets.google_access_token.get_secret_value(), settings.targets.google_calendar, settings.timeouts.google_calendar.timeout_seconds, policy=policy("google_calendar"), logger=logger)
        stack.callback(calendar.close)
        analyzer = Analyzer(openrouter, prompts, settings.retries.validation)
        dialog = TelegramDialogController(
            store, telegram, settings.telegram.user_id, settings.telegram.chat_id, logger,
            {"todoist": todoist, "google_calendar": calendar}, settings.test_mode,
        )
        orchestrator = Orchestrator(analyzer, store, dialog, settings.telegram.chat_id, topics, settings.limits.max_mail_bytes, logger, mime_limits=settings.limits)
        orchestrator.stop_event = stop_event
        yield Application(settings, store, logger, imap, openrouter, analyzer, telegram, todoist, calendar, orchestrator, stop_event, dialog)
