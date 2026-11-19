"""Browser checks against the delivered pages and a real, temporary lead store.

Manual Playwright check of landing/ (7.9.7: moved from the landing release); run from the repository
root with ``python ui_tests/landing/landing_browser_check.py``. Screenshots go to landing/.checks.
"""
import sys
import tempfile
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2] / "landing"
sys.path.insert(0, str(ROOT))
import lead_service  # noqa: E402 - from landing/, which is not a package

CSP = ("default-src 'none'; script-src 'self' https://www.googletagmanager.com; style-src 'self'; font-src 'self'; "
       "img-src 'self' https://*.google-analytics.com https://www.googletagmanager.com; media-src 'self'; "
       "connect-src 'self' https://*.google-analytics.com https://*.analytics.google.com "
       "https://www.googletagmanager.com; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
OVERFLOW = ("() => [...document.querySelectorAll('body *')].filter(e=>e.getBoundingClientRect().right>innerWidth+1)"
            ".map(e=>[e.tagName,e.className,e.getBoundingClientRect().right]).slice(0,6)")
FITS = "document.documentElement.scrollWidth<=innerWidth"


class Preview(lead_service.LeadHandler, SimpleHTTPRequestHandler):
    def do_GET(self):
        SimpleHTTPRequestHandler.do_GET(self)

    def end_headers(self):
        self.send_header("Content-Security-Policy", CSP)
        super().end_headers()


def check_content(page, language):
    assert page.locator("html").get_attribute("lang") == language
    assert "mailhelp" not in page.content().lower()
    story = page.locator(".story-picture img")
    assert "/assets/workspace-screen-v2." in story.get_attribute("src")
    assert "/assets/workspace-screen-v2-small." in story.get_attribute("srcset")
    assert page.locator(f'a.demo-link[href="https://demo.inboxstride.de/{language}/"]').count() == 3
    demo = "Demo ausprobieren" if language == "de" else "Try the live demo"
    assert page.locator(".hero-actions .demo-link").inner_text().strip() == demo
    assert page.locator(".everyday-item").count() == 4
    assert page.locator(".faq-list details").count() == 7
    expect(page.locator(".everyday")).to_contain_text(
        "Für den Start vorgesehen" if language == "de" else "Planned for launch")
    expect(page.get_by_role("heading", level=1)).to_be_visible()
    hero_box = page.locator(".hero-image").bounding_box()
    assert hero_box["height"] <= hero_box["width"] * 1.05


def check_form(page, store, email, language):
    page.locator(".hero-actions .interest-link").click()
    expect(page.locator("#email")).to_be_in_viewport()
    page.locator("#email").fill(email)
    page.locator('input[name="consent"]').check()
    with page.expect_response("**/api/interest") as response:
        page.locator('button[type="submit"]').click()
    assert response.value.status == 200
    expect(page.locator(".form-status")).to_contain_text("Danke" if language == "de" else "Thank you")
    assert any(record["email"] == email for _, record in store.records())


def check_legal(page, origin, case):
    language = case[2]
    for legal in (["/impressum/", "/datenschutz/"] if language == "de" else ["/en/legal/", "/en/privacy/"]):
        page.goto(origin + legal)
        assert page.locator("html").get_attribute("lang") == language
        expect(page.get_by_role("main")).to_contain_text("Hartmann")
        assert page.evaluate(FITS), (*case, legal, page.evaluate(OVERFLOW))
        page.locator(".language a:not(.active)").click()
        assert page.locator("html").get_attribute("lang") != language


def check_page(browser, origin, store, screenshots, case, path):
    """One engine, viewport and language: content, form, screenshot and legal pages."""
    engine, width, language = case
    mobile = width < 700
    context = browser.new_context(viewport={"width": width, "height": {1440: 1000, 390: 844, 320: 740}[width]},
                                  locale="de-DE" if language == "de" else "en-GB", is_mobile=mobile, has_touch=mobile)
    page = context.new_page()
    errors, external = [], []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("request", lambda request: None if request.url.startswith((origin, "blob:" + origin))
            else external.append(request.url))
    page.goto(origin + path)
    page.locator("[data-consent-reject]").click()
    page.evaluate("document.fonts.ready")
    check_content(page, language)
    assert page.evaluate(FITS), (*case, "overflow")
    check_form(page, store, f"{engine}-{width}-{language}@example.test", language)
    assert not external and not errors, (external, errors)
    # Get screenshots of fully loaded imagery at both responsive sizes.
    page.locator(".story-picture").scroll_into_view_if_needed()
    page.wait_for_function("() => [...document.images].every(i=>i.complete && i.naturalWidth>0)")
    page.evaluate("scrollTo({top:0,behavior:'instant'})")
    page.screenshot(path=str(screenshots / f"{engine}-{width}-{language}.png"), full_page=True)
    check_legal(page, origin, case)
    context.close()


def failing_route(mode):
    def fail(route):
        if mode == "offline":
            route.abort()
        elif mode == "html":
            route.fulfill(status=429, content_type="text/html", body="<h1>Slow down</h1>")
        elif mode == "null":
            route.fulfill(status=200, content_type="application/json", body="null")
        else:
            route.fulfill(status=400, json={"ok": False, "message": "Please check your email address."})
    return fail


def check_failures(browser, origin):
    """Network, HTML rate-limit and malformed JSON responses stay understandable."""
    context = browser.new_context()
    page = context.new_page()
    page.goto(origin + "/en/")
    page.locator("[data-consent-reject]").click()
    for mode in ["offline", "html", "null", "invalid"]:
        page.route("**/api/interest", failing_route(mode))
        page.locator("#email").fill("retry@example.test")
        page.locator('input[name="consent"]').check()
        page.locator('button[type="submit"]').click()
        expect(page.locator(".form-status.error")).to_be_visible()
        expect(page.locator("#email")).to_have_value("retry@example.test")
        expect(page.locator('button[type="submit"]')).to_be_enabled()
        page.unroute("**/api/interest")
    context.close()


def check_without_javascript(browser, origin, engine):
    """The form works with JavaScript switched off."""
    context = browser.new_context(java_script_enabled=False)
    page = context.new_page()
    page.goto(origin + "/")
    page.locator("#email").fill(f"{engine}-nojs@example.test")
    page.locator('input[name="consent"]').press("Space")
    expect(page.locator('input[name="consent"]')).to_be_checked()
    page.locator('button[type="submit"]').press("Enter")
    page.wait_for_url(origin + "/danke/")
    expect(page.get_by_role("heading", level=1)).to_contain_text("Danke")
    context.close()


def main():
    screenshots = ROOT / ".checks"
    screenshots.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        store = lead_service.LeadStore(Path(temporary))
        server = lead_service.LeadServer(("127.0.0.1", 0), store, set())
        server.RequestHandlerClass = partial(Preview, directory=str(ROOT / "public"))
        origin = "http://127.0.0.1:" + str(server.server_address[1])
        server.origins.add(origin)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as runtime:
                for engine in ["chromium", "webkit"]:
                    browser = getattr(runtime, engine).launch(**({"channel": "chrome"} if engine == "chromium" else {}))
                    for width in [1440, 390, 320]:
                        for language, path in [("de", "/"), ("en", "/en/")]:
                            check_page(browser, origin, store, screenshots, (engine, width, language), path)
                    check_failures(browser, origin)
                    check_without_javascript(browser, origin, engine)
                    browser.close()
            print("BROWSER_CHECKS_OK: Chromium + WebKit, DE + EN, 1440 / 390 / 320 px, live form, legal pages, "
                  "network failures, no-JS fallback")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(5)


if __name__ == "__main__":
    main()
