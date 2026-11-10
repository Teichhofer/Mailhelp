"""Planung 5.3, step H10: the help chat in the browser, with a simulated answer."""
import re
from types import SimpleNamespace

from playwright.sync_api import expect

from checks import audit
from conftest import sign_in
from mailhelp.config import HelpChatSettings
from mailhelp.helpdocs import HelpAnswer, load
from mailhelp.helpdocs.chat import HelpChat


class Analyzer:
    prompts = SimpleNamespace(prompts={"settings_help": object()})

    def settings_help(self, question, sources, history, settings):
        return "call", HelpAnswer(answer="Das Abrufintervall legt fest, wie oft Mailhelp nach Mails sucht.",
                                  source_ids=[sources[0].id])


def test_a_question_from_a_setting_is_answered_with_sources(page, mailhelp):
    service = HelpChat(mailhelp.store, HelpChatSettings, load, Analyzer, mailhelp.auth.active)
    mailhelp.site.archive.help.chat = service
    sign_in(page, mailhelp)
    page.goto(f"{mailhelp.url}/einstellungen?bereich=abruf")
    page.locator('#einstellung-poll-interval-seconds a.ask-help').click()
    expect(page.get_by_text("Bezug: Abrufintervall (Sekunden)")).to_be_visible()
    assert audit(page, "help-chat-53-" + page.device, page.mobile) == []
    page.get_by_label("Deine Frage zu Einstellungen und Bedienung").fill("Was bewirkt das Abrufintervall?")
    page.get_by_role("button", name="Frage senden").click()
    expect(page.get_by_text("Antwort wird vorbereitet")).to_be_visible()
    service.run_once()
    expect(page.locator(".help-answer")).to_contain_text("wie oft Mailhelp nach Mails sucht", timeout=10000)
    expect(page.locator(".help-sources a").first).to_have_attribute("href", re.compile(r"^/hilfe/dokumentation/"))
    assert audit(page, "help-chat-answer-53-" + page.device, page.mobile) == []
    page.get_by_role("button", name="Chat leeren").click()
    expect(page.locator(".help-turn")).to_have_count(0)
    assert page.errors == []
