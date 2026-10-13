"""Mailhelp pages and actions on top of the checked router.

Authentication and CSRF are enforced here for every page except the login
flow, ``/health`` and static files.  Review state is only read through the
read models; changes are submitted to the command inbox and executed by the
main thread.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol
from urllib.parse import parse_qs

from pydantic import ValidationError

from .. import __version__
from ..config import WebSettings
from ..configuration import AdminCommand, AdminKind
from ..models import ProposalStatus
from ..review.commands import CommandKind, CommandSource, ReviewCommand
from ..review.inbox import CommandConflict, CommandEntry, CommandInbox, CommandInboxFull
from ..review.views import ReviewViews
from .actions import command_page, needs_choice, result_kind, stale_page
from .app import WebApp
from .auth import WebAuth, WebSession
from .http import Request, Response
from .login_site import PAIR_COOKIE, SESSION_COOKIE, LoginSite
from .pages import error_page, layout, notice
from .review_site import ReviewSite
from .sender_site import LIST_PATH as SENDERS_PATH
from .sender_site import SenderSite
from .status_pages import ServiceInfo, status_page

FORM_TYPE = "application/x-www-form-urlencoded"
# How long the progress page waits for a quick result before it shows "running".
SETTLE_SECONDS = 1.5


class EventLogger(Protocol):
    def event(self, level: str, module: str, event: str, **fields: object) -> None: ...


Handler = Callable[..., Response]
if TYPE_CHECKING:
    from ..notification_runtime import NotificationRuntime


class MailhelpSite:
    """Register the Mailhelp routes on a :class:`WebApp`."""

    def __init__(self, app: WebApp, auth: WebAuth, settings: WebSettings,
                 configured_timezone: str, logger: EventLogger, views: ReviewViews,
                 commands: CommandInbox, *, link_base: Callable[[], str] | None = None,
                 llm_calls_per_minute: int | None = None,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC),
                 configuration=None, metrics=None, lifecycle=None, models=None):
        self.app, self.auth, self.settings = app, auth, settings
        self.views, self.commands = views, commands
        self.lifecycle = lifecycle
        self.link_base = link_base or (lambda: f"http://127.0.0.1:{settings.port}")
        self.llm_calls_per_minute, self.clock = llm_calls_per_minute, clock
        # The web interface starts together with Mailhelp.
        self.started_at = clock()
        self.configured_timezone, self.logger = configured_timezone, logger
        self.local_hosts = {f"127.0.0.1:{settings.port}", f"localhost:{settings.port}"}
        self.login_pages = LoginSite(self)
        self.review = ReviewSite(self)
        app.route("GET", "/offen", self.signed_in(self.review.home))
        app.route("GET", "/anmelden", self.login_pages.login)
        app.route("POST", "/anmelden/code", self.login_pages.request_code)
        app.route("POST", "/anmelden", self.login_pages.pair)
        app.route("POST", "/abmelden", self.signed_in(self.login_pages.logout))
        app.route("GET", "/geraete", self.signed_in(self.login_pages.devices))
        app.route("POST", r"/geraete/(?P<session_id>[a-f0-9]{16})/abmelden",
                  self.signed_in(self.login_pages.revoke))
        app.route("POST", "/geraete/alle-abmelden", self.signed_in(self.login_pages.revoke_all))
        app.route("GET", "/", self.signed_in(self.review.home))
        app.route("GET", r"/vorschlag/(?P<mail_id>[a-f0-9]{24})/(?P<proposal_id>[A-Za-z0-9_-]{1,64})",
                  self.signed_in(self.review.detail))
        app.route("GET", r"/mail/(?P<mail_id>[a-f0-9]{24})", self.signed_in(self.review.mail))
        app.route("GET", r"/mail/(?P<mail_id>[a-f0-9]{24})/anhang/(?P<index>[0-9]{1,5})",
                  self.signed_in(self.review.attachment))
        app.route("GET", "/status", self.signed_in(self.status))
        app.route("GET", "/api/stand", self.signed_in(self.state))
        app.route("POST", "/aktion", self.signed_in(self.act))
        app.route("GET", r"/aktion/(?P<entry_id>[a-f0-9]{32})", self.signed_in(self.progress))
        from .archive_site import ArchiveSite
        self.archive = ArchiveSite(self, configuration, metrics, lifecycle, models)
        self.senders = SenderSite(self)
        from .experience import ExperienceSite
        self.experience = ExperienceSite(self)
        from .activity_site import ActivitySite
        self.activity = ActivitySite(self)
        from .setup_site import SetupSite
        self.setup_page = SetupSite(self)
        self.notification_runtime: NotificationRuntime | None = None

    # --- helpers ------------------------------------------------------------------


    def _form(self, request: Request) -> dict[str, str] | Response:
        content_type = (request.header("content-type") or "").split(";")[0].strip().lower()
        if content_type != FORM_TYPE:
            return Response.text(415, "Nur Formulardaten werden angenommen.")
        try:
            return request.form()
        except (UnicodeDecodeError, ValueError):
            return Response.text(400, "Ungültige Formulardaten.")

    @staticmethod
    def _forbidden() -> Response:
        return Response.html(403, error_page(
            "Sicherheitsprüfung fehlgeschlagen",
            "Die Anfrage konnte nicht bestätigt werden. Bitte die Seite neu laden und erneut versuchen."))

    def signed_in(self, handler: Handler) -> Handler:
        """Require a live session; a POST also requires its CSRF token."""
        def guarded(request: Request, **arguments: str) -> Response:
            session = self.auth.authenticate(request.cookies().get(SESSION_COOKIE))
            if session is None:
                if request.wants_json():
                    return Response.json(401, {"error": "nicht angemeldet"})
                if request.method == "GET":
                    return Response.redirect("/anmelden")
                return self._forbidden()
            if request.method == "POST":
                if (self.lifecycle is not None and self.lifecycle.state != "running"
                        and request.path != "/einstellungen/beenden"):
                    return self._reply(request, 503, "Mailhelp wird beendet; keine neuen Aktionen möglich.")
                form = self._form(request)
                if isinstance(form, Response):
                    return form
                if not self.auth.csrf_valid(session.id, form.get("csrf")):
                    self.logger.event("WARNING", "web", "csrf_rejected", path=request.path)
                    return self._forbidden()
                return handler(request, session, form, **arguments)
            return handler(request, session, **arguments)
        return guarded


    # --- pairing ------------------------------------------------------------------





    # --- sessions -----------------------------------------------------------------










    def status(self, request: Request, session: WebSession) -> Response:
        overview = self.views.overview()
        now = self.clock()
        info = ServiceInfo(
            version=__version__, test_mode=self.views.test_mode, started_at=self.started_at, now=now,
            address=self.link_base(), devices=len(self.auth.sessions()),
            llm_calls_per_minute=self.llm_calls_per_minute, commands=self.commands.counts())
        system = self.views.system(now)
        metrics = self.archive.metrics
        runtime = metrics.runtime() if metrics is not None else None
        info = replace(info, runtime=runtime,
                       services=tuple(metrics.expected_services()) if metrics is not None else (),
                       fingerprint=self._status_fingerprint(overview, system, runtime))
        return Response.html(200, status_page(overview.run, overview, self.configured_timezone, system, info))

    @staticmethod
    def _status_fingerprint(overview, system, runtime) -> str:
        """Changes when anything the status page shows changes (contact times excluded)."""
        parts = [overview.fingerprint, system.run_finished, system.run_total, system.mails_failed,
                 system.mails_waiting_relevance, sorted(system.analysis.items()),
                 sorted((str(key), value) for key, value in system.proposals.items())]
        if runtime is not None:
            parts += [runtime["stage"], runtime.get("mail_id"), runtime.get("next_poll")]
        return hashlib.sha256(json.dumps(parts, default=str).encode("utf-8")).hexdigest()[:16]

    def act(self, request: Request, session: WebSession, form: dict[str, str]) -> Response:
        """Queue a version-bound command for the main thread; answer at once."""
        try:
            command = ReviewCommand(
                kind=CommandKind(form.get("kind", "")), source=CommandSource.WEB,
                actor=f"web:{session.id}", mail_id=form.get("mail_id", ""),
                proposal_id=form.get("proposal_id") or None,
                version=int(form.get("version", "")), idempotency_key=form.get("key", ""),
                text=form.get("text") or None, decision=form.get("decision") or None)
        except (ValueError, ValidationError):
            return self._reply(request, 422, "Die Aktion ist unvollständig oder ungültig.")
        stale = self._stale(command)
        if stale is not None:
            current = (self.views.proposal(command.mail_id, command.proposal_id)
                       if command.proposal_id else None)
            if request.wants_json():
                return Response.json(409, {"error": stale,
                                           "current_version": current.version if current else None})
            return Response.html(409, stale_page(stale, current))
        try:
            entry, new = self.commands.submit(command)
        except CommandConflict:
            return self._reply(request, 422, "Diese Aktion wurde bereits mit anderen Angaben gesendet.")
        except CommandInboxFull:
            return self._reply(request, 503, "Mailhelp ist gerade ausgelastet. Bitte gleich erneut versuchen.")
        self.logger.event("INFO", "web", "command_submitted", command_id=entry.id,
                          kind=command.kind.value, repeated=not new)
        location = f"/aktion/{entry.id}"
        if request.wants_json():
            response = Response.json(202, {"id": entry.id, "status": entry.status.value,
                                           "status_url": location})
            response.headers["Location"] = location
            return response
        return Response.redirect(location)

    def _stale(self, command: ReviewCommand) -> str | None:
        """Refuse an outdated version before it is queued (checked again when it runs)."""
        if command.kind == CommandKind.RELEVANCE:
            open_ = {(view.mail_id, view.version) for view in self.views.overview().relevance}
            if (command.mail_id, command.version) not in open_:
                return "Diese Relevanzfrage ist bereits beantwortet oder veraltet."
            return None
        assert command.proposal_id is not None
        current = self.views.proposal(command.mail_id, command.proposal_id)
        if (current is None or current.version != command.version
                or current.status not in {ProposalStatus.PENDING_CONFIRMATION,
                                          ProposalStatus.NEEDS_CLARIFICATION}):
            return "Dieser Vorschlag wurde inzwischen geändert oder entschieden."
        return None

    @staticmethod
    def _reply(request: Request, status: int, message: str) -> Response:
        if request.wants_json():
            return Response.json(status, {"error": message})
        return Response.html(status, error_page("Aktion nicht möglich", message))

    def progress(self, request: Request, session: WebSession, entry_id: str) -> Response:
        entry = self.commands.get(entry_id)
        if entry is None or entry.command.actor != f"web:{session.id}":
            return self._reply(request, 404, "Diese Aktion ist nicht (mehr) bekannt.")
        if request.wants_json():
            return Response.json(200, {
                "id": entry.id, "status": entry.status.value,
                "result": entry.result.model_dump(mode="json") if entry.result else None})
        entry = self._settled(entry)
        command = entry.command
        if isinstance(command, AdminCommand):
            if entry.result is None:
                return Response.html(
                    200, layout("Einstellungen werden gespeichert", "<h1>Wird verarbeitet</h1>", refresh=1)
                )
            if command.kind == AdminKind.SENDERS:
                # Back to where the change was made; that page shows the result.
                mail_id = command.patch.get("mail_id")
                target = f"/mail/{mail_id}" if mail_id else SENDERS_PATH
                return Response.redirect(f"{target}?ergebnis={entry.id}")
            return Response.html(
                200, layout("Ergebnis", notice(entry.result.message, result_kind(entry.result.status))
                            + '<a href="/einstellungen">Zurück</a>')
            )
        current = (self.views.proposal(command.mail_id, command.proposal_id)
                   if command.proposal_id else None)
        if entry.result is not None and not needs_choice(entry, current):
            # Done: back to the overview, which shows the result on top.
            return Response.redirect(f"/?ergebnis={entry.id}")
        return Response.html(200, command_page(entry, self.auth.csrf_token(session.id), current))

    def _settled(self, entry: CommandEntry) -> CommandEntry:
        """Wait briefly for a quick result so the page usually needs no reload."""
        deadline = time.monotonic() + SETTLE_SECONDS
        while entry.result is None and time.monotonic() < deadline:
            time.sleep(0.05)
            entry = self.commands.get(entry.id) or entry
        return entry

    def state(self, request: Request, session: WebSession) -> Response:
        """Fingerprint of the overview (or the status page); the page reloads when it changes."""
        report_id = parse_qs(request.query, max_num_fields=5).get("bericht")
        if report_id:
            return self.activity.state(report_id[0])
        overview = self.views.overview()
        if parse_qs(request.query, max_num_fields=5).get("seite") == ["status"]:
            metrics = self.archive.metrics
            return Response.json(200, {"fingerprint": self._status_fingerprint(
                overview, self.views.system(self.clock()),
                metrics.runtime() if metrics is not None else None)})
        return Response.json(200, {"fingerprint": overview.fingerprint})






__all__ = ["FORM_TYPE", "MailhelpSite", "PAIR_COOKIE", "SESSION_COOKIE"]
