"""Telegram command /web: link to the web interface with a one-time code."""
from __future__ import annotations

import re
from datetime import timedelta

import pytest

from mailhelp.config import WebSettings
from mailhelp.review.inbox import CommandInbox
from mailhelp.storage import JsonStore
from mailhelp.telegram.commands import HELP, TelegramCommands
from mailhelp.web.auth import CODE_ATTEMPTS, CODE_REQUESTS, PairingLimited, PairingRefused
from mailhelp.web.factory import base_url, create_web
from mailhelp.web.site import _link_code
from test_web_auth import LOCAL, SECRET, TAILNET, Browser, auth, site  # noqa: F401  (fixtures)


def test_a_telegram_code_works_in_any_browser_once(auth):
    code = auth.issue_code()
    assert re.fullmatch(r"\d{4}", code) and auth.code_requested("irgendein-browser")
    assert code not in str(auth.store.load("web-pairing"))
    token = auth.redeem("neues-telefon", f"{code[:2]} {code[2:]}", "iPhone")
    assert auth.authenticate(token).device == "iPhone"
    with pytest.raises(PairingRefused, match="angefordert"):
        auth.redeem("anderer-browser", code, "x")


def test_a_new_telegram_code_replaces_the_previous_one(auth):
    first = auth.issue_code()
    second = auth.issue_code()
    with pytest.raises(PairingRefused, match="stimmt nicht"):
        auth.redeem("browser", first, "x")
    assert auth.redeem("browser", second, "x")


def test_browser_and_telegram_codes_coexist_and_share_the_limits(auth):
    auth.request_code("browser", "PC")
    browser_code = re.search(r"Code (\d{4})", auth.messages[-1]).group(1)
    telegram_code = auth.issue_code()
    assert auth.redeem("browser", telegram_code, "per Link")
    assert auth.redeem("browser", browser_code, "angefordert")
    auth.issue_code()
    with pytest.raises(PairingLimited):
        auth.issue_code()  # more than three codes in ten minutes
    auth.clock_.now += timedelta(minutes=11)
    auth.request_code("browser", "PC")
    auth.issue_code()
    for _ in range(CODE_ATTEMPTS):
        with pytest.raises(PairingRefused, match="stimmt nicht"):
            auth.redeem("browser", "0000", "x")
    # Wrong attempts count against every code this browser could use.
    assert auth.store.load("web-pairing")["codes"] == []
    assert CODE_REQUESTS == 3


def test_link_code_is_only_taken_from_a_clean_query():
    assert _link_code("code=1234") == "1234"
    for query in ("", "code=123", "code=abcdefgh", "code=１２３４", "code=12345",
                  "code=12345678", "&".join(f"x{index}=1" for index in range(10))):
        assert _link_code(query) == ""


def test_opening_the_link_prefills_the_code_and_pairs(site):
    code = site.auth.issue_code()
    phone = Browser(site, TAILNET)
    html = phone.request("GET", f"/anmelden?code={code}").body.decode()
    assert f'value="{code}"' in html and "Code aus Telegram" in html
    csrf = re.search(r'name="csrf" value="([^"]+)"', html).group(1)
    paired = phone.request("POST", "/anmelden", {"csrf": csrf, "code": code})
    assert paired.status == 303 and paired.headers["Location"] == "/"
    assert phone.request("GET", "/").status == 200


def test_without_any_code_the_login_starts_with_the_request_button(site):
    page = Browser(site).request("GET", "/anmelden").body.decode()
    assert "Code per Telegram senden" in page and "Code aus Telegram" not in page


class Telegram:
    def __init__(self):
        self.sent = []

    def send(self, chat_id, text, reply_markup=None):
        self.sent.append(text)


def test_telegram_command_sends_link_and_code():
    telegram = Telegram()

    def limited():
        raise PairingLimited("Zu viele Codes angefordert – bitte später erneut versuchen.")

    TelegramCommands(None, None, None, telegram, 2, None, None, None, lambda: "Link").handle("/web")
    TelegramCommands(None, None, None, telegram, 2, None, None, None, limited).handle("/web")
    TelegramCommands(None, None, None, telegram, 2, None).handle("/web")
    assert telegram.sent == ["Link", "Zu viele Codes angefordert – bitte später erneut versuchen.",
                             "Die Weboberfläche ist nicht aktiviert."]
    assert "/web – Link und Code" in HELP


def settings_with(tmp_path, hosts):
    from test_application import settings as app_settings
    configured = app_settings(tmp_path)
    configured.web = WebSettings(enabled=True, allowed_hosts=hosts)
    return configured


def test_the_link_uses_the_tailnet_name_when_configured(tmp_path):
    assert base_url(settings_with(tmp_path, [LOCAL, "localhost:8765"])) == "http://127.0.0.1:8765"
    assert base_url(settings_with(tmp_path, [LOCAL, TAILNET])) == f"https://{TAILNET}"


@pytest.mark.parametrize(("hosts", "url", "pc_only"), [
    ([LOCAL, TAILNET], f"https://{TAILNET}", False),
    ([LOCAL], "http://127.0.0.1:8765", True),
])
def test_invite_message(tmp_path, hosts, url, pc_only):
    with JsonStore(tmp_path / "data") as store:
        components = create_web(settings_with(tmp_path, hosts), SECRET, store, print,
                                __import__("test_web_auth").Logger(), CommandInbox(store))
        text = components.invite()
        code = re.search(rf"{re.escape(url)}/anmelden\?code=(\d{{4}})", text).group(1)
        assert f"Code: {code}" in text and "10 Minuten" in text
        assert ("nur am PC" in text) is pc_only
        assert components.auth.redeem("telefon", code, "iPhone")
