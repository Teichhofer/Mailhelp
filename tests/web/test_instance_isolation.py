"""8.7.9 (AP5): two customer instances side by side stay apart – sessions, codes and references.

Each instance has its own state directory, as on the server (``/opt/mailhelp-kunde`` and the demo).
Swapping cookies, codes or mail references between them never reaches the other instance's data.
"""
from __future__ import annotations

import pytest

from mailhelp.persistence.storage import JsonStore
from mailhelp.web.auth import PAIRING
from tests.fakes.customer_mode import signed_in
from tests.fakes.shared_web_actions import Web
from tests.fakes.shared_web_auth import Browser
from tests.scenarios.web_scenario import mail_id, populate


@pytest.fixture
def pair(tmp_path, monkeypatch):
    monkeypatch.setattr("mailhelp.web.site.SETTLE_SECONDS", 0)
    with JsonStore(tmp_path / "a") as first, JsonStore(tmp_path / "b") as second:
        populate(first)  # only the first instance holds mails and proposals
        a, b = Web(first), Web(second)
        a.auth.enter_customer_mode("kunde-a")
        b.auth.enter_customer_mode("kunde-b")
        yield a, b


def test_a_session_cookie_of_one_instance_is_refused_by_the_other(pair):
    a, b = pair
    browser = signed_in(a)
    assert browser.request("GET", "/mail/" + mail_id(1)).status == 200
    intruder = Browser(b.app)
    intruder.cookies["mh_session"] = browser.cookies["mh_session"]
    assert intruder.request("GET", "/").status == 303 and intruder.request("GET", "/mail/" + mail_id(1)).status == 303
    assert b.auth.authenticate(browser.cookies["mh_session"]) is None


def test_a_pairing_code_of_one_instance_does_not_sign_in_at_the_other(pair):
    a, b = pair
    code = a.auth.issue_code()
    browser = Browser(b.app)
    csrf = browser.csrf()
    b.store.save(PAIRING, {**b.store.load(PAIRING, {}), "requests": []})
    browser.request("POST", "/anmelden", {"csrf": csrf, "code": code, "geraet": "Fremd"})
    assert "mh_session" not in browser.cookies and b.auth.sessions() == []
    own = Browser(a.app)  # still valid where it was issued
    a.store.save(PAIRING, {**a.store.load(PAIRING, {}), "requests": []})
    own.request("POST", "/anmelden", {"csrf": own.csrf(), "code": code, "geraet": "Eigenes Gerät"})
    assert own.request("GET", "/").status == 200


def test_references_of_one_instance_are_unknown_at_the_other(pair):
    a, b = pair
    other = signed_in(b)
    assert other.request("GET", "/mail/" + mail_id(1)).status == 404
    assert other.request("GET", "/vorschlag/" + mail_id(1) + "/elternabend").status == 404
    assert b"Elternabend" not in other.request("GET", "/").body
    assert b"Elternabend" in signed_in(a).request("GET", "/").body


def test_signing_out_every_customer_of_one_instance_leaves_the_other_untouched(pair):
    a, b = pair
    first, second = signed_in(a), signed_in(b)
    assert a.auth.revoke_all(customers_only=True) >= 1
    assert first.request("GET", "/").status == 303 and second.request("GET", "/").status == 200
