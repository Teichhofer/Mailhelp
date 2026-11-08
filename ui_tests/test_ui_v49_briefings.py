"""Briefing settings and email layout on desktop, mobile and narrow screens."""
from datetime import UTC, datetime, timedelta

from playwright.sync_api import expect

from checks import audit
from conftest import sign_in
from mailhelp.notifications.briefing_aggregate import BriefingContent, BriefingItem
from mailhelp.notifications.briefing_template import render_briefing
from pages import SettingsPage
from tests.scenarios.web_scenario import mail_id


def test_briefing_settings_have_usable_controls_and_save_times(page, mailhelp):
    sign_in(page, mailhelp)
    settings = SettingsPage(page, mailhelp.url).open("briefing")
    setting = settings.expand("Uhrzeiten für Postfach-Briefings")
    expect(setting.get_by_label("Neuer Wert")).to_have_value("07:00, 13:00, 18:00")
    assert audit(page, "v49-settings-" + page.device, page.mobile) == []
    settings.propose(setting, "08:15; 17:45")
    settings.confirm()
    expect(page.locator("main")).to_contain_text("Gespeichert", timeout=10000)
    assert mailhelp.site.archive.configuration.active.briefings.times == ["08:15", "17:45"]
    settings.open("briefing")
    mailbox = settings.expand("Zielpostfach für Briefings")
    expect(mailbox.get_by_label("Neuer Wert")).to_have_value("default")
    assert page.errors == [] and mailhelp.writer.created == []


def test_rendered_email_is_accessible_and_links_only_open_authenticated_cards(page, mailhelp):
    now = datetime(2026, 11, 8, 6, tzinfo=UTC)
    item = BriefingItem(mail_id(1), "elternabend", 1, "Treffen <script>untrusted</script>",
                        "09.11.2026", "Klärung nötig", ("Wann genau?",))
    content = BriefingContent(now - timedelta(hours=6), now, events=(item,))
    html = render_briefing(content, "07:00", "Europe/Berlin", mailhelp.url)["html"]
    # A synthetic email preview served only by the browser test, never an application route.
    page.route("**/synthetic-briefing", lambda route: route.fulfill(body=html, content_type="text/html"))
    page.goto(mailhelp.url + "/synthetic-briefing")
    expect(page.get_by_role("heading", level=1)).to_contain_text("Mailhelp Briefing 07:00")
    assert audit(page, "v49-email-" + page.device, page.mobile) == []
    assert page.locator("script,form,img,iframe").count() == 0
    link = page.get_by_role("link", name="In Mailhelp prüfen:")
    assert link.get_attribute("href") == f"{mailhelp.url}/vorschlag/{mail_id(1)}/elternabend"
    link.click()
    expect(page.page).to_have_url(mailhelp.url + "/anmelden")
    assert mailhelp.writer.created == [] and page.errors == []
