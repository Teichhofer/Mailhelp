"""User actions on activity reports: version-checked, idempotent and serialized.

The web interface and the background run change a report only through this
service, under one lock.  Progress written by the run does not raise the
version, so a form the user is filling in stays valid while the report runs.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from contextvars import ContextVar
from datetime import UTC, date, datetime
from threading import RLock
from typing import Any

from .models import ActivityReport, ReportDefinition, ReportEvent, ReportMail, ReportStatus
from .store import ActivityReportStore

_KEY = re.compile(r"^[A-Za-z0-9_-]{8,80}$")
MAX_OPERATIONS = 200
# Allowed status changes per action; anything else is a stale form.
TRANSITIONS = {
    "start": ({ReportStatus.READY}, ReportStatus.RUNNING),
    "pause": ({ReportStatus.RUNNING}, ReportStatus.PAUSED),
    "resume": ({ReportStatus.PAUSED}, ReportStatus.RUNNING),
    "cancel": ({ReportStatus.COUNTING, ReportStatus.READY, ReportStatus.RUNNING, ReportStatus.PAUSED},
               ReportStatus.CANCELLED),
}


class ReportConflict(ValueError):
    """The form refers to another version, or the action does not fit the status."""


class ActivityService:
    def __init__(self, store: ActivityReportStore, clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self.store, self.clock = store, clock
        self.lock = RLock()
        self.actor: ContextVar[str | None] = ContextVar("activity_actor", default=None)
        self.active: Callable[[str], bool] = lambda _actor: False
        self.blocked_senders: Callable[[], tuple[list[str], list[str]]] | None = None

    def check_actor(self) -> None:
        actor = self.actor.get()
        if actor is not None and not self.active(actor):
            raise ReportConflict("Die Sitzung ist nicht mehr gültig. Bitte erneut anmelden.")

    def authorized(self, report: ActivityReport) -> bool:
        return report.authorized_actor is None or self.active(report.authorized_actor)

    def create(self, definition: ReportDefinition, addresses: list[str], domains: list[str],
               key: str | None = None) -> ActivityReport:
        """A new report starts counting at once; reading content needs the explicit start.

        With *key*, a repeated form submission returns the report it created first.
        """
        digest = hashlib.sha256(repr(("create", definition.model_dump(mode="json"))).encode()).hexdigest()
        if key is not None and not _KEY.fullmatch(key):
            raise ReportConflict("Ungültiger Idempotenzschlüssel")
        with self.lock:
            self.check_actor()
            if key is not None:
                for existing in self.store.reports():
                    done = existing.operations.get(key)
                    if done is not None:
                        if done != digest:
                            raise ReportConflict("Idempotenzkonflikt")
                        return existing
            report = self.store.create(definition, addresses, domains, self.clock())
            report.authorized_actor = self.actor.get()
            if key is not None:
                report.operations[key] = digest
                self.store.save(report)
            return report

    def _change(self, report_id: str, version: int, key: str, digest_input: tuple[Any, ...],
                change: Callable[[ActivityReport], None]) -> ActivityReport:
        if not _KEY.fullmatch(key):
            raise ReportConflict("Ungültiger Idempotenzschlüssel")
        digest = hashlib.sha256(repr(digest_input).encode()).hexdigest()
        with self.lock:
            self.check_actor()
            report = self.store.load(report_id)
            if report is None:
                raise ReportConflict("Bericht nicht gefunden")
            done = report.operations.get(key)
            if done is not None:
                if done != digest:
                    raise ReportConflict("Idempotenzkonflikt")
                return report
            if report.version != version:
                raise ReportConflict("Der Bericht wurde inzwischen geändert; bitte neu laden")
            change(report)
            if self.actor.get() is not None:
                report.authorized_actor = self.actor.get()
            report.version += 1
            report.operations[key] = digest
            for old in list(report.operations)[:-MAX_OPERATIONS]:
                del report.operations[old]
            self.store.save(report)
            return report

    def act(self, report_id: str, version: int, key: str, action: str) -> ActivityReport:
        if action not in TRANSITIONS:
            raise ReportConflict("Unbekannte Aktion")
        allowed, target = TRANSITIONS[action]

        def change(report: ActivityReport) -> None:
            if report.status not in allowed:
                raise ReportConflict("Diese Aktion passt nicht zum aktuellen Stand")
            report.status = target
            report.message = ""
            if action == "start":
                report.started_at = self.clock()
                if self.blocked_senders is not None:
                    report.blocked_addresses, report.blocked_domains = self.blocked_senders()
            if target == ReportStatus.CANCELLED:
                report.finished_at = self.clock()
        return self._change(report_id, version, key, ("act", action, version), change)

    def delete(self, report_id: str, version: int, key: str = "internal-delete") -> None:
        """Delete every file of a report that is not reading the mailbox right now."""
        with self.lock:
            self.check_actor()
            if not _KEY.fullmatch(key):
                raise ReportConflict("Ungültiger Idempotenzschlüssel")
            operations = self.store.store.load("activity-deletions", {})
            identity = f"{report_id}:{key}"
            if identity in operations and operations[identity] != version:
                raise ReportConflict("Idempotenzkonflikt")
            report = self.store.load(report_id)
            if report is None:
                return
            if report.version != version:
                raise ReportConflict("Der Bericht wurde inzwischen geändert; bitte neu laden")
            if report.status in {ReportStatus.COUNTING, ReportStatus.RUNNING}:
                raise ReportConflict("Ein laufender Bericht muss zuerst pausiert oder abgebrochen werden")
            if key in report.operations:
                raise ReportConflict("Idempotenzkonflikt")
            operations[identity] = version
            self.store.store.save("activity-deletions", dict(list(operations.items())[-MAX_OPERATIONS:]))
            self.store.delete(report_id)

    def correct(self, report_id: str, version: int, key: str, mail_key: str,
                change: Callable[[ActivityReport, ReportMail], None], digest_input: tuple[Any, ...]) -> ActivityReport:
        """Apply one user correction to one mail of the report."""
        def apply(report: ActivityReport) -> None:
            mail = self.store.mail(report_id, mail_key)
            if mail is None:
                raise ReportConflict("Mail nicht im Bericht")
            change(report, mail)
            self.store.save_mail(report_id, mail)
        return self._change(report_id, version, key, ("correct", mail_key, *digest_input), apply)

    def set_relevance(self, report_id: str, version: int, key: str, mail_key: str, relevant: bool) -> ActivityReport:
        def change(report: ActivityReport, mail: ReportMail) -> None:
            if mail.skipped is not None:
                raise ReportConflict("Übersprungene Mails wurden nicht gelesen")
            mail.user_relevant = relevant
            # Dates of a mail the model judged irrelevant are extracted on request.
            if relevant and not mail.events_extracted and not mail.text_removed \
                    and mail_key not in report.pending_extractions:
                report.pending_extractions.append(mail_key)
        return self.correct(report_id, version, key, mail_key, change, ("relevance", relevant))

    def set_event(self, report_id: str, version: int, key: str, mail_key: str, event_id: str | None,
                  values: dict[str, Any]) -> ActivityReport:
        """Edit, exclude or (without *event_id*) add a date; ``values`` are already validated."""
        def change(_report: ActivityReport, mail: ReportMail) -> None:
            if event_id is None:
                if len(mail.events) >= 50:
                    raise ReportConflict("Zu viele Termine für diese Mail")
                number = max((int(item.id[1:]) for item in mail.events), default=0) + 1
                mail.events.append(ReportEvent(id=f"e{number}", manual=True, **values))
                return
            event = next((item for item in mail.events if item.id == event_id), None)
            if event is None:
                raise ReportConflict("Termin nicht gefunden")
            updated = event.model_copy(update=values)
            mail.events[mail.events.index(event)] = ReportEvent.model_validate(
                updated.model_dump() | {"edited": event.edited or set(values) - {"excluded"} != set()})
        return self.correct(report_id, version, key, mail_key, change,
                            ("event", event_id, tuple(sorted((k, str(v)) for k, v in values.items()))))

    def repeat(self, report_id: str, version: int, key: str, topic: str) -> ActivityReport:
        """A changed topic starts a new report; only source texts may be reused."""
        def change(source: ActivityReport) -> None:
            values = source.definition.model_dump() | {"topic": topic}
            definition = ReportDefinition.model_validate(values)
            target = self.create(definition, source.blocked_addresses, source.blocked_domains)
            target.authorized_actor = self.actor.get()
            for old in self.store.mails(source.id):
                if old.text and not old.text_removed and old.skipped is None:
                    cached = ReportMail(key=old.key, folder=old.folder, uid=old.uid, message_id=old.message_id,
                                        received_at=old.received_at, sender=old.sender, subject=old.subject,
                                        text=old.text, attachments=old.attachments, cached_input=True)
                    self.store.save_mail(target.id, cached)
            self.store.save(target)
            source.repetitions[key] = target.id
        source = self._change(report_id, version, key, ("repeat", topic, version), change)
        target = self.store.load(source.repetitions[key])
        if target is None:
            raise ReportConflict("Der neue Bericht wurde inzwischen gelöscht")
        return target


def event_values(title: str, day: str, start_time: str, end_time: str, location: str) -> dict[str, Any]:
    """Form fields of a date as validated model values (raises ``ValueError``)."""
    values: dict[str, Any] = {"title": title.strip(), "day": date.fromisoformat(day),
                              "start_time": start_time.strip() or None, "end_time": end_time.strip() or None,
                              "location": location.strip() or None}
    ReportEvent(id="e1", **values)
    return values


__all__ = ["ActivityService", "ReportConflict", "TRANSITIONS", "event_values"]
