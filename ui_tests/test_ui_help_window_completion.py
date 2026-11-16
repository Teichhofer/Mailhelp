"""Remaining real user flows: IME search, fallback forms, source races and logout privacy."""
import re

from playwright.sync_api import expect

from conftest import navigate_collected, sign_in
from mailhelp.helpdocs import HelpAnswer
from tests.fakes.help_window54 import Analyzer, chat_service


def test_window54_logout_erases_the_local_draft_before_the_response(page, mailhelp):
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/einstellungen")
    page.get_by_label("Hilfschat öffnen", exact=True).click()
    page.get_by_label("Deine Frage zu Einstellungen und Bedienung").fill("Privater Entwurf vor Abmeldung")
    page.goto(mailhelp.url + "/geraete")
    assert "Privater Entwurf" in page.evaluate("sessionStorage.getItem('mailhelp.help-window.v1')")
    requested = []

    def sign_out(route):
        # The response never arrives, so no signed-out page can erase the draft: only the
        # submission itself can. (Evaluating or continuing here stalls the harness.)
        requested.append(route.request.method)
        route.abort("aborted")

    page.route(re.compile(r".*/geraete/[a-f0-9]+/abmelden$"), sign_out)
    # On small screens the open window may cover the button; the keyboard reaches it anyway.
    page.get_by_role("button", name="Abmelden", exact=True).focus()
    page.keyboard.press("Enter")
    for _ in range(100):
        if requested:
            break
        page.wait_for_timeout(50)
    assert requested == ["POST"]
    assert page.url == mailhelp.url + "/geraete"
    assert page.evaluate("sessionStorage.getItem('mailhelp.help-window.v1')") is None


def test_window54_ime_and_public_page_results_use_the_same_live_search(page, mailhelp):
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/einstellungen")
    field = page.get_by_role("searchbox", name="Einstellung suchen")
    requests = []
    page.on("request", lambda request: requests.append(request.url)
            if "/api/einstellungen/suche" in request.url else None)
    page.clock.install()
    field.dispatch_event("compositionstart")
    field.fill("Postfächer")
    page.clock.run_for(300)
    assert requests == []
    expect(page.locator("#settings-live-results")).to_be_hidden()
    field.dispatch_event("compositionend")
    page.clock.run_for(200)
    expect(page.locator("#settings-live-results li a").first).to_have_text("Postfächer")
    assert len(requests) == 1
    field.fill("web.port")
    page.clock.run_for(200)
    expect(page.locator("#settings-live-results")).to_contain_text("Datei")
    expect(page.locator("#settings-live-results li a").first).to_have_text("web.port")


def test_window54_blocked_storage_autosaves_then_preserves_a_search_form_submission(page, mailhelp):
    page.add_init_script("Object.defineProperty(window, 'sessionStorage', {get() {throw Error('blocked')}});")
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/einstellungen")
    page.get_by_label("Hilfschat öffnen", exact=True).click()
    question = page.get_by_label("Deine Frage zu Einstellungen und Bedienung")
    question.fill("Entwurf vor Formularnavigation")
    page.wait_for_function("""async () => {
      const r = await fetch('/api/hilfe/fenster'); const s = await r.json();
      return s.ui.draft === 'Entwurf vor Formularnavigation';
    }""")
    page.get_by_role("searchbox", name="Einstellung suchen").fill("Zeitzone")
    navigate_collected(page, mailhelp, page.get_by_role("button", name="Suchen", exact=True))
    page.wait_for_url(mailhelp.url + "/einstellungen?suche=Zeitzone")
    expect(question).to_have_value("Entwurf vor Formularnavigation")
    page.get_by_role("button", name="Hilfschat schließen", exact=True).click()
    page.wait_for_function("async () => !(await (await fetch('/api/hilfe/fenster')).json()).ui.opened")
    expect(page.locator("#help-window")).to_be_hidden()
    page.reload()
    expect(page.locator("#help-window")).to_be_hidden()


def test_window54_a_late_source_never_replaces_the_newer_document(page, mailhelp):
    class TwoSources(Analyzer):
        def settings_help(self, question, sources, history, settings, *, before_call):
            before_call()
            return "synthetic", HelpAnswer(answer="Synthetische Antwort mit zwei Quellen.",
                                           source_ids=[source.id for source in sources[:2]],
                                           setting_ids=["setting:poll_interval_seconds"])

    service = chat_service(mailhelp)
    service.analyzer = TwoSources
    sign_in(page, mailhelp)
    # Starting on the area keeps the final settings link a same-document jump, so the
    # coverage of everything before it survives until the teardown takes it.
    page.goto(mailhelp.url + "/einstellungen?bereich=abruf")
    page.get_by_label("Hilfschat öffnen", exact=True).click()
    page.get_by_label("Deine Frage zu Einstellungen und Bedienung").fill("Was bewirkt das Abrufintervall?")
    page.get_by_role("button", name="Frage senden", exact=True).click()
    expect(page.get_by_text("Antwort wird vorbereitet", exact=False)).to_be_visible()
    service.run_once()
    links = page.locator('.help-sources a[href^="/hilfe/dokumentation/"]')
    expect(links).to_have_count(2)
    held = []

    def delay_first(route):
        if not held:
            held.append((route, route.fetch()))
        else:
            route.continue_()

    page.route("**/hilfe/dokumentation/**", delay_first)
    links.first.click()
    links.nth(1).click()
    expect(page.locator("#help-document")).to_be_visible()
    current = page.locator(".help-document-text").text_content()
    held[0][0].fulfill(response=held[0][1])
    page.wait_for_timeout(100)  # Deliver the intentionally late response before checking it cannot win.
    expect(page.locator(".help-document-text")).to_have_text(current)
    page.get_by_role("button", name="Zurück zum Gespräch", exact=True).click()
    page.locator('.help-sources a[href^="/einstellungen"]').click()
    page.wait_for_url(re.compile(r".*/einstellungen\?bereich=abruf#einstellung-poll-interval-seconds$"))
    expect(page.locator("#help-window")).to_be_visible()


def test_window54_a_jump_to_a_setting_of_the_same_page_keeps_unsaved_values(page, mailhelp):
    # 5.4.1 regression: the anchor jump fired popstate, which reloaded the whole page and
    # discarded the value typed into the open setting.
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/einstellungen?bereich=abruf")
    page.get_by_label("Hilfschat öffnen", exact=True).click()
    row = page.locator("#einstellung-poll-interval-seconds")
    row.locator("summary").click()
    row.get_by_label("Neuer Wert", exact=True).fill("75")
    page.evaluate("window.sameDocument = true")
    page.get_by_role("searchbox", name="Einstellung suchen").fill("Zeitzone")
    result = page.locator('#settings-live-results a[href="/einstellungen?bereich=abruf#einstellung-timezone"]')
    result.click()
    page.wait_for_url(mailhelp.url + "/einstellungen?bereich=abruf#einstellung-timezone")
    expect(page.locator("#einstellung-timezone details")).to_have_attribute("open", "")
    assert page.evaluate("window.sameDocument") is True
    expect(row.get_by_label("Neuer Wert", exact=True)).to_have_value("75")
    expect(page.locator("#help-window")).to_be_visible()
    assert page.errors == []
