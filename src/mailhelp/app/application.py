"""Kontrollierte Polling-Schleife des Dienstes; der Aufbau steht in composition.py."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import Event, Lock, Thread
from typing import TYPE_CHECKING, Any

from ..config import RetentionPeriod, Settings, Topic
from ..domain.mail import MailState
from ..domain.run import MailRunState
from ..external.contracts import OAuthTokenError, TargetWriter
from ..llm.openrouter import OpenRouterClient
from ..logging import JsonlLogger, log_and_continue
from ..mailbox.imap import ImapReader
from ..mailbox.mailbox_run import MailboxRunService, MailboxSource
from ..mailbox.mailbox_settings import effective_settings
from ..persistence.storage import JsonStore
from ..processing.analysis import Analyzer
from ..processing.orchestrator import Orchestrator, ProcessingResult
from ..proposals.target_profiles import ProfileWriters
from ..runtime.retention import RetentionService
from ..telegram import TelegramClient, TelegramDialogController
from ..web import WebServer
from . import access_checks, run_loop
from .service_coordinator import ServiceCoordinator

if TYPE_CHECKING:
    from ..config.configuration import ConfigurationService
    from ..external.providers import Writers
    from ..mailbox.imap import FetchedMail
    from ..mailbox.iserv import IServRunService
    from ..mailbox.iserv_runtime import IServRuntime
    from ..mailbox.mailbox_runtime import MailboxRuntime
    from ..notifications.notification_runtime import NotificationRuntime
    from ..proposals.target_profiles import ProfileWriters
    from ..runtime.experience import ExperienceRuntime
    from ..runtime.lifecycle import Lifecycle
    from ..runtime.standalone import DisabledTelegram

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
    todoist: TargetWriter
    calendar: TargetWriter
    orchestrator: Orchestrator
    stop_event: Event
    dialog: TelegramDialogController | None = None
    sender_store: JsonStore | None = None
    _wait_for_user: bool = False
    _fatal_error: str | None = None
    # Web stop handshake; its final state is set when the run loop ends.
    lifecycle: Lifecycle | None = None
    configuration: ConfigurationService | None = None
    # One writer pair, or one per target profile (3.2).
    profile_writers: Writers | ProfileWriters | None = None
    # Parent letters of IServ accounts (3.3.7); ``None`` without configured accounts.
    iserv: IServRunService | None = None
    iserv_runtime: IServRuntime | None = None
    # Mailboxes activated in the web interface, installed between cycles (3.5).
    mailbox_runtime: MailboxRuntime | None = None
    resources: Any = None
    reload: Any = None
    web_site: Any = None
    # Monotonic time of the last maintenance run; it blocks the main thread and runs at an interval.
    _maintained_at: float | None = None
    # Settings and topics saved by a web command, taken over by the mail loop at its next cycle (3.6.4).
    _pending_settings: Settings | None = None
    _pending_topics: list[Topic] | None = None
    _pending_lock: Lock = field(default_factory=Lock, repr=False)
    # Receiver thread, web interface, experience and notification runtimes beside the loop.
    services: ServiceCoordinator = field(default_factory=ServiceCoordinator)
    # Every enabled mailbox with its reader (3.1); ``imap`` is the reader of the first one.
    sources: list[MailboxSource] = field(default_factory=list)

    mailbox: MailboxRunService = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.sources:
            self.sources = [MailboxSource(self.settings.imap.enabled_mailboxes()[0], self.imap)]
        self.mailbox = MailboxRunService(
            self.settings, self.store, self.logger, self.sources, self.orchestrator,
            self.stop_event, self._process_mail,
        )

    def check_access(self) -> dict[str, str | None]:
        return access_checks.check_access(self)

    def confirm_access_in_background(self) -> Thread:
        return access_checks.confirm_access_in_background(self)

    def confirm_access(self) -> None:
        return access_checks.confirm_access(self)

    def _active_writers(self) -> list[TargetWriter]:
        return access_checks._active_writers(self)

    def _check_telegram_access(self) -> None:
        return access_checks._check_telegram_access(self)

    def request_settings(self, settings: Settings) -> None:
        """Remember live settings from the operator thread; the mail loop applies them."""
        with self._pending_lock:
            self._pending_settings = settings

    def request_topics(self, topics: list[Topic]) -> None:
        """Remember changed topics; a fingerprint never changes during a mail's processing."""
        with self._pending_lock:
            self._pending_topics = topics

    def _apply_requested_configuration(self) -> None:
        with self._pending_lock:
            settings, topics = self._pending_settings, self._pending_topics
            self._pending_settings = self._pending_topics = None
        if settings is not None:
            self.apply_settings(settings)
        if topics is not None:
            self.orchestrator.change_topics(topics)

    def apply_settings(self, settings: Settings) -> None:
        """Main-thread activation of the explicitly live configuration subset."""
        self.settings = settings
        self.mailbox.settings = settings
        self.orchestrator.event_defaults = settings.event_defaults
        self.orchestrator.mailbox_settings = settings
        self.orchestrator.reconciliation_settings = settings.proposal_reconciliation
        self.orchestrator.reconciliation.max_candidates = settings.proposal_reconciliation.max_semantic_candidates
        # Cached web views depend on settings such as target profiles.
        self.store.touch()
        learning = getattr(self.dialog, "learning", None)
        if learning is not None:
            learning.period = settings.retention.decision_learning_days
        metrics = self.logger.metrics
        assert metrics is not None  # attached together with the logger (_attach_metrics)
        metrics.settings = settings.metrics
        if metrics.comparison is not None:
            metrics.comparison.settings = settings.metrics

    @property
    def web(self) -> WebServer | None:
        return self.services.web

    @web.setter
    def web(self, web: WebServer | None) -> None:
        self.services.web = web

    @property
    def experience(self) -> ExperienceRuntime | None:
        return self.services.experience

    @experience.setter
    def experience(self, experience: ExperienceRuntime | None) -> None:
        self.services.experience = experience

    @property
    def notifications(self) -> NotificationRuntime | None:
        return self.services.notifications

    @notifications.setter
    def notifications(self, notifications: NotificationRuntime | None) -> None:
        self.services.notifications = notifications

    def stop(self) -> None:
        self.stop_event.set()
        self.orchestrator.stop()
        if self.services.operator is not None:
            self.services.operator.stop()
        if self.services.receiver is not None:
            self.services.receiver.stop()

    def _start_receiver(self) -> None:
        dialog = self.dialog
        if dialog is not None:
            # The offset is read only once the dialog proves to have an inbox.
            self.services.start_receiver(getattr(dialog, "inbox", None), self.telegram,
                                         lambda: dialog.receive_offset(), self.logger, _TELEGRAM_ERROR_BACKOFF_SECONDS)

    def _start_web(self) -> None:
        self.services.start_web(self.logger, lambda text: self.telegram.send(self.settings.telegram.chat_id, text))

    def _start_operator(self) -> None:
        """From here on, Telegram input and web commands no longer wait for mail processing."""
        if self.dialog is not None:
            self.services.start_operator(
                lambda: self._poll_telegram(timeout=0),
                min(self.settings.poll_interval_seconds, _TELEGRAM_ERROR_BACKOFF_SECONDS),
                self.settings.poll_interval_seconds)

    def _idle(self, delay: float) -> None:
        return run_loop._idle(self, delay)

    def _poll_imap(self, max_mails: int | None = None, *,
                   ignore_historical_start: bool = False) -> list[ProcessingResult]:
        return run_loop._poll_imap(self, max_mails, ignore_historical_start=ignore_historical_start)


    def _poll_telegram(self, timeout: int | None = None) -> bool:
        return run_loop._poll_telegram(self, timeout)

    def _stop_after_fatal_oauth_error(self, exc: OAuthTokenError) -> None:
        return run_loop._stop_after_fatal_oauth_error(self, exc)

    def _process_mail(self, mail: FetchedMail) -> ProcessingResult:
        return run_loop._process_mail(self, mail)
            # An unclear relevance answer interrupts analysis. Once Telegram
            # resolved it, resume this same mail before advancing the mailbox.

    def _wait_for_telegram_decision(self) -> bool:
        return run_loop._wait_for_telegram_decision(self)

    def run(self, max_mails: int | None = None, *,
            ignore_historical_start: bool = False) -> str | None:
        return run_loop.run(self, max_mails, ignore_historical_start=ignore_historical_start)

    def _announce_start(self) -> None:
        return run_loop._announce_start(self)

    def _maintain(self) -> None:
        now = time.monotonic()
        last = self._maintained_at
        if last is not None and now - last < self.settings.retention.cleanup_interval_minutes * 60:
            return
        self._maintained_at = now
        try:
            def period(state: MailState) -> RetentionPeriod:
                cfg = self.orchestrator.mailbox_settings
                number = (state.proposal_policy or {}).get(
                    "mailbox_id", self.orchestrator.mailbox_number(state.imap.account_id)
                )
                return (
                    effective_settings(cfg, number).retention.full_mail_days
                    if cfg is not None and cfg.imap.mailbox(number) is not None
                    else self.settings.retention.full_mail_days
                )

            RetentionService(self.store, self.settings.retention, self.logger, full_mail_period=period).run()
            metrics = getattr(self.logger, "metrics", None)
            if metrics is not None:
                metrics.maintain()
        except Exception as exc:
            # No state content is included in this operational event.
            log_and_continue(self.logger, "retention", "cleanup_failed", exc,
                             processed_at=datetime.now(UTC).isoformat(), failure_count=1)

    def _cycle(self, max_mails: int | None, ignore_historical_start: bool) -> bool:
        return run_loop._cycle(self, max_mails, ignore_historical_start)

    def _finish(self, max_mails: int | None) -> None:
        return run_loop._finish(self, max_mails)


    def _mailbox_lines(self, runs: list[MailRunState | None]) -> str:
        return run_loop._mailbox_lines(self, runs)

