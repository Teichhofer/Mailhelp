"""5.4: the authenticated embedded chat, separate from settings form submissions."""
import json
from datetime import timedelta
from types import SimpleNamespace

import pytest

from mailhelp.config import HelpChatSettings
from mailhelp.helpdocs import HelpAnswer, load
from mailhelp.helpdocs.chat import HelpChat
from mailhelp.web.help_window import WindowState, return_path, window_name
from tests.fakes.shared_web_actions import web as web  # noqa: F401
from tests.fakes.shared_web_auth import Browser
from tests.fakes.shared_web_v12 import configure


def test_window54_state_is_available_without_a_separate_chat_page(web):
    response = web.browser.request("GET", "/api/hilfe/fenster", accept="application/json")
    assert response.status == 200
    data = json.loads(response.body)
    assert "csrf" in data and "html" in data
    assert 'id="help-question"' in data["html"]


def test_window54_old_links_return_to_the_settings(web):
    response = web.browser.request("GET", "/hilfe?einstellung=poll_interval_seconds")
    assert response.status == 303
    assert response.headers["Location"] == "/einstellungen?hilfe=offen&einstellung=poll_interval_seconds"


def fields(web, **extra):
    session = web.auth.sessions()[0]
    state = web.site.archive.help.window.state(session)
    return {"csrf": web.auth.csrf_token(session.id), "key": "a" * 32,
            "window_version": str(state.version), "window_action": "open", **extra}


def test_window54_form_state_survives_search_errors_and_closes_explicitly(web, tmp_path):
    configure(web, tmp_path)
    form = fields(web, draft="</textarea><script>unsafe</script>", einstellung="poll_interval_seconds",
                  return_to="/einstellungen?bereich=abruf")
    response = web.browser.request("POST", "/hilfe/fenster", form)
    assert response.status == 303 and response.headers["Location"] == form["return_to"]
    assert web.browser.request("POST", "/hilfe/fenster", form).status == 303  # replay
    assert web.browser.request("POST", "/hilfe/fenster", {**form, "draft": "anders"}).status == 409
    for path in ("/einstellungen?suche=Zeitzone", "/themen", "/einstellungen?bereich=unbekannt"):
        page = web.browser.request("GET", path).body.decode()
        assert 'aria-label="Hilfe zu Einstellungen" hidden' not in page
        assert "&lt;/textarea&gt;&lt;script&gt;unsafe" in page
        assert 'id="help-widget"' in page
    saved = web.browser.request("POST", "/einstellungen/speichern", {
        "csrf": form["csrf"], "name": "timezone", "value": "invalid"})
    assert saved.status == 422 and 'id="help-widget"' in saved.body.decode()
    close = fields(web, key="b" * 32, window_action="close", return_to="https://evil.test")
    response = web.browser.request("POST", "/hilfe/fenster", close)
    assert response.headers["Location"] == "/einstellungen"
    assert 'aria-label="Hilfe zu Einstellungen" hidden' in web.browser.request("GET", "/einstellungen").body.decode()


@pytest.mark.parametrize("target", ["https://evil.test", "//evil.test", "/status", "/einstellungen\\evil",
                                    "/einstellungen\nX:evil", "http://[broken", "a" * 1001])
def test_window54_return_targets_are_restricted(target):
    assert return_path(target) == "/einstellungen"


def test_window54_query_and_fragment_are_preserved_without_reopening_closed_windows():
    assert return_path("/einstellungen?hilfe=offen&einstellung=x&suche=Mail#feld") == "/einstellungen?suche=Mail"
    assert return_path("/themen") == "/themen"
    assert return_path("/einstellungen/zugangsdaten?gespeichert=x%3Cy") == "/einstellungen/zugangsdaten"


def test_window54_unknown_reference_is_not_rendered_in_a_question_form(web):
    html = web.site.archive.help._form("csrf", 1, "unknown<script>")
    assert "Bezug:" not in html and "unknown" not in html


def test_window54_no_js_question_failure_keeps_the_window_open(web):
    form = fields(web, frage="Was ist das Abrufintervall?", version="1")
    response = web.browser.request("POST", "/hilfe/frage", form)
    assert response.status == 503
    assert 'id="help-window"' in response.body.decode()
    assert 'aria-label="Hilfe zu Einstellungen" hidden' not in response.body.decode()


def test_window54_post_targets_use_existing_get_routes_and_position_controls_work_without_js(web):
    window = web.site.archive.help.window
    assert window.target("/einstellungen/speichern") == "/einstellungen"
    assert window.target("/themen/speichern") == "/themen"
    assert window.target("/dienst/unknown/path") == "/einstellungen"
    assert window.target("/einstellungen?suche=Mail") == "/einstellungen?suche=Mail"
    for index, (direction, corner) in enumerate((("left", "bottom-left"), ("up", "top-left"),
                                                ("right", "top-right"), ("down", "bottom-right"))):
        result = web.browser.request("POST", "/hilfe/fenster", fields(
            web, key=str(index) * 32, window_action="move", direction=direction), accept="application/json")
        assert result.status == 200 and json.loads(result.body)["ui"]["corner"] == corner
    result = web.browser.request("POST", "/hilfe/fenster", fields(
        web, key="e" * 32, window_action="move", direction="invalid"), accept="application/json")
    assert result.status == 409


def test_window54_invalid_actions_and_authorization(web, monkeypatch):
    for change in ({"window_action": "other"}, {"key": "bad"}, {"window_version": "stale"},
                   {"window_version": "2"}, {"draft": "x" * 8001}):
        assert web.browser.request("POST", "/hilfe/fenster", fields(web, **change),
                                   accept="application/json").status in {409, 413}
    assert web.browser.request("POST", "/hilfe/fenster", {"window_action": "open"}).status == 403
    stranger = Browser(web.app)
    assert stranger.request("GET", "/api/hilfe/fenster", accept="application/json").status == 401
    state = fields(web)
    monkeypatch.setattr(web.auth, "active", lambda _: False)
    assert web.browser.request("POST", "/hilfe/fenster", state, accept="application/json").status == 403


def test_window54_corrupt_expired_and_revoked_state_is_removed(web):
    session = web.auth.sessions()[0]
    name = window_name(session.id)
    web.store.save(name, {"invalid": True})
    assert not web.site.archive.help.window.state(session).opened
    web.store.save(name, WindowState(opened=True, draft="secret", expires=1).model_dump())
    assert not web.site.archive.help.window.state(session).opened
    assert name not in web.store.names()
    web.browser.request("POST", "/hilfe/fenster", fields(web, draft="Entwurf"))
    assert name in web.store.names()
    web.auth.revoke(session.id)
    assert name not in web.store.names()


def test_window54_session_expiry_and_revoke_all_delete_fallback(web):
    session = web.auth.sessions()[0]
    web.browser.request("POST", "/hilfe/fenster", fields(web, draft="Entwurf"))
    before = web.auth.clock
    web.auth.clock = lambda: session.expires_at + timedelta(seconds=1)
    assert web.auth.sessions() == []
    assert window_name(session.id) not in web.store.names()
    web.auth.clock = before
    web.store.save(window_name(session.id), WindowState(opened=True, expires=9999999999).model_dump())
    assert web.auth.revoke_all() == 1
    assert window_name(session.id) not in web.store.names()


def test_window54_periodic_cleanup_removes_idle_and_orphaned_fallbacks(web, monkeypatch):
    window = web.site.archive.help.window
    session = web.auth.sessions()[0]
    name = window_name(session.id)
    web.store.save(name, WindowState(opened=True, expires=9999999999).model_dump())
    orphan = window_name("orphan")
    web.store.save(orphan, WindowState(expires=9999999999).model_dump())
    web.store.save("help-window-broken", {"invalid": True})
    window.cleanup()
    assert name in web.store.names() and orphan not in web.store.names()
    web.store.save(name, WindowState(draft="Abgelaufen", expires=1).model_dump())
    window.cleanup()
    assert name not in web.store.names()
    web.store.save(name, WindowState(expires=9999999999).model_dump())
    original = web.store.load_model
    monkeypatch.setattr(web.store, "load_model", lambda filename, *args: None if filename == name else original(filename, *args))
    window.cleanup()
    assert name not in web.store.names()


def test_window54_chat_json_submission_clear_and_safe_sources(web):
    class Analyzer:
        prompts = SimpleNamespace(prompts={"settings_help": object()})

        def settings_help(self, question, sources, history, settings, *, before_call=lambda: None):
            before_call()
            return "call", HelpAnswer(answer="<script>unsicher</script>", source_ids=[sources[0].id])

    chat = HelpChat(web.store, HelpChatSettings, load, Analyzer, web.auth.active, redact=lambda s: s.replace("token", "X"))
    web.site.archive.help.chat = chat
    ui = web.browser.request("POST", "/hilfe/fenster", fields(web, draft="token"), accept="application/json")
    assert json.loads(ui.body)["ui"]["draft"] == "X"
    session = web.auth.sessions()[0]
    send = {"csrf": web.auth.csrf_token(session.id), "key": "b" * 32, "version": "1",
            "frage": "Was bewirkt das Abrufintervall?", "einstellung": "poll_interval_seconds"}
    response = web.browser.request("POST", "/hilfe/frage", send, accept="application/json")
    assert response.status == 200 and "Antwort wird vorbereitet" in json.loads(response.body)["html"]
    again = web.browser.request("POST", "/hilfe/frage", send, accept="application/json")
    assert again.status == 200 and len(chat.state(session.id).jobs) == 1
    chat.run_once()
    response = web.browser.request("GET", "/api/hilfe/fenster?einstellung=poll_interval_seconds")
    data = json.loads(response.body)
    assert "&lt;script&gt;unsicher" in data["html"] and "/hilfe/dokumentation/" in data["html"]
    assert data["setting"] == "poll_interval_seconds"
    response = web.browser.request("POST", "/hilfe/leeren", send, accept="application/json")
    assert response.status == 200 and "help-turn" not in json.loads(response.body)["html"]
    response = web.browser.request("POST", "/hilfe/frage", send, accept="application/json")
    assert response.status == 200  # a cleared, already accepted request remains an idempotent replay
    response = web.browser.request("POST", "/hilfe/frage", {**send, "key": "c" * 32}, accept="application/json")
    assert response.status == 409 and json.loads(response.body)["error"]
