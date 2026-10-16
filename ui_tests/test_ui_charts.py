"""Evaluation charts: enlargement, pointer/focus details, touch and the no-script fallback."""
from playwright.sync_api import expect

from checks import audit
from conftest import sign_in


def seed_charts(mailhelp):
    metrics = mailhelp.site.archive.metrics
    for number, outcome in enumerate(("response_received", "request_failed", "response_received")):
        metrics.observe("request_started", {"call_id": f"chart-{number}", "model": "synthetic/Modell <img src=x>",
                                           "stage": "summary", "backend": "OpenRouter"})
        metrics.observe(outcome, {"call_id": f"chart-{number}", "reported_cost": "0.0012"})


def test_charts_zoom_and_show_details_with_pointer_keyboard_and_touch(page, mailhelp):
    seed_charts(mailhelp)
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/auswertung")
    chart = page.locator("figure.chart").first
    zoom = chart.get_by_role("button", name="vergrößern", exact=False)
    expect(zoom).to_have_count(1)
    point = chart.locator("rect[data-chart-detail]").first
    tip = chart.get_by_role("tooltip")
    point.hover()
    expect(tip).to_be_visible()
    expect(tip).to_have_text(point.get_attribute("aria-label"))
    tip.hover()  # Details remain readable when the pointer moves onto the tooltip.
    expect(tip).to_be_visible()
    zoom.hover()
    expect(tip).to_be_hidden()
    point.focus()
    page.get_by_role("heading", name="Kosten und Zeiten").hover()
    expect(tip).to_be_visible()  # Keyboard focus keeps the details open.
    point.press("Tab")
    expect(tip).to_contain_text("fehlgeschlagen 1")
    point.press("ArrowRight")
    point.press("Escape")
    expect(tip).to_be_hidden()
    zoom.focus()
    chart.get_by_text("Werte als Tabelle", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    width = chart.locator("svg").bounding_box()["width"]
    point.click()
    dialog = page.get_by_role("dialog", name="KI-Aufrufe je Tag – vergrößert", exact=True)
    expect(dialog).to_be_visible()
    assert dialog.locator("svg").bounding_box()["width"] > width
    assert page.evaluate("() => { const ids = [...document.querySelectorAll('[id]')].map(n => n.id); "
                         "return new Set(ids).size === ids.length; }")
    expect(dialog.locator("figure")).to_have_attribute("aria-labelledby", "zoom-chart-calls-title")
    enlarged = dialog.locator("rect[data-chart-detail]").first
    if page.mobile:
        enlarged.tap()
    else:
        enlarged.click()
    expect(dialog.get_by_role("tooltip")).to_have_text(enlarged.get_attribute("aria-label"))
    tip_box = dialog.get_by_role("tooltip").bounding_box()
    plot_box = dialog.locator(".chart-plot").bounding_box()
    assert tip_box["x"] >= plot_box["x"] - 1
    assert tip_box["x"] + tip_box["width"] <= plot_box["x"] + plot_box["width"] + 1
    expect(page.get_by_role("dialog")).to_have_count(1)
    assert audit(page, "charts-expanded-" + page.device, page.mobile) == []
    page.emulate_media(color_scheme="dark")
    assert audit(page, "charts-expanded-dark-" + page.device, page.mobile) == []
    enlarged.focus()
    enlarged.press("Escape")
    expect(dialog).to_have_count(0)
    expect(zoom).to_be_focused()
    zoom.press("Enter")
    expect(dialog).to_be_visible()
    dialog.get_by_role("button", name="Schließen", exact=True).click()
    expect(dialog).to_have_count(0)
    expect(zoom).to_be_focused()
    assert mailhelp.writer.created == [] and page.errors == []


def test_horizontal_chart_details_are_plain_text_and_tables_still_work(page, mailhelp):
    seed_charts(mailhelp)
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/auswertung")
    chart = page.locator("figure.chart").last
    chart.get_by_role("button", name="vergrößern", exact=False).click()
    dialog = page.get_by_role("dialog")
    point = dialog.locator("rect[data-chart-detail]").first
    point.focus()
    tip = dialog.get_by_role("tooltip")
    expect(tip).to_contain_text("Modell <img src=x>: 0,0036 $")
    expect(tip.locator("img")).to_have_count(0)
    dialog.get_by_text("Werte als Tabelle", exact=True).click()
    expect(dialog.locator("table")).to_be_visible()
    dialog.get_by_role("button", name="Schließen", exact=True).click()
    assert page.errors == []


def test_charts_and_tables_remain_available_without_javascript(browser, mailhelp):
    seed_charts(mailhelp)
    context = browser.new_context(java_script_enabled=False, viewport={"width": 390, "height": 844})
    try:
        page = context.new_page()
        sign_in(page, mailhelp)
        page.goto(mailhelp.url + "/auswertung")
        expect(page.locator("figure.chart")).to_have_count(5)
        expect(page.locator(".chart-zoom").first).to_be_hidden()
        chart = page.locator("figure.chart").first
        chart.get_by_text("Werte als Tabelle", exact=True).click()
        expect(chart.locator("table")).to_be_visible()
        assert "erfolgreich 2" in chart.locator("rect title").first.text_content()
    finally:
        context.close()
