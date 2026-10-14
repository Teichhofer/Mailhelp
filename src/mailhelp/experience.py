"""Composition and minute scheduler for the optional 2.0 services."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from threading import Event, Thread
from typing import TYPE_CHECKING

from .activity.llm import ActivityAnalyzer
from .activity.runner import ActivityRunner, available_report_folders, default_report_folders
from .activity.service import ActivityService
from .activity.store import ActivityReportStore
from .briefing import DailyBriefingService
from .drafts import DraftService, DraftTarget
from .imap import ImapReader, mailbox_account_id, reader_arguments
from .webpush import PushService

ACTIVITY_PROMPTS = {"activity_relevance", "activity_events"}
if TYPE_CHECKING:
    from .notification_runtime import NotificationRuntime


@contextmanager
def _reader(settings, secrets, mailbox):
    """One IMAP session of *mailbox*; closed again on every exit."""
    address, options = reader_arguments(mailbox, secrets.imap_credentials(mailbox.id))
    reader = ImapReader(*address, settings.timeouts.imap.timeout_seconds, **options)
    try:
        yield reader
    finally:
        reader.close()


def _draft_targets(settings, secrets):
    """Drafts go to the mailbox the mail came from, keyed by its account id (3.1)."""
    def target(mailbox):
        @contextmanager
        def connection():
            with _reader(settings, secrets, mailbox) as reader:
                yield reader.connection
        return DraftTarget(connection, secrets.imap_credentials(mailbox.id).username, mailbox.drafts_folder)
    return {mailbox_account_id(mailbox, secrets.imap_credentials(mailbox.id)): target(mailbox)
            for mailbox in settings.imap.enabled_mailboxes()}


class ExperienceRuntime:
    def __init__(self, app, components, secrets):
        self.app, self.site = app, components.site
        self.notifications: NotificationRuntime | None = None
        self.stop_event, self.thread = Event(), None
        settings = app.settings
        feature = self.site.experience
        if settings.push.enabled:
            feature.push = PushService(app.store, components.auth, settings.push.subject)
        # Drafts are generated only on request in the web interface; without the
        # draft_reply prompt (prompts.yaml of an earlier release) they stay off.
        from .mailbox_settings import effective_settings

        if (
            any(effective_settings(settings, box.id).smart_reply for box in settings.imap.enabled_mailboxes())
            and "draft_reply" in app.analyzer.prompts.prompts
        ):
            self.mailbox_numbers = {mailbox_account_id(box, secrets.imap_credentials(box.id)): box.id
                                    for box in settings.imap.enabled_mailboxes()}
            targets = _draft_targets(settings, secrets)
            first = next(iter(targets.values()))
            feature.drafts = DraftService(app.store, components.auth.active, first.connection, first.sender,
                first.folder, settings.test_mode, app.analyzer, lambda: app.settings.personal_info,
                targets=targets.get, mailbox_policy=self.draft_policy)
        self.activity = None
        # Activity reports only read the mailbox; without both prompts they stay off.
        if settings.activity_report.enabled and ACTIVITY_PROMPTS <= set(app.analyzer.prompts.prompts):
            def open_reader(mailbox):
                configured = app.settings.imap.mailbox(mailbox)
                if configured is None or not configured.enabled:
                    raise LookupError("Postfach des Berichts ist nicht mehr eingerichtet")
                return _reader(app.settings, secrets, configured)
            service = ActivityService(ActivityReportStore(app.store))
            service.active = components.auth.active
            service.blocked_senders = lambda: (
                list(self.site.archive.configuration.blocked_senders().addresses),
                list(self.site.archive.configuration.blocked_senders().domains))
            service.mailbox_senders = lambda number: self.site.archive.configuration.blocked_senders()
            self.activity = ActivityRunner(
                service,
                ActivityAnalyzer(
                    app.analyzer,
                    lambda: app.settings.personal_info,
                    mailbox_personal_info=lambda number: effective_settings(app.settings, number).personal_info,
                ),
                open_reader,
                settings,
                app.logger,
                llm_calls_per_minute=lambda: app.settings.limits.llm_calls_per_minute,
            )
            pages = self.site.activity
            pages.service = service
            pages.mailboxes = lambda: [(item.id, item.label) for item in app.settings.imap.enabled_mailboxes()]
            def suggested(mailbox):
                configured = app.settings.imap.mailbox(mailbox)
                if configured.activity_report_folder is not None:
                    return [configured.activity_report_folder]
                return default_report_folders(lambda: open_reader(mailbox), configured.folders)
            pages.suggest_folders = suggested
            pages.available_folders = lambda mailbox: available_report_folders(lambda: open_reader(mailbox))
            pages.with_unscheduled = settings.activity_report.export_mails_without_events
        channels: dict[str, Callable[[str], object]] = {"local": lambda _text: None}
        if settings.telegram.enabled:
            channels["telegram"] = lambda text: app.telegram.send(settings.telegram.chat_id, text)
        if feature.push is not None:
            channels["push"] = lambda _text: feature.push.notify("briefing")
        self.briefing = DailyBriefingService(app.store, settings.daily_briefing, settings.timezone,
            app.calendar, app.todoist, self.site.views, channels)
        from .mailbox_briefing import configure
        configure(app, self.briefing, self.site.views)

    def draft_policy(self, account):
        from .mailbox_settings import effective_settings
        number = self.mailbox_numbers.get(account, 1)
        cfg = effective_settings(self.app.settings, number)
        return cfg.smart_reply, cfg.personal_info

    def _section(self, name, step):
        """Push and briefing fail independently of each other."""
        try:
            step()
        except Exception as exc:
            self.app.logger.event("WARNING", "experience", f"{name}_failed", error_class=type(exc).__name__)

    def _push(self):
        overview = self.site.views.overview()
        identities = sorted([f"{v.mail_id}:{v.proposal_id}:{v.version}" for v in overview.open]
                            + [f"{v.mail_id}:relevance:{v.version}" for v in overview.relevance])
        previous = self.app.store.load("push-decisions", [])
        self.app.store.save("push-decisions", identities)
        if set(identities) - set(previous):
            self.site.experience.push.notify()

    def tick(self):
        feature = self.site.experience
        if self.notifications is not None:
            self._section("notifications", self.notifications.tick)
        elif feature.push is not None:
            self._section("push", self._push)
        self.briefing.settings = self.app.settings.daily_briefing
        if self.activity is not None:
            # Limits changed in the settings apply to the next mail of a running report.
            self.activity.settings = self.app.settings
            self.site.activity.with_unscheduled = self.app.settings.activity_report.export_mails_without_events
        if self.notifications is None:
            self._section("briefing", self.briefing.tick)

    def run(self):
        while not self.stop_event.is_set():
            try:
                self.tick()
            except Exception as exc:
                self.app.logger.event("WARNING", "experience", "background_failed",
                                      error_class=type(exc).__name__)
            self.stop_event.wait(5)

    def start(self):
        if self.activity is not None:
            self.activity.start()
        self.thread = Thread(target=self.run, name="mailhelp-experience", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.activity is not None:
            self.activity.stop()
        if self.thread is not None:
            self.thread.join(timeout=15)
