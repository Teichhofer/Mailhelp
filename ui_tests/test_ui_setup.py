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
    from mailhelp.orchestrator import Orchestrator
    app.orchestrator = Orchestrator(app.analyzer, app.store, object(), 2, [], 1024)
    app.orchestrator.configure_mailboxes(app.settings, app.analyzer.prompts, {"0" * 24: 1})
    app.settings.web.enabled = True
    site.setup_page.runtime = SetupRuntime(app, site, None, target_probe=lambda *args: None)
    site.notification_runtime = NotificationRuntime(app, site)
    return mailhelp


def test_mailbox_tabs_show_inheritance_and_preserve_a_local_draft(page, setup_server):
    sign_in(page, setup_server)
    for tab in ("targets", "filters", "topics", "replies", "notifications"):
        page.goto(setup_server.url + "/einstellungen/postfaecher/1?tab=" + tab)
        expect(page.get_by_role("heading", name="Postfach", exact=True)).to_be_visible()
        assert audit(page, "mailbox-" + tab + "-" + page.device, page.mobile) == []
    page.goto(setup_server.url + "/einstellungen/postfaecher/1?tab=replies")
    value = page.get_by_label("Signatur, Rolle und Anrede", exact=True)
    value.fill("Synthetische Signatur")
    value.locator("..").get_by_role("button", name="Im Entwurf speichern", exact=True).click()
    expect(page.get_by_role("heading", name="Entwurf prüfen", exact=True)).to_be_visible()
    assert setup_server.site.archive.configuration.active.personal_info == ""
    page.get_by_role("button", name="Entwurf verwerfen", exact=True).click()
    expect(page.get_by_role("heading", name="Entwurf prüfen", exact=True)).to_have_count(0)


def test_target_profile_controls_are_labelled_and_accessible(page, setup_server):
    import yaml

    from mailhelp.config import TargetProfileSettings
    runtime = setup_server.site.setup_page.runtime
    cfg = runtime.app.settings
    cfg.target_profiles = [TargetProfileSettings(
        id=2, label="Arbeit", google_calendar="primary", todoist_project="inbox")]
    path = runtime.app.configuration.directory / "config.yaml"
    path.write_text(yaml.safe_dump(cfg.model_dump(mode="json")), encoding="utf-8")
    sign_in(page, setup_server)
    page.goto(setup_server.url + "/einstellungen/zielprofile")
    expect(page.get_by_role("heading", name="Zielprofile", exact=True)).to_be_visible()
    expect(page.get_by_role("heading", name="Arbeit · 2", exact=True)).to_be_visible()
    assert audit(page, "target-profiles-" + page.device, page.mobile) == []
    assert page.locator("[id]").evaluate_all("items => new Set(items.map(item => item.id)).size === items.length")


def test_profile_switch_card_stays_unconfirmed_and_visible_on_small_phones(page, setup_server):
    from web_scenario import proposal, save_mail

    from mailhelp import profile_binding
    from mailhelp.config import TargetProfileSettings
    runtime = setup_server.site.setup_page.runtime
    cfg = runtime.app.settings
    cfg.target_profiles = [TargetProfileSettings(id=2, label="Arbeit", calendar_provider="outlook",
                                                 task_provider="microsoft_todo")]
    item = proposal(88, "profile-switch", kind="event", title="Synthetischer Profilwechsel",
        start="2030-11-20T14:00:00+01:00", end="2030-11-20T15:00:00+01:00",
        target=cfg.targets.calendar_target, target_provider="google")
    save_mail(setup_server.store, 88, "synthetic@example.test", "Profilwechsel", [item])
    setup_server.dialog.relevance_handler = runtime.app.orchestrator
    setup_server.site.views.profile_label = lambda p: profile_binding.label(cfg, p)
    sign_in(page, setup_server)
    page.goto(setup_server.url + f"/vorschlag/{item.source_mail_id}/{item.id}")
    page.get_by_role("button", name="Auf Zielprofil Arbeit umstellen", exact=True).click()
    expect(page.locator(".notice[role=status]")).to_contain_text("neue Version separat bestätigen", timeout=10000)
    current = setup_server.dialog.repository.load_current(item.source_mail_id, item.id)
    assert current.target_profile == 2 and current.version == 2 and current.status == "pending_confirmation"
    assert setup_server.writer.created == []
    expect(page.locator(".badge").filter(has_text="Outlook-Kalender · Arbeit")).to_be_visible()
    assert audit(page, "profile-switch-" + page.device, page.mobile) == []


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


def test_iserv_accounts_are_added_as_an_accessible_draft(page, setup_server):
    sign_in(page, setup_server)
    page.goto(setup_server.url + "/einstellungen/iserv")
    expect(page.get_by_role("heading", name="IServ-Konten", exact=True)).to_be_visible()
    assert audit(page, "iserv-empty-" + page.device, page.mobile) == []
    page.get_by_label("IServ-Adresse der Schule (https://…)", exact=True).fill("https://schule.example")
    page.get_by_label("Ältere Briefe nicht verarbeiten vor", exact=False).fill("01.09.2026")
    page.get_by_role("button", name="IServ-Konto als Entwurf hinzufügen", exact=True).click()
    expect(page.get_by_role("heading", name="Entwurf prüfen", exact=True)).to_be_visible()
    expect(page.get_by_role("heading", name="Elternbriefe · 1", exact=True)).to_be_visible()
    assert audit(page, "iserv-draft-" + page.device, page.mobile) == []
    assert setup_server.site.archive.configuration.active.iserv.accounts == []
    account = setup_server.site.setup_page.runtime.setup.draft_settings().iserv.accounts[0]
    assert account.historical_start.isoformat() == "2026-09-01T00:00:00+00:00"  # fixture timezone: UTC
    page.get_by_role("button", name="Entwurf verwerfen", exact=True).click()
    expect(page.get_by_role("heading", name="Entwurf prüfen", exact=True)).to_have_count(0)


def test_status_lists_iserv_and_other_configured_accounts(page, setup_server):
    from mailhelp.config import IServAccountSettings
    setup_server.site.archive.configuration.active.iserv.accounts = [
        IServAccountSettings(id=1, label="Grundschule", server="https://schule.example"),
        IServAccountSettings(id=2, label="Pausiert", server="https://pause.example", enabled=False)]
    import yaml
    configuration = setup_server.site.archive.configuration
    (configuration.directory / "config.yaml").write_text(
        yaml.safe_dump(configuration.active.model_dump(mode="json")), encoding="utf-8")
    sign_in(page, setup_server)
    page.goto(setup_server.url + "/status")
    expect(page.get_by_role("heading", name="Konfigurierte Konten", exact=True)).to_be_visible()
    expect(page.get_by_text("IServ 1 · Grundschule", exact=True)).to_be_visible()
    expect(page.get_by_text("IServ 2 · Pausiert", exact=True)).to_be_visible()
    assert audit(page, "status-accounts-" + page.device, page.mobile) == []
    metrics = setup_server.site.archive.metrics
    metrics.observe("poll_failed", {"service": "iserv", "account": 1, "error": "private"})
    page.reload()
    expect(page.get_by_text("Fehler beim letzten Verbindungsversuch", exact=True)).to_be_visible()
    metrics.observe("letters_listed", {"service": "iserv", "account": 1})
    page.reload()
    expect(page.get_by_text("Fehler beim letzten Verbindungsversuch", exact=True)).to_have_count(0)
    assert setup_server.writer.created == []


def test_credentials_are_write_only_and_accessible(page, setup_server, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    sign_in(page, setup_server)
    page.goto(setup_server.url + "/einstellungen/zugangsdaten")
    expect(page.get_by_role("heading", name="Zugangsdaten", exact=True)).to_be_visible()
    assert audit(page, "credentials-" + page.device, page.mobile) == []
    field = page.get_by_label("Neuer Wert für OPENROUTER_API_KEY", exact=True)
    expect(field).to_have_attribute("type", "password")
    field.fill("sk-synthetisch")
    form = field.locator("xpath=ancestor::form")
    form.get_by_label("Wert ausdrücklich in .env speichern").check()
    form.get_by_role("button", name="Speichern", exact=True).click()
    expect(page.get_by_text("OPENROUTER_API_KEY gespeichert", exact=False)).to_be_visible()
    assert "sk-synthetisch" not in page.content()
