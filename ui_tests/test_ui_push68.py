"""Push diagnosis and recovery in real pages with synthetic browser/provider APIs."""

import json

import pytest
from playwright.sync_api import expect

from conftest import sign_in
from mailhelp.config.notifications import NotificationSettings
from mailhelp.notifications.webpush import PushService
from push_browser_fakes68 import PUSH_STUB
from tests.fakes.push68 import subscription


def open_push(page, mailhelp, script=""):
    push = PushService(mailhelp.store, mailhelp.auth, "mailto:ops@example.test", lambda **_: None)
    mailhelp.site.experience.push = push
    mailhelp.site.archive.configuration.active.notifications = NotificationSettings(
        categories={"decisions": ["web_push"]}
    )
    page.add_init_script(
        PUSH_STUB
        + (
            'Object.defineProperty(navigator,"standalone",{configurable:true,value:true});'
            if page.device == "mobile"
            else ""
        )
        + script
    )
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/einstellungen?bereich=benachrichtigungen")
    return push


def activate(page):
    page.evaluate("json => window.__push.subscribed = window.__subscription(json)", subscription())
    page.locator("#push-enable").click()
    expect(page.locator("#push-enable")).to_be_enabled()
    expect(page.locator("#push-status")).to_have_text("Push ist auf diesem Gerät aktiviert.")


def test_regression_foreign_server_key_replaces_existing_subscription(page, mailhelp):
    if page.device != "desktop":
        return
    open_push(page, mailhelp)
    activate(page)
    page.evaluate("window.__push.existing.options.applicationServerKey = new Uint8Array(65).buffer")
    page.locator("#push-enable").click()
    expect(page.locator("#push-enable")).to_be_enabled()
    expect(page.locator("#push-status")).to_have_text("Push ist auf diesem Gerät aktiviert.")
    assert page.evaluate("window.__push.unsubscribed") == 1


@pytest.mark.parametrize(
    "script,text",
    [
        ('Object.defineProperty(window,"isSecureContext",{value:false});', "nicht per HTTPS"),
        ('Object.defineProperty(navigator,"userAgent",{value:"iPhone"});', "Home-Bildschirm"),
        (
            'Object.defineProperty(navigator,"platform",{value:"MacIntel"});'
            'Object.defineProperty(navigator,"maxTouchPoints",{value:5});',
            "Home-Bildschirm",
        ),
        ("delete window.PushManager;", "unterstützt kein Web-Push"),
        ("delete navigator.serviceWorker; delete Navigator.prototype.serviceWorker;", "unterstützt kein Web-Push"),
        ('window.__push.permission="denied";', "blockiert"),
        ('window.__push.permission="default";', "Push aktivieren, um"),
        ("window.__push.registerError=true;", "Hintergrunddienst startet nicht"),
        ("window.__push.hang=true;", "innerhalb von zehn Sekunden"),
    ],
)
def test_first_missing_stage_has_one_action(page, mailhelp, script, text):
    if page.device != "desktop":
        return
    open_push(page, mailhelp, script)
    expect(page.locator("#push-status")).to_contain_text(text, timeout=13000)
    expect(page.locator("[data-push-stage]")).to_have_count(9)
    page.locator("#push-enable").click()
    expect(page.locator("#push-status")).to_contain_text("blockiert" if "default" in script else text, timeout=13000)


def test_ios_installed_app_and_subscription_replacement_failures(page, mailhelp):
    open_push(
        page,
        mailhelp,
        'Object.defineProperty(navigator,"userAgent",{value:"iPhone"});'
        'Object.defineProperty(navigator,"standalone",{value:true});',
    )
    activate(page)
    page.evaluate("window.__push.existing.options = {}; window.__push.remove = false;")
    page.locator("#push-enable").click()
    expect(page.locator("#push-status")).to_contain_text("alte Abonnement konnte nicht")
    page.evaluate("window.__push.remove=true; window.__push.subscribeError=true;")
    page.locator("#push-enable").click()
    expect(page.locator("#push-status")).to_contain_text("Browser-Abonnement konnte nicht angelegt")
    page.evaluate("window.__push.subscribeError=false;")
    activate(page)
    page.evaluate("window.__push.remove=false;")
    page.locator("#push-disable").click()
    expect(page.locator("#push-status")).to_contain_text("Am Server deaktiviert")
    page.evaluate(
        "window.__pushMessage(null);window.__pushMessage({});"
        'window.__pushMessage({type:"mailhelp-push-received",kind:"test"});'
    )


@pytest.mark.parametrize(
    "code,text",
    [
        ("provider_rejected", "Vom Anbieter abgelehnt"),
        ("retryable", "vorübergehend"),
        ("rate_limited", "Eine Minute"),
        ("test_stale", "Prüfstand"),
        ("unknown", "Browser-Abonnement konnte nicht"),
        ("accepted", "Warte"),
    ],
)
def test_test_push_outcomes_and_worker_receipt(page, setup_server, code, text):
    if page.device != "desktop":
        return
    mailhelp = setup_server
    open_push(page, mailhelp)
    activate(page)
    page.route("**/api/push/test", lambda route: route.fulfill(json={"code": code, "diagnostic_version": 2}))
    page.locator("#push-test").click()
    if code != "accepted":
        expect(page.locator("#push-status")).to_contain_text(text)
        return
    expect(page.locator("#push-status")).to_contain_text("Warte auf dieses Gerät")
    page.evaluate(
        'window.__pushMessage({type:"other"});'
        'window.__pushMessage({type:"mailhelp-push-received",kind:"decisions"});'
        'window.__pushMessage({type:"mailhelp-push-received",kind:"test"});'
    )
    expect(page.locator("#push-status")).to_contain_text("auf diesem Gerät angekommen")
    # A missing device receipt must not be reported as a visible system notification.
    page.locator("#push-test").click()
    expect(page.locator("#push-status")).to_contain_text("Fokus-Modus", timeout=23000)


@pytest.mark.parametrize(
    "mode,text",
    [
        ("network", "nicht erreichbar"),
        ("401", "Anmeldung abgelaufen"),
        ("403", "Sicherheitsprüfung"),
        ("500", "nicht erreichbar"),
        ("disabled", "nicht eingeschaltet"),
        ("unknown", "Browser-Abonnement konnte nicht"),
    ],
)
def test_activation_api_errors_have_specific_actions(page, mailhelp, mode, text):
    if page.device != "desktop":
        return
    open_push(page, mailhelp)

    def reply(route):
        if mode == "network":
            route.abort()
        else:
            route.fulfill(
                status=int(mode) if mode.isdigit() else 503,
                json={"code": {"403": "csrf_rejected", "disabled": "push_disabled", "unknown": "unknown"}.get(mode)},
            )

    page.route("**/api/push/public-key", reply)
    page.locator("#push-enable").click()
    expect(page.locator("#push-status")).to_contain_text(text)


def test_no_channels_and_server_key_rotation_are_visible(page, mailhelp):
    push = open_push(page, mailhelp)
    activate(page)
    mailhelp.site.archive.configuration.active.notifications.categories.decisions = ["telegram"]
    state = json.loads(page.request.get(mailhelp.url + "/api/push/status").body())
    state["device"].update(rejected=True, last_code="provider_rejected")
    page.route("**/api/push/status", lambda route: route.fulfill(json=state))
    page.reload()
    expect(page.locator('[data-push-stage="9"]')).to_contain_text("Vom Anbieter abgelehnt")
    expect(page.locator("#push-test")).to_be_disabled()
    assert push.public_key


def test_key_length_missing_worker_and_absent_worker_version(page, mailhelp):
    if page.device != "desktop":
        return
    open_push(page, mailhelp)
    activate(page)
    page.evaluate(
        "window.__push.existing.options.applicationServerKey = new Uint8Array(1).buffer;"
        "window.__push.registration.active = null;"
    )
    page.locator("#push-enable").click()
    expect(page.locator("#push-enable")).to_be_enabled()
    expect(page.locator("#push-status")).to_have_text("Push ist auf diesem Gerät aktiviert.")
    assert page.evaluate("window.__push.unsubscribed") == 1
    page.evaluate("delete navigator.serviceWorker; delete Navigator.prototype.serviceWorker;")
    page.locator("#push-enable").click()
    expect(page.locator("#push-status")).to_contain_text("unterstützt kein Web-Push")


def test_receipt_before_provider_response_and_missing_profile_channel(page, setup_server):
    if page.device != "desktop":
        return
    mailhelp = setup_server
    push = open_push(page, mailhelp)
    activate(page)

    def reply(route):
        page.evaluate('window.__pushMessage({type:"mailhelp-push-received",kind:"test"})')
        route.fulfill(json={"code": "accepted", "diagnostic_version": 2})

    page.route("**/api/push/test", reply)
    page.locator("#push-test").click()
    expect(page.locator("#push-status")).to_contain_text("auf diesem Gerät angekommen")
    value = next(iter(mailhelp.store.load("push-subscriptions")["devices"].values()))
    script = (
        "window.__push.existing=window.__subscription(" + json.dumps(value) + ");"
        "window.__push.existing.options.applicationServerKey=Uint8Array.from(atob("
        + json.dumps(push.public_key.replace("-", "+").replace("_", "/"))
        + "),c=>c.charCodeAt(0)).buffer;"
    )
    mailhelp.site.archive.configuration.active.notifications.categories.decisions = []
    page.add_init_script(script)
    page.reload()
    expect(page.locator("#push-status")).to_have_text("Neue Vorschläge werden nicht per Push gemeldet.")


def test_busy_activation_and_redirected_session(page, mailhelp):
    if page.device != "desktop":
        return
    open_push(page, mailhelp)
    routes = []
    page.route("**/api/push/public-key", lambda route: routes.append(route))
    page.locator("#push-enable").click()
    page.wait_for_timeout(100)
    page.locator("#push-enable").dispatch_event("click")
    assert len(routes) == 1
    routes[0].fulfill(status=302, headers={"Location": "/anmelden"})
    expect(page.locator("#push-status")).to_contain_text("Anmeldung abgelaufen")


def test_server_stopped_offering_push_after_page_was_rendered(page, mailhelp):
    if page.device != "desktop":
        return
    open_push(page, mailhelp)
    state = json.loads(page.request.get(mailhelp.url + "/api/push/status").body())
    state["offered"] = False
    page.route("**/api/push/status", lambda route: route.fulfill(json=state))
    page.reload()
    expect(page.locator("#push-status")).to_contain_text("nicht eingeschaltet")
    expect(page.locator('[data-push-stage="1"]')).to_contain_text("✗")
