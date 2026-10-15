"""Start and stop of the helpers around the mail loop (Planung 3.3, pillar 2).

The Telegram receiver thread, the optional web interface with its experience
runtime and the notification runtime run beside the polling loop of
:class:`~mailhelp.application.Application`; none of them may block mail processing.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .logging import JsonlLogger, log_and_continue
from .telegram.receiver import TelegramInbox, TelegramReceiver, UpdateSource
from .web import WebServer, WebServerError

if TYPE_CHECKING:
    from .experience import ExperienceRuntime
    from .notification_runtime import NotificationRuntime


@dataclass
class ServiceCoordinator:
    web: WebServer | None = None
    experience: ExperienceRuntime | None = None
    notifications: NotificationRuntime | None = None
    receiver: TelegramReceiver | None = None

    def start_receiver(self, inbox: object, telegram: UpdateSource, offset: Callable[[], int],
                       logger: JsonlLogger, backoff_seconds: float) -> None:
        """Receive Telegram input in its own thread if the dialog has an inbox."""
        if not isinstance(inbox, TelegramInbox):
            return
        self.receiver = TelegramReceiver(telegram, inbox, offset(), logger, backoff_seconds)
        self.receiver.start()

    def stop_receiver(self) -> None:
        receiver, self.receiver = self.receiver, None
        if receiver is not None:
            receiver.stop()
            # A long-poll in flight ends with the Telegram client; never block exit.
            receiver.join(timeout=1)

    def start_web(self, logger: JsonlLogger, notify: Callable[[str], None]) -> None:
        """Start the optional web interface; mail processing continues without it."""
        if self.web is None:
            if self.notifications is not None:
                self.notifications.start()
            return
        try:
            self.web.start()
            if self.experience is not None:
                self.experience.start()
        except WebServerError as exc:
            logger.event("ERROR", "web", "server_start_failed", error=str(exc))
            self.web = None
            try:
                notify(f"⚠️ {exc}. Mailhelp läuft ohne Weboberfläche weiter.")
            except Exception as notification_error:
                log_and_continue(logger, "telegram", "web_start_notice_failed", notification_error)

    def stop_web(self) -> None:
        if self.notifications is not None:
            self.notifications.stop()
        if self.experience is not None:
            self.experience.stop()
        web, self.web = self.web, None
        if web is not None:
            web.stop()
