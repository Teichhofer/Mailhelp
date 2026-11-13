"""Minimal authenticated first-run routes; no mail or external write adapters exist here."""
from __future__ import annotations

from collections.abc import Callable

from pydantic import ValidationError

from ..config import WebSettings
from ..runtime.initial_checks import InitialChecks, invalid_findings
from ..runtime.initial_setup import SECRET_FIELDS, InitialSetup
from ..runtime.local_pairing import issue
from ..runtime.setup_messages import CheckResult, SetupProblem, classify, finding
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
        self.checks = InitialChecks(setup)
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
            ("POST", "/einrichtung/pruefen", self.check),
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
        except PermissionError:
            return self._forbidden()
        except Exception as error:  # noqa: BLE001 – classified by type; the text never reaches the browser
            return self._explain(session, form, error)
        return Response.redirect("/einrichtung/start")

    def _explain(self, session: WebSession, form: dict[str, str], error: Exception) -> Response:
        """6.1: a failed save shows what is wrong on the same step, with the entered values kept."""
        step = int(form["step"]) if form.get("step", "").isdigit() and 1 <= int(form["step"]) <= 5 else 0
        if not step:
            return self._failed()
        if step == 5:
            try:
                results = self.checks.check_all("web:" + session.id)
            except PermissionError:
                return self._forbidden()
        elif isinstance(error, ValidationError):
            results = [CheckResult(step=step, ok=False, findings=invalid_findings(error))]
        elif isinstance(error, SetupProblem):
            results = [CheckResult(step=step, ok=False, findings=[
                finding(error.code, detail=error.detail, field=error.field)])]
        else:
            results = [CheckResult(step=step, ok=False, findings=[finding(classify(error))])]
        return self._result(session, step, form, results, 409)

    def check(self, _request: Request, session: WebSession, form: dict[str, str]) -> Response:
        """6.1: check the entered values of one step (5: every step); nothing is saved."""
        actor = "web:" + session.id
        step = int(form["step"]) if form.get("step", "").isdigit() else 0
        if not 1 <= step <= min(5, self.setup.state().completed_step + 1):
            return Response.text(400, "Ungültiger Prüfschritt.")
        try:
            results = self.checks.check_all(actor) if step == 5 else [self.checks.check(actor, form)]
        except PermissionError:
            return self._forbidden()
        limited = any(item.code == "limit" for result in results for item in result.findings)
        return self._result(session, step, form, results, 429 if limited else 200)

    def _result(self, session: WebSession, step: int, form: dict[str, str], results: list[CheckResult],
                status: int) -> Response:
        hidden = {"csrf", "key", "version", "step", "password", "confirm", *SECRET_FIELDS.get(step, ())}
        values = {name: value for name, value in form.items() if name not in hidden}
        return Response.html(status, initial_page(self.setup.state(), self.auth.csrf_token(session.id), step,
                                                  checks=results, values=values))

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
