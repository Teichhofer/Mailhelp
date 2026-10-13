"""Routes of activity reports (2.2): read-only mailbox, every change version-checked and idempotent.

A report never writes to the mailbox, the calendar or Todoist; it only reads and
asks the model.  The paid run starts with an explicit action on the report page.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from ..activity.costs import estimate
from ..activity.export import filename, workbook
from ..activity.models import ReportDefinition
from ..activity.presentation import ReportFilter, fingerprint
from ..activity.service import ActivityService, ReportConflict, event_values
from .activity_pages import disabled_page, list_page, mail_page, new_page, report_page
from .http import Request, Response
from .pages import layout, notice

REPORT = r"/berichte/(?P<report_id>[a-f0-9]{32})"
MAIL = REPORT + r"/mail/(?P<index>[0-9]{1,6})"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class ActivitySite:
    def __init__(self, site):
        self.site = site
        # Set by the runtime when activity_report.enabled and both prompts exist.
        self.service: ActivityService | None = None
        self.suggest_folders: Callable[[], list[str]] = lambda: ["INBOX"]
        self.available_folders: Callable[[], list[str]] = lambda: ["INBOX"]
        self.with_unscheduled = True
        route = site.app.route
        route("GET", "/berichte", site.signed_in(self.reports))
        route("GET", "/berichte/neu", site.signed_in(self.new))
        route("POST", "/berichte", site.signed_in(self.secured(self.create)))
        route("GET", REPORT, site.signed_in(self.report))
        route("POST", REPORT + "/aktion", site.signed_in(self.secured(self.act)))
        route("GET", REPORT + "/export.xlsx", site.signed_in(self.export))
        route("GET", MAIL, site.signed_in(self.mail))
        route("POST", MAIL, site.signed_in(self.secured(self.correct)))

    def secured(self, handler):
        def execute(request, session, form, **arguments):
            if self.service is None:
                return self._disabled()
            self.service.active = self.site.auth.active
            token = self.service.actor.set(session.id)
            try:
                return handler(request, session, form, **arguments)
            finally:
                self.service.actor.reset(token)
        return execute

    def _csrf(self, session) -> str:
        return self.site.auth.csrf_token(session.id)

    @staticmethod
    def _disabled() -> Response:
        return Response.html(404, disabled_page())

    def _missing(self, request: Request) -> Response:
        return self.site._reply(request, 404, "Dieser Bericht ist nicht (mehr) vorhanden.")

    def reports(self, request: Request, session) -> Response:
        if self.service is None:
            return Response.html(200, disabled_page())
        return Response.html(200, list_page(self.service.store.reports()))

    def new(self, request: Request, session) -> Response:
        if self.service is None:
            return self._disabled()
        try:
            folders = self.suggest_folders()
        except Exception as exc:
            # The mailbox may be unreachable; the user can still type the folders.
            self.site.logger.event("WARNING", "activity", "folder_suggestion_failed",
                                   error_class=type(exc).__name__)
            folders = ["INBOX"]
        return Response.html(200, new_page(self._csrf(session), folders))

    def create(self, request: Request, session, form: dict[str, str]) -> Response:
        assert self.service is not None  # secured() establishes the enabled service.
        try:
            folders = [line.strip() for line in form.get("folders", "").splitlines() if line.strip()]
            definition = ReportDefinition(
                title=form.get("title", "").strip(), topic=form.get("topic", "").strip(),
                since=date.fromisoformat(form.get("since", "")), until=date.fromisoformat(form.get("until", "")),
                folders=folders, include_sent=form.get("include_sent") == "on",
                skip_automated=form.get("skip_automated") == "on")
            if not set(folders) <= set(self.available_folders()):
                raise ValueError("Unbekannter Ordner")
        except (ValueError, ValidationError):
            message = ("Bitte Titel, ein Thema mit mindestens 10 Zeichen, einen Zeitraum von höchstens drei "
                       "Jahren und jeden Ordner nur einmal angeben.")
            return Response.html(422, new_page(self._csrf(session), [], form, message))
        except OSError:
            return self.site._reply(request, 503,
                                    "Die Ordnerliste ist gerade nicht erreichbar. Bitte erneut versuchen.")
        configuration = self.site.archive.configuration
        blocked = configuration.blocked_senders() if configuration is not None else None
        try:
            report = self.service.create(definition, list(blocked.addresses) if blocked else [],
                                         list(blocked.domains) if blocked else [], form.get("key", ""))
        except ReportConflict as exc:
            return self.site._reply(request, 409, str(exc))
        self.site.logger.event("INFO", "activity", "report_created", report_id=report.id)
        return Response.redirect(f"/berichte/{report.id}")

    def report(self, request: Request, session, report_id: str) -> Response:
        if self.service is None:
            return self._disabled()
        report = self.service.store.load(report_id)
        if report is None:
            return self._missing(request)
        metrics = self.site.archive.metrics
        records = metrics.records()[0] if metrics is not None else []
        return Response.html(200, report_page(report, self.service.store.mails(report_id), self._csrf(session),
                                              ReportFilter.parse(request.query), estimate(report, records)))

    def state(self, report_id: str) -> Response:
        if self.service is None:
            return self._disabled()
        # The id comes from the query string; only the route format may reach the store.
        report = self.service.store.load(report_id) if re.fullmatch(r"[a-f0-9]{32}", report_id) else None
        if report is None:
            return Response.json(404, {"error": "Bericht nicht vorhanden"})
        return Response.json(200, {"fingerprint": fingerprint(report, self.service.store.mails(report_id))})

    def act(self, request: Request, session, form: dict[str, str], report_id: str) -> Response:
        assert self.service is not None
        action = form.get("action", "")
        try:
            version = int(form.get("version", ""))
            if action == "delete":
                self.service.delete(report_id, version, form.get("key", ""))
            elif action == "repeat":
                report = self.service.repeat(report_id, version, form.get("key", ""), form.get("topic", ""))
                return Response.redirect(f"/berichte/{report.id}")
            else:
                self.service.act(report_id, version, form.get("key", ""), action)
        except ValueError as exc:
            # ReportConflict is a ValueError: stale form, wrong status or replay with other content.
            if isinstance(exc, ReportConflict):
                return self.site._reply(request, 409, str(exc))
            return self.site._reply(request, 422, "Die Aktion ist unvollständig oder ungültig.")
        self.site.logger.event("INFO", "activity", "report_action", report_id=report_id, action=action)
        if action == "delete":
            return Response.html(200, layout("Bericht gelöscht", notice("Der Bericht wurde gelöscht.")
                                             + '<p><a href="/berichte">Zu den Berichten</a></p>',
                                             active="/berichte"))
        return Response.redirect(f"/berichte/{report_id}")

    def _mail(self, report_id: str, index: str):
        assert self.service is not None
        report = self.service.store.load(report_id)
        mails = self.service.store.mails(report_id) if report is not None else []
        position = int(index)
        return report, (mails[position] if position < len(mails) else None)

    def mail(self, request: Request, session, report_id: str, index: str) -> Response:
        if self.service is None:
            return self._disabled()
        report, mail = self._mail(report_id, index)
        if report is None or mail is None:
            return self._missing(request)
        return Response.html(200, mail_page(report, int(index), mail, self._csrf(session),
                                            self.site.configured_timezone))

    def correct(self, request: Request, session, form: dict[str, str], report_id: str, index: str) -> Response:
        assert self.service is not None
        report, mail = self._mail(report_id, index)
        if report is None or mail is None:
            return self._missing(request)
        mode, key = form.get("mode", ""), form.get("key", "")
        try:
            version = int(form.get("version", ""))
            if mode in {"relevant", "irrelevant"}:
                self.service.set_relevance(report_id, version, key, mail.key, mode == "relevant")
            elif mode in {"exclude", "include"}:
                self.service.set_event(report_id, version, key, mail.key, form.get("event", ""),
                                       {"excluded": mode == "exclude"})
            elif mode == "event":
                values = event_values(form.get("title", ""), form.get("day", ""), form.get("start_time", ""),
                                      form.get("end_time", ""), form.get("location", ""))
                self.service.set_event(report_id, version, key, mail.key, form.get("event") or None, values)
            else:
                raise ValueError(mode)
        except ReportConflict as exc:
            return self.site._reply(request, 409, str(exc))
        except (ValueError, ValidationError):
            return self.site._reply(request, 422, "Bitte Termin, gültiges Datum und Uhrzeiten als HH:MM angeben.")
        return Response.redirect(f"/berichte/{report_id}/mail/{index}")

    def export(self, request: Request, session, report_id: str) -> Response:
        if self.service is None:
            return self._disabled()
        report = self.service.store.load(report_id)
        if report is None:
            return self._missing(request)
        zone = self.site.configured_timezone
        data = workbook(report, self.service.store.mails(report_id), zone, self.with_unscheduled)
        name = filename(report, self.site.clock().astimezone(ZoneInfo(zone)).date())
        self.site.logger.event("INFO", "activity", "report_exported", report_id=report_id)
        return Response(200, data, XLSX, headers={"Content-Disposition": f'attachment; filename="{name}"'})


__all__ = ["ActivitySite"]
