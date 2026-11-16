"""5.3.13: a refused stop or restart says why, logs a fixed reason and offers a fresh confirmation.

Regression: after a restart, "Beenden" and "Neustart" only answered "nicht bestätigt oder
Anforderung veraltet" without a way forward and without any reason in the log.
"""
import json
import re

import pytest

from mailhelp.runtime.lifecycle import Lifecycle, StopRefused
from tests.fakes.shared_web_v12 import configure

STOP, RESTART = "/einstellungen/beenden", "/einstellungen/neustarten"


def _hidden(html):
    return dict(re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)">', html))


def _refusals(web):
    return [fields for (_level, _module, event), fields in web.site.logger.events if event == "stop_refused"]


@pytest.mark.parametrize("path", [STOP, RESTART])
def test_a_confirmation_from_before_a_restart_offers_a_fresh_one_that_works(web, tmp_path, path):
    _, _, before, _, calls = configure(web, tmp_path)
    old = web.form(path, action=path)
    # The process restarts: a new lifecycle with a new process identity serves the site.
    after = Lifecycle(lambda: calls.append("stop"), web.dialog.review.web_authorizer)
    web.site.lifecycle = web.site.archive.lifecycle = after
    refused = web.browser.request("POST", path, old)
    page = refused.body.decode()
    assert refused.status == 409 and "früheren Mailhelp-Start" in page
    fresh = _hidden(page)
    assert fresh["process"] == after.process != before.process and fresh["confirm"] == "yes"
    assert fresh["key"] != old["key"]
    assert _refusals(web) == [{"reason": "stale_process", "restart": path == RESTART}]
    accepted = web.browser.request("POST", path, fresh)
    assert accepted.status == 202
    accepted.after_send()
    assert calls == ["stop"] and after.restart_requested is (path == RESTART)


@pytest.mark.parametrize(("change", "reason", "offered"), [
    ({"confirm": "no"}, "unconfirmed", True),
    ({"key": "short"}, "invalid_key", True),
])
def test_an_incomplete_confirmation_is_offered_again(web, tmp_path, change, reason, offered):
    _, _, lifecycle, _, calls = configure(web, tmp_path)
    form = web.form(STOP, action=STOP)
    refused = web.browser.request("POST", STOP, {**form, **change})
    page = refused.body.decode()
    assert refused.status == 409 and "unvollständig" in page
    assert (_hidden(page).get("process") == lifecycle.process) is offered
    assert _refusals(web) == [{"reason": reason, "restart": False}]
    assert calls == [] and lifecycle.state == "running"


def test_a_revoked_session_and_a_running_stop_get_no_new_confirmation(web, tmp_path):
    _, _, lifecycle, _, calls = configure(web, tmp_path)
    first = web.form(STOP, action=STOP)
    second = web.form(STOP, action=STOP)
    assert web.browser.request("POST", STOP, first).status == 202
    running = web.browser.request("POST", STOP, second)
    assert running.status == 409 and "bereits angefordert" in running.body.decode()
    assert "process" not in _hidden(running.body.decode())
    revoked = Lifecycle(lambda: calls.append("stop"), lambda actor: False)
    web.site.lifecycle = web.site.archive.lifecycle = revoked
    unauthorized = web.browser.request("POST", STOP, {**second, "process": revoked.process})
    assert unauthorized.status == 409 and "neu anmelden" in unauthorized.body.decode()
    assert "process" not in _hidden(unauthorized.body.decode())
    assert [item["reason"] for item in _refusals(web)] == ["already_requested", "unauthorized"]
    assert calls == []


def test_a_json_client_receives_the_reason_code(web, tmp_path):
    configure(web, tmp_path)
    form = web.form(STOP, action=STOP)
    answer = web.browser.request("POST", STOP, {**form, "process": "0" * 32}, accept="application/json")
    assert answer.status == 409
    body = json.loads(answer.body)
    assert body["reason"] == "stale_process" and "früheren Mailhelp-Start" in body["error"]


def test_the_lifecycle_names_each_refusal():
    lifecycle = Lifecycle(lambda: None, lambda actor: actor == "allowed")
    cases = [(("0" * 32, "a" * 32, "allowed"), "stale_process"),
             ((lifecycle.process, "a" * 32, "other"), "unauthorized"),
             ((lifecycle.process, "z" * 32, "allowed"), "invalid_key")]
    for arguments, reason in cases:
        with pytest.raises(StopRefused) as refused:
            lifecycle.request(*arguments)
        assert refused.value.reason == reason and isinstance(refused.value, ValueError)
    lifecycle.request(lifecycle.process, "a" * 32, "allowed")
    with pytest.raises(StopRefused) as refused:
        lifecycle.request(lifecycle.process, "b" * 32, "allowed")
    assert refused.value.reason == "already_requested"
