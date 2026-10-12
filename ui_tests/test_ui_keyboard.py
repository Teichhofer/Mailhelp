"""Keyboard operation and visible focus (desktop)."""
from __future__ import annotations

from playwright.sync_api import expect
from web_scenario import mail_id

from conftest import item, sign_in


def focused(page) -> dict:
    return page.evaluate("""() => { const el = document.activeElement; const style = getComputedStyle(el);
        return {tag: el.tagName, text: (el.innerText || el.value || '').trim(),
                outline: style.outlineStyle, width: parseFloat(style.outlineWidth)}; }""")


def test_login_works_with_the_keyboard_and_focus_is_visible(page, mailhelp):
    if page.device != "desktop":
        return
    page.goto(f"{mailhelp.url}/anmelden")
    for _ in range(10):
        page.keyboard.press("Tab")
        if focused(page)["text"] == "Code per Telegram senden":
            break
    state = focused(page)
    assert state["text"] == "Code per Telegram senden"
    assert state["outline"] != "none" and state["width"] >= 2
    page.keyboard.press("Enter")
    # The code field gets the focus by itself.
    expect(page.get_by_label("Code aus Telegram")).to_be_focused()
    page.keyboard.type(mailhelp.pairing_code())
    page.keyboard.press("Enter")
    page.wait_for_url(f"{mailhelp.url}/")
    assert page.errors == []


def test_details_and_actions_are_reachable_with_the_keyboard(page, mailhelp):
    if page.device != "desktop":
        return
    sign_in(page, mailhelp)
    item(page, f"#v-{mail_id(1)}-elternabend")
    pane = page.locator(".detail-pane")
    expect(pane.get_by_role("heading", name="Termin")).to_be_visible()
    summary = pane.locator("summary").filter(has_text="Beleg vollständig anzeigen").first
    summary.focus()
    page.keyboard.press("Enter")
    expect(pane.locator("details[open] .full").first).to_be_visible()
    button = pane.get_by_role("button", name="Im Kalender anlegen")
    button.focus()
    assert focused(page)["outline"] != "none"
    page.keyboard.press("Enter")
    expect(page.locator(".undo-toast")).to_contain_text("wird bestätigt")
    expect(page.locator("main > .notice").first).to_contain_text("Angelegt.", timeout=15000)
    assert page.errors == []
