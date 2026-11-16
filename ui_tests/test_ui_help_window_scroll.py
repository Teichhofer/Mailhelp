"""5.5.2: the help window keeps its reading position across page changes and the reader."""
import json

from playwright.sync_api import expect

from conftest import sign_in
from mailhelp.helpdocs import HelpAnswer
from tests.fakes.help_window54 import chat_service

LONG = " ".join(f"Schritt {number}: Einstellungen öffnen, Wert prüfen und speichern." for number in range(1, 40))


class LongAnswers:
    from types import SimpleNamespace
    prompts = SimpleNamespace(prompts={"settings_help": object()})

    def settings_help(self, question, sources, history, settings, *, before_call=lambda: None):
        before_call()
        return "synthetic", HelpAnswer(answer=LONG, source_ids=[sources[0].id],
                                       setting_ids=["setting:poll_interval_seconds"])


def ask(page, service, text, answers):
    page.get_by_label("Deine Frage zu Einstellungen und Bedienung").fill(text)
    page.get_by_role("button", name="Frage senden", exact=True).click()
    expect(page.get_by_text("Antwort wird vorbereitet", exact=False)).to_be_visible()
    service.run_once()
    expect(page.locator("#help-window .help-turn")).to_have_count(answers, timeout=10000)


def conversation(page, mailhelp, questions=2):
    service = chat_service(mailhelp)
    service.analyzer = LongAnswers
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/einstellungen")
    page.get_by_label("Hilfschat öffnen", exact=True).click()
    for number in range(1, questions + 1):
        ask(page, service, f"Frage {number} zum Abrufintervall?", number)
    return service


def scroll_to(page, position):
    page.locator("#help-window-content").evaluate("(content, top) => { content.scrollTop = top; }", position)
    page.wait_for_timeout(300)  # the position is stored after a short pause in scrolling
    return page.locator("#help-window-content").evaluate("content => content.scrollTop")


def at(page, target):
    page.wait_for_function("t => Math.abs(document.getElementById('help-window-content').scrollTop - t) <= 2",
                           arg=target)


def position(page):
    return page.locator("#help-window-content").evaluate("content => content.scrollTop")


def test_window55_reading_position_survives_a_page_change_and_reload(page, mailhelp):
    conversation(page, mailhelp)
    target = scroll_to(page, 260)
    assert target > 100
    page.goto(mailhelp.url + "/themen")
    expect(page.locator("#help-window .help-turn")).to_have_count(2)
    at(page, target)
    page.reload()
    expect(page.locator("#help-window .help-turn")).to_have_count(2)
    at(page, target)
    # Closing and reopening returns to the same place as well.
    page.get_by_role("button", name="Hilfschat schließen", exact=True).click()
    page.get_by_label("Hilfschat öffnen", exact=True).click()
    expect(page.locator("#help-window .help-turn")).to_have_count(2)
    at(page, target)
    assert page.errors == []


def test_window55_returning_from_a_source_restores_the_reading_position(page, mailhelp):
    conversation(page, mailhelp)
    target = scroll_to(page, 200)
    # Clicked in place: a pointer click would first scroll the link into view (a new position).
    page.locator('#help-window .help-sources a[href^="/hilfe/dokumentation/"]').first.evaluate("a => a.click()")
    expect(page.locator("#help-document")).to_be_visible()
    page.get_by_role("button", name="Zurück zum Gespräch", exact=True).click()
    expect(page.locator("#help-window-content")).to_be_visible()
    assert abs(position(page) - target) <= 2
    assert page.errors == []


def test_window55_a_reader_at_the_end_follows_and_a_reader_above_stays(page, mailhelp):
    service = conversation(page, mailhelp)
    content = page.locator("#help-window-content")
    # Further up: a new answer from another tab of this session does not move the text.
    target = scroll_to(page, 120)
    session = mailhelp.auth.sessions()[0].id
    service.submit(session, "Frage aus einem anderen Tab?", "c" * 32, service.state(session).version, None)
    service.run_once()
    expect(page.locator("#help-window .help-turn")).to_have_count(3, timeout=10000)
    assert abs(position(page) - target) <= 2
    # At the end: the next answer is followed.
    scroll_to(page, 100000)
    service.submit(session, "Noch eine Frage?", "d" * 32, service.state(session).version, None)
    service.run_once()
    expect(page.locator("#help-window .help-turn")).to_have_count(4, timeout=10000)
    page.wait_for_function("""() => { const c = document.getElementById('help-window-content');
        return c.scrollTop + c.clientHeight >= c.scrollHeight - 4; }""")
    # Clearing starts at the top again.
    page.get_by_role("button", name="Chat leeren", exact=True).click()
    expect(page.locator("#help-window .help-turn")).to_have_count(0)
    assert content.evaluate("content => content.scrollTop") == 0


def test_window55_a_manipulated_position_starts_at_the_top(page, mailhelp):
    conversation(page, mailhelp, questions=1)
    stored = json.loads(page.evaluate("sessionStorage.getItem('mailhelp.help-window.v1')"))
    for broken in ("oben", -50, None):
        # Set before the page script runs: leaving the page stores the current position first.
        value = json.dumps(json.dumps({**stored, "scroll": broken}))
        page.add_init_script(f"sessionStorage.setItem('mailhelp.help-window.v1', {value});")
        page.reload()
        expect(page.locator("#help-window .help-turn")).to_have_count(1)
        assert position(page) == 0
    assert page.errors == []
