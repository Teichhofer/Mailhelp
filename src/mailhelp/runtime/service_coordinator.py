"""Start and stop of the helpers around the mail loop (Planung 3.3, pillar 2).

The Telegram receiver thread, the optional web interface with its experience
runtime and the notification runtime run beside the polling loop of
:class:`~mailhelp.runtime.application.Application`; none of them may block mail processing.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..logging import JsonlLogger, log_and_continue
from ..telegram.receiver import TelegramInbox, TelegramReceiver, UpdateSource
from ..web import WebServer, WebServerError
from .operator_thread import OperatorThread

if TYPE_CHECKING:
    from ..notifications.notification_runtime import NotificationRuntime
    from .diagnostics import DiagnosticsService
    from .experience import ExperienceRuntime
    from .learning_worker import LearningWorker
    from .oauth_web import BrowserOAuth
    from .reanalysis_worker import ReanalysisWorker


@dataclass
class ServiceCoordinator:
    diagnostics: DiagnosticsService | None = None
    learning: LearningWorker | None = None
    reanalysis: ReanalysisWorker | None = None
    help_chat: Any = None
    oauth: BrowserOAuth | None = None
    web: WebServer | None = None
    experience: ExperienceRuntime | None = None
    notifications: NotificationRuntime | None = None
    receiver: TelegramReceiver | None = None
    operator: OperatorThread | None = None

    def start_receiver(self, inbox: object, telegram: UpdateSource, offset: Callable[[], int],
                       logger: JsonlLogger, backoff_seconds: float) -> None:
        """Receive Telegram input in its own thread if the dialog has an inbox."""
        if not isinstance(inbox, TelegramInbox):
            return
        self.receiver = TelegramReceiver(telegram, inbox, offset(), logger, backoff_seconds)
        self.receiver.start()

    def start_operator(self, serve: Callable[[], bool], retry_seconds: float, idle_seconds: float) -> None:
        """Serve Telegram input and web commands in their own thread; needs the receiver's inbox."""
        if self.receiver is None:
            return
        inbox = self.receiver.inbox
        self.operator = OperatorThread(serve, inbox.wait, inbox.wake, retry_seconds, idle_seconds)
        self.operator.start()

    def stop_operator(self) -> None:
        operator, self.operator = self.operator, None
        if operator is not None:
            operator.stop()
            # A running command finishes first; adapter timeouts bound it.
            operator.join()

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
            if self.oauth is not None:
                self.oauth.start_worker()
            if self.learning is not None:
                self.learning.start()
            if self.reanalysis is not None:
                self.reanalysis.start()
            if self.help_chat is not None:
                self.help_chat.start()
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
        if self.diagnostics is not None:
            self.diagnostics.stop()
        if self.learning is not None:
            self.learning.stop()
        if self.reanalysis is not None:
            self.reanalysis.stop()
        if self.help_chat is not None:
            self.help_chat.stop()
        if self.oauth is not None:
            self.oauth.stop()
        if self.notifications is not None:
            self.notifications.stop()
        if self.experience is not None:
            self.experience.stop()
        web, self.web = self.web, None
        if web is not None:
            web.stop()
