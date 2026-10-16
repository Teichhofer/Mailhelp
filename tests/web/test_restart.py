"""Restart uses the same process-bound confirmation as stop; no real process is launched."""
import pytest
from shared_web_auth import Browser
from shared_web_v12 import configure

from mailhelp.lifecycle import Lifecycle

PATH = "/einstellungen/neustarten"


def test_restart_button_and_confirmed_restart_after_response(web, tmp_path):
    _, _, lifecycle, _, calls = configure(web, tmp_path)
    page = web.browser.request("GET", "/einstellungen").body.decode()
    assert f'href="{PATH}">Mailhelp neu starten</a>' in page
    form = web.form(PATH, action=PATH)
    assert calls == [] and not lifecycle.restart_requested
    assert web.browser.request("POST", PATH, {**form, "process": "old"}).status == 409
    assert web.browser.request("POST", PATH, {**form, "confirm": "no"}).status == 409
    assert web.browser.request("POST", PATH, {**form, "csrf": "invalid"}).status == 403
    answer = web.browser.request("POST", PATH, form)
    assert answer.status == 202 and not lifecycle.restart_requested
    assert web.browser.request("POST", PATH, form).status == 202
    answer.after_send()
    answer.after_send()
    assert calls == ["stop"] and lifecycle.restart_requested
    replay = web.browser.request("POST", PATH, form)
    assert replay.status == 202
    replay.after_send()
    assert calls == ["stop"]
    assert Browser(web.site.app).request("GET", PATH).status == 303
    assert Browser(web.site.app).request("POST", PATH, form).status == 403
    fresh = Lifecycle(lambda: None, lambda actor: True)
    with pytest.raises(ValueError):
        fresh.request(lifecycle.process, form["key"], "web:session", restart=True)
    assert not fresh.restart_requested


def test_restart_unavailable_and_missing_form(web):
    assert web.browser.request("GET", PATH).status == 503
    csrf = web.browser.csrf("/")
    assert web.browser.request("POST", PATH, {"csrf": csrf}).status == 409


@pytest.mark.parametrize("restart", [False, True])
def test_lifecycle_same_key_is_idempotent_and_action_bound(restart):
    calls = []
    lifecycle = Lifecycle(lambda: calls.append("stop"), lambda actor: True)
    callback = lifecycle.request(lifecycle.process, "a" * 32, "actor", restart=restart)
    with pytest.raises(ValueError):
        lifecycle.request(lifecycle.process, "a" * 32, "actor", restart=not restart)
    callback()
    lifecycle.request(lifecycle.process, "a" * 32, "actor", restart=restart)()
    assert calls == ["stop"] and lifecycle.restart_requested == restart


def test_restart_rechecks_session_and_old_callback_cannot_execute_a_new_request():
    allowed, calls = [True], []
    lifecycle = Lifecycle(lambda: calls.append("stop"), lambda actor: allowed[0])
    old = lifecycle.request(lifecycle.process, "a" * 32, "actor", restart=True)
    allowed[0] = False
    old()
    assert lifecycle.state == "running" and not lifecycle.restart_requested
    allowed[0] = True
    current = lifecycle.request(lifecycle.process, "b" * 32, "actor")
    old()
    assert calls == []
    current()
    assert calls == ["stop"] and not lifecycle.restart_requested
