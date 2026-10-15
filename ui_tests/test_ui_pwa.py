"""Installable app: service worker, shell cache and offline page."""
from __future__ import annotations

from playwright.sync_api import expect

from checks import audit
from conftest import COVERAGE, DEVICES, Page, sign_in

SHELL = ["/offline.html", "/static/app.css", "/static/icon-192.png", "/static/icon-512.png"]


def new_page(browser, device, **options):
    context = browser.new_context(locale="de-DE", timezone_id="Europe/Berlin",
                                  **DEVICES[device], **options)
    return Page(context.new_page(), device)


def test_installed_app_shows_the_offline_page_and_caches_no_data(browser, mailhelp):
    for device in DEVICES:
        page = new_page(browser, device, service_workers="allow")
        try:
            sign_in(page, mailhelp)
            assert page.evaluate("navigator.serviceWorker.ready.then(() => true)")
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
        page.context.route("**/sw.js", lambda route: route.fulfill(status=404, body="nein"))
        sign_in(page, mailhelp)
        page.wait_for_timeout(300)
        assert page.evaluate("navigator.serviceWorker.getRegistration().then((r) => r === undefined)")
        page.errors[:] = [error for error in page.errors if "404" not in error and "sw.js" not in error]
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
          await caches.delete("mailhelp-shell-v5");
          const uncachedShell = await respond(fetchHandler, new Request("/static/app.css"));
          const page = await respond(fetchHandler, navigation("/health"));
          return { installed, keys, post, foreign, data,
                   cachedShell: cachedShell.status, uncachedShell: uncachedShell.status,
                   page: page.status };
        }""")
        assert result["installed"] == ["skipped", "claimed"]
        assert result["keys"] == ["mailhelp-shell-v5"]
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
          const shown = [], opened = [], navigated = [];
          self.registration = { showNotification: (title, options) => { shown.push([title, options]); } };
          const push = async (data) => { const waits = [];
            handlers.push({ data, waitUntil: (promise) => waits.push(promise) }); await Promise.all(waits); };
          const json = (value) => ({ json: () => value });
          await push(json({ tag: "briefing", body: "Privater Betreff" }));
          await push(json({ tag: "constructor" }));
          await push(json({ tag: "unbekannt" }));
          await push(null);
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
          return { shown, opened, navigated, closed };
        }""")
        bodies = [(title, options["body"], options["tag"], options["data"]["kind"])
                  for title, options in result["shown"]]
        assert bodies == [
            ("Mailhelp", "Dein Tagesüberblick ist verfügbar.", "mailhelp-briefing", "briefing"),
            ("Mailhelp", "Neue Entscheidungen warten in Mailhelp.", "mailhelp-decisions", "decisions"),
            ("Mailhelp", "Neue Entscheidungen warten in Mailhelp.", "mailhelp-decisions", "decisions"),
            ("Mailhelp", "Neue Entscheidungen warten in Mailhelp.", "mailhelp-decisions", "decisions")]
        assert result["closed"] and result["navigated"] == ["/offen"]
        assert result["opened"] == ["/briefing", "/offen"]
        assert page.errors == []
    finally:
        page.context.close()
