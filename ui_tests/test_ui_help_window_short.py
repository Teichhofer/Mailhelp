"""5.5.4: the window shows a short answer; the complete one opens on request."""
from types import SimpleNamespace

from playwright.sync_api import expect

from checks import audit
from conftest import sign_in
from mailhelp.helpdocs import HelpAnswer
from tests.fakes.help_window54 import chat_service

FULL = ("Das Abrufintervall steuert, wie oft Mailhelp neue Mails abruft. 1. Einstellungen öffnen. "
        "2. Bereich Mailabruf und Betrieb wählen. 3. Abrufintervall (Sekunden) ändern, prüfen und speichern.")


class BothVersions:
    prompts = SimpleNamespace(prompts={"settings_help": object()})

    def settings_help(self, question, sources, history, settings, *, before_call=lambda: None):
        before_call()
        return "synthetic", HelpAnswer(answer=FULL, short_answer="Es legt den Abstand zwischen zwei Abrufen fest.",
                                       source_ids=[sources[0].id], setting_ids=["setting:poll_interval_seconds"])


def test_window55_short_answer_with_the_full_answer_on_request(page, mailhelp):
    service = chat_service(mailhelp)
    service.analyzer = BothVersions
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/einstellungen")
    page.get_by_label("Hilfschat öffnen", exact=True).click()
    page.get_by_label("Deine Frage zu Einstellungen und Bedienung").fill("Was bewirkt das Abrufintervall?")
    page.get_by_role("button", name="Frage senden", exact=True).click()
    expect(page.get_by_text("Antwort wird vorbereitet", exact=False)).to_be_visible()
    service.run_once()
    window = page.locator("#help-window")
    expect(window.locator(".help-answer-short")).to_have_text("Es legt den Abstand zwischen zwei Abrufen fest.",
                                                              timeout=10000)
    full = window.locator(".help-answer-text")
    expect(full).to_be_hidden()
    summary = window.get_by_text("Ausführliche Antwort anzeigen", exact=True)
    summary.click()
    # 5.5.7: steps the model sent on one line appear as a list.
    expect(full.locator("p")).to_have_text("Das Abrufintervall steuert, wie oft Mailhelp neue Mails abruft.")
    expect(full.locator("ol > li")).to_have_text(["Einstellungen öffnen.", "Bereich Mailabruf und Betrieb wählen.",
                                                  "Abrufintervall (Sekunden) ändern, prüfen und speichern."])
    summary.click()
    expect(full).to_be_hidden()
    summary.focus()
    page.keyboard.press("Enter")
    expect(full).to_be_visible()
    assert audit(page, "help-window55-short-" + page.device, page.mobile) == []
    assert page.errors == []


class MarkdownAnswer(BothVersions):
    def settings_help(self, question, sources, history, settings, *, before_call=lambda: None):
        before_call()
        return "synthetic", HelpAnswer(
            answer="### Lernlauf starten\n\n1. **Lernen** öffnen\n2. **Schätzung anzeigen** wählen\n"
                   "3. Mit `--learn 20` geht es auch im Terminal\n\n- Liest nur\n- <b>kein HTML</b>",
            short_answer="Unter **Lernen** einen lesenden Lernlauf starten.",
            source_ids=[sources[0].id])


def test_window55_markdown_answers_are_formatted_in_the_window(page, mailhelp):
    # 5.5.6: answers arrive as Markdown and are shown as lists and emphasis, never as raw marks.
    service = chat_service(mailhelp)
    service.analyzer = MarkdownAnswer
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/einstellungen")
    page.get_by_label("Hilfschat öffnen", exact=True).click()
    page.get_by_label("Deine Frage zu Einstellungen und Bedienung").fill("Wie funktioniert die Lernfunktion?")
    page.get_by_role("button", name="Frage senden", exact=True).click()
    expect(page.get_by_text("Antwort wird vorbereitet", exact=False)).to_be_visible()
    service.run_once()
    window = page.locator("#help-window")
    short = window.locator(".help-answer-short")
    expect(short.locator("strong")).to_have_text("Lernen", timeout=10000)
    expect(short).not_to_contain_text("**")
    window.get_by_text("Ausführliche Antwort anzeigen", exact=True).click()
    full = window.locator(".help-answer-text")
    expect(full.locator("ol > li")).to_have_count(3)
    expect(full.locator("ol > li").first.locator("strong")).to_have_text("Lernen")
    expect(full.locator("code")).to_have_text("--learn 20")
    expect(full.locator("ul > li")).to_have_text(["Liest nur", "<b>kein HTML</b>"])
    expect(full.locator(".help-md-heading")).to_have_text("Lernlauf starten")
    assert full.locator("b").count() == 0
    assert audit(page, "help-window55-markdown-" + page.device, page.mobile) == []
    assert page.errors == []
