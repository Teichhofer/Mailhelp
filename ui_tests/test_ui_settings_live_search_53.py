"""Planung 5.3, step H4: live search below the settings search field."""
import json
import re
import time

import pytest
from playwright.sync_api import expect

from checks import audit
from conftest import sign_in

API = re.compile(r".*/api/einstellungen/suche.*")


def open_settings(page, mailhelp):
    sign_in(page, mailhelp)
    page.goto(f"{mailhelp.url}/einstellungen")
    return page.locator("#settings-search"), page.locator("#settings-live-results"), page.locator(
        "#settings-live-status")


def test_matches_appear_while_typing_and_clearing_removes_them(page, mailhelp):
    field, results, status = open_settings(page, mailhelp)
    field.press_sequentially("Z")
    expect(results.locator("li").first).to_be_visible()
    field.fill("Zeitzone")
    expect(results.locator("li a").first).to_have_text("Zeitzone")
    expect(status).to_have_text(re.compile(r"^\d+ Treffer$"))
    assert page.url.endswith("/einstellungen")  # no history entry per letter
    assert audit(page, "settings-live-53-" + page.device, page.mobile) == []
    field.fill("")
    expect(results).to_be_hidden()
    expect(status).to_have_text("")
    field.fill("niemandkenntdieseoption")
    expect(status).to_have_text("Keine Einstellung gefunden.")
    field.fill("Zeitzone")
    field.press("Enter")
    page.wait_for_url(re.compile(r"suche=Zeitzone"))
    expect(page.locator("#einstellung-timezone")).to_be_visible()
    assert page.errors == []


def test_a_late_answer_never_replaces_the_newer_search(page, mailhelp):
    field, results, _status = open_settings(page, mailhelp)
    held = []

    def hold_first(route):
        if "suche=Telegram" in route.request.url and not held:
            held.append(route)
            return
        route.continue_()

    page.route(API, hold_first)
    field.fill("Telegram")
    for _attempt in range(200):  # wait until the first request is held back
        if held:
            break
        page.wait_for_timeout(10)
    assert held
    field.fill("Zeitzone")
    expect(results.locator("li a").first).to_have_text("Zeitzone")
    held[0].fulfill(status=200, content_type="application/json", body=json.dumps(
        {"query": "Telegram", "total": 1, "all": "/einstellungen?suche=Telegram",
         "results": [{"id": "x", "label": "Veraltet", "area": "A", "summary": "B", "key": None,
                      "href": "/", "path": "Eigene Seite"}]}))
    page.wait_for_timeout(200)
    expect(results.locator("li a").first).to_have_text("Zeitzone")


def test_an_error_keeps_the_form_search_usable(page, mailhelp):
    field, results, status = open_settings(page, mailhelp)
    page.route(API, lambda route: route.fulfill(status=500, body="kaputt"))
    field.fill("Zeitzone")
    expect(status).to_contain_text("„Suchen“ funktioniert weiterhin")
    expect(results).to_be_hidden()
    page.unroute(API)
    page.get_by_role("button", name="Suchen").click()
    expect(page.locator("#einstellung-timezone")).to_be_visible()


def test_results_are_visible_within_300_ms_in_95_percent_of_100_searches(page, mailhelp):
    if page.device != "desktop":
        pytest.skip("Die Laufzeit wird einmal auf der Referenzansicht gemessen")
    field, results, _status = open_settings(page, mailhelp)
    terms = ["Zeitzone", "Aufbewahrung", "Telegram Benutzer", "KI", "Abruf", "Postfach", "Protokoll",
             "Zeitlimit imap", "Bild", "Kosten"]
    durations = []
    for number in range(100):
        term = terms[number % len(terms)]
        field.fill("")
        expect(results).to_be_hidden()
        started = time.perf_counter()
        field.fill(term)
        expect(results.locator("li").first).to_be_visible()
        expect(results).to_have_attribute("data-query", term)
        durations.append((time.perf_counter() - started) * 1000)
    fast = sum(duration <= 300 for duration in durations)
    print(f"LIVE_SEARCH_LATENCY {{\"runs\": 100, \"within_300_ms\": {fast}, "
          f"\"median_ms\": {sorted(durations)[50]:.1f}, \"p95_ms\": {sorted(durations)[94]:.1f}}}")
    assert fast >= 95
