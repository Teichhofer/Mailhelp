"""Mailhelp pages and actions on top of the checked router.

Authentication and CSRF are enforced here for every page except the login
flow, ``/health`` and static files.  Review state is only read through the
read models; changes are submitted to the command inbox and executed by the
main thread.
"""

from __future__ import annotations

from typing import Callable, Protocol

from ..config import WebSettings
from ..review.inbox import CommandInbox
from ..review.views import ReviewViews
from .app import WebApp
from .auth import PairingLimited, PairingRefused, WebAuth, WebSession, device_name
from .http import Request, Response
from .pages import devices_page, error_page, login_page
from .review_pages import detail_page, overview_page, status_page

SESSION_COOKIE = "mh_session"
PAIR_COOKIE = "mh_pair"
PAIR_COOKIE_SECONDS = 15 * 60
FORM_TYPE = "application/x-www-form-urlencoded"


class EventLogger(Protocol):
    def event(self, level: str, module: str, event: str, **fields: object) -> None: ...


Handler = Callable[..., Response]


class MailhelpSite:
    """Register the Mailhelp routes on a :class:`WebApp`."""

    def __init__(self, app: WebApp, auth: WebAuth, settings: WebSettings,
                 configured_timezone: str, logger: EventLogger, views: ReviewViews,
                 commands: CommandInbox):
        self.app, self.auth, self.settings = app, auth, settings
        self.views, self.commands = views, commands
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
        app.route("GET", "/status", self.signed_in(self.status))
        app.route("GET", "/api/stand", self.signed_in(self.state))

    # --- helpers ------------------------------------------------------------------

    def _cookie(self, request: Request, name: str, value: str, max_age: int) -> str:
        # Requests through Tailscale Serve arrive over HTTPS; local ones over HTTP.
        secure = "; Secure" if request.host not in self.local_hosts else ""
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
                                   self.auth.code_requested(nonce)).encode("utf-8")
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
        return Response.html(200, overview_page(self.views.overview()))

    def detail(self, request: Request, session: WebSession, mail_id: str,
               proposal_id: str) -> Response:
        view = self.views.proposal(mail_id, proposal_id)
        if view is None:
            return Response.html(404, error_page(
                "Nicht gefunden", "Dieser Vorschlag ist nicht (mehr) vorhanden."))
        return Response.html(200, detail_page(view))

    def status(self, request: Request, session: WebSession) -> Response:
        overview = self.views.overview()
        return Response.html(200, status_page(overview.run, overview, self.configured_timezone,
                                              len(self.commands.queued())))

    def state(self, request: Request, session: WebSession) -> Response:
        """Fingerprint of the overview; the page reloads when it changes."""
        return Response.json(200, {"fingerprint": self.views.overview().fingerprint})


__all__ = ["FORM_TYPE", "MailhelpSite", "PAIR_COOKIE", "SESSION_COOKIE"]
