"""5.3 H10: the help chat page with simulated answers; also usable without JavaScript."""
import json
import re
from html import unescape
from types import SimpleNamespace

import pytest

from mailhelp.config import HelpChatSettings
from mailhelp.helpdocs import HelpAnswer, HelpUnavailable, load
from mailhelp.helpdocs.chat import HelpChat
from tests.fakes.shared_web_actions import web as web  # noqa: F401 - the fixture
from tests.fakes.shared_web_v12 import configure


class Analyzer:
    def __init__(self):
        self.prompts = SimpleNamespace(prompts={"settings_help": object()})

    def settings_help(self, question, sources, history, settings, *, before_call=lambda: None):
        before_call()
        return "call", HelpAnswer(answer="Erklärung <b>fett</b>\n1. Schritt", source_ids=[sources[0].id],
                                  setting_ids=["setting:poll_interval_seconds"])


@pytest.fixture
def chat(web):
    settings = HelpChatSettings()
    service = HelpChat(web.store, lambda: settings, load, Analyzer, web.auth.active)
    web.site.archive.help.chat = service
    return SimpleNamespace(web=web, service=service, settings=settings)


def form(page, action):
    block = re.search(rf'<form method="post" action="{action}"[^>]*>(.*?)</form>', page, re.S).group(1)
    return {name: unescape(value) for name, value in re.findall(r'name="([^"]+)" value="([^"]*)"', block)}


def get(web, path="/hilfe"):
    if path.startswith("/hilfe"):
        query = path.partition("?")[2]
        response = web.browser.request("GET", "/api/hilfe/fenster?" + query)
        return json.loads(response.body)["html"]
    return web.browser.request("GET", path).body.decode()


def test_without_the_service_the_documentation_stays_reachable(web):
    page = get(web)
    assert "Der Hilfschat ist in dieser Installation nicht aktiv" in page and 'href="/hilfe/dokumentation"' in page


def test_a_question_is_sent_shown_as_pending_and_answered_with_server_links(chat):
    page = get(chat.web, "/hilfe?einstellung=poll_interval_seconds")
    assert "Keine Passwörter oder Tokens eingeben" in page and "Bezug: Abrufintervall (Sekunden)" in page
    fields = form(page, "/hilfe/frage")
    assert fields["einstellung"] == "poll_interval_seconds"
    response = chat.web.browser.request("POST", "/hilfe/frage", {**fields, "frage": "Was bewirkt das Abrufintervall?"})
    assert response.status == 303 and response.headers["Location"] == "/einstellungen"
    pending = get(chat.web)
    job = re.search(r'data-help-job="([a-f0-9]{32})"', pending).group(1)
    assert "Antwort wird vorbereitet" in pending and 'http-equiv="refresh"' not in pending
    status = chat.web.browser.request("GET", f"/api/hilfe/auftrag/{job}")
    assert json.loads(status.body) == {"status": "queued", "error": None}
    chat.service.run_once()
    page = get(chat.web)
    assert "Erklärung &lt;b&gt;fett&lt;/b&gt;" in page and "<b>fett" not in page
    assert 'href="/hilfe/dokumentation/web-einstellungen/mailabruf-und-betrieb"' in page
    assert 'href="/einstellungen?bereich=abruf#einstellung-poll-interval-seconds"' in page
    assert chat.web.browser.request("GET", "/api/hilfe/auftrag/" + "0" * 32).status == 404


def test_refusals_answer_with_a_status_and_a_reason(chat):
    page = get(chat.web)
    fields = form(page, "/hilfe/frage")
    send = lambda **extra: chat.web.browser.request("POST", "/hilfe/frage", {**fields, **extra})  # noqa: E731
    assert send(version="x", frage="Hallo?").status == 422
    assert send(frage="  ").status == 422
    assert send(frage="Was bewirkt das Abrufintervall?").status == 303
    assert send(frage="Etwas anderes?").status == 409       # same key, other question
    assert send(key="b" * 32, frage="Noch eine?").status == 409  # one question at a time
    chat.service.run_once()
    chat.settings.requests_per_minute_per_session = 1
    assert send(key="c" * 32, frage="Noch eine?").status == 429
    assert send(key="d" * 32, version="7", frage="Noch eine?").status == 409
    assert chat.web.browser.request("POST", "/hilfe/frage", {"frage": "ohne csrf"}).status == 403


def test_errors_interruptions_and_clearing(chat, monkeypatch):
    page = get(chat.web)
    chat.web.browser.request("POST", "/hilfe/frage", {**form(page, "/hilfe/frage"), "frage": "Bananenbrot?"})
    chat.service.run_once()  # no source: a local answer without the model
    assert "keinen passenden Abschnitt" in get(chat.web)
    chat.service.analyzer = lambda: None
    page = get(chat.web)
    chat.web.browser.request("POST", "/hilfe/frage", {**form(page, "/hilfe/frage"), "frage": "Was bewirkt das Abrufintervall?"})
    chat.service.run_once()
    assert "In prompts.yaml fehlt der Schritt settings_help" in get(chat.web)
    state = chat.service.state(chat.web.auth.sessions()[0].id)
    assert state.turns[0].revision
    stale = state.turns[0].model_copy(update={"source_ids": ["betrieb/sicherung"], "revision": "alt"})
    name = "help-chat-" + __import__("hashlib").sha256(chat.web.auth.sessions()[0].id.encode()).hexdigest()[:32]
    chat.web.store.save(name, state.model_copy(update={"turns": [stale]}).model_dump(mode="json"))
    assert "betrieb/sicherung (frühere Dokumentationsfassung)" in get(chat.web)

    def broken():
        raise HelpUnavailable("kaputt")
    monkeypatch.setattr(chat.web.site.archive.help, "base", broken)
    assert "(frühere Dokumentationsfassung)" in get(chat.web)
    page = get(chat.web)
    clear = form(page, "/hilfe/leeren")
    assert chat.web.browser.request("POST", "/hilfe/leeren", clear).status == 303
    assert chat.web.browser.request("POST", "/hilfe/leeren", clear).status == 303  # stale: no effect
    assert "Chat leeren" not in get(chat.web)


def test_the_settings_offer_help_on_every_setting(web, tmp_path):
    configure(web, tmp_path)
    page = get(web, "/einstellungen?bereich=abruf")
    assert '<a class="button" href="/hilfe">Hilfe zu Einstellungen</a>' in page
    assert 'href="/hilfe?einstellung=poll_interval_seconds">Dazu fragen</a>' in page


def test_an_unknown_setting_reference_is_ignored(chat):
    assert "Bezug:" not in get(chat.web, "/hilfe?einstellung=gibt_es_nicht")


def test_the_status_api_without_service(web):
    assert web.browser.request("GET", "/api/hilfe/auftrag/" + "a" * 32).status == 404
    assert web.browser.request("POST", "/hilfe/frage", {"csrf": web.auth.csrf_token(web.auth.sessions()[0].id),
                                                        "frage": "x"}).status == 503
    assert web.browser.request("POST", "/hilfe/leeren", {"csrf": web.auth.csrf_token(web.auth.sessions()[0].id)}
                               ).status == 303
