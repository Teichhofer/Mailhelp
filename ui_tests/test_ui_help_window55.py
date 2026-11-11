"""5.5: the help window over plain HTTP in the home network and its tidier controls."""
import re
from urllib.parse import parse_qs

import pytest
from playwright.sync_api import expect

from conftest import sign_in

BLOCKED_STORAGE = "Object.defineProperty(window, 'sessionStorage', {get() {throw Error('blocked')}});"
# Outside a secure context (http://192.168.…) Chrome offers no crypto.randomUUID.
INSECURE = {
    "without_random_uuid": "Object.defineProperty(Crypto.prototype, 'randomUUID', {value: undefined});",
    "without_any_crypto_random": ("Object.defineProperty(Crypto.prototype, 'randomUUID', {value: undefined});"
                                  "Object.defineProperty(Crypto.prototype, 'getRandomValues', {value: undefined});"),
}


@pytest.mark.parametrize("context", sorted(INSECURE))
def test_window55_fallback_keys_work_without_crypto_random_uuid(page, mailhelp, context):
    # 5.5 regression: the fallback called crypto.randomUUID() and showed
    # "crypto.randomUUID is not a function" in the window instead of saving the draft.
    page.add_init_script(INSECURE[context] + BLOCKED_STORAGE)
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/einstellungen")
    keys = []
    page.on("request", lambda request: keys.extend(parse_qs(request.post_data or "").get("key", []))
            if request.method == "POST" and request.url.endswith("/hilfe/fenster") else None)
    page.get_by_label("Hilfschat öffnen", exact=True).click()
    page.get_by_label("Deine Frage zu Einstellungen und Bedienung").fill("Entwurf über HTTP")
    page.wait_for_function("""async () => {
      const state = await (await fetch('/api/hilfe/fenster')).json();
      return state.ui.draft === 'Entwurf über HTTP';
    }""")
    expect(page.locator("#help-window-status")).not_to_contain_text("randomUUID")
    assert keys and all(re.fullmatch(r"[0-9a-f]{32}", key) for key in keys)
    assert len(set(keys)) == len(keys)
    assert page.errors == []


def test_window55_the_chat_button_stays_usable_over_a_confirmation_form(page, mailhelp):
    # 5.5.2 regression: whole confirmation forms were raised above the help window, also while
    # it was closed. The topics page is one such form: it covered the window's close button
    # and afterwards the chat button. Only the confirming buttons need to stay on top.
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/themen")
    page.get_by_label("Hilfschat öffnen", exact=True).click()
    window = page.get_by_role("region", name="Hilfe zu Einstellungen", exact=True)
    expect(window).to_be_visible()
    form = page.locator('#inhalt form:has(input[name="confirm"][value="yes"])').first
    button = form.locator("button").last
    assert form.evaluate("form => getComputedStyle(form).zIndex") == "auto"
    assert button.evaluate("button => getComputedStyle(button).zIndex") == "26"
    page.get_by_role("button", name="Hilfschat schließen", exact=True).click(timeout=5000)
    expect(window).to_be_hidden()
    assert button.evaluate("button => getComputedStyle(button).zIndex") == "auto"
    page.get_by_label("Hilfschat öffnen", exact=True).click(timeout=5000)
    expect(window).to_be_visible()
    assert page.errors == []
