"""Pairing, sessions, CSRF and authorization of the web interface."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import pytest

from mailhelp.config import WebSettings
from mailhelp.storage import JsonStore
from mailhelp.telegram.commands import HELP, TelegramCommands
from mailhelp.web import Request, WebApp
from mailhelp.web.auth import (CODE_ATTEMPTS, CODE_REQUESTS, FAILURE_LIMIT, MAX_SESSIONS,
                               PairingLimited, PairingRefused, WebAuth, device_name)
from mailhelp.web.factory import create_web
from mailhelp.web.site import FORM_TYPE, PAIR_COOKIE, SESSION_COOKIE, MailhelpSite

LOCAL = "127.0.0.1:8765"
TAILNET = "mailhelp-pc.tail.ts.net"
SECRET = "s" * 40
IPHONE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 "
          "(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1")


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 11, 12, tzinfo=timezone.utc)

    def __call__(self):
        return self.now


class Logger:
    def __init__(self):
        self.events = []

    def event(self, level, module, event, **fields):
        self.events.append((level, event, fields))


def code_from(messages):
    return re.search(r"Code (\d{4}) (\d{4})", messages[-1]).group(0)[5:]


@pytest.fixture
def auth(tmp_path):
    messages, clock = [], Clock()
    with JsonStore(tmp_path) as store:
        service = WebAuth(store, SECRET, 30, messages.append, clock)
        service.messages, service.clock_ = messages, clock
        yield service


# --- WebAuth ---------------------------------------------------------------------

@pytest.mark.parametrize(("agent", "chosen", "expected"), [
    (IPHONE, None, "iPhone · Safari"),
    ("Mozilla/5.0 (Windows NT 10.0) Chrome/140.0 Safari/537.36 Edg/140.0", "", "Windows · Edge"),
    ("Mozilla/5.0 (Windows NT 10.0) Chrome/140.0 Safari/537.36", None, "Windows · Chrome"),
    ("Mozilla/5.0 (iPhone) CriOS/140 Safari/604.1", None, "iPhone · Chrome"),
    ("Mozilla/5.0 (Macintosh) Firefox/140.0", None, "Mac · Firefox"),
    ("Mozilla/5.0 (Linux; Android 15)", None, "Android"),
    ("Mozilla/5.0 (iPad)", None, "iPad"),
    ("Mozilla/5.0 (X11; Linux x86_64)", None, "Linux"),
    (None, None, "Unbekanntes Gerät"),
    (IPHONE, "  Mein   iPhone ", "Mein iPhone"),
    (IPHONE, "x" * 80, "x" * 60),
])
def test_device_names(agent, chosen, expected):
    assert device_name(agent, chosen) == expected


def test_a_code_is_sent_to_telegram_and_creates_one_session(auth):
    auth.request_code("browser", "iPhone")
    assert auth.code_requested("browser") and not auth.code_requested("other")
    assert "„iPhone“" in auth.messages[-1] and "10 Minuten" in auth.messages[-1]
    code = code_from(auth.messages)
    stored = auth.store.load("web-pairing")
    assert code.replace(" ", "") not in str(stored)
    with pytest.raises(PairingRefused, match="angefordert"):
        auth.redeem("other", code, "Fremd")
    token = auth.redeem("browser", code, "iPhone")
    assert "Neues Gerät" in auth.messages[-1] and "/web_abmelden" in auth.messages[-1]
    assert token not in str(auth.store.load("web-sessions"))
    session = auth.authenticate(token)
    assert session.device == "iPhone" and auth.active(session.id)
    # The code is spent.
    with pytest.raises(PairingRefused):
        auth.redeem("browser", code, "iPhone")


def test_wrong_codes_spend_the_code_and_expired_codes_are_refused(auth):
    auth.request_code("browser", "PC")
    code = code_from(auth.messages)
    for _ in range(CODE_ATTEMPTS):
        with pytest.raises(PairingRefused, match="stimmt nicht"):
            auth.redeem("browser", "00000000" if code != "0000 0000" else "11111111", "PC")
    with pytest.raises(PairingRefused, match="angefordert"):
        auth.redeem("browser", code, "PC")
    auth.clock_.now += timedelta(minutes=11)
    auth.request_code("browser", "PC")
    code = code_from(auth.messages)
    auth.clock_.now += timedelta(minutes=10, seconds=1)
    with pytest.raises(PairingRefused, match="abgelaufen"):
        auth.redeem("browser", code, "PC")


def test_code_requests_and_failures_are_rate_limited(auth):
    for _ in range(CODE_REQUESTS):
        auth.request_code("browser", "PC")
    with pytest.raises(PairingLimited):
        auth.request_code("browser", "PC")
    auth.clock_.now += timedelta(minutes=10, seconds=1)
    for index in range(FAILURE_LIMIT // CODE_ATTEMPTS):
        auth.clock_.now += timedelta(seconds=1)
        if index and index % CODE_REQUESTS == 0:
            auth.clock_.now += timedelta(minutes=10, seconds=1)
        auth.request_code(f"browser-{index}", "PC")
        for _ in range(CODE_ATTEMPTS):
            with pytest.raises(PairingRefused):
                auth.redeem(f"browser-{index}", "x", "PC")
    with pytest.raises(PairingLimited):
        auth.redeem("browser-0", "x", "PC")
    with pytest.raises(PairingLimited):
        auth.request_code("fresh", "PC")
    auth.clock_.now += timedelta(hours=1)
    auth.request_code("fresh", "PC")


def pair(auth, device="PC", browser="browser"):
    auth.request_code(browser, device)
    return auth.redeem(browser, code_from(auth.messages), device)


def test_sessions_expire_are_touched_rarely_and_can_be_revoked(auth):
    first = pair(auth, "PC")
    auth.clock_.now += timedelta(minutes=1)
    second = pair(auth, "iPhone", "phone")
    saved = auth.store.load("web-sessions")
    auth.clock_.now += timedelta(minutes=1)
    auth.authenticate(first)
    assert auth.store.load("web-sessions") == saved
    auth.clock_.now += timedelta(minutes=5)
    assert auth.authenticate(first).last_used_at == auth.clock_.now
    assert [item.device for item in auth.sessions()] == ["PC", "iPhone"]
    assert auth.authenticate(None) is None and auth.authenticate("") is None
    assert auth.authenticate("unbekannt") is None
    phone = auth.authenticate(second)
    assert auth.revoke(phone.id) and not auth.revoke(phone.id)
    assert auth.authenticate(second) is None and not auth.active(phone.id)
    auth.clock_.now += timedelta(days=31)
    assert auth.authenticate(first) is None and auth.sessions() == []
    pair(auth, "Neu", "new")
    assert auth.revoke_all() == 1 and auth.sessions() == []


def test_the_number_of_sessions_is_bounded(auth):
    tokens = []
    for index in range(MAX_SESSIONS + 1):
        auth.clock_.now += timedelta(minutes=11)
        tokens.append(pair(auth, f"Gerät {index}", f"browser-{index}"))
    assert len(auth.sessions()) == MAX_SESSIONS
    assert auth.authenticate(tokens[0]) is None and auth.authenticate(tokens[-1]) is not None


def test_csrf_tokens_are_bound_and_keyed(auth, tmp_path):
    token = auth.csrf_token("session")
    assert auth.csrf_valid("session", token)
    assert not auth.csrf_valid("other", token) and not auth.csrf_valid("session", None)
    other = WebAuth(auth.store, "t" * 40, 30, print)
    assert not other.csrf_valid("session", token)
    assert auth.new_browser_nonce() != auth.new_browser_nonce()


# --- routes ------------------------------------------------------------------------

class Browser:
    """A minimal cookie-keeping client for the in-process web app."""

    def __init__(self, app, host=LOCAL, agent=IPHONE):
        self.app, self.host, self.agent, self.cookies = app, host, agent, {}

    def request(self, method, path, form=None, content_type=FORM_TYPE, **headers):
        cookie = "; ".join(f"{name}={value}" for name, value in self.cookies.items())
        base = {"host": self.host, "user-agent": self.agent, "cookie": cookie}
        body = urlencode(form or {}).encode() if form is not None else b""
        if form is not None:
            base["content-type"] = content_type
        response = self.app(Request(method, path, {**base, **headers}, body=body))
        for line in response.cookies:
            name, value = line.split(";")[0].split("=", 1)
            if "Max-Age=0" in line:
                self.cookies.pop(name, None)
            else:
                self.cookies[name] = value
        return response

    def csrf(self, path="/anmelden"):
        page = self.request("GET", path).body.decode()
        return re.search(r'name="csrf" value="([^"]+)"', page).group(1)


@pytest.fixture
def site(tmp_path):
    messages, logger = [], Logger()
    with JsonStore(tmp_path) as store:
        auth = WebAuth(store, SECRET, 30, messages.append)
        app = WebApp([LOCAL, TAILNET])
        MailhelpSite(app, auth, WebSettings(allowed_hosts=[LOCAL, TAILNET]), "Europe/Berlin", logger)
        app.messages, app.logger, app.auth = messages, logger, auth
        yield app


def signed_in(site, host=LOCAL, device=""):
    browser = Browser(site, host)
    csrf = browser.csrf()
    assert browser.request("POST", "/anmelden/code", {"csrf": csrf}).headers["Location"] == "/anmelden"
    response = browser.request("POST", "/anmelden", {"csrf": csrf, "code": code_from(site.messages),
                                                     "geraet": device})
    assert response.status == 303 and response.headers["Location"] == "/"
    return browser, response


def test_pairing_flow_sets_strict_cookies(site):
    browser = Browser(site)
    login = browser.request("GET", "/anmelden")
    assert login.status == 200 and "Code per Telegram senden" in login.body.decode()
    assert PAIR_COOKIE in browser.cookies
    pair_cookie = login.cookies[0]
    assert "HttpOnly" in pair_cookie and "SameSite=Strict" in pair_cookie and "Secure" not in pair_cookie
    _, response = signed_in(site)
    session_cookie = next(line for line in response.cookies if line.startswith(SESSION_COOKIE))
    assert "Max-Age=2592000" in session_cookie and "SameSite=Strict" in session_cookie
    assert any(line.startswith(f"{PAIR_COOKIE}=;") for line in response.cookies)


def test_cookies_are_secure_through_tailscale(site):
    browser, response = signed_in(site, TAILNET)
    assert all("; Secure" in line for line in response.cookies)
    assert browser.request("GET", "/").status == 200


def test_login_page_shows_the_code_form_and_redirects_signed_in_users(site):
    browser = Browser(site)
    csrf = browser.csrf()
    browser.request("POST", "/anmelden/code", {"csrf": csrf})
    page = browser.request("GET", "/anmelden").body.decode()
    assert 'autocomplete="one-time-code"' in page and "Neuen Code senden" in page
    wrong = browser.request("POST", "/anmelden", {"csrf": csrf, "code": "1"})
    assert wrong.status == 200 and "Der Code stimmt nicht." in wrong.body.decode()
    browser.request("POST", "/anmelden", {"csrf": csrf, "code": code_from(site.messages)})
    assert browser.request("GET", "/anmelden").headers["Location"] == "/"


def test_pairing_requests_are_checked(site):
    browser = Browser(site)
    assert browser.request("POST", "/anmelden/code", {"csrf": "x"}).headers["Location"] == "/anmelden"
    csrf = browser.csrf()
    assert browser.request("POST", "/anmelden/code", {"csrf": "falsch"}).status == 403
    assert browser.request("POST", "/anmelden", {"csrf": "falsch", "code": "1"}).status == 403
    assert browser.request("POST", "/anmelden/code", {"csrf": csrf}, content_type="text/plain").status == 415
    bad = browser.app(Request("POST", "/anmelden/code", {
        "host": LOCAL, "content-type": FORM_TYPE, "cookie": f"{PAIR_COOKIE}={browser.cookies[PAIR_COOKIE]}"},
        body=b"csrf=\xff"))
    assert bad.status == 400
    assert any(event == "csrf_rejected" for _, event, _ in site.logger.events)


def test_pairing_limits_and_telegram_failures_are_explained(site, monkeypatch):
    browser = Browser(site)
    csrf = browser.csrf()
    for _ in range(CODE_REQUESTS):
        browser.request("POST", "/anmelden/code", {"csrf": csrf})
    limited = browser.request("POST", "/anmelden/code", {"csrf": csrf})
    assert limited.status == 429 and "Zu viele Anfragen" in limited.body.decode()

    def locked(*_):
        raise PairingLimited("Zu viele Fehlversuche")

    monkeypatch.setattr(site.auth, "redeem", locked)
    assert browser.request("POST", "/anmelden", {"csrf": csrf, "code": "1"}).status == 429

    def down(*_):
        raise RuntimeError("telegram down")

    monkeypatch.setattr(site.auth, "request_code", down)
    unavailable = browser.request("POST", "/anmelden/code", {"csrf": csrf})
    assert unavailable.status == 503 and "Telegram" in unavailable.body.decode()


def test_pages_require_a_session_and_forged_tailscale_headers_do_nothing(site):
    stranger = Browser(site, TAILNET)
    forged = {"tailscale-user-login": "owner@example.test", "tailscale-user-name": "Owner"}
    assert stranger.request("GET", "/", **forged).headers["Location"] == "/anmelden"
    assert stranger.request("GET", "/geraete", **forged).headers["Location"] == "/anmelden"
    assert stranger.request("POST", "/geraete/alle-abmelden", {"csrf": "x"}, **forged).status == 403
    stranger.cookies[SESSION_COOKIE] = "geraten"
    assert stranger.request("GET", "/").headers["Location"] == "/anmelden"


def test_session_posts_need_form_data_and_the_session_csrf_token(site):
    browser, _ = signed_in(site)
    assert browser.request("POST", "/abmelden", {"csrf": "falsch"}).status == 403
    assert browser.request("POST", "/abmelden", {"csrf": "x"}, content_type="application/json").status == 415
    # A token of another session is not accepted either.
    other, _ = signed_in(site)
    stolen = other.csrf("/geraete")
    assert browser.request("POST", "/abmelden", {"csrf": stolen}).status == 403
    assert browser.request("GET", "/").status == 200


def test_devices_page_escapes_names_and_revokes(site):
    browser, _ = signed_in(site, device='<script>alert("x")</script>')
    other, _ = signed_in(site, device="Laptop")
    page = browser.request("GET", "/geraete").body.decode()
    assert "<script>alert" not in page and "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;" in page
    assert "dieses Gerät" in page and "Laptop" in page
    csrf = browser.csrf("/geraete")
    laptop = next(item for item in site.auth.sessions() if item.device == "Laptop")
    response = browser.request("POST", f"/geraete/{laptop.id}/abmelden", {"csrf": csrf})
    assert response.headers["Location"] == "/geraete"
    assert other.request("GET", "/").headers["Location"] == "/anmelden"
    own = site.auth.sessions()[0]
    response = browser.request("POST", f"/geraete/{own.id}/abmelden", {"csrf": csrf})
    assert response.headers["Location"] == "/anmelden" and SESSION_COOKIE not in browser.cookies


def test_logout_and_revoke_all(site):
    browser, _ = signed_in(site)
    other, _ = signed_in(site)
    csrf = browser.csrf("/geraete")
    assert browser.request("POST", "/abmelden", {"csrf": csrf}).headers["Location"] == "/anmelden"
    assert browser.request("GET", "/").headers["Location"] == "/anmelden"
    assert other.request("GET", "/").status == 200
    response = other.request("POST", "/geraete/alle-abmelden", {"csrf": other.csrf("/geraete")})
    assert response.headers["Location"] == "/anmelden" and site.auth.sessions() == []


# --- Telegram command and assembly ----------------------------------------------

class Telegram:
    def __init__(self):
        self.sent = []

    def send(self, chat_id, text, reply_markup=None):
        self.sent.append(text)


def test_telegram_command_signs_out_every_device():
    telegram = Telegram()
    TelegramCommands(None, None, None, telegram, 2, None, None, lambda: 3).handle("/web_abmelden")
    TelegramCommands(None, None, None, telegram, 2, None).handle("/web_abmelden")
    assert telegram.sent == ["🔐 Alle Geräte der Weboberfläche wurden abgemeldet (3).",
                             "Die Weboberfläche ist nicht aktiviert."]
    assert "/web_abmelden" in HELP


def test_create_web_requires_the_secret_and_authorizes_live_sessions(tmp_path):
    from test_application import settings as app_settings
    configured = app_settings(tmp_path)
    with JsonStore(tmp_path / "data") as store:
        with pytest.raises(ValueError, match="MAILHELP_WEB_SECRET"):
            create_web(configured, None, store, print, Logger())
        messages = []
        components = create_web(configured, SECRET, store, messages.append, Logger())
        components.auth.request_code("b", "PC")
        token = components.auth.redeem("b", code_from(messages), "PC")
        session = components.auth.authenticate(token)
        assert components.authorize(f"web:{session.id}")
        assert not components.authorize("web:0000000000000000")
        assert components.server.port == 8765
