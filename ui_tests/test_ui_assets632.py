"""The first navigation after an update must escape an older worker's shell cache."""
import hashlib

from playwright.sync_api import expect

from conftest import DEVICES, Page, sign_in


def test_regression_v632_first_navigation_uses_new_css_with_old_worker(browser, mailhelp):
    app = mailhelp.site.app
    css = app.assets["app.css"]

    def stylesheet(content):
        app.assets["app.css"] = content
        if hasattr(app, "asset_urls"):
            app.asset_urls["app.css"] = "/static/app.css?v=" + hashlib.sha256(content).hexdigest()[:16]

    stylesheet(css + b"\n:root { --v632-marker: old; } .swipeable article.card { touch-action:auto; }")
    context = browser.new_context(service_workers="allow", **DEVICES["mobile"])
    page = Page(context.new_page(), "mobile")
    try:
        sign_in(page, mailhelp)
        page.evaluate("navigator.serviceWorker.ready.then(() => true)")
        page.reload()
        marker = "getComputedStyle(document.documentElement).getPropertyValue('--v632-marker').trim()"
        assert page.evaluate(marker) == "old"
        # The old controller handles the first navigation, before a new worker can take over.
        stylesheet(css + b"\n:root { --v632-marker: new; }")
        page.reload()
        assert page.evaluate(marker) == "new"
        expect(page.locator(".swipeable article.card").first).to_have_css("touch-action", "pan-y pinch-zoom")
    finally:
        page.context.close()
