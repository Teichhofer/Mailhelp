"""7.1: the public pages of the demo instance and the dispatch to each visitor's own interface.

Nothing here reaches a mailbox, Telegram or a model. A signed-in request goes to the interface of the
visitor area that belongs to the server-side session; routes that would set up, connect or analyse
anything are refused before they reach it, also when called directly.
"""
from __future__ import annotations

import re
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .app import WebApp
from .auth import WebAuth
from .http import Request, Response
from .login_site import PAIR_COOKIE, PAIR_COOKIE_SECONDS, SESSION_COOKIE, cookie
from .pages import e, error_page, layout, notice

DEMO_NOTICE = "Demo – Beispieldaten. Es werden keine echten Termine oder Aufgaben angelegt."
SESSION_SECONDS = 2 * 60 * 60
# Starts of new demos per client and in total within one hour; a running demo is never affected.
STARTS_PER_CLIENT, STARTS_TOTAL, START_WINDOW = 5, 60, 3600.0
PUBLIC = re.compile(r"/(anmelden|demo/starten|health|static/.*|sw\.js|manifest\.webmanifest|offline\.html)")
# Setup, credentials, connections, devices, push and every model call are not part of the demo.
BLOCKED = re.compile(r"/(einrichtung|diagnose|geraete|auth|push|api/push|api/local-pair|hilfe|api/hilfe|berichte|"
                     r"einstellungen/(zugangsdaten|postfaecher|iserv|zielprofile|web-passwort|neustarten|beenden|"
                     r"benachrichtigungen)|lernen/(postfach|entscheidungen)|themen/lernen|mail/[^/]+/entwurf)(/.*)?")
# Opening the learning overview is fine; starting a learning run calls a model.
BLOCKED_POST = re.compile(r"/lernen")

VisitorApp = Callable[[Request], Response]
# The test mode carries the demo; its fixed texts become demo texts on every visitor page (7.1, D5).
# tests/web/test_demo_site.py checks that each original text still exists in the code.
DEMO_TEXTS = {
    "Simuliert (Testmodus)": "In der Demo angelegt",
    "Simuliert – nichts eingetragen": "In der Demo angelegt – nichts extern eingetragen",
    "Testmodus: Der Eintrag wird nur simuliert.": "Demo: Der Eintrag wird nur in der Demo angelegt.",
    "Speicherung im Testmodus simuliert.": "In der Demo gespeichert.",
    "Testmodus – Einträge werden nur simuliert": "Demo – Einträge werden nur in der Demo angelegt",
}
# Button labels are replaced only as the complete text of an element.
DEMO_LABELS = {"Simulieren": "In der Demo anlegen"}
_MAIN = re.compile(r'<main id="inhalt"[^>]*>')
_ANSWER_FORM = re.compile(r'<form method="post" action="/aktion" class="stack">.*?</form>', re.S)
Prepared = dict[tuple[str, str, int], str]


def _field(form: str, name: str) -> str:
    match = re.search(rf'name="{name}" value="([^"]*)"', form)
    return match.group(1) if match else ""


def _prefill(form: str, prepared: Prepared) -> str:
    """Offer the prepared example answer of this proposal version in its answer form."""
    if 'name="kind" value="answer"' not in form or not _field(form, "version").isdigit():
        return form
    answer = prepared.get((_field(form, "mail_id"), _field(form, "proposal_id"), int(_field(form, "version"))))
    if answer is None:
        return form
    hint = f'<p class="hint">In der Demo vorbereitet: „{e(answer)}“</p>'
    return re.sub(r"(<textarea[^>]*>)</textarea>", lambda match: hint + match.group(1) + e(answer) + "</textarea>",
                  form, count=1)


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


def demo_response(response: Response, prepared: Prepared | None = None) -> Response:
    """Demo wording and the permanent demo notice on every page of the visitor interface."""
    if not response.content_type.startswith(("text/html", "application/json")):
        return response
    text = response.body.decode("utf-8")
    for original, replacement in DEMO_TEXTS.items():
        text = text.replace(original, replacement)
    if response.content_type.startswith("text/html"):
        for original, replacement in DEMO_LABELS.items():
            text = text.replace(f">{original}<", f">{replacement}<")
        text = _ANSWER_FORM.sub(lambda match: _prefill(match.group(0), prepared or {}), text)
        banner = (notice(DEMO_NOTICE, "info")
                  + '<p class="hint"><a href="/demo/neu-starten">Demo neu starten</a></p>')
        text = _MAIN.sub(lambda match: match.group(0) + banner, text, count=1)
    response.body = text.encode("utf-8")
    return response


class StartLimits:
    """Bounded starts of new demos, per client and in total, within a sliding window."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self.starts: deque[tuple[float, str]] = deque()

    def allow(self, client: str) -> bool:
        now = self.clock()
        while self.starts and now - self.starts[0][0] >= START_WINDOW:
            self.starts.popleft()
        own = sum(1 for _, holder in self.starts if holder == client)
        if own >= STARTS_PER_CLIENT or len(self.starts) >= STARTS_TOTAL:
            return False
        self.starts.append((now, client))
        return True


def demo_restart_page(csrf: str, key: str) -> str:
    body = ("<p>Alle Änderungen in deiner Demo werden verworfen, und die 30 Beispielmails werden neu geladen. "
            "Andere Besucher sind davon nicht betroffen.</p>"
            f'<form method="post" action="/demo/neu-starten" class="stack">'
            f'<input type="hidden" name="csrf" value="{e(csrf)}"><input type="hidden" name="key" value="{e(key)}">'
            '<button class="button danger" type="submit">Demo jetzt neu starten</button>'
            '<a class="button" href="/">Abbrechen</a></form>')
    return layout("Demo neu starten", f'<section class="card narrow"><h1>Demo neu starten</h1>{body}</section>')


@dataclass(frozen=True)
class DemoHooks:
    """What the demo site asks of the visitor areas (app.demo)."""
    start: Callable[[str, str], None]
    visitor_app: Callable[[str], VisitorApp | None]
    full: Callable[[], bool]
    reset: Callable[[str, str], None]


class DemoSite:
    def __init__(self, public: WebApp, auth: WebAuth, logger: Any, hooks: DemoHooks,
                 prepared: Prepared | None = None, *, trust_proxy: bool = False,
                 limits: StartLimits | None = None) -> None:
        self.public, self.auth, self.logger = public, auth, logger
        self.prepared = prepared or {}
        self.start, self.visitor_app, self.full = hooks.start, hooks.visitor_app, hooks.full
        self.reset, self.trust_proxy = hooks.reset, trust_proxy
        self.limits = limits or StartLimits()
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
        if request.path == "/demo/neu-starten":
            assert session is not None  # visitor_app only answers for a live session
            return self.restart(request, session.id)
        if BLOCKED.fullmatch(request.path) or request.method == "POST" and BLOCKED_POST.fullmatch(request.path):
            return Response.html(403, error_page("In der Demo nicht verfügbar",
                                                 "Diese Funktion verbindet echte Konten oder ruft eine KI auf. "
                                                 "In der Demo ist sie gesperrt."))
        return demo_response(app(request), self.prepared)

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
            if not self.limits.allow(self.client(request)):
                return self.login(request, "Zu viele Demo-Starts in kurzer Zeit. Bitte später erneut versuchen.", 429)
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

    def client(self, request: Request) -> str:
        """The client address; behind a trusted reverse proxy the address that proxy appended last."""
        forwarded = (request.header("x-forwarded-for") or "").split(",")[-1].strip()
        return forwarded if self.trust_proxy and forwarded else request.client

    def restart(self, request: Request, session_id: str) -> Response:
        """Confirm, then replace only this visitor's area with a fresh copy of the dataset."""
        if request.method == "GET":
            page = demo_restart_page(self.auth.csrf_token(session_id), self.auth.new_browser_nonce())
            return Response.html(200, demo_response(Response.html(200, page)).body.decode("utf-8"))
        try:
            form = request.form(max_num_fields=4)
        except (UnicodeDecodeError, ValueError):
            return Response.text(400, "Ungültige Formulardaten.")
        key = form.get("key", "")
        if not self.auth.csrf_valid(session_id, form.get("csrf")) or not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", key):
            return Response.text(403, "Sicherheitsprüfung fehlgeschlagen.")
        self.reset(session_id, key)
        self.logger.event("INFO", "demo", "visitor_reset")
        return Response.redirect("/")
