"""Mailhelp pages and actions on top of the checked router.

Authentication and CSRF are enforced here for every page except the login
flow, ``/health`` and static files.  Review state is only read through the
read models; changes are submitted to the command inbox and executed by the
main thread.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import time
from dataclasses import replace
from datetime import datetime, timezone
from typing import Callable, Protocol
from urllib.parse import parse_qs

from .. import __version__
from ..config import WebSettings
from ..configuration import AdminCommand
from pydantic import ValidationError

from ..models import ProposalStatus
from ..review.commands import CommandKind, CommandSource, ReviewCommand
from ..review.inbox import CommandConflict, CommandEntry, CommandInbox, CommandInboxFull
from ..review.views import ReviewViews
from .app import WebApp
from .auth import PairingLimited, PairingRefused, WebAuth, WebSession, device_name
from .http import Request, Response
from .pages import devices_page, error_page, login_page, layout, notice
from .actions import (command_page, needs_choice, proposal_actions, relevance_actions,
                      result_kind, stale_page)
from .review_pages import ServiceInfo, detail_page, mail_page, overview_page, status_page

SESSION_COOKIE = "mh_session"
PAIR_COOKIE = "mh_pair"
PAIR_COOKIE_SECONDS = 15 * 60
FORM_TYPE = "application/x-www-form-urlencoded"
# How long the progress page waits for a quick result before it shows "running".
SETTLE_SECONDS = 1.5


class EventLogger(Protocol):
    def event(self, level: str, module: str, event: str, **fields: object) -> None: ...


Handler = Callable[..., Response]


class MailhelpSite:
    """Register the Mailhelp routes on a :class:`WebApp`."""

    def __init__(self, app: WebApp, auth: WebAuth, settings: WebSettings,
                 configured_timezone: str, logger: EventLogger, views: ReviewViews,
                 commands: CommandInbox, *, link_base: Callable[[], str] | None = None,
                 llm_calls_per_minute: int | None = None,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
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
        app.route("GET", "/anmelden", self.login)
        app.route("POST", "/anmelden/code", self.request_code)
        app.route("POST", "/anmelden", self.pair)
        app.route("POST", "/abmelden", self.signed_in(self.logout))
        app.route("GET", "/geraete", self.signed_in(self.devices))
        app.route("POST", r"/geraete/(?P<session_id>[a-f0-9]{16})/abmelden",
                  self.signed_in(self.revoke))
        app.route("POST", "/geraete/alle-abmelden", self.signed_in(self.revoke_all))
        app.route("GET", "/", self.signed_in(self.home))
        app.route("GET", r"/vorschlag/(?P<mail_id>[a-f0-9]{24})/(?P<proposal_id>[A-Za-z0-9_-]{1,64})",
                  self.signed_in(self.detail))
        app.route("GET", r"/mail/(?P<mail_id>[a-f0-9]{24})", self.signed_in(self.mail))
        app.route("GET", "/status", self.signed_in(self.status))
        app.route("GET", "/api/stand", self.signed_in(self.state))
        app.route("POST", "/aktion", self.signed_in(self.act))
        app.route("GET", r"/aktion/(?P<entry_id>[a-f0-9]{32})", self.signed_in(self.progress))
        from .archive_site import ArchiveSite
        self.archive = ArchiveSite(self, configuration, metrics, lifecycle, models)

    # --- helpers ------------------------------------------------------------------

    def _cookie(self, request: Request, name: str, value: str, max_age: int) -> str:
        # Only a host name (Tailscale Serve) is reached over HTTPS; the local
        # address and LAN IP addresses use plain HTTP, where Secure cookies fail.
        hostname = request.host.rpartition(":")[0] if ":" in request.host else request.host
        secure = "; Secure" if not _ip_or_localhost(hostname) else ""
        return f"{name}={value}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}{secure}"

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
                if self.lifecycle is not None and self.lifecycle.state != "running" and request.path != "/einstellungen/beenden":
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

    def _signed_out(self, request: Request, location: str = "/anmelden") -> Response:
        response = Response.redirect(location)
        response.cookies.append(self._cookie(request, SESSION_COOKIE, "", 0))
        return response

    # --- pairing ------------------------------------------------------------------

    def _pairing_form(self, request: Request) -> tuple[str, dict[str, str]] | Response:
        nonce = request.cookies().get(PAIR_COOKIE)
        if not nonce:
            return Response.redirect("/anmelden")
        form = self._form(request)
        if isinstance(form, Response):
            return form
        if not self.auth.csrf_valid(f"pair:{nonce}", form.get("csrf")):
            self.logger.event("WARNING", "web", "csrf_rejected", path=request.path)
            return self._forbidden()
        return nonce, form

    def login(self, request: Request) -> Response:
        if self.auth.authenticate(request.cookies().get(SESSION_COOKIE)) is not None:
            return Response.redirect("/")
        nonce = request.cookies().get(PAIR_COOKIE)
        response = Response.html(200, "")
        if not nonce:
            nonce = self.auth.new_browser_nonce()
            response.cookies.append(self._cookie(request, PAIR_COOKIE, nonce, PAIR_COOKIE_SECONDS))
        response.body = login_page(self.auth.csrf_token(f"pair:{nonce}"),
                                   self.auth.code_requested(nonce),
                                   code=_link_code(request.query)).encode("utf-8")
        return response

    def request_code(self, request: Request) -> Response:
        checked = self._pairing_form(request)
        if isinstance(checked, Response):
            return checked
        nonce, _ = checked
        try:
            self.auth.request_code(nonce, device_name(request.header("user-agent")))
        except PairingLimited as exc:
            self.logger.event("WARNING", "web", "pairing_limited", step="request")
            return Response.html(429, error_page("Bitte später erneut versuchen", str(exc),
                                                 signed_in=False))
        except Exception as exc:
            self.logger.event("ERROR", "web", "pairing_code_not_sent", error_class=type(exc).__name__)
            return Response.html(503, error_page(
                "Code nicht gesendet",
                "Der Code konnte nicht über Telegram gesendet werden. Bitte später erneut versuchen.",
                signed_in=False))
        self.logger.event("INFO", "web", "pairing_code_requested")
        return Response.redirect("/anmelden")

    def pair(self, request: Request) -> Response:
        checked = self._pairing_form(request)
        if isinstance(checked, Response):
            return checked
        nonce, form = checked
        device = device_name(request.header("user-agent"), form.get("geraet"))
        try:
            token = self.auth.redeem(nonce, form.get("code", ""), device)
        except PairingLimited as exc:
            self.logger.event("WARNING", "web", "pairing_limited", step="redeem")
            return Response.html(429, error_page("Bitte später erneut versuchen", str(exc),
                                                 signed_in=False))
        except PairingRefused as exc:
            self.logger.event("WARNING", "web", "pairing_refused")
            # Shown again with the error; a normal page, not a failed request.
            return Response.html(200, login_page(self.auth.csrf_token(f"pair:{nonce}"),
                                                 self.auth.code_requested(nonce), str(exc)))
        self.logger.event("INFO", "web", "device_paired")
        response = Response.redirect("/")
        response.cookies.append(self._cookie(request, SESSION_COOKIE, token,
                                             self.settings.session_days * 86400))
        response.cookies.append(self._cookie(request, PAIR_COOKIE, "", 0))
        return response

    # --- sessions -----------------------------------------------------------------

    def logout(self, request: Request, session: WebSession, _form: dict[str, str]) -> Response:
        self.auth.revoke(session.id)
        self.logger.event("INFO", "web", "session_revoked", scope="current")
        return self._signed_out(request)

    def devices(self, request: Request, session: WebSession) -> Response:
        return Response.html(200, devices_page(
            self.auth.sessions(), session, self.auth.csrf_token(session.id), self.configured_timezone))

    def revoke(self, request: Request, session: WebSession, _form: dict[str, str],
               session_id: str) -> Response:
        self.auth.revoke(session_id)
        self.logger.event("INFO", "web", "session_revoked", scope="single")
        if session_id == session.id:
            return self._signed_out(request)
        return Response.redirect("/geraete")

    def revoke_all(self, request: Request, _session: WebSession, _form: dict[str, str]) -> Response:
        self.auth.revoke_all()
        self.logger.event("INFO", "web", "session_revoked", scope="all")
        return self._signed_out(request)

    def home(self, request: Request, session: WebSession) -> Response:
        csrf = self.auth.csrf_token(session.id)
        message, kind = self._result_notice(request, session)
        return Response.html(200, overview_page(self.views.overview(), actions=proposal_actions(csrf),
                                                relevance_actions=relevance_actions(csrf),
                                                message=message, message_kind=kind))

    def _result_notice(self, request: Request, session: WebSession) -> tuple[str | None, str]:
        """The result of the action this browser just finished (?ergebnis=<id>)."""
        entry_id = parse_qs(request.query, max_num_fields=5).get("ergebnis", [""])[0] \
            if request.query else ""
        entry = self.commands.get(entry_id) if re.fullmatch(r"[a-f0-9]{32}", entry_id) else None
        if entry is None or entry.result is None or entry.command.actor != f"web:{session.id}":
            return None, "ok"
        return entry.result.message, result_kind(entry.result.status)

    def mail(self, request: Request, session: WebSession, mail_id: str) -> Response:
        view = self.views.mail(mail_id)
        if view is None:
            return Response.html(404, error_page("Nicht gefunden", "Diese Mail ist nicht (mehr) vorhanden."))
        question = next((item for item in self.views.overview().relevance if item.mail_id == mail_id), None)
        page = mail_page(view, question, relevance_actions(self.auth.csrf_token(session.id)))
        return Response.html(200, page.replace("</main>", self.archive.analysis(mail_id) + "</main>"))

    def detail(self, request: Request, session: WebSession, mail_id: str,
               proposal_id: str) -> Response:
        view = self.views.proposal(mail_id, proposal_id)
        if view is None:
            return Response.html(404, error_page(
                "Nicht gefunden", "Dieser Vorschlag ist nicht (mehr) vorhanden."))
        page = detail_page(view, actions=proposal_actions(self.auth.csrf_token(session.id)), mail=self.views.mail(mail_id))
        link = f'<p><a class="button" href="/vorschlag/{mail_id}/{proposal_id}/bearbeiten">Felder bearbeiten</a></p>'
        return Response.html(200, page.replace("</main>", link + self.archive.analysis(mail_id) + "</main>"))

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
                return Response.html(200, layout("Einstellungen werden gespeichert", "<h1>Wird verarbeitet</h1>", refresh=1))
            return Response.html(200, layout("Ergebnis", notice(entry.result.message, result_kind(entry.result.status)) + '<a href="/einstellungen">Zurück</a>'))
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
        overview = self.views.overview()
        if parse_qs(request.query, max_num_fields=5).get("seite") == ["status"]:
            metrics = self.archive.metrics
            return Response.json(200, {"fingerprint": self._status_fingerprint(
                overview, self.views.system(self.clock()),
                metrics.runtime() if metrics is not None else None)})
        return Response.json(200, {"fingerprint": overview.fingerprint})


def _ip_or_localhost(name: str) -> bool:
    try:
        ipaddress.ip_address(name)
    except ValueError:
        return name == "localhost"
    return True


def _link_code(query: str) -> str:
    """The code from a /web link (only digits, at most 8), else empty."""
    try:
        value = parse_qs(query, max_num_fields=5).get("code", [""])[0]
    except ValueError:
        return ""
    return value if value.isascii() and value.isdigit() and len(value) == 8 else ""


__all__ = ["FORM_TYPE", "MailhelpSite", "PAIR_COOKIE", "SESSION_COOKIE"]
