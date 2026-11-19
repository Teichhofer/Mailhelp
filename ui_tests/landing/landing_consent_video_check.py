"""Consent/video checks with a simulated GTM; no real analytics traffic.

Manual Playwright check of landing/ (7.9.7: moved from the landing release); run from the repository
root with ``python ui_tests/landing/landing_consent_video_check.py``. Screenshots go to landing/.checks.
"""
import json
import sys
import threading
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from landing_browser_check import FITS, OVERFLOW, ROOT, Preview  # noqa: E402 - sibling script, not a package

VIDEO = 'document.querySelector("video")'
GTM = 'https://www.googletagmanager.com/**'


class QuietPreview(Preview):
    def copyfile(self, source, outputfile):
        try:
            super().copyfile(source, outputfile)
        except (ConnectionResetError, BrokenPipeError):
            pass  # Native video playback may stop an in-flight file request.


def consent_entries(page):
    data = page.evaluate('window.dataLayer.map(x=>x.length===undefined?x:Array.from(x))')
    entries = [x for x in data if isinstance(x, list)]
    defaults = [x for x in entries if x[:2] == ['consent', 'default']][0][2]
    updates = [x for x in entries if x[:2] == ['consent', 'update']][0][2]
    return defaults, updates


def check_video(page, lang, width):
    page.locator('video').scroll_into_view_if_needed()
    page.evaluate(f'{VIDEO}.load()')
    page.wait_for_function(f'() => {VIDEO}.readyState>=2')
    assert 9 < page.evaluate(f'{VIDEO}.duration') < 11
    page.evaluate(f'{VIDEO}.muted=true;{VIDEO}.play()')
    page.wait_for_function(f'() => {VIDEO}.currentTime>0.1')
    page.evaluate(f'{VIDEO}.pause()')
    if width == 1440:
        page.locator('.film').screenshot(path=str(ROOT / '.checks' / f'video-{lang}.png'))


def check_choices(page, context, origin, external):
    """Refusal survives a reload; consent loads Google once per page; withdrawal removes its cookies."""
    panel = page.locator('[data-consent-panel]')
    page.locator('[data-consent-reject]').click()
    expect(panel).to_be_hidden()
    page.reload()
    expect(panel).to_be_hidden()
    assert external == []
    page.locator('[data-consent-settings]').click()
    page.locator('[data-consent-accept]').click()
    page.wait_for_function('() => window.mockGtmLoads===1')
    assert len(external) == 1
    defaults, updates = consent_entries(page)
    assert defaults['analytics_storage'] == 'denied'
    assert updates['analytics_storage'] == 'granted'
    assert all(updates[k] == 'denied' for k in ['ad_storage', 'ad_user_data', 'ad_personalization'])
    assert page.evaluate('window["ga-disable-G-ZQP60GV6NS"]') is False
    page.locator('[data-consent-settings]').click()
    page.locator('[data-consent-close]').click()
    assert len(external) == 1
    page.reload()
    page.wait_for_function('() => window.mockGtmLoads===1')
    assert len(external) == 2
    context.add_cookies([{'name': '_ga', 'value': 'synthetic', 'url': origin}])
    page.locator('[data-consent-settings]').click()
    with page.expect_navigation():
        page.locator('[data-consent-reject]').click()
    assert len(external) == 2
    assert not any(c['name'].startswith('_ga') for c in context.cookies())
    assert page.evaluate('window["ga-disable-G-ZQP60GV6NS"]') is True


def check_consent(browser, origin, engine, lang, path, width):
    context = browser.new_context(viewport={'width': width, 'height': 900})
    external, media, errors = [], [], []

    def mock(route):
        external.append(route.request.url)
        route.fulfill(status=200, content_type='application/javascript',
                      body='window.mockGtmLoads=(window.mockGtmLoads||0)+1;')
    context.route(GTM, mock)
    page = context.new_page()
    page.on('request', lambda request: media.append(request.url) if '.mp4' in request.url else None)
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(origin + path)
    panel = page.locator('[data-consent-panel]')
    expect(panel).to_be_visible()
    assert external == [] and media == []
    assert page.locator('video').get_attribute('preload') == 'none'
    assert page.locator('video').get_attribute('autoplay') is None
    assert page.evaluate(FITS), page.evaluate(OVERFLOW)
    box = panel.bounding_box()
    assert box['x'] >= 0 and box['x'] + box['width'] <= width + 1
    if width == 320:
        page.screenshot(path=str(ROOT / '.checks' / f'{engine}-consent-{lang}.png'))
    check_choices(page, context, origin, external)
    if engine == 'chromium':
        check_video(page, lang, width)
    assert errors == [], errors
    context.close()


def check_invalid_choices(browser, origin):
    """Invalid/obsolete choices must never start Google."""
    for value in ['broken-json', quote(json.dumps({'revision': 'old', 'choice': 'analytics', 'at': 1}))]:
        context = browser.new_context()
        context.add_cookies([{'name': 'inboxstride_consent', 'value': value, 'url': origin}])
        blocked = []
        context.route(GTM, lambda route, blocked=blocked: (blocked.append(route.request.url), route.abort()))
        page = context.new_page()
        page.goto(origin)
        expect(page.locator('[data-consent-panel]')).to_be_visible()
        assert blocked == []
        context.close()


def check_without_javascript(browser, origin):
    """No JS: no tags, no unusable settings control, native video remains."""
    context = browser.new_context(java_script_enabled=False)
    page = context.new_page()
    page.goto(origin)
    expect(page.locator('[data-consent-settings]')).to_be_hidden()
    assert page.locator('video[controls]').count() == 1
    context.close()


def main():
    (ROOT / '.checks').mkdir(exist_ok=True)
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietPreview, directory=str(ROOT / 'public')))
    origin = 'http://127.0.0.1:' + str(server.server_port)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as runtime:
            for engine in ['chromium', 'webkit']:
                browser = getattr(runtime, engine).launch(**({'channel': 'chrome'} if engine == 'chromium' else {}))
                for lang, path in [('de', '/'), ('en', '/en/')]:
                    for width in [320, 1440]:
                        check_consent(browser, origin, engine, lang, path, width)
                check_invalid_choices(browser, origin)
                check_without_javascript(browser, origin)
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
    print('CONSENT_VIDEO_OK: Chromium/WebKit, DE/EN, mobile/desktop, opt-in, refusal, reload, withdrawal, '
          'invalid consent, no-JS; Chromium MP4 playback.')


if __name__ == '__main__':
    main()
