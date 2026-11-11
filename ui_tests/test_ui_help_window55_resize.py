"""5.5.3: the help window is resized at its borders and corners, within the screen."""
import json

from playwright.sync_api import expect

from checks import audit
from conftest import sign_in


def opened(page, mailhelp):
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/einstellungen")
    page.get_by_label("Hilfschat öffnen", exact=True).click()
    expect(page.get_by_label("Deine Frage zu Einstellungen und Bedienung")).to_be_focused()
    return page.locator("#help-window")


def drag(page, selector, dx, dy):
    grip = page.locator("#help-window " + selector).bounding_box()
    x, y = grip["x"] + grip["width"] / 2, grip["y"] + grip["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + dx, y + dy, steps=4)
    page.mouse.up()


def room(page):
    return page.evaluate("""() => ({width: innerWidth - 16,
        height: innerHeight - document.querySelector('nav.tab-bar').getBoundingClientRect().height - 24})""")


def test_window55_left_and_top_borders_grow_the_window_and_the_size_is_kept(page, mailhelp):
    panel = opened(page, mailhelp)
    assert page.locator("#help-window .help-resize-w").evaluate("g => getComputedStyle(g).cursor") == "ew-resize"
    assert page.locator("#help-window .help-resize-n").evaluate("g => getComputedStyle(g).cursor") == "ns-resize"
    assert page.locator("#help-window .help-resize-nw").evaluate("g => getComputedStyle(g).cursor") == "nwse-resize"
    assert page.locator("#help-window .help-resize-ne").evaluate("g => getComputedStyle(g).cursor") == "nesw-resize"
    limit = room(page)
    start = panel.bounding_box()
    drag(page, ".help-resize-w", -60, 0)
    wider = panel.bounding_box()
    assert abs(wider["width"] - min(start["width"] + 60, limit["width"])) <= 2
    if wider["width"] < limit["width"] - 1:
        assert abs((wider["x"] + wider["width"]) - (start["x"] + start["width"])) <= 2  # right border stays
    else:  # full width: the window keeps the 8-pixel margin on both sides
        assert abs(wider["x"] - 8) <= 1
    drag(page, ".help-resize-n", 0, -60)
    taller = panel.bounding_box()
    assert taller["height"] >= start["height"] and taller["height"] <= limit["height"] + 1
    assert abs((taller["y"] + taller["height"]) - (wider["y"] + wider["height"])) <= 2  # bottom stays
    page.reload()
    expect(panel).to_be_visible()
    page.wait_for_function("document.getElementById('help-window').style.width !== ''")
    kept = panel.bounding_box()
    assert abs(kept["width"] - taller["width"]) <= 2 and abs(kept["height"] - taller["height"]) <= 2
    assert audit(page, "help-window55-resize-" + page.device, page.mobile) == []
    assert page.errors == []


def test_window55_corners_respect_the_minimum_and_the_screen(page, mailhelp):
    panel = opened(page, mailhelp)
    limit = room(page)
    drag(page, ".help-resize-se", -2000, -2000)
    small = panel.bounding_box()
    assert abs(small["width"] - min(280, limit["width"])) <= 2 and abs(small["height"] - 180) <= 2
    drag(page, ".help-resize-nw", -3000, -3000)
    large = panel.bounding_box()
    assert large["width"] <= limit["width"] + 1 and large["height"] <= limit["height"] + 1
    assert large["x"] >= 7 and large["y"] >= 7
    # A smaller screen limits the window; the chosen size returns on a larger one.
    viewport = page.viewport_size
    page.set_viewport_size({"width": 320, "height": 480})
    shrunk = panel.bounding_box()
    assert shrunk["x"] >= 0 and shrunk["x"] + shrunk["width"] <= 320
    page.set_viewport_size(viewport)
    expect(panel).to_be_visible()
    assert panel.bounding_box()["width"] >= shrunk["width"]
    assert page.errors == []


def test_window55_keyboard_resizes_with_shift_and_arrow_keys(page, mailhelp):
    panel = opened(page, mailhelp)
    drag(page, ".help-resize-se", -2000, -2000)  # start from the minimum so growing is possible
    start = panel.bounding_box()
    page.locator(".help-window-head h2").focus()
    page.keyboard.press("Shift+ArrowRight")
    page.keyboard.press("Shift+ArrowDown")
    grown = panel.bounding_box()
    assert grown["width"] > start["width"] and grown["height"] > start["height"]
    page.keyboard.press("Shift+ArrowLeft")
    page.keyboard.press("Shift+ArrowUp")
    back = panel.bounding_box()
    assert abs(back["width"] - start["width"]) <= 2 and abs(back["height"] - start["height"]) <= 2
    assert page.errors == []


def test_window55_a_manipulated_size_falls_back_to_the_default(page, mailhelp):
    panel = opened(page, mailhelp)
    default = panel.bounding_box()
    stored = json.loads(page.evaluate("sessionStorage.getItem('mailhelp.help-window.v1')"))
    for width, height in (("breit", None), (100, 50), (-400, "hoch")):
        value = json.dumps(json.dumps({**stored, "width": width, "height": height}))
        page.add_init_script(f"sessionStorage.setItem('mailhelp.help-window.v1', {value});")
        page.reload()
        expect(panel).to_be_visible()
        assert panel.evaluate("p => p.style.width") == "" and panel.evaluate("p => p.style.height") == ""
        assert abs(panel.bounding_box()["width"] - default["width"]) <= 2
    assert page.errors == []
