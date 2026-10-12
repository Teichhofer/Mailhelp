"""Composition and minute scheduler for the optional 2.0 services."""
from contextlib import contextmanager
from threading import Event, Thread

from .briefing import DailyBriefingService
from .drafts import DraftService
from .imap import ImapReader
from .webpush import PushService


class ExperienceRuntime:
    def __init__(self, app, components, secrets):
        self.app, self.site = app, components.site
        self.stop_event, self.thread = Event(), None
        settings = app.settings
        feature = self.site.experience
        if settings.push.enabled:
            feature.push = PushService(app.store, components.auth, settings.push.subject)
        # Drafts are generated only on request in the web interface; without the
        # draft_reply prompt (prompts.yaml of an earlier release) they stay off.
        if settings.smart_reply and "draft_reply" in app.analyzer.prompts.prompts:
            @contextmanager
            def connection():
                import imaplib
                factory = imaplib.IMAP4_SSL if settings.imap.connection_mode == "ssl" else imaplib.IMAP4
                reader = ImapReader(settings.imap.host, settings.imap.port, secrets.imap_username,
                    secrets.imap_password.get_secret_value(), settings.timeouts.imap.timeout_seconds,
                    factory=factory, starttls=settings.imap.connection_mode == "starttls")
                try:
                    yield reader.connection
                finally:
                    reader.close()
            feature.drafts = DraftService(app.store, components.auth.active, connection,
                secrets.imap_username, settings.imap.drafts_folder, settings.test_mode, app.analyzer,
                lambda: app.settings.personal_info)
        channels = {"local": lambda _text: None}
        if settings.telegram.enabled:
            channels["telegram"] = lambda text: app.telegram.send(settings.telegram.chat_id, text)
        if feature.push is not None:
            channels["push"] = lambda _text: feature.push.notify("briefing")
        self.briefing = DailyBriefingService(app.store, settings.daily_briefing, settings.timezone,
            app.calendar, app.todoist, self.site.views, channels)

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
        if feature.push is not None:
            self._section("push", self._push)
        self.briefing.settings = self.app.settings.daily_briefing
        self._section("briefing", self.briefing.tick)

    def run(self):
        while not self.stop_event.is_set():
            try:
                self.tick()
            except Exception as exc:
                self.app.logger.event("WARNING", "experience", "background_failed",
                                      error_class=type(exc).__name__)
            self.stop_event.wait(60)

    def start(self):
        self.thread = Thread(target=self.run, name="mailhelp-experience", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=15)
