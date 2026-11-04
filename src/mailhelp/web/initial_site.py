"""Minimal authenticated first-run routes; no mail or external write adapters exist here."""
from __future__ import annotations

from collections.abc import Callable

from ..config import WebSettings
from ..runtime.initial_setup import InitialSetup
from ..runtime.local_pairing import issue
from .app import WebApp
from .auth import PairingLimited, WebAuth, WebSession
from .http import Request, Response
from .initial_pages import initial_page
from .login_site import SESSION_COOKIE, LoginSite
from .pages import error_page, layout
from .server import EventLogger


class InitialSite:
    def __init__(self, app: WebApp, auth: WebAuth, settings: WebSettings, logger: EventLogger,
                 setup: InitialSetup, stop: Callable[[], None]):
        self.app, self.auth, self.settings, self.logger = app, auth, settings, logger
        self.setup, self.stop = setup, stop
        self.configured_timezone = "Europe/Berlin"
        self.login_pages = LoginSite(self)
        for method, path, public_handler in (
            ("GET", "/anmelden", self.login_pages.login), ("POST", "/anmelden", self.login_pages.pair),
            ("POST", "/anmelden/code", self.login_pages.request_code),
            ("POST", "/anmelden/passwort", self.login_pages.password),
            ("POST", "/api/local-pair", self.local_pair)):
            app.route(method, path, public_handler)
        for method, path, handler in (
            ("GET", "/", self.page), ("GET", "/einrichtung/start", self.page),
            ("GET", r"/einrichtung/schritt/(?P<step>[1-5])", self.page),
            ("POST", "/einrichtung/speichern", self.save),
            ("POST", r"/einrichtung/test/(?P<component>imap|llm|ziele)", self.probe),
            ("POST", "/abmelden", self.login_pages.logout)):
            app.route(method, path, self.signed_in(handler))

    def _form(self, request: Request) -> dict[str, str] | Response:
        if (request.header("content-type") or "").split(";")[0] != "application/x-www-form-urlencoded":
            return Response.text(415, "Nur Formulardaten werden angenommen.")
        try:
            return request.form(max_num_fields=40)
        except (UnicodeDecodeError, ValueError):
            return Response.text(400, "Ungültige Formulardaten.")

    @staticmethod
    def _forbidden() -> Response:
        return Response.text(403, "Sicherheitsprüfung fehlgeschlagen.")

    def signed_in(self, handler: Callable[..., Response]) -> Callable[..., Response]:
        def guarded(request: Request, **arguments: str) -> Response:
            session = self.auth.authenticate(request.cookies().get(SESSION_COOKIE))
            if session is None:
                return Response.redirect("/anmelden") if request.method == "GET" else self._forbidden()
            if request.method == "POST":
                form = self._form(request)
                if isinstance(form, Response):
                    return form
                if not self.auth.csrf_valid(session.id, form.get("csrf")):
                    return self._forbidden()
                return handler(request, session, form, **arguments)
            return handler(request, session, **arguments)
        return guarded

    def page(self, _request: Request, session: WebSession, step: str = "") -> Response:
        state = self.setup.state()
        number = int(step) if step else state.step
        if number > state.completed_step + 1:
            return Response.redirect("/einrichtung/start")
        return Response.html(200, initial_page(state, self.auth.csrf_token(session.id), number))

    def save(self, _request: Request, session: WebSession, form: dict[str, str]) -> Response:
        try:
            if form.get("step") == "5":
                if form.get("confirm") != "yes":
                    raise ValueError("Speichern ausdrücklich bestätigen.")
                self.setup.finish("web:" + session.id, int(form["version"]), form["key"])
                response = Response.html(200, layout("Einrichtung abgeschlossen",
                    '<h1>Einrichtung abgeschlossen</h1><p>Mailhelp aktiviert jetzt den Normalbetrieb.</p>'
                    '<p><a class="button" href="/lernen">Zum Lernmodus</a></p>', signed_in=False))
                response.after_send = self.stop
                return response
            self.setup.save("web:" + session.id, form)
        except Exception:
            return self._failed()
        return Response.redirect("/einrichtung/start")

    def probe(self, _request: Request, session: WebSession, form: dict[str, str], component: str) -> Response:
        if form.get("step") != {"imap": "2", "llm": "3", "ziele": "4"}[component]:
            return Response.text(400, "Ungültiger Prüfschritt.")
        try:
            self.setup.save("web:" + session.id, form, probe=True)
        except Exception:
            # Server responses may contain passwords; only this fixed message reaches the browser.
            return self._failed()
        return Response.redirect("/einrichtung/start")

    @staticmethod
    def _failed() -> Response:
        return Response.html(409, error_page("Einrichtung nicht gespeichert",
            "Eingaben und Verbindungsdaten prüfen. Bei einem Versionskonflikt die Einrichtung neu laden. "
            "Gespeicherte Zugangsdaten bleiben erhalten; Passwörter werden nicht erneut angezeigt.", signed_in=False))

    def local_pair(self, request: Request) -> Response:
        form = self._form(request)
        if isinstance(form, Response):
            return form
        try:
            code = issue(self.auth, form.get("message", ""), form.get("signature", ""))
        except (PermissionError, PairingLimited):
            return self._forbidden()
        return Response.json(200, {"code": code})
