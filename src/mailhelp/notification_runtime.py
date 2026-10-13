"""Bridge existing decision, briefing and result services to the shared queue."""
from __future__ import annotations

import hashlib
from threading import Event, Thread
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from .briefing import DailyBriefingService
from .notification_config import effective_profile
from .notifications import NotificationService, QueueFull
from .review.commands import CommandSource, ReviewCommand
from .review.inbox import COMMAND_INBOX, CommandInbox, CommandInboxState
from .review.views import ProposalView, ReviewViews


class NotificationRuntime:
    def __init__(self, app, site):
        self.app, self.site = app, site
        if app.dialog.commands is None:
            app.dialog.commands = CommandInbox(app.store)
            site.commands = app.dialog.commands
        app.dialog.review.completed = self.completed
        app.telegram.route_background = True
        self.stop_event, self.thread = Event(), None
        self.queue = NotificationService(app.store, lambda: app.settings, self.destinations,
                                         self.relevant, self.send, logger=app.logger)
        self.briefing = DailyBriefingService(app.store, app.settings.daily_briefing, app.settings.timezone,
            app.calendar, app.todoist, site.views, {"local": lambda text: None})
        self._migrate()
        app.dialog.outbox.background = self.background
        # Old queued references are transferred before the old outbox is drained.
        old = app.dialog.outbox.load()
        for entry in old.entries:
            if entry.status == "queued":
                try:
                    self.background(entry.model_dump())
                except QueueFull:
                    break
        old.entries = []
        app.store.save("telegram-outbox", old.model_dump(mode="json"))

    @classmethod
    def without_web(cls, app):
        site = SimpleNamespace(views=ReviewViews(app.store, app.settings.timezone, app.settings.test_mode),
                               commands=app.dialog.commands, experience=SimpleNamespace(push=None))
        return cls(app, site)

    def decisions(self):
        overview = self.site.views.overview()
        return {(f"{row.mail_id}:{row.proposal_id}", row.version): row for row in overview.open} | {
            (f"{row.mail_id}:relevance", row.version): row for row in overview.relevance}

    def destinations(self, category):
        cfg = self.app.settings
        channels = getattr(effective_profile(cfg).categories, category)
        result = []
        if "telegram" in channels and cfg.telegram.enabled:
            result.append(("telegram", ""))
        push = self.site.experience.push
        if "web_push" in channels and cfg.push.enabled and push is not None:
            result.extend(("web_push", device) for device in push.destinations())
        return result

    def relevant(self, item):
        if item.category == "decisions":
            return (item.reference, item.version) in self.decisions()
        if item.category == "daily_briefing":
            now = self.queue.clock().astimezone(ZoneInfo(self.app.settings.timezone))
            return self.app.settings.daily_briefing.enabled and item.reference == now.date().isoformat()
        if item.category == "action_results":
            entry = self.site.commands.get(item.reference)
            return entry is not None and entry.result is not None
        health = self.app.store.load("service-health", {"errors": {}, "version": 0})
        if item.reference.startswith("service:"):
            return item.reference.removeprefix("service:") in health["errors"] and item.version == health["version"]
        return any(f"{row.mail_id}:{row.stage}:{row.cause}" == item.reference
                   for row in self.site.views.system(self.queue.clock()).errors)

    def send(self, items, profile):
        first = items[0]
        if first.channel == "web_push":
            self.site.experience.push.deliver(first.device, first.category)
            return
        text = {"decisions": "Entscheidungen warten in Mailhelp. Öffne /offen oder die Weboberfläche.",
                "daily_briefing": "Der Tagesüberblick ist in Mailhelp verfügbar.",
                "action_results": "Ein Aktionsergebnis ist in Mailhelp verfügbar.",
                "system_errors": "Betriebsproblem in Mailhelp. Bitte Diagnose prüfen."}[first.category]
        if profile.telegram_content == "summary":
            if first.category == "daily_briefing":
                text = self.app.store.load("briefing-latest", {}).get("text", text)
            elif first.category == "decisions":
                rows = self.decisions()
                text = "Entscheidungen in Mailhelp:\n" + "\n".join(
                    str(rows[(item.reference, item.version)].subject) for item in items)[:3500]
            elif first.category == "action_results":
                text = "\n".join(self.site.commands.get(item.reference).result.message for item in items)[:3500]
        self.app.telegram.send(self.app.settings.telegram.chat_id, text)

    def background(self, reference):
        kind = reference["kind"]
        if kind != "message":
            proposal = reference.get("proposal_id") or "relevance"
            self.enqueue_decision(f"{reference['mail_id']}:{proposal}", reference["version"])
        # Summary-only mail messages are visible in the authenticated mail view;
        # they never gain a second identity beside their decisions.
        return hashlib.sha256(str(reference).encode()).hexdigest()[:32]

    def completed(self, command, result):
        if isinstance(command, ReviewCommand) and command.source == CommandSource.TELEGRAM:
            self.site.commands.record_completed(command, result)

    def _migrate(self):
        if self.app.store.load("notifications-migration") is not None:
            return
        if self.app.store.load("notifications-backup") is None:
            markers = {}
            old = self.app.dialog.outbox.load()
            interrupted = {(entry.mail_id, entry.proposal_id, entry.version) for entry in old.entries
                           if entry.status == "sending"}
            previous = set(self.app.store.load("push-decisions", []))
            for (reference, version), row in self.decisions().items():
                statuses = {}
                if f"{reference}:{version}" in previous:
                    statuses["web_push"] = "sent"
                if isinstance(row, ProposalView):
                    proposal = self.app.dialog.repository.load_current(row.mail_id, row.proposal_id)
                    marker = self.app.dialog.repository.notification_status(proposal)
                    if (row.mail_id, row.proposal_id, row.version) in interrupted or marker == "sending":
                        statuses["telegram"] = "uncertain"
                    elif marker == "completed":
                        statuses["telegram"] = "sent"
                elif (row.mail_id, row.version) not in self.app.dialog.outbox.queued_relevance():
                    statuses["telegram"] = "uncertain"
                markers[f"{reference}:{version}"] = statuses
            self.app.store.save("notifications-backup", {
                "schema_version": 1, "decision_markers": markers,
                "push_decisions": self.app.store.load("push-decisions", []),
                "daily_briefing": self.app.store.load("daily-briefing", {}),
                "outbox": old.model_dump(mode="json", exclude={"entries": {
                    "__all__": {"text", "sender", "subject"}}}),
                "queue": self.app.store.load("notification-queue", None)})
        self.app.store.save("notifications-migration", {"schema_version": 1})
        commands = self.app.store.load_model(COMMAND_INBOX, CommandInboxState, CommandInboxState())
        self.app.store.save("notification-results", [entry.id for entry in commands.entries
                                                      if entry.result is not None])

    def tick(self):
        try:
            self._produce()
        except QueueFull:
            # Sources remain durable. Drain existing items before trying to add more.
            pass
        finally:
            self.queue.tick()

    def _produce(self):
        for reference, version in self.decisions():
            try:
                self.enqueue_decision(reference, version)
            except QueueFull:
                break
        commands = self.app.store.load_model(COMMAND_INBOX, CommandInboxState, CommandInboxState())
        marked = set(self.app.store.load("notification-results", []))
        current = {entry.id for entry in commands.entries}
        for entry in commands.entries:
            if entry.id not in marked and entry.result is not None and isinstance(entry.command, ReviewCommand):
                exclude = ("telegram",) if entry.command.source == CommandSource.TELEGRAM else ()
                self.queue.enqueue("action_results", entry.id, exclude_channels=exclude)
                marked.add(entry.id)
        self.app.store.save("notification-results", sorted(marked & current))
        for row in self.site.views.system(self.queue.clock()).errors:
            self.queue.enqueue("system_errors", f"{row.mail_id}:{row.stage}:{row.cause}")
        health = self.app.store.load("service-health", {"errors": {}, "version": 0})
        for name in health["errors"]:
            self.queue.enqueue("system_errors", "service:" + name, health["version"])
        self.briefing.settings = self.app.settings.daily_briefing
        self.briefing.zone = ZoneInfo(self.app.settings.timezone)
        previous = self.app.store.load("daily-briefing", {})
        self.briefing.tick()
        latest = self.app.store.load("briefing-latest")
        if latest is not None and self.app.settings.daily_briefing.enabled:
            self.queue.enqueue("daily_briefing", latest["day"])
            # Existing 2.x markers survive an upgrade before today's briefing.
            if previous.get("day") == latest["day"]:
                state = self.queue.state()
                for item in state.entries.values():
                    old = "push" if item.channel == "web_push" else "telegram"
                    if (item.category == "daily_briefing" and item.reference == latest["day"]
                            and item.status == "pending" and old in previous.get("channels", {})):
                        item.status = previous["channels"][old]
                self.app.store.save("notification-queue", state.model_dump(mode="json"))

    def enqueue_decision(self, reference, version):
        try:
            self.queue.enqueue("decisions", reference, version)
        finally:
            markers = self.app.store.load("notifications-backup", {}).get("decision_markers", {})
            statuses = markers.get(f"{reference}:{version}", {})
            with self.app.store.locked():
                state = self.queue.state()
                for item in state.entries.values():
                    if ((item.category, item.reference, item.version) == ("decisions", reference, version)
                            and item.status == "pending" and item.attempts == 0 and item.channel in statuses):
                        item.status = statuses[item.channel]
                self.app.store.save("notification-queue", state.model_dump(mode="json"))

    def run(self):
        while not self.stop_event.is_set():
            try:
                self.tick()
            except Exception as exc:
                self.app.logger.event("WARNING", "notifications", "background_failed",
                                      error_class=type(exc).__name__)
            self.stop_event.wait(5)

    def start(self):
        self.thread = Thread(target=self.run, name="mailhelp-notifications", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=15)
