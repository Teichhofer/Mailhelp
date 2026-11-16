"""7.1: the public pages of the demo instance and the dispatch to each visitor's own interface.

Nothing here reaches a mailbox, Telegram or a model. A signed-in request goes to the interface of the
visitor area that belongs to the server-side session; routes that would set up, connect or analyse
anything are refused before they reach it, also when called directly.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from .app import WebApp
from .auth import WebAuth
from .http import Request, Response
from .login_site import PAIR_COOKIE, PAIR_COOKIE_SECONDS, SESSION_COOKIE, cookie
from .pages import e, error_page, layout, notice

DEMO_NOTICE = "Demo – Beispieldaten. Es werden keine echten Termine oder Aufgaben angelegt."
SESSION_SECONDS = 2 * 60 * 60
PUBLIC = re.compile(r"/(anmelden|demo/starten|health|static/.*|sw\.js|manifest\.webmanifest|offline\.html)")
# Setup, credentials, connections, devices, push and every model call are not part of the demo.
BLOCKED = re.compile(r"/(einrichtung|diagnose|geraete|auth|push|api/push|api/local-pair|hilfe|api/hilfe|berichte|"
                     r"einstellungen/(zugangsdaten|postfaecher|iserv|zielprofile|web-passwort|neustarten|beenden|"
                     r"benachrichtigungen)|lernen/(postfach|entscheidungen)|themen/lernen|mail/[^/]+/entwurf)(/.*)?")
# Opening the learning overview is fine; starting a learning run calls a model.
BLOCKED_POST = re.compile(r"/lernen")

VisitorApp = Callable[[Request], Response]


def demo_login_page(csrf: str, key: str, error: str | None = None) -> str:
    message = notice(error, "error") if error else ""
    body = (notice(DEMO_NOTICE, "info") + message
            + "<p>Diese Instanz zeigt Mailhelp mit 30 vorbereiteten Beispielmails. Es wird kein Postfach, "
              "kein Telegram und kein Kalender verbunden; jede Besucherin und jeder Besucher erhält eine "
              "eigene Kopie, die zwei Stunden gilt.</p>"
            + f'<form method="post" action="/demo/starten" class="stack">'
              f'<input type="hidden" name="csrf" value="{e(csrf)}">'
              f'<input type="hidden" name="key" value="{e(key)}">'
              '<button class="button primary" type="submit">Demo starten</button></form>')
    return layout("Demo", f'<section class="card narrow">\n<h1>Gerät koppeln</h1>\n{body}\n</section>',
                  signed_in=False)


class DemoSite:
    def __init__(self, public: WebApp, auth: WebAuth, logger: Any, start: Callable[[str, str], None],
                 visitor_app: Callable[[str], VisitorApp | None], full: Callable[[], bool]) -> None:
        self.public, self.auth, self.logger = public, auth, logger
        self.start, self.visitor_app, self.full = start, visitor_app, full
        public.route("GET", "/anmelden", self.login)
        public.route("POST", "/demo/starten", self.begin)

    def __call__(self, request: Request) -> Response:
        if PUBLIC.fullmatch(request.path):
            return self.public(request)
        session = self.auth.authenticate(request.cookies().get(SESSION_COOKIE))
        app = self.visitor_app(session.id) if session is not None else None
        if app is None:
            return Response.redirect("/anmelden") if request.method == "GET" else Response.text(
                403, "Sicherheitsprüfung fehlgeschlagen.")
        if BLOCKED.fullmatch(request.path) or request.method == "POST" and BLOCKED_POST.fullmatch(request.path):
            return Response.html(403, error_page("In der Demo nicht verfügbar",
                                                 "Diese Funktion verbindet echte Konten oder ruft eine KI auf. "
                                                 "In der Demo ist sie gesperrt."))
        return app(request)

    def _nonce(self, request: Request, response: Response) -> str:
        nonce = request.cookies().get(PAIR_COOKIE)
        if not nonce:
            nonce = self.auth.new_browser_nonce()
            response.cookies.append(cookie(request, PAIR_COOKIE, nonce, PAIR_COOKIE_SECONDS))
        return nonce

    def login(self, request: Request, error: str | None = None, status: int = 200) -> Response:
        session = self.auth.authenticate(request.cookies().get(SESSION_COOKIE))
        if session is not None and self.visitor_app(session.id) is not None:
            return Response.redirect("/")
        response = Response.html(status, "")
        nonce = self._nonce(request, response)
        key = self.auth.new_browser_nonce()
        response.body = demo_login_page(self.auth.csrf_token(f"pair:{nonce}"), key, error).encode("utf-8")
        return response

    def begin(self, request: Request) -> Response:
        nonce = request.cookies().get(PAIR_COOKIE)
        try:
            form = request.form(max_num_fields=4)
        except (UnicodeDecodeError, ValueError):
            return Response.text(400, "Ungültige Formulardaten.")
        key = form.get("key", "")
        if not nonce or not self.auth.csrf_valid(f"pair:{nonce}", form.get("csrf")) \
                or not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", key):
            self.logger.event("WARNING", "demo", "start_rejected", path=request.path)
            return Response.text(403, "Sicherheitsprüfung fehlgeschlagen.")
        token = request.cookies().get(SESSION_COOKIE)
        session = self.auth.authenticate(token)
        if session is None:
            if self.full():
                return self.login(request, "Gerade sind alle Demo-Plätze belegt. Bitte später erneut versuchen.",
                                  429)
            token = self.auth.demo_session("Demo")
            session = self.auth.authenticate(token)
        assert session is not None and token is not None  # demo_session created this session just now
        try:
            self.start(session.id, key)
        except (OSError, ValueError, RuntimeError) as exc:
            self.logger.event("ERROR", "demo", "start_failed", error=type(exc).__name__)
            return self.login(request, "Die Demo konnte nicht gestartet werden. Bitte später erneut versuchen.",
                              503)
        response = Response.redirect("/")
        response.cookies.append(cookie(request, SESSION_COOKIE, token, SESSION_SECONDS))
        self.logger.event("INFO", "demo", "visitor_started")
        return response
