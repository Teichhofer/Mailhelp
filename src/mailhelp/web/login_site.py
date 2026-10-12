"""Dedicated routes with unchanged authentication and response contracts."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .auth import WebSession
from .http import Request, Response

if TYPE_CHECKING:
    from .site import MailhelpSite
import ipaddress
from urllib.parse import parse_qs

from .auth import PairingLimited, PairingRefused, device_name
from .pages import devices_page, error_page, login_page

SESSION_COOKIE = "mh_session"
PAIR_COOKIE = "mh_pair"
PAIR_COOKIE_SECONDS = 15 * 60


class LoginSite:
    def __init__(self, site: MailhelpSite):
        self.site = site

    def _cookie(self, request: Request, name: str, value: str, max_age: int) -> str:
        # Only a host name (Tailscale Serve) is reached over HTTPS; the local
        # address and LAN IP addresses use plain HTTP, where Secure cookies fail.
        hostname = request.host.rpartition(":")[0] if ":" in request.host else request.host
        secure = "; Secure" if not _ip_or_localhost(hostname) else ""
        return f"{name}={value}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}{secure}"

    def _signed_out(self, request: Request, location: str = "/anmelden") -> Response:
        response = Response.redirect(location)
        response.cookies.append(self._cookie(request, SESSION_COOKIE, "", 0))
        return response

    def _pairing_form(self, request: Request) -> tuple[str, dict[str, str]] | Response:
        nonce = request.cookies().get(PAIR_COOKIE)
        if not nonce:
            return Response.redirect("/anmelden")
        form = self.site._form(request)
        if isinstance(form, Response):
            return form
        if not self.site.auth.csrf_valid(f"pair:{nonce}", form.get("csrf")):
            self.site.logger.event("WARNING", "web", "csrf_rejected", path=request.path)
            return self.site._forbidden()
        return nonce, form

    def login(self, request: Request) -> Response:
        if self.site.auth.authenticate(request.cookies().get(SESSION_COOKIE)) is not None:
            return Response.redirect("/")
        nonce = request.cookies().get(PAIR_COOKIE)
        response = Response.html(200, "")
        if not nonce:
            nonce = self.site.auth.new_browser_nonce()
            response.cookies.append(self._cookie(request, PAIR_COOKIE, nonce, PAIR_COOKIE_SECONDS))
        response.body = login_page(self.site.auth.csrf_token(f"pair:{nonce}"),
                                   self.site.auth.code_requested(nonce),
                                   code=link_code(request.query), channel=self.site.auth.channel).encode("utf-8")
        return response

    def request_code(self, request: Request) -> Response:
        checked = self._pairing_form(request)
        if isinstance(checked, Response):
            return checked
        nonce, _ = checked
        try:
            self.site.auth.request_code(nonce, device_name(request.header("user-agent")))
        except PairingLimited as exc:
            self.site.logger.event("WARNING", "web", "pairing_limited", step="request")
            return Response.html(429, error_page("Bitte später erneut versuchen", str(exc),
                                                 signed_in=False))
        except Exception as exc:
            self.site.logger.event("ERROR", "web", "pairing_code_not_sent", error_class=type(exc).__name__)
            return Response.html(503, error_page(
                "Code nicht gesendet",
                "Der Code konnte nicht über Telegram gesendet werden. Bitte später erneut versuchen.",
                signed_in=False))
        self.site.logger.event("INFO", "web", "pairing_code_requested")
        return Response.redirect("/anmelden")

    def pair(self, request: Request) -> Response:
        checked = self._pairing_form(request)
        if isinstance(checked, Response):
            return checked
        nonce, form = checked
        device = device_name(request.header("user-agent"), form.get("geraet"))
        try:
            token = self.site.auth.redeem(nonce, form.get("code", ""), device)
        except PairingLimited as exc:
            self.site.logger.event("WARNING", "web", "pairing_limited", step="redeem")
            return Response.html(429, error_page("Bitte später erneut versuchen", str(exc),
                                                 signed_in=False))
        except PairingRefused as exc:
            self.site.logger.event("WARNING", "web", "pairing_refused")
            # Shown again with the error; a normal page, not a failed request.
            return Response.html(200, login_page(self.site.auth.csrf_token(f"pair:{nonce}"),
                                                 self.site.auth.code_requested(nonce), str(exc),
                                                 channel=self.site.auth.channel))
        self.site.logger.event("INFO", "web", "device_paired")
        response = Response.redirect("/")
        response.cookies.append(self._cookie(request, SESSION_COOKIE, token,
                                             self.site.settings.session_days * 86400))
        response.cookies.append(self._cookie(request, PAIR_COOKIE, "", 0))
        return response

    def logout(self, request: Request, session: WebSession, _form: dict[str, str]) -> Response:
        self.site.auth.revoke(session.id)
        self.site.logger.event("INFO", "web", "session_revoked", scope="current")
        return self._signed_out(request)

    def devices(self, request: Request, session: WebSession) -> Response:
        return Response.html(200, devices_page(
            self.site.auth.sessions(), session, self.site.auth.csrf_token(session.id), self.site.configured_timezone))

    def revoke(self, request: Request, session: WebSession, _form: dict[str, str],
               session_id: str) -> Response:
        self.site.auth.revoke(session_id)
        self.site.logger.event("INFO", "web", "session_revoked", scope="single")
        if session_id == session.id:
            return self._signed_out(request)
        return Response.redirect("/geraete")

    def revoke_all(self, request: Request, _session: WebSession, _form: dict[str, str]) -> Response:
        self.site.auth.revoke_all()
        self.site.logger.event("INFO", "web", "session_revoked", scope="all")
        return self._signed_out(request)


def _ip_or_localhost(name: str) -> bool:
    try:
        ipaddress.ip_address(name)
    except ValueError:
        return name == "localhost"
    return True


def link_code(query: str) -> str:
    """The code from a /web link (only digits, exactly 4), else empty."""
    try:
        value = parse_qs(query, max_num_fields=5).get("code", [""])[0]
    except ValueError:
        return ""
    return value if value.isascii() and value.isdigit() and len(value) == 4 else ""
