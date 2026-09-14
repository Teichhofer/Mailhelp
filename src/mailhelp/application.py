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
from .openrouter import OpenRouterClient
from .orchestrator import Orchestrator
from .storage import JsonStore
from .telegram import TelegramClient, TelegramDialogController


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
        for folder in self.settings.imap["folders"]:
            if self.stop_event.is_set():
                break
            checkpoint = self.store.load(f"imap-{_safe_name(folder)}", {})
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
                self.store.save(f"imap-{_safe_name(folder)}", {"uidvalidity": mail.uidvalidity, "uid": mail.uid})
            if not mails and self.imap.last_uidvalidity is not None:
                uid = checkpoint.get("uid", 0) if checkpoint.get("uidvalidity") == self.imap.last_uidvalidity else 0
                self.store.save(f"imap-{_safe_name(folder)}", {"uidvalidity": self.imap.last_uidvalidity, "uid": uid})

    def _poll_telegram(self) -> None:
        if self.dialog is not None:
            try:
                self.dialog.poll_once()
            except Exception as exc:
                self.logger.event("ERROR", "telegram", "poll_failed", error=str(exc))
            return
        state = self.store.load("telegram-offset", {"offset": 0})
        try:
            updates = self.telegram.poll(state["offset"])
        except Exception as exc:
            self.logger.event("ERROR", "telegram", "poll_failed", error=str(exc))
            return
        for update in updates:
            offset = int(update["update_id"]) + 1
            self.store.save("telegram-offset", {"offset": offset})
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
        log_dir = Path(settings.logging["directory"])
        if not log_dir.is_absolute():
            log_dir = base_directory / log_dir
        store = stack.enter_context(JsonStore(data))
        logger = JsonlLogger(log_dir, settings.logging.get("include_llm_requests", False), settings.logging.get("include_llm_responses", False))
        imap = ImapReader(settings.imap["host"], settings.imap["port"], secrets.imap_username, secrets.imap_password.get_secret_value())
        stack.callback(imap.close)
        openrouter = OpenRouterClient(secrets.openrouter_api_key.get_secret_value(), 30, settings.retries["network"], settings.limits["llm_calls_per_minute"])
        stack.callback(openrouter.close)
        telegram = TelegramClient(secrets.telegram_bot_token.get_secret_value(), 35)
        stack.callback(telegram.close)
        todoist = HttpWriter("todoist", secrets.todoist_token.get_secret_value(), settings.targets["todoist_project"])
        stack.callback(todoist.close)
        calendar = HttpWriter("google_calendar", secrets.google_access_token.get_secret_value(), settings.targets["google_calendar"])
        stack.callback(calendar.close)
        analyzer = Analyzer(openrouter, prompts, settings.retries["validation"])
        dialog = TelegramDialogController(
            store, telegram, settings.telegram["user_id"], settings.telegram["chat_id"], logger,
            {"todoist": todoist, "google_calendar": calendar}, settings.test_mode,
        )
        orchestrator = Orchestrator(analyzer, store, dialog, settings.telegram["chat_id"], topics, settings.limits["max_mail_bytes"])
        yield Application(settings, store, logger, imap, openrouter, analyzer, telegram, todoist, calendar, orchestrator, orchestrator.stop_event, dialog)
