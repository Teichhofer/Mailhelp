"""5.4: recovery, isolation and authorization of the persistent settings window."""
import json

from playwright.sync_api import expect

from conftest import Page, navigate_collected, sign_in
from tests.fakes.help_window54 import chat_service


def window(page):
    return page.get_by_role("region", name="Hilfe zu Einstellungen", exact=True)


def test_window54_revoked_session_hides_private_content_and_clears_local_draft(page, mailhelp):
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/einstellungen")
    page.get_by_label("Hilfschat öffnen", exact=True).click()
    page.get_by_label("Deine Frage zu Einstellungen und Bedienung").fill("Privater Entwurf")
    mailhelp.auth.revoke(mailhelp.auth.sessions()[0].id)
    expect(window(page)).to_be_hidden(timeout=10000)
    assert page.evaluate("sessionStorage.getItem('mailhelp.help-window.v1')") is None
    assert page.locator("#help-window-content").text_content() == ""


def test_window54_failed_fallback_keeps_the_current_page_and_can_recover(page, mailhelp):
    page.add_init_script("""Object.defineProperty(window, 'sessionStorage', {
      get() { throw new Error('synthetic blocked storage'); }
    });""")
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/einstellungen")
    page.route("**/hilfe/fenster", lambda route: route.fulfill(
        status=503, content_type="application/json", body='{"error":"Speicher vorübergehend gesperrt"}'))
    page.get_by_label("Hilfschat öffnen", exact=True).click()
    page.get_by_label("Deine Frage zu Einstellungen und Bedienung").fill("Nicht verlieren")
    nav = page.get_by_role("navigation", name="Einstellungsbereiche")
    nav.get_by_role("link", name="Mailabruf", exact=True).click()
    expect(page.locator("#help-window-status")).to_contain_text("Speicher vorübergehend gesperrt")
    expect(page.page).to_have_url(mailhelp.url + "/einstellungen")
    expect(page.get_by_label("Deine Frage zu Einstellungen und Bedienung")).to_have_value("Nicht verlieren")
    page.unroute("**/hilfe/fenster")
    navigate_collected(page, mailhelp, nav.get_by_role("link", name="Mailabruf", exact=True))
    expect(page.page).to_have_url(mailhelp.url + "/einstellungen?bereich=abruf")
    expect(window(page)).to_be_visible()
    expect(page.get_by_label("Deine Frage zu Einstellungen und Bedienung")).to_have_value("Nicht verlieren")


def test_window54_failed_question_preserves_draft_and_closed_job_is_not_resent(page, mailhelp):
    service = chat_service(mailhelp)
    config = service.settings()
    config.enabled = False
    service.settings = lambda: config
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/einstellungen")
    page.get_by_label("Hilfschat öffnen", exact=True).click()
    question = page.get_by_label("Deine Frage zu Einstellungen und Bedienung")
    question.fill("Was bedeutet das Abrufintervall?")
    page.get_by_role("button", name="Frage senden", exact=True).click()
    expect(page.locator("#help-window-status")).to_contain_text("ausgeschaltet")
    expect(question).to_have_value("Was bedeutet das Abrufintervall?")
    config.enabled = True
    page.get_by_role("button", name="Frage senden", exact=True).click()
    expect(page.get_by_text("Antwort wird vorbereitet", exact=False)).to_be_visible()
    page.get_by_role("button", name="Hilfschat schließen", exact=True).click()
    service.run_once()
    page.get_by_label("Hilfschat öffnen", exact=True).click()
    expect(page.locator(".help-answer")).to_contain_text("Intervall steuert den Mailabruf", timeout=10000)
    assert len(service.state(mailhelp.auth.sessions()[0].id).jobs) == 1
    page.route("**/hilfe/dokumentation/**", lambda route: route.fulfill(status=503, body="Nicht erreichbar"))
    page.locator(".help-sources a").first.click()
    expect(page.locator("#help-window-status")).to_contain_text("Dokumentation nicht verfügbar")
    expect(window(page)).to_be_visible()


def test_window54_tabs_have_independent_open_state_and_drafts(page, mailhelp):
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/einstellungen")
    page.get_by_label("Hilfschat öffnen", exact=True).click()
    page.get_by_label("Deine Frage zu Einstellungen und Bedienung").fill("Entwurf A")
    peer = Page(page.context.new_page(), page.device)
    try:
        peer.goto(mailhelp.url + "/einstellungen")
        expect(window(peer)).to_be_hidden()
        peer.get_by_label("Hilfschat öffnen", exact=True).click()
        peer.get_by_label("Deine Frage zu Einstellungen und Bedienung").fill("Entwurf B")
        peer.get_by_role("button", name="Hilfschat schließen", exact=True).click()
        page.bring_to_front()
        expect(window(page)).to_be_visible()
        expect(page.get_by_label("Deine Frage zu Einstellungen und Bedienung")).to_have_value("Entwurf A")
    finally:
        peer.collect()
        peer.close()


def test_window54_expired_and_corrupt_browser_state_does_not_restore_drafts(page, mailhelp):
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/einstellungen")
    page.get_by_label("Hilfschat öffnen", exact=True).click()
    page.get_by_label("Deine Frage zu Einstellungen und Bedienung").fill("Abgelaufen")
    page.evaluate("""() => {
      const key = 'mailhelp.help-window.v1', s = JSON.parse(sessionStorage.getItem(key));
      s.expires = 1; sessionStorage.setItem(key, JSON.stringify(s));
    }""")
    # Real navigation retains the last typed state by design; emulate a previously closed tab snapshot at startup.
    page.add_init_script("""sessionStorage.setItem('mailhelp.help-window.v1', JSON.stringify({
      scope: 'old-session', opened: true, draft: 'Nicht aus anderer Anmeldung übernehmen', expires: 1
    }));""")
    page.reload()
    expect(window(page)).to_be_hidden()
    page.get_by_label("Hilfschat öffnen", exact=True).click()
    expect(page.get_by_label("Deine Frage zu Einstellungen und Bedienung")).to_have_value("")
    page.add_init_script("sessionStorage.setItem('mailhelp.help-window.v1', '{broken');")
    page.reload()
    expect(window(page)).to_be_hidden()
    page.get_by_label("Hilfschat öffnen", exact=True).click()
    expect(window(page)).to_be_visible()


def test_window54_changed_session_scope_and_polling_errors_are_safe(page, mailhelp):
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/einstellungen")
    page.route("**/api/hilfe/fenster**", lambda route: route.fulfill(
        status=503, content_type="application/json", body="{}"))
    page.get_by_label("Hilfschat öffnen", exact=True).click()
    expect(page.locator("#help-window-status")).to_contain_text("Anfrage fehlgeschlagen")
    page.unroute("**/api/hilfe/fenster**")
    page.route("**/api/hilfe/fenster**", lambda route: route.fulfill(
        content_type="application/json", body=json.dumps({"scope": "another-session"})))
    page.get_by_role("button", name="Hilfschat schließen", exact=True).click()
    page.get_by_label("Hilfschat öffnen", exact=True).click()
    expect(window(page)).to_be_hidden(timeout=10000)
    assert page.evaluate("sessionStorage.getItem('mailhelp.help-window.v1')") is None


def test_window54_legacy_link_and_viewport_fallback(page, mailhelp):
    page.add_init_script("Object.defineProperty(window, 'visualViewport', {value: undefined});")
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/hilfe?einstellung=poll_interval_seconds")
    expect(window(page)).to_be_visible()
    expect(page.page).to_have_url(mailhelp.url + "/einstellungen")
    expect(page.get_by_text("Bezug: Abrufintervall (Sekunden)")).to_be_visible()
    page.locator(".help-window-head h2").focus()
    page.keyboard.press("ArrowLeft")
    page.set_viewport_size({"width": 360, "height": 640})
    box = page.locator("#help-window").bounding_box()
    assert 0 <= box["x"] and box["x"] + box["width"] <= 360


def test_window54_polling_preserves_question_selection_and_expires_an_idle_draft(page, mailhelp):
    service = chat_service(mailhelp)
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/einstellungen")
    page.get_by_label("Hilfschat öffnen", exact=True).click()
    question = page.get_by_label("Deine Frage zu Einstellungen und Bedienung")
    question.fill("Frage behalten")
    question.evaluate("input => input.setSelectionRange(2, 6)")
    # Another client of this session clears the server conversation; an unsubmitted local draft stays local.
    service.clear(mailhelp.auth.sessions()[0].id, 1)
    expect(page.locator("#help-window-status")).to_contain_text("Gespräch aktualisiert", timeout=10000)
    expect(question).to_be_focused()
    assert question.evaluate("input => [input.selectionStart, input.selectionEnd]") == [2, 6]
    expect(question).to_have_value("Frage behalten")
    page.clock.install()
    page.clock.fast_forward(86400001)
    expect(question).to_have_value("", timeout=10000)
    expect(window(page)).to_be_visible()


def test_window54_delayed_snapshot_does_not_reopen_a_closed_window(page, mailhelp):
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/einstellungen")
    held = []
    page.route("**/api/hilfe/fenster**", lambda route: held.append((route, route.fetch().json())))
    page.get_by_label("Hilfschat öffnen", exact=True).click()
    expect(window(page)).to_be_visible()
    page.get_by_role("button", name="Hilfschat schließen", exact=True).click()
    page.wait_for_function("() => document.querySelector('#help-window').hidden")
    assert held
    held[0][0].fulfill(json=held[0][1])
    page.unroute("**/api/hilfe/fenster**")
    expect(window(page)).to_be_hidden()


def test_window54_double_submit_and_cached_page_restore_keep_one_job(page, mailhelp):
    service = chat_service(mailhelp)
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/einstellungen")
    page.get_by_label("Hilfschat öffnen", exact=True).click()
    page.get_by_label("Deine Frage zu Einstellungen und Bedienung").fill("Was bedeutet das Abrufintervall?")
    held = []
    page.route("**/hilfe/frage", lambda route: held.append(route))
    send = page.get_by_role("button", name="Frage senden", exact=True)
    send.click()
    send.click()
    assert len(held) == 1
    held[0].continue_()
    expect(page.get_by_text("Antwort wird vorbereitet", exact=False)).to_be_visible()
    page.evaluate("""() => {
      window.dispatchEvent(new PageTransitionEvent('pagehide', {persisted:true}));
      window.dispatchEvent(new PageTransitionEvent('pageshow', {persisted:true}));
      document.dispatchEvent(new Event('visibilitychange'));
    }""")
    expect(window(page)).to_be_visible()
    service.run_once()
    expect(page.locator(".help-answer")).to_be_visible(timeout=10000)
    assert len(service.state(mailhelp.auth.sessions()[0].id).jobs) == 1
    page.locator(".help-sources a").last.click()
    expect(window(page)).to_be_visible()
    expect(page.page).to_have_url(mailhelp.url + "/einstellungen?bereich=abruf#einstellung-poll-interval-seconds")


def test_window54_failed_fallback_warns_before_unload_and_recovers_on_link_navigation(page, mailhelp):
    page.add_init_script("""Object.defineProperty(window, 'sessionStorage', {
      get() { throw new Error('synthetic blocked storage'); }
    });""")
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/einstellungen")
    page.get_by_label("Hilfschat öffnen", exact=True).click()
    page.get_by_label("Deine Frage zu Einstellungen und Bedienung").fill("Entwurf bleibt hier")
    page.route("**/hilfe/fenster", lambda route: route.fulfill(status=503, content_type="application/json",
                                                             body='{"error":"Speicher gesperrt"}'))
    # 5.5: typing saves automatically; there is no "Entwurf behalten" any more.
    page.get_by_label("Deine Frage zu Einstellungen und Bedienung").press_sequentially(" hier")
    expect(page.locator("#help-window-status")).to_contain_text("Speicher gesperrt")
    assert page.evaluate("""() => {
      const event = new Event('beforeunload', {cancelable: true});
      window.dispatchEvent(event); return event.defaultPrevented;
    }""")
    expect(page.get_by_label("Deine Frage zu Einstellungen und Bedienung")).to_have_value("Entwurf bleibt hier hier")
    page.unroute("**/hilfe/fenster")
    nav = page.get_by_role("navigation", name="Einstellungsbereiche")
    navigate_collected(page, mailhelp, nav.get_by_role("link", name="Mailabruf", exact=True))
    expect(page.page).to_have_url(mailhelp.url + "/einstellungen?bereich=abruf")
    expect(window(page)).to_be_visible()
    expect(page.get_by_label("Deine Frage zu Einstellungen und Bedienung")).to_have_value("Entwurf bleibt hier hier")
