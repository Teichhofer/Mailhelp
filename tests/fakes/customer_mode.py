"""8.7: browsers paired in customer mode for the role tests (synthetic sessions only)."""
from __future__ import annotations

from mailhelp.web.auth import PAIRING
from tests.fakes.shared_web_auth import Browser


def signed_in(web, role=None, device="Kundengerät"):
    """A browser paired with a code; an operator code only comes from the host."""
    browser = Browser(web.app)
    csrf = browser.csrf()
    web.store.save(PAIRING, {**web.store.load(PAIRING, {}), "requests": []})  # not the limit under test
    code = web.auth.issue_code(role)
    browser.request("POST", "/anmelden", {"csrf": csrf, "code": code, "geraet": device})
    return browser


def session_of(web, browser):
    return web.auth.authenticate(browser.cookies["mh_session"])
