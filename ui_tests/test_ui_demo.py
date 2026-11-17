"""7.1: the demo in real browsers – start without Telegram, decide, answer, restart, two separate visitors."""
from __future__ import annotations

import re
import socket
import threading
import time
from types import SimpleNamespace

import pytest
from playwright.sync_api import expect

from mailhelp.app import demo
from mailhelp.config import WebSettings
from mailhelp.persistence.storage import JsonStore
from mailhelp.web.demo_site import DEMO_NOTICE
from pages import MASTER, DetailPane
from tests.fakes.demo_questions import asked_dataset

CONFIRM = "In der Demo anlegen"


class Log:
    def event(self, *args, **kwargs):
        return None


@pytest.fixture
def instance(tmp_path):
    yield from serve(tmp_path)


@pytest.fixture
def asked(tmp_path, monkeypatch):
    """7.6: the shipped demo asks nothing; this copy keeps one question with a prepared answer."""
    dataset = asked_dataset(tmp_path / "dataset")
    monkeypatch.setattr(demo, "packaged", lambda: dataset)
    yield from serve(tmp_path)


def serve(tmp_path):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    settings = WebSettings(enabled=True, host="127.0.0.1", port=port, allowed_hosts=[f"127.0.0.1:{port}"])
    stopped = threading.Event()
    with JsonStore(tmp_path / "data" / "demo") as store:
        server, runtimes = demo.create_demo(tmp_path, store, settings, "s" * 40, Log())
        worker = threading.Thread(target=demo._work, args=(runtimes, stopped), daemon=True)
        server.start()
        worker.start()
        try:
            yield SimpleNamespace(url=f"http://127.0.0.1:{port}", runtimes=runtimes)
        finally:
            stopped.set()
            worker.join(timeout=5)
            server.stop()
            runtimes.close()


def start_demo(page, instance):
    page.goto(f"{instance.url}/anmelden")
    expect(page.get_by_role("heading", name="Gerät koppeln")).to_be_visible()
    expect(page.get_by_text("Code per Telegram senden")).to_have_count(0)
    page.get_by_role("button", name="Demo starten").click()
    # The notice is on the login page too; only leaving it shows that the session cookie is set.
    page.wait_for_url(lambda url: "/anmelden" not in url)
    expect(page.get_by_text(DEMO_NOTICE).first).to_be_visible()


def open_card(page, has, text=""):
    """Open the first matching card; on the desktop its actions are in the detail pane.

    ``has`` must also match hidden elements (no role query): the master list hides the actions.
    """
    article = page.locator(f"{MASTER} article.card", has=has).filter(has_text=text).first
    selector = "#" + article.get_attribute("id")
    if getattr(page, "device", "desktop") != "desktop":
        return page.locator(selector)
    article.click(position={"x": 12, "y": 12})
    shown = DetailPane(page).entry(selector)
    expect(shown).to_be_visible()
    return shown


def created(page, instance, title):
    """The history filtered to entries created in the demo; the worker confirms asynchronously."""
    for _ in range(40):
        page.goto(f"{instance.url}/verlauf?status=simulated")
        if title in page.locator("main").inner_text():
            return True
        page.wait_for_timeout(500)
    return False


def confirm_first(page):
    card = open_card(page, page.locator("button", has_text=CONFIRM))
    title = card.locator("h2, h3").first.inner_text()
    with page.expect_navigation():
        card.get_by_role("button", name=CONFIRM).click()
    return title


def test_a_visitor_starts_the_demo_and_confirms_in_the_own_copy(page, instance):
    start_demo(page, instance)
    page.goto(f"{instance.url}/mails")
    expect(page.locator("main")).to_contain_text("Black Week")
    page.goto(f"{instance.url}/")
    title = confirm_first(page)
    assert created(page, instance, title)
    expect(page.locator("main")).to_contain_text("In der Demo angelegt")
    assert page.errors == []


def test_a_prepared_answer_and_a_restart(page, asked):
    if page.device != "desktop":
        pytest.skip("Der Ablauf ist geräteunabhängig; das Wischen prüft der Telefon-Test")
    instance = asked
    start_demo(page, instance)
    prepared = page.get_by_text("In der Demo vorbereitet")
    form = open_card(page, prepared, "16:00").locator("form", has=prepared).first
    expect(form.locator("textarea")).to_have_value(re.compile("16:00 Uhr"))
    form.get_by_role("button", name="Antwort senden").click()
    page.goto(f"{instance.url}/")
    expect(page.locator(f"{MASTER} form", has=prepared)).to_have_count(0, timeout=10000)
    page.get_by_role("link", name="Demo neu starten").first.click()
    page.get_by_role("button", name="Demo jetzt neu starten").click()
    expect(page.locator(f"{MASTER} form", has=page.get_by_text("In der Demo vorbereitet"))).to_have_count(1)
    assert page.errors == []


def test_setup_routes_are_closed_in_the_browser(page, instance):
    start_demo(page, instance)
    page.goto(f"{instance.url}/einstellungen/zugangsdaten")
    expect(page.get_by_text("In der Demo nicht verfügbar")).to_be_visible()


def test_two_browser_contexts_work_separately(browser, instance):
    first, second = browser.new_context(), browser.new_context()
    try:
        one, two = first.new_page(), second.new_page()
        for item in (one, two):
            item.errors = []
            start_demo(item, instance)
        title = confirm_first(one)
        assert created(one, instance, title)
        two.goto(f"{instance.url}/verlauf?status=simulated")
        expect(two.locator("main")).not_to_contain_text(title)
    finally:
        first.close()
        second.close()


def test_the_demo_works_in_webkit_on_a_phone(browser_runtime, instance):
    webkit = browser_runtime.webkit.launch()
    try:
        context = webkit.new_context(**browser_runtime.devices["iPhone 13"])
        page = context.new_page()
        start_demo(page, instance)
        page.goto(f"{instance.url}/mails")
        expect(page.locator("main")).to_contain_text("Black Week")
        page.goto(f"{instance.url}/einrichtung")
        expect(page.get_by_text("In der Demo nicht verfügbar")).to_be_visible()
        context.close()
    finally:
        webkit.close()


def test_the_whole_stack_is_decided_key_after_key_in_under_half_a_minute(page, instance):
    """7.6: every card can be decided at once – 1 confirms and moves on, until nothing is open."""
    if page.device != "desktop":
        pytest.skip("Tastenkürzel gibt es nur auf dem Desktop; das Wischen prüft der Telefon-Test")
    start_demo(page, instance)
    expect(page.locator(".demo-keys-hint")).to_be_visible()
    cards = page.locator(f"{MASTER} article.card")
    total = cards.count()
    assert total >= 6
    started = time.monotonic()
    open_card(page, page.locator("button", has_text=CONFIRM))
    pane = DetailPane(page).root
    for number in range(total):
        # The next card is ready once the pane shows it with its buttons enabled.
        expect(pane.get_by_role("button", name=CONFIRM)).to_be_enabled()
        page.keyboard.press("1")
        expect(cards.nth(number).locator("[data-card-command-status]")).to_have_count(1)
    for _ in range(60):
        page.goto(f"{instance.url}/")
        if page.locator("#inbox-zero").count():
            break
        page.wait_for_timeout(500)
    assert time.monotonic() - started < 30
    expect(page.get_by_role("link", name="Demo zurücksetzen und nochmals testen")).to_be_visible()
    assert page.errors == []
