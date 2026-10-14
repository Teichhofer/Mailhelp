"""Setup forms, safe diagnostics and profiles on desktop, narrow phones and without JS."""
from types import SimpleNamespace as NS

import pytest
from playwright.sync_api import expect
from shared_core import prompt_config

from checks import audit
from conftest import sign_in
from mailhelp.notification_runtime import NotificationRuntime
from mailhelp.setup_runtime import SetupRuntime


@pytest.fixture
def setup_server(mailhelp):
    site = mailhelp.site
    app = NS(settings=site.archive.configuration.active, configuration=site.archive.configuration,
             dialog=mailhelp.dialog, store=mailhelp.store, telegram=mailhelp.telegram, logger=site.logger,
             analyzer=NS(prompts=prompt_config()), calendar=None, todoist=None)
    app.configuration.activate = lambda cfg: setattr(app, "settings", cfg)
    app.settings.web.enabled = True
    site.setup_page.runtime = SetupRuntime(app, site, None, target_probe=lambda *args: None)
    site.notification_runtime = NotificationRuntime(app, site)
    return mailhelp


def test_setup_pages_are_accessible_and_touch_controls_have_48_pixels(page, setup_server):
    sign_in(page, setup_server)
    for path, title in (("/einrichtung", "Einrichtung"), ("/diagnose", "Diagnose"),
                        ("/einstellungen/benachrichtigungen", "Benachrichtigungsprofil"),
                        ("/benachrichtigungen", "Zustellhistorie")):
        page.goto(setup_server.url + path)
        expect(page.get_by_role("heading", name=title, exact=True)).to_be_visible()
        assert audit(page, "setup-" + title + "-" + page.device, page.mobile) == []
        assert page.locator(".setup-page .button").evaluate_all(
            "elements => elements.every(element => element.getBoundingClientRect().height >= 48)")


def test_profile_requires_explicit_review_before_becoming_active(page, setup_server):
    sign_in(page, setup_server)
    page.goto(setup_server.url + "/einstellungen/benachrichtigungen")
    control = page.get_by_label("Ruhezeiten aktivieren", exact=True)
    control.select_option("true")
    control.locator("..").get_by_role("button", name="Entwurf speichern").click()
    expect(page.get_by_role("heading", name="Einrichtung", exact=True)).to_be_visible()
    assert setup_server.site.archive.configuration.active.notifications is None
    page.get_by_label("Gezeigte Änderungen ausdrücklich übernehmen").check()
    page.get_by_role("button", name="Einstellungen übernehmen", exact=True).click()
    expect(page.get_by_role("status").filter(has_text="Gespeichert")).to_be_visible(timeout=10000)
    assert setup_server.site.archive.configuration.active.notifications.quiet_hours.enabled


def test_no_javascript_setup_and_diagnosis_remain_operable(browser, setup_server):
    context = browser.new_context(java_script_enabled=False)
    page = context.new_page()
    try:
        sign_in(page, setup_server)
        page.goto(setup_server.url + "/diagnose")
        page.get_by_role("button", name="llm prüfen", exact=True).click()
        expect(page.get_by_role("heading", name="Diagnose", exact=True)).to_be_visible()
        result = page.locator("section").filter(has=page.get_by_role("heading", name="llm", exact=True))
        expect(result).to_contain_text("bereit")
        page.goto(setup_server.url + "/einrichtung")
        control = page.get_by_label("Zeitzone (IANA)")
        control.fill("Europe/Berlin")
        control.locator("..").get_by_role("button", name="Entwurf speichern").click()
        expect(page.get_by_role("heading", name="Einrichtung", exact=True)).to_be_visible()
        expect(page.get_by_label("Zeitzone (IANA)")).to_have_value("Europe/Berlin")
    finally:
        context.close()
