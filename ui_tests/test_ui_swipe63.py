"""6.3: deciding a card on "Offen" by swiping it (Planung 6.3).

The touches are real touch events through the Chrome DevTools protocol, so the browser applies
``touch-action`` and its own scrolling exactly as on a phone.
"""
from __future__ import annotations

from urllib.parse import parse_qsl

import pytest
from playwright.sync_api import expect

from checks import audit
from conftest import hold, sign_in
from tests.scenarios.web_scenario import mail_id

ELTERNABEND, FORMULAR = f"#v-{mail_id(1)}-elternabend", f"#v-{mail_id(1)}-formular"
ZAHNARZT, RELEVANCE = f"#v-{mail_id(2)}-zahnarzt", f"#r-{mail_id(7)}"
BACKDROP = ".swipe-backdrop"


@pytest.fixture(params=[0, 0.1], ids=["straight", "drift"])
def phone(page, request):
    """The swipe is a phone and tablet gesture; the desktop has its own tests below."""
    if page.device != "mobile":
        pytest.skip("Wischen wird auf dem Telefon geprüft")
    page.swipe_drift = request.param
    return page


class Touch:
    """One finger on the screen, moved in small steps like a real swipe."""

    def __init__(self, page, x, y):
        self.page, self.x, self.y = page, x, y
        self.send("touchStart", [(x, y)])

    def send(self, kind, points):
        self.page.cdp.send("Input.dispatchTouchEvent", {
            "type": kind, "touchPoints": [{"x": x, "y": y, "id": index} for index, (x, y) in enumerate(points)]})

    def move(self, dx, dy=None, steps=8):
        if dy is None:
            dy = abs(dx) * getattr(self.page, "swipe_drift", 0)
        start_x, start_y = self.x, self.y
        distance = (dx * dx + dy * dy) ** 0.5
        for step in range(1, steps + 1):
            progress = min(1, max(step / steps, 15 / distance)) if distance else 1
            self.x, self.y = start_x + dx * progress, start_y + dy * progress
            self.send("touchMove", [(self.x, self.y)])
        return self

    def end(self):
        self.send("touchEnd", [])

    def cancel(self):
        self.send("touchCancel", [])


def grab(page, selector, x=None, part="p.source"):
    """Put a finger on the plain text of a card (not on a button or link)."""
    target = page.locator(f"{selector} {part}").first
    target.scroll_into_view_if_needed()
    box = target.bounding_box()
    return Touch(page, box["x"] + box["width"] / 2 if x is None else x, box["y"] + box["height"] / 2)


def swipe(page, selector, dx, dy=None, x=None):
    # Right swipes start left of the middle, left swipes right of it, so the finger stays on screen.
    touch = grab(page, selector, x if x is not None else (90 if dx > 0 else 300))
    touch.move(dx, dy)
    touch.end()


def actions(page):
    sent = []
    page.on("request", lambda request: sent.append(request.post_data)
            if request.method == "POST" and request.url.endswith("/aktion") else None)
    return sent


def offset(page, selector):
    return page.locator(selector).evaluate("(card) => new DOMMatrix(getComputedStyle(card).transform).m41")


def at(page, selector, expected):
    """Chrome delivers pointer moves once per frame: wait for the last one."""
    for _ in range(40):
        if abs(offset(page, selector) - expected) <= 1:
            return
        page.wait_for_timeout(25)
    assert abs(offset(page, selector) - expected) <= 1


def shot(page, name):
    """A picture of the card and its backdrop only, for the release documentation (Planung 6.3, 8)."""
    import checks
    # A full-page picture moves sticky parts; the window shows what the finger sees.
    page.evaluate("document.querySelector('.swipe-backdrop').scrollIntoView({block: 'start'})")
    page.evaluate("window.scrollBy(0, -8)")
    box = page.locator(BACKDROP).bounding_box()
    page.screenshot(path=str(checks.SCREENSHOTS / f"{name}.png"),
                    clip={"x": 0, "y": max(0, box["y"] - 8), "width": page.viewport_size["width"], "height": 420})


def settled(page, selector):
    expect(page.locator(BACKDROP)).to_have_count(0)
    expect(page.locator(selector)).not_to_have_class("swipe-card")
    assert page.locator(selector).evaluate("(card) => card.style.transform") == ""


def form_fields(page, selector, kind):
    """What the card's button would send."""
    return page.locator(f'{selector} input[name="kind"][value="{kind}"]').evaluate(
        "(input) => new URLSearchParams(new FormData(input.form)).toString()")


@pytest.mark.parametrize("steps", [2, 20])
@pytest.mark.parametrize("dy", [20, 40])
def test_regression_v632_natural_swipe_with_vertical_drift(phone, mailhelp, steps, dy):
    sign_in(phone, mailhelp)
    sent = actions(phone)
    grab(phone, ELTERNABEND, 90).move(200, dy, steps=steps).end()
    expect(phone.locator(ELTERNABEND)).to_contain_text("Angelegt")
    assert len(sent) == 1 and len(mailhelp.writer.created) == 1


@pytest.mark.parametrize("part", ["h3 a", "summary", ".decision-bar button"])
def test_regression_v632_swipe_can_start_on_a_control(phone, mailhelp, part):
    sign_in(phone, mailhelp)
    sent = actions(phone)
    details = phone.locator(f"{ELTERNABEND} details").first
    opened = details.evaluate("node => node.open")
    details.evaluate("node => { window.v632Toggles = 0; node.addEventListener('toggle', () => window.v632Toggles++); }")
    touch = grab(phone, ELTERNABEND, 90, part)
    touch.move(200, 20, steps=2).end()
    expect(phone.locator(ELTERNABEND)).to_contain_text("Angelegt")
    assert len(sent) == 1 and phone.url == mailhelp.url + "/"
    assert opened is False and phone.evaluate("window.v632Toggles") == 0


@pytest.mark.parametrize("jitter", [0, 5])
@pytest.mark.parametrize("part", ["h3 a", "summary", ".decision-bar button"])
def test_v632_tapping_controls_still_activates_them(phone, mailhelp, jitter, part):
    sign_in(phone, mailhelp)
    touch = grab(phone, ELTERNABEND, part=part)
    touch.move(jitter, 0).end()
    if part == "h3 a":
        phone.wait_for_url(mailhelp.url + f"/vorschlag/{mail_id(1)}/elternabend")
    elif part == "summary":
        expect(phone.locator(f"{ELTERNABEND} details").first).to_have_attribute("open", "")
    else:
        expect(phone.locator(ELTERNABEND)).to_contain_text("Angelegt")
        assert len(mailhelp.writer.created) == 1


def test_v632_delayed_touch_click_is_suppressed_and_the_next_tap_works(phone, mailhelp):
    sign_in(phone, mailhelp)
    sent = actions(phone)
    touch = grab(phone, ELTERNABEND, 90, "h3 a")
    touch.move(60, 5, steps=2)
    at(phone, ELTERNABEND, 60)
    touch.end()
    title = phone.locator(f"{ELTERNABEND} h3 a")
    title.dispatch_event("click", {"detail": 1})
    assert phone.url == mailhelp.url + "/" and sent == []
    settled(phone, ELTERNABEND)
    # A separate ordinary tap starts after Chrome's native post-gesture suppression window.
    phone.wait_for_timeout(600)
    title.tap()
    phone.wait_for_url(mailhelp.url + f"/vorschlag/{mail_id(1)}/elternabend")


def test_v632_keyboard_activation_and_clicks_outside_the_card_are_preserved(phone, mailhelp):
    sign_in(phone, mailhelp)
    touch = grab(phone, ELTERNABEND, 90, "h3 a")
    touch.move(60, 5, steps=2)
    at(phone, ELTERNABEND, 60)
    touch.end()
    phone.locator("h1").dispatch_event("click", {"detail": 1})
    summary = phone.locator(f"{ELTERNABEND} summary").first
    summary.dispatch_event("click", {"detail": 0})
    details = phone.locator(f"{ELTERNABEND} details").first
    expect(details).to_have_attribute("open", "")
    summary.dispatch_event("click", {"detail": 1})
    expect(details).to_have_attribute("open", "")



@pytest.mark.parametrize(("dx", "dy"), [(10, -200), (120, 120), (30, 24)])
def test_v632_vertical_and_ambiguous_movements_do_not_decide(phone, mailhelp, dx, dy):
    sign_in(phone, mailhelp)
    sent = actions(phone)
    grab(phone, ELTERNABEND, 90).move(dx, dy, steps=2).end()
    assert phone.locator(BACKDROP).count() == 0 and sent == []


def test_swipe_right_creates_exactly_what_the_button_would(phone, mailhelp):
    page = phone
    sign_in(page, mailhelp)
    sent = actions(page)
    expected = form_fields(page, ELTERNABEND, "confirm")
    swipe(page, ELTERNABEND, 200)
    expect(page.locator(f"{ELTERNABEND} [data-command-result] .notice")).to_contain_text("Angelegt.", timeout=20000)
    assert sent == [expected]
    assert dict(parse_qsl(expected))["version"] == "1" and dict(parse_qsl(expected))["csrf"]
    assert mailhelp.writer.created == ["Elternabend Klasse 4b"]
    # The card stays in its place with its result; nothing flew out of view.
    settled(page, ELTERNABEND)
    expect(page.locator(ELTERNABEND)).to_be_in_viewport()
    assert page.errors == []


def test_swipe_left_rejects(phone, mailhelp):
    page = phone
    sign_in(page, mailhelp)
    sent = actions(page)
    expected = form_fields(page, FORMULAR, "reject")
    swipe(page, FORMULAR, -200)
    expect(page.locator(f"{FORMULAR} [data-command-result] .notice")).to_contain_text("verworfen", timeout=20000)
    assert sent == [expected]
    assert mailhelp.store.load(f"proposal-{mail_id(1)}-formular")["status"] == "rejected"
    assert mailhelp.writer.created == []
    assert page.errors == []


@pytest.mark.parametrize(("dx", "decision", "text"), [(200, "relevant", "Relevant"),
                                                        (-200, "irrelevant", "Irrelevant")])
def test_a_relevance_question_is_swiped_both_ways(phone, mailhelp, dx, decision, text):
    page = phone
    sign_in(page, mailhelp)
    sent = actions(page)
    touch = grab(page, RELEVANCE, 90 if dx > 0 else 300).move(dx)
    expect(page.locator(f"{BACKDROP} .swipe-text")).to_have_text(text)
    touch.end()
    expect(page.locator(f"{RELEVANCE} [data-card-command-status], {RELEVANCE} [data-command-result]").first
           ).to_be_attached(timeout=10000)
    assert len(sent) == 1 and dict(parse_qsl(sent[0]))["decision"] == decision
    assert page.errors == []


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_the_backdrop_says_before_letting_go_whether_and_what_happens(phone, mailhelp, theme):
    page = phone
    page.emulate_media(color_scheme=theme)
    sign_in(page, mailhelp)
    sent = actions(page)
    backdrop = page.locator(BACKDROP)
    touch = grab(page, ELTERNABEND, 90).move(60)
    # Before the threshold: light ground, the wording of the button, the card follows the finger exactly.
    expect(backdrop).to_have_class("swipe-backdrop swipe-accept")
    expect(backdrop.locator(".swipe-text")).to_have_text("Im Kalender anlegen")
    expect(backdrop.locator(".swipe-symbol")).to_have_text("✓")
    at(page, ELTERNABEND, 60)
    shot(page, f"swipe63-karte-hell-{theme}")
    assert audit(page, f"swipe63-hell-{theme}", True) == []
    # From the threshold (40 % of the card, at most 160 px): strong ground; beyond it the card slows down.
    width = page.locator(ELTERNABEND).evaluate("(card) => card.offsetWidth")
    limit = min(width * 0.4, 160)
    touch.move(limit - 60 + 40)
    expect(backdrop).to_have_class("swipe-backdrop swipe-accept swipe-armed")
    at(page, ELTERNABEND, limit + 40 * 0.25)
    shot(page, f"swipe63-karte-kraeftig-{theme}")
    assert audit(page, f"swipe63-kraeftig-{theme}", True) == []
    # Back below the threshold: light again, and letting go sends nothing.
    touch.move(-80)
    expect(backdrop).to_have_class("swipe-backdrop swipe-accept")
    touch.move(-200)
    expect(backdrop).to_have_class("swipe-backdrop swipe-reject")
    expect(backdrop.locator(".swipe-text")).to_have_text("Verwerfen")
    expect(backdrop.locator(".swipe-symbol")).to_have_text("✕")
    touch.move(150)
    touch.end()
    settled(page, ELTERNABEND)
    page.wait_for_timeout(300)
    assert sent == []
    assert page.errors == []


def test_a_blocked_direction_resists_and_names_the_reason(phone, mailhelp):
    page = phone
    sign_in(page, mailhelp)
    sent = actions(page)
    touch = grab(page, ZAHNARZT, 90).move(200)
    backdrop = page.locator(BACKDROP)
    expect(backdrop).to_have_class("swipe-backdrop swipe-accept swipe-blocked")
    expect(backdrop.locator(".swipe-symbol")).to_have_text("🔒")
    expect(backdrop.locator(".swipe-text")).to_have_text("")
    at(page, ZAHNARZT, 24)
    shot(page, "swipe63-karte-gesperrt")
    assert audit(page, "swipe63-gesperrt", True) == []
    touch.end()
    expect(page.locator(".undo-toast")).to_have_text("Erst die Rückfrage beantworten.")
    settled(page, ZAHNARZT)
    # Left stays possible on the same card.
    swipe(page, ZAHNARZT, -200)
    expect(page.locator(f"{ZAHNARZT} [data-command-result] .notice")).to_contain_text("verworfen", timeout=20000)
    assert len(sent) == 1 and dict(parse_qsl(sent[0]))["kind"] == "reject"
    assert page.errors == []


def test_a_card_without_reason_names_the_general_one(phone, mailhelp):
    page = phone
    sign_in(page, mailhelp)
    page.locator(f'{FORMULAR} input[name="kind"][value="confirm"]').evaluate("(input) => input.form.remove()")
    swipe(page, FORMULAR, 200)
    expect(page.locator(".undo-toast")).to_have_text("Diese Aktion ist für diesen Vorgang nicht möglich.")


def test_unsent_answer_text_blocks_both_directions(phone, mailhelp):
    page = phone
    sign_in(page, mailhelp)
    sent = actions(page)
    page.locator(ZAHNARZT).get_by_label("Wann beginnt der Termin?").fill("10 Uhr")
    swipe(page, ZAHNARZT, -200)
    expect(page.locator(".undo-toast")).to_have_text("Erst die Antwort senden oder das Feld leeren.")
    page.wait_for_timeout(300)
    assert sent == []
    expect(page.locator(ZAHNARZT).get_by_label("Wann beginnt der Termin?")).to_have_value("10 Uhr")


def test_scrolling_and_slanted_moves_never_move_a_card(phone, mailhelp):
    page = phone
    sign_in(page, mailhelp)
    sent = actions(page)
    before = page.evaluate("scrollY")
    touch = grab(page, FORMULAR, 200)
    touch.move(0, -300)
    assert page.locator(BACKDROP).count() == 0 and offset(page, FORMULAR) == 0
    touch.end()
    assert page.evaluate("scrollY") > before  # the page scrolled natively
    # A steep diagonal belongs to scrolling, even when the finger later turns sideways.
    touch = grab(page, FORMULAR, 300)
    touch.move(-20, 30, steps=2)
    touch.move(-200)
    assert page.locator(BACKDROP).count() == 0 and offset(page, FORMULAR) == 0
    touch.end()
    # A tap on the card text decides nothing either.
    touch = grab(page, FORMULAR, 200)
    touch.end()
    page.wait_for_timeout(300)
    assert sent == []
    assert page.errors == []


def test_no_swipe_starts_where_the_touch_means_something_else(phone, mailhelp):
    page = phone
    sign_in(page, mailhelp)
    sent = actions(page)

    def untouched(touch, selector=FORMULAR):
        touch.move(-200)
        assert page.locator(BACKDROP).count() == 0 and offset(page, selector) == 0
        touch.end()

    # In an input, at the screen edges (the browser's back gesture) and outside any card.
    page.locator(f"{FORMULAR} details").last.evaluate("node => node.open = true")
    untouched(grab(page, FORMULAR, None, 'textarea'))
    untouched(grab(page, FORMULAR, 10))
    untouched(grab(page, FORMULAR, page.viewport_size["width"] - 10))
    untouched(grab(page, "main", None, "h1"))
    # With selected text.
    page.locator(f"{FORMULAR} p.source").evaluate(
        "(node) => getSelection().selectAllChildren(node)")
    untouched(grab(page, FORMULAR, 300))
    page.evaluate("getSelection().removeAllRanges()")
    # In something that scrolls sideways on its own.
    page.locator(f"{FORMULAR} p.source").evaluate("""(node) => {
      const box = document.createElement('div');
      box.className = 'wide-test'; box.style.cssText = 'overflow-x:auto;white-space:nowrap';
      box.innerHTML = '<span>' + 'breite Tabelle '.repeat(40) + '</span>';
      node.after(box);
    }""")
    untouched(grab(page, FORMULAR, 300, ".wide-test span"))
    # A card that can no longer be rejected (e.g. a check of a written entry) does not move at all.
    page.locator(f'{FORMULAR} input[name="kind"][value="reject"]').evaluate("(input) => input.form.remove()")
    untouched(grab(page, FORMULAR, 300))
    # A mouse does not swipe.
    box = page.locator(f"{ELTERNABEND} p.source").bounding_box()
    page.mouse.move(300, box["y"] + 5)
    page.mouse.down()
    page.mouse.move(100, box["y"] + 5, steps=8)
    assert page.locator(BACKDROP).count() == 0 and offset(page, ELTERNABEND) == 0
    page.mouse.up()
    page.wait_for_timeout(300)
    assert sent == []
    assert page.errors == []


def test_a_second_finger_or_a_system_cancel_stops_the_swipe(phone, mailhelp):
    page = phone
    sign_in(page, mailhelp)
    sent = actions(page)
    touch = grab(page, ELTERNABEND, 90).move(200)
    expect(page.locator(BACKDROP)).to_have_class("swipe-backdrop swipe-accept swipe-armed")
    # Zooming: a second finger lands.
    touch.send("touchStart", [(touch.x, touch.y), (200, touch.y + 40)])
    settled(page, ELTERNABEND)
    touch.send("touchEnd", [])
    touch = grab(page, ELTERNABEND, 90).move(200)
    touch.cancel()
    settled(page, ELTERNABEND)
    page.wait_for_timeout(300)
    assert sent == []
    assert page.errors == []


def test_a_card_being_processed_cannot_be_swiped_again(phone, mailhelp, monkeypatch):
    page = phone
    release = hold(mailhelp, monkeypatch)
    sign_in(page, mailhelp)
    sent = actions(page)
    swipe(page, FORMULAR, -200)
    expect(page.locator(f"{FORMULAR} [data-card-command-status]")).to_be_attached()
    expect(page.locator(f"{FORMULAR} [data-card-command-status]")).to_have_text("Wird verarbeitet …")
    touch = grab(page, FORMULAR, 300).move(-200)
    assert page.locator(BACKDROP).count() == 0
    touch.end()
    release.set()
    expect(page.locator(f"{FORMULAR} [data-command-result] .notice")).to_contain_text("verworfen", timeout=20000)
    assert len(sent) == 1
    assert page.errors == []


def test_an_outdated_version_shows_the_refusal_on_the_card(phone, mailhelp):
    page = phone
    sign_in(page, mailhelp)
    page.evaluate("""document.querySelectorAll('input[name="version"]').forEach((input) => { input.value = '9'; })""")
    swipe(page, FORMULAR, -200)
    refused = page.locator(FORMULAR).get_by_role("alert").first
    expect(refused).to_be_visible(timeout=15000)
    assert mailhelp.store.load(f"proposal-{mail_id(1)}-formular")["status"] == "pending_confirmation"
    assert page.errors == []


def test_with_reduced_motion_the_card_jumps_back(phone, mailhelp):
    page = phone
    page.emulate_media(reduced_motion="reduce")
    sign_in(page, mailhelp)
    touch = grab(page, ELTERNABEND, 90).move(60)
    touch.end()
    assert offset(page, ELTERNABEND) == 0  # no glide back
    settled(page, ELTERNABEND)


def test_wide_windows_keep_the_split_view_without_swiping(phone, mailhelp):
    page = phone
    sign_in(page, mailhelp)
    page.set_viewport_size({"width": 1366, "height": 900})
    expect(page.locator(".swipe-hint")).to_be_hidden()
    box = page.locator(f".master-pane {FORMULAR} p.source").bounding_box()
    touch = Touch(page, box["x"] + box["width"] - 20, box["y"] + box["height"] / 2).move(-200)
    assert page.locator(BACKDROP).count() == 0
    touch.end()


def test_the_tip_appears_once_and_goes_after_understanding(phone, mailhelp):
    page = phone
    sign_in(page, mailhelp)
    tip = page.locator(".swipe-hint")
    expect(tip).to_be_visible()
    expect(tip).to_contain_text("nach rechts wischen für relevant, nach links für irrelevant")
    # Below the first card it explains, so the first decision keeps its place on the first screen.
    assert tip.evaluate("(node) => node.previousElementSibling.id") == RELEVANCE[1:]
    top = "(node) => node.getBoundingClientRect().top"
    assert page.locator(".open-items article.card").first.evaluate(top) < tip.evaluate(top)
    assert audit(page, "swipe63-tipp", True) == []
    tip.get_by_role("button", name="Verstanden").click()
    expect(tip).to_be_hidden()
    page.reload()
    expect(page.locator(".open-items")).to_be_visible()
    expect(tip).to_be_hidden()


def test_the_first_swipe_ends_the_tip(phone, mailhelp):
    page = phone
    sign_in(page, mailhelp)
    tip = page.locator(".swipe-hint")
    expect(tip).to_be_visible()
    swipe(page, FORMULAR, -200)
    expect(tip).to_be_hidden()
    expect(page.locator(f"{FORMULAR} [data-command-result] .notice")).to_contain_text("verworfen", timeout=20000)
    page.reload()
    expect(page.locator(".open-items")).to_be_visible()
    expect(tip).to_be_hidden()


def test_without_storage_the_tip_shows_on_every_visit_and_can_be_closed(phone, mailhelp):
    page = phone
    page.add_init_script("Object.defineProperty(window, 'localStorage', {get() {throw Error('blocked')}});")
    sign_in(page, mailhelp)
    tip = page.locator(".swipe-hint")
    tip.get_by_role("button", name="Verstanden").click()
    expect(tip).to_be_hidden()
    page.reload()
    expect(tip).to_be_visible()
    assert page.errors == []


def test_without_touch_there_is_no_tip(page, mailhelp):
    if page.device != "desktop":
        return
    sign_in(page, mailhelp)
    expect(page.locator(".master-pane")).to_be_visible()
    assert page.locator(".swipe-hint").get_attribute("hidden") == ""
    assert page.errors == []


def test_without_javascript_nothing_changes(browser, mailhelp):
    from conftest import DEVICES, Page

    context = browser.new_context(locale="de-DE", java_script_enabled=False, service_workers="block",
                                  **DEVICES["mobile"])
    page = Page(context.new_page(), "mobile")
    try:
        sign_in(page, mailhelp)
        expect(page.locator(".swipe-hint")).to_be_hidden()
        expect(page.locator(FORMULAR).get_by_role("button", name="Verwerfen")).to_be_visible()
        assert page.locator(BACKDROP).count() == 0
    finally:
        context.close()
