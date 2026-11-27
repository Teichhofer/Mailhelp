"""7.1: the public pages of the demo instance and the dispatch to each visitor's own interface.

Nothing here reaches a mailbox, Telegram or a model. A signed-in request goes to the interface of the
visitor area that belongs to the server-side session; routes that would set up, connect or analyse
anything are refused before they reach it, also when called directly.
"""

from __future__ import annotations

import json
import re
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from threading import RLock
from typing import Any

from ..i18n import COOKIE, Locale, current, msg, negotiate, stored, tr, use_locale
from .app import WebApp
from .auth import WebAuth
from .http import Request, Response, rejected
from .login_site import PAIR_COOKIE, PAIR_COOKIE_SECONDS, SESSION_COOKIE, cookie
from .pages import CUSTOMER_VIEW, e, error_page, filter_links, layout, notice
from .permissions import PUBLIC_LINKS, customer_may

DEMO_NOTICE = msg("Demo – Beispieldaten. Es werden keine echten Termine oder Aufgaben angelegt.")
SESSION_SECONDS = 2 * 60 * 60
DEMO_INSTANCE = "demo"
# Starts of new demos per client and in total within one hour; a running demo is never affected.
STARTS_PER_CLIENT, STARTS_TOTAL, START_WINDOW = 5, 60, 3600.0
PUBLIC = re.compile(
    r"/(anmelden|sprache|de/|en/|demo/starten|health|static/.*|sw\.js|"
    r"manifest(?:-en)?\.webmanifest|offline(?:-en)?\.html)"
)
# 8.8.5 (Planung 8.8 AP5): deny by default. A visitor reaches only customer routes (CUSTOMER_ROUTES), and of
# those not the ones that connect accounts, change settings, send messages or call a model.
BLOCKED = re.compile(r"/(einrichtung|diagnose|auth|google|microsoft|notion|postfach|geraete|push|api/push|"
                     r"api/local-pair|hilfe|api/hilfe|berichte|benachrichtigungen|einstellungen/.+|"
                     r"lernen/(postfach|entscheidungen)|themen|"
                     r"mail/[^/]+/(entwurf|nachanalyse|absender-[a-z]+|domain-ignorieren))(/.*)?")
# Opening topics and learning is fine; saving topics, starting a learning run or re-running failed mails is not.
BLOCKED_POST = re.compile(r"/(lernen|themen|mails/fehler)(/.*)?")


def demo_may(method: str, path: str) -> bool:
    """Whether a demo visitor may call ``method path`` (always a subset of the customer routes)."""
    return (customer_may(method, path) and not BLOCKED.fullmatch(path)
            and not (method == "POST" and BLOCKED_POST.fullmatch(path)))


def demo_may_link(href: str) -> bool:
    """Whether a local link works in a demo visitor's session."""
    path = href.split("#", 1)[0].split("?", 1)[0]
    return bool(PUBLIC_LINKS.fullmatch(path)) or path == "/demo/neu-starten" or demo_may("GET", path)

VisitorApp = Callable[[Request], Response]
# The test mode carries the demo; its fixed texts become demo texts on every visitor page (7.1, D5).
# tests/web/test_demo_site.py checks that each original text still exists in the code.
DEMO_TEXTS = {
    "Simuliert (Testmodus)": msg("In der Demo angelegt"),
    "Simuliert – nichts eingetragen": msg("In der Demo angelegt – nichts extern eingetragen"),
    "Testmodus: Der Eintrag wird nur simuliert.": msg("Demo: Der Eintrag wird nur in der Demo angelegt."),
    "Speicherung im Testmodus simuliert.": msg("In der Demo gespeichert."),
    "Testmodus – Einträge werden nur simuliert": msg("Demo – Einträge werden nur in der Demo angelegt"),
}
# Button labels are replaced only as the complete text of an element.
DEMO_LABELS = {"Simulieren": msg("In der Demo anlegen")}
_MAIN = re.compile(r'<main id="inhalt"[^>]*>')
_ANSWER_FORM = re.compile(r'<form method="post" action="/aktion" class="stack">.*?</form>', re.S)
Prepared = dict[tuple[str, str, int], str]
# 7.6.2: the quick flow – keys on the desktop above the open list, a new round when all is decided.
KEYS_HINT = msg(
    
        '<p class="hint demo-keys-hint">Tipp: Mit den Tasten <kbd>1</kbd> (anlegen) '
        "und <kbd>2</kbd> (verwerfen) entscheidest du die ausgewählte Karte am schnellsten.</p>"
    
)
AGAIN = msg('<p><a class="button primary" href="/demo/neu-starten">Demo zurücksetzen und nochmals testen</a></p>')
_OPEN_LIST = re.compile(r'<div class="swipe-hint" data-swipe-hint')
_INBOX_ZERO = re.compile(r'<h2 id="inbox-zero">.*?</h2>', re.S)


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
    hint = '<p class="hint">' + tr("In der Demo vorbereitet: „{answer}“", answer=e(answer)) + "</p>"
    return re.sub(r"(<textarea[^>]*>)</textarea>", lambda match: hint + match.group(1) + e(answer) + "</textarea>",
                  form, count=1)


def demo_login_page(csrf: str, key: str, error: str | None = None) -> str:
    message = notice(error, "error") if error else ""
    body = (
        notice(tr(DEMO_NOTICE), "info")
        + message
        + "<p>"
        + tr(
            "Diese Instanz zeigt Mailhelp mit 30 vorbereiteten Beispielmails. Es wird kein Postfach, "
            "kein Telegram und kein Kalender verbunden; jede Besucherin und jeder Besucher erhält eine "
            "eigene Kopie, die zwei Stunden gilt."
        )
        + "</p>"
        + f'<form method="post" action="/demo/starten" class="stack">'
        f'<input type="hidden" name="csrf" value="{e(csrf)}">'
        f'<input type="hidden" name="key" value="{e(key)}">'
        f'<input type="hidden" name="locale" value="{current().value}">'
        f'<button class="button primary" type="submit">{tr("Demo starten")}</button></form>'
    )
    return layout(
        "Demo", f'<section class="card narrow">\n<h1>{tr("Demo starten")}</h1>\n{body}\n</section>', signed_in=False
    )


def demo_response(response: Response, prepared: Prepared | None = None) -> Response:
    """Demo wording and the permanent demo notice on every page of the visitor interface."""
    if not response.content_type.startswith(("text/html", "application/json")):
        return response
    text = response.body.decode("utf-8")
    if response.content_type.startswith("application/json"):
        payload = json.loads(text)
        if isinstance(payload, dict) and isinstance(payload.get("message"), str):
            with use_locale(current(), wording=DEMO_TEXTS | DEMO_LABELS):
                payload["message"] = stored(payload["message"])
            text = json.dumps(payload, ensure_ascii=False)
    else:
        text = _ANSWER_FORM.sub(lambda match: _prefill(match.group(0), prepared or {}), text)
        text = _OPEN_LIST.sub(lambda match: tr(KEYS_HINT) + match.group(0), text, count=1)
        text = _INBOX_ZERO.sub(lambda match: match.group(0) + tr(AGAIN), text, count=1)
        banner = (
            notice(tr(DEMO_NOTICE), "info")
            + f'<p class="hint"><a href="/demo/neu-starten">{tr("Demo neu starten")}</a></p>'
        )
        text = filter_links(_MAIN.sub(lambda match: match.group(0) + banner, text, count=1), demo_may_link)
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


def demo_restart_page(csrf: str, key: str, generation: int = 1) -> str:
    body = (
        "<p>"
        + tr(
            "Alle Änderungen in deiner Demo werden verworfen, und die 30 Beispielmails werden neu geladen. "
            "Andere Besucher sind davon nicht betroffen."
        )
        + "</p>"
        f'<form method="post" action="/demo/neu-starten" class="stack">'
        f'<input type="hidden" name="csrf" value="{e(csrf)}"><input type="hidden" name="key" value="{e(key)}">'
        f'<input type="hidden" name="locale" value="{current().value}">'
        f'<input type="hidden" name="demo_generation" value="{generation}">'
        f'<button class="button danger" type="submit">{tr("Demo jetzt neu starten")}</button>'
        f'<a class="button" href="/">{tr("Abbrechen")}</a></form>'
    )
    return layout(
        tr("Demo neu starten"), f'<section class="card narrow"><h1>{tr("Demo neu starten")}</h1>{body}</section>'
    )


@dataclass(frozen=True)
class DemoHooks:
    """What the demo site asks of the visitor areas (app.demo)."""

    start: Callable[[str, str, Locale], None]
    visitor_app: Callable[[str], VisitorApp | None]
    full: Callable[[], bool]
    reset: Callable[[str, str, Locale, int], None]
    dataset_locale: Callable[[str], Locale | None]
    prepared: Callable[[str], Prepared]
    generation: Callable[[str], int]


class DemoSite:
    def __init__(self, public: WebApp, auth: WebAuth, logger: Any, hooks: DemoHooks,
                 prepared: Prepared | None = None, *, trust_proxy: bool = False,
                 limits: StartLimits | None = None) -> None:
        self.lock = RLock()
        self.public, self.auth, self.logger = public, auth, logger
        self.prepared = prepared or {}
        self.start, self.visitor_app, self.full = hooks.start, hooks.visitor_app, hooks.full
        self.reset, self.trust_proxy = hooks.reset, trust_proxy
        self.dataset_locale, self.answers = hooks.dataset_locale, hooks.prepared
        self.generation = hooks.generation
        self.limits = limits or StartLimits()
        public.route("GET", "/anmelden", self.login)
        public.route("POST", "/demo/starten", self.begin)

    def __call__(self, request: Request) -> Response:
        locale = negotiate(request.cookies().get(COOKIE), request.header("accept-language"), self.public.default_locale)
        with self.lock, use_locale(locale, wording=DEMO_TEXTS | DEMO_LABELS):
            return self.dispatch(request)

    def dispatch(self, request: Request) -> Response:
        rejection = rejected(request, self.public.allowed_hosts, self.public.lan_port)
        if rejection is not None:
            return rejection
        if PUBLIC.fullmatch(request.path):
            return self.public(request)
        session = self.auth.authenticate(request.cookies().get(SESSION_COOKIE))
        app = self.visitor_app(session.id) if session is not None else None
        if app is None:
            return (
                Response.redirect("/anmelden")
                if request.method == "GET"
                else Response.text(403, tr(msg("Sicherheitsprüfung fehlgeschlagen.")))
            )
        if request.path == "/demo/neu-starten":
            assert session is not None  # visitor_app only answers for a live session
            return self.restart(request, session.id)
        if not demo_may(request.method, request.path):
            return self.refused()
        assert session is not None  # visitor_app only answers for a live session
        response = demo_response(app(request), self.answers(session.id))
        if response.content_type.startswith("text/html") and self.dataset_locale(session.id) != current():
            hint = notice(
                tr(
                    "Die Beispieldaten bleiben in ihrer bisherigen Sprache. "
                    "Starte die Demo neu, um die Beispieldaten in der gewählten Sprache zu laden."
                )
            )
            response.body = _MAIN.sub(
                lambda match: match.group(0) + hint, response.body.decode("utf-8"), count=1
            ).encode("utf-8")
        return response

    @staticmethod
    def refused() -> Response:
        """The same 403 for every route outside the demo, framed like the visitor's customer pages."""
        view = CUSTOMER_VIEW.set(True)
        try:
            page = error_page(tr("In der Demo nicht verfügbar"),
                              tr("Diese Funktion verbindet echte Konten, ändert Einstellungen oder ruft eine KI auf. "
                                 "In der Demo ist sie gesperrt."))
        finally:
            CUSTOMER_VIEW.reset(view)
        return Response.html(403, filter_links(page, demo_may_link))

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
            return Response.text(400, msg("Ungültige Formulardaten."))
        key = form.get("key", "")
        if (
            not nonce
            or not self.auth.csrf_valid(f"pair:{nonce}", form.get("csrf"))
            or not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", key)
        ):
            self.logger.event("WARNING", "demo", "start_rejected", path=request.path)
            return Response.text(403, msg("Sicherheitsprüfung fehlgeschlagen."))
        try:
            locale = Locale(form.get("locale", current().value))
        except ValueError:
            return Response.text(400, tr("Ungültige Sprachwahl."))
        token = request.cookies().get(SESSION_COOKIE)
        session = self.auth.authenticate(token)
        created = session is None
        if session is None:
            if not self.limits.allow(self.client(request)):
                return self.login(
                    request, tr("Zu viele Demo-Starts in kurzer Zeit. Bitte später erneut versuchen."), 429
                )
            if self.full() or len(self.auth.sessions()) >= self.auth.max_sessions:
                return self.login(
                    request, tr("Gerade sind alle Demo-Plätze belegt. Bitte später erneut versuchen."), 429
                )
            token = self.auth.demo_session("Demo")
            session = self.auth.authenticate(token)
        assert session is not None and token is not None  # demo_session created this session just now
        try:
            self.start(session.id, key, locale)
        except ValueError:
            if created:
                self.auth.revoke(session.id)
            return Response.text(409, tr("Dieser Demo-Auftrag wurde bereits mit anderen Angaben verwendet."))
        except (OSError, RuntimeError) as exc:
            if created:
                self.auth.revoke(session.id)
            self.logger.event("ERROR", "demo", "start_failed", error=type(exc).__name__)
            return self.login(
                request, tr("Die Demo konnte nicht gestartet werden. Bitte später erneut versuchen."), 503
            )
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
            page = demo_restart_page(
                self.auth.csrf_token(session_id), self.auth.new_browser_nonce(), self.generation(session_id)
            )
            return Response.html(200, demo_response(Response.html(200, page)).body.decode("utf-8"))
        try:
            form = request.form(max_num_fields=4)
        except (UnicodeDecodeError, ValueError):
            return Response.text(400, msg("Ungültige Formulardaten."))
        key = form.get("key", "")
        if not self.auth.csrf_valid(session_id, form.get("csrf")) or not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", key):
            return Response.text(403, msg("Sicherheitsprüfung fehlgeschlagen."))
        try:
            locale = Locale(form.get("locale", current().value))
        except ValueError:
            return Response.text(400, tr("Ungültige Sprachwahl."))
        generation = form.get("demo_generation", "1")
        if not re.fullmatch(r"[1-9][0-9]{0,9}", generation):
            return Response.text(400, msg("Ungültige Formulardaten."))
        try:
            self.reset(session_id, key, locale, int(generation))
        except ValueError:
            return Response.text(409, tr("Dieser Demo-Auftrag wurde bereits mit anderen Angaben verwendet."))
        except (OSError, RuntimeError) as exc:
            self.logger.event("ERROR", "demo", "reset_failed", error=type(exc).__name__)
            return Response.html(
                503,
                error_page(
                    tr("Demo neu starten"), tr("Der Neustart ist fehlgeschlagen. Deine bisherige Demo bleibt erhalten.")
                ),
            )
        self.logger.event("INFO", "demo", "visitor_reset")
        return Response.redirect("/")
