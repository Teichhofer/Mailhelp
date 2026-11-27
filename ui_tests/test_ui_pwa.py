"""Installable app: service worker, shell cache and offline page."""
from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect

from checks import audit
from conftest import COVERAGE, DEVICES, Page, item, sign_in, wait_until

SHELL = ["/offline.html", "/offline-en.html", "/static/app.css", "/static/icon-192.png", "/static/icon-512.png"]


def new_page(browser, device, **options):
    context = browser.new_context(locale="de-DE", timezone_id="Europe/Berlin",
                                  **DEVICES[device], **options)
    return Page(context.new_page(), device)


def wait_for_worker(page, locale: str | None = None) -> None:
    """Wait (bounded) until the worker, optionally the one for ``locale``, is activated and controls the page.

    8.7.13 (Linux browser suite): ``registration.active`` already names a worker that is still activating, and
    ``evaluate(serviceWorker.ready)`` waits without a time limit. Going offline before the activation ended
    left the navigation waiting for the worker until the context was closed. The condition is async, so it
    goes through ``wait_until`` (``wait_for_function`` would count its promise as true at once).
    """
    wait_until(page, """locale => navigator.serviceWorker.getRegistration().then(r => {
      const worker = r && r.active, controller = navigator.serviceWorker.controller;
      const matches = script => !locale || new URL(script.scriptURL).searchParams.get('lang') === locale;
      return !!worker && worker.state === 'activated' && matches(worker) && !!controller && matches(controller);
    })""", locale)


@pytest.mark.smoke
def test_installed_app_shows_the_offline_page_and_caches_no_data(browser, mailhelp):
    for device in DEVICES:
        page = new_page(browser, device, service_workers="allow")
        try:
            sign_in(page, mailhelp)
            wait_for_worker(page)
            page.reload()
            cached = page.evaluate("""caches.keys().then((keys) => Promise.all(keys.map((key) =>
                caches.open(key).then((cache) => cache.keys())
                .then((requests) => requests.map((request) => new URL(request.url).pathname)))))""")
            assert [sorted(paths) for paths in cached] == [sorted(SHELL)]
            assert page.locator("link[rel=manifest]").get_attribute("href") == "/manifest.webmanifest"
            page.context.set_offline(True)
            page.page.goto(f"{mailhelp.url}/status")
            expect(page.get_by_role("heading", name="PC nicht erreichbar")).to_be_visible()
            assert audit(page, f"offline-{device}", page.mobile) == []
            page.context.set_offline(False)
            page.get_by_role("link", name="Erneut versuchen").click()
            expect(page.get_by_role("heading", name="Offene Entscheidungen")).to_be_visible()
            page.errors[:] = [error for error in page.errors if "ERR_INTERNET_DISCONNECTED" not in error]
            assert page.errors == []
        finally:
            page.context.close()


def test_a_failed_worker_registration_is_harmless(browser, mailhelp):
    page = new_page(browser, "desktop", service_workers="allow")
    try:
        page.context.route("**/sw.js*", lambda route: route.fulfill(status=404, body="nein"))
        sign_in(page, mailhelp)
        page.wait_for_timeout(300)
        assert page.evaluate("navigator.serviceWorker.getRegistration().then((r) => r === undefined)")
        page.errors[:] = [error for error in page.errors if "404" not in error and "sw.js" not in error]
        assert page.errors == []
    finally:
        page.context.close()


def test78_real_worker_switches_the_offline_language_with_the_browser_choice(browser, mailhelp):
    """The worker registered by a page in a language serves the offline page in that language.

    8.7.13: one fresh browser context per language, whose first worker is the one of that language. Replacing
    the running worker inside one context (a browser mechanism, not Mailhelp code) stalled Linux Chrome under
    Playwright now and then: the new worker waited for the debugger and the next navigation never finished.
    """
    for locale, heading in [("en", "Computer unreachable"), ("de", "PC nicht erreichbar")]:
        # The login pages are German; their worker would be replaced by the one of the chosen language, so
        # the session moves into a context whose first page already has that language.
        login = new_page(browser, "desktop", service_workers="block")
        try:
            sign_in(login, mailhelp)
            session = login.context.storage_state()
        finally:
            login.context.close()
        page = new_page(browser, "desktop", service_workers="allow", storage_state=session)
        try:
            page.goto(mailhelp.url + "/" + locale + "/")
            wait_for_worker(page, locale)
            page.reload()
            wait_for_worker(page, locale)
            expect(page.locator("html")).to_have_attribute("lang", locale)
            page.context.set_offline(True)
            page.page.goto(mailhelp.url + "/status")
            expect(page.get_by_role("heading", name=heading)).to_be_visible()
            page.context.set_offline(False)
            page.errors[:] = [error for error in page.errors if "ERR_INTERNET_DISCONNECTED" not in error]
            assert page.errors == []
        finally:
            page.context.close()


# The worker's handlers run in a test page with stubbed worker globals, so that
# every branch can be triggered and its block coverage measured.
HARNESS = """<!doctype html><html><body><script>
window.handlers = {};
window.addEventListener = (type, handler) => { window.handlers[type] = handler; };
window.skipWaiting = () => Promise.resolve("skipped");
window.clients = { claim: () => Promise.resolve("claimed") };
window.respond = (handler, request) => new Promise((resolve) => {
  let responded = false;
  handler({ request, respondWith: (promise) => { responded = true; resolve(promise); } });
  if (!responded) resolve("network");
});
window.navigation = (url) => { const request = new Request(url);
  Object.defineProperty(request, "mode", { value: "navigate" }); return request; };
</script><script src="/sw.js"></script></body></html>"""


def test78_english_worker_keeps_push_neutral_and_offline_actions_unreplayed(browser, mailhelp):
    page = new_page(browser, "desktop", service_workers="block")
    try:
        url = mailhelp.url + "/__sw-en?lang=en"
        page.page.route(url, lambda route: route.fulfill(body=HARNESS, content_type="text/html"))
        page.goto(url)
        result = page.evaluate("""async () => {
          const waits = [], shown = [];
          const event = {waitUntil: promise => waits.push(promise)};
          handlers.install(event); await Promise.all(waits);
          clients.matchAll = () => Promise.resolve([]);
          self.registration = {showNotification: (title, options) => {
            shown.push({title, body:options.body, data:options.data}); return Promise.resolve();}};
          for (const tag of Object.keys(NOTIFICATIONS_EN)) {
            const done = [];
            handlers.push({data:{json:()=>({tag,body:'PRIVATE SUBJECT',url:'https://foreign.test/'})},
              waitUntil:promise=>done.push(promise)});
            await Promise.all(done);
          }
          return {shown,offline:OFFLINE};
        }""")
        assert result["offline"] == "/offline-en.html"
        assert len(result["shown"]) == 7
        assert result["shown"][0]["body"] == "New tasks or events are ready for your decision."
        assert all("PRIVATE SUBJECT" not in row["body"] and row["title"] == "Mailhelp" for row in result["shown"])
        page.context.set_offline(True)
        offline = page.evaluate("""async () => {
          const response=await respond(handlers.fetch,navigation('/status'));
          return {html:await response.text(),post:await respond(handlers.fetch,new Request('/aktion',{method:'POST'}))};
        }""")
        assert 'lang="en"' in offline["html"] and "Computer unreachable" in offline["html"]
        assert offline["post"] == "network"
    finally:
        page.context.close()


def test_service_worker_rules(browser, mailhelp):
    page = new_page(browser, "desktop", service_workers="block")
    try:
        page.page.route(f"{mailhelp.url}/__sw",
                        lambda route: route.fulfill(body=HARNESS, content_type="text/html"))
        page.page.goto(f"{mailhelp.url}/__sw")
        result = page.evaluate("""async () => {
          await caches.open("mailhelp-alt");
          await caches.open("mailhelp-shell-v3");
          await caches.open("mailhelp-shell-v4");
          const waits = [];
          const event = { waitUntil: (promise) => waits.push(promise) };
          handlers.install(event);
          handlers.activate(event);
          const installed = await Promise.all(waits);
          const keys = await caches.keys();
          const fetchHandler = handlers.fetch;
          const post = await respond(fetchHandler, new Request("/aktion", { method: "POST" }));
          const foreign = await respond(fetchHandler, new Request("https://example.test/x"));
          const data = await respond(fetchHandler, new Request("/api/stand"));
          const cachedShell = await respond(fetchHandler, new Request("/static/app.css"));
          await caches.delete(CACHE);
          const uncachedShell = await respond(fetchHandler, new Request("/static/app.css"));
          const page = await respond(fetchHandler, navigation("/health"));
          return { installed, keys, post, foreign, data, cache: CACHE,
                   cachedShell: cachedShell.status, uncachedShell: uncachedShell.status,
                   page: page.status };
        }""")
        assert result["installed"] == ["skipped", "claimed"]
        # Versioned by the shell files (regression: a fixed "v5" kept an outdated stylesheet cached).
        assert re.fullmatch(r"mailhelp-shell-[0-9a-f]{16}", result["cache"])
        assert result["keys"] == [result["cache"]]
        assert (result["post"], result["foreign"], result["data"]) == ("network",) * 3
        assert (result["cachedShell"], result["uncachedShell"], result["page"]) == (200, 200, 200)
        page.context.set_offline(True)
        offline = page.evaluate("""async () => {
          const cache = await caches.open("mailhelp-shell-v3");
          await cache.put("/offline.html", new Response("offline-seite"));
          const response = await respond(handlers.fetch, navigation("/status"));
          return response.text(); }""")
        assert offline == "offline-seite"
    finally:
        page.context.close()
    assert "sw.js" in COVERAGE.counts


def test_push_notifications_show_fixed_texts_and_open_the_app(browser, mailhelp):
    page = new_page(browser, "desktop", service_workers="block")
    try:
        page.page.route(f"{mailhelp.url}/__sw",
                        lambda route: route.fulfill(body=HARNESS, content_type="text/html"))
        page.page.goto(f"{mailhelp.url}/__sw")
        result = page.evaluate("""async () => {
          const shown = [], opened = [], navigated = [], messages = [];
          clients.matchAll = () => Promise.resolve([{postMessage: (data) => messages.push(data)}]);
          self.registration = { showNotification: (title, options) => {
            shown.push([title, options]); return Promise.resolve(); } };
          const push = async (data) => { const waits = [];
            handlers.push({ data, waitUntil: (promise) => waits.push(promise) }); await Promise.all(waits); };
          const json = (value) => ({ json: () => value });
          await push(json({ tag: "briefing", body: "Privater Betreff" }));
          await push(json({ tag: "constructor" }));
          await push(json({ tag: "unbekannt" }));
          await push(null);
          for (const tag of ["decisions", "daily_briefing", "action_results", "system_errors", "test"]) {
            await push(json({tag}));
          }
          const source = {postMessage: data => messages.push(data)};
          if (handlers.message) {
            handlers.message({}); handlers.message({data:{}});
            handlers.message({data:{type:"mailhelp-worker-status"}});
            handlers.message({data:{type:"mailhelp-worker-status"},source});
          }
          let windows = [];
          clients.matchAll = () => Promise.resolve(windows);
          clients.openWindow = (url) => { opened.push(url); return Promise.resolve(null); };
          const click = async (data) => { const waits = []; let closed = false;
            handlers.notificationclick({ notification: { data, close: () => { closed = true; } },
                                         waitUntil: (promise) => waits.push(promise) });
            await Promise.all(waits); return closed; };
          const closed = await click({ kind: "briefing" });
          windows = [{ url: "https://other.example/", focus: () => Promise.reject() },
                     { url: location.origin + "/status",
                       focus() { return Promise.resolve({ navigate: (url) => { navigated.push(url); } }); } }];
          await click(undefined);
          windows = [{ url: location.origin + "/", focus: () => Promise.resolve({
                       navigate: () => Promise.reject(new TypeError("uncontrolled")) }) }];
          await click({ kind: "__proto__" });
          return { shown, opened, navigated, closed, messages };
        }""")
        bodies = [(title, options["body"], options["tag"], options["data"]["kind"])
                  for title, options in result["shown"]]
        expected = [
            ("briefing", "Dein Tagesüberblick ist verfügbar."),
            *( [("information", "Neue Informationen in Mailhelp.")] * 3 ),
            ("decisions", "Neue Aufgaben oder Termine zur Entscheidung."),
            ("daily_briefing", "Dein Tagesüberblick ist verfügbar."),
            ("action_results", "Ein Aktionsergebnis ist in Mailhelp verfügbar."),
            ("system_errors", "Ein Betriebsproblem benötigt deine Aufmerksamkeit."),
            ("test", "Test: Web-Push funktioniert auf diesem Gerät.")]
        assert bodies == [("Mailhelp", text, "mailhelp-" + kind, kind) for kind, text in expected]
        assert result["messages"][-1]["type"] == "mailhelp-worker-status"
        assert result["closed"] and result["navigated"] == ["/"]
        assert result["opened"] == ["/briefing", "/"]
        assert page.errors == []
    finally:
        page.context.close()


@pytest.mark.smoke
def test_an_action_sent_offline_is_neither_executed_nor_replayed_later(browser, mailhelp):
    """Planung 4.1, Schritt 9.13: the worker never stores or repeats a confirmation."""
    from tests.scenarios.web_scenario import mail_id
    page = new_page(browser, "desktop", service_workers="allow")
    try:
        sign_in(page, mailhelp)
        wait_for_worker(page)
        page.reload()
        button = item(page, f"#v-{mail_id(1)}-elternabend").get_by_role("button", name="Im Kalender anlegen")
        page.context.set_offline(True)
        button.click()
        page.wait_for_timeout(2500)  # longer than the undo delay of the test server
        page.context.set_offline(False)
        page.page.goto(mailhelp.url)
        expect(page.get_by_role("heading", name="Offene Entscheidungen")).to_be_visible()
        page.wait_for_timeout(500)
        expect(page.locator(f"#v-{mail_id(1)}-elternabend")).to_have_count(1)
        assert mailhelp.writer.created == []
        assert (mailhelp.store.load("command-inbox") or {"entries": []})["entries"] == []
        assert not any("Angelegt" in text for text in mailhelp.telegram.sent)
        page.errors[:] = [error for error in page.errors if "ERR_INTERNET_DISCONNECTED" not in error]
        assert page.errors == []
    finally:
        page.context.close()
