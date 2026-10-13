"""Version 1.2 pages and workflows on desktop and iPhone, synthetic data only."""
from playwright.sync_api import expect
from web_scenario import mail_id

from checks import audit
from conftest import sign_in
from pages import SettingsPage


def test_archive_history_statistics_settings_and_topics(page, mailhelp):
    sign_in(page, mailhelp)
    for route in ('mails', 'verlauf', 'auswertung', 'einstellungen', 'themen', 'einstellungen/beenden'):
        page.goto(f'{mailhelp.url}/{route}')
        assert audit(page, f'v12-{route.replace("/", "-")}-{page.device}', page.mobile) == []
    assert not mailhelp.stop.is_set()
    page.goto(f'{mailhelp.url}/mails')
    page.get_by_label('Suche (Absender, Betreff, Zusammenfassung)').fill('Klassenfahrt')
    page.get_by_role('button', name='Suchen', exact=True).click()
    expect(page.locator('main')).to_contain_text('1 gespeicherte Mails')
    assert page.errors == []


def test_deterministic_edit_and_settings_confirmation(page, mailhelp):
    sign_in(page, mailhelp)
    path = f'/vorschlag/{mail_id(1)}/formular/bearbeiten'
    page.goto(mailhelp.url + path)
    assert audit(page, f'v12-edit-{page.device}', page.mobile) == []
    page.get_by_label('Titel', exact=True).fill('Neuer Titel aus dem Formular')
    page.get_by_role('button', name='Speichern', exact=True).click()
    expect(page.get_by_role('heading', name='Offene Entscheidungen')).to_be_visible(timeout=10000)
    expect(page.locator(f'#v-{mail_id(1)}-formular')).to_contain_text('Neuer Titel aus dem Formular')
    assert mailhelp.writer.created == []
    settings = SettingsPage(page, mailhelp.url).open()
    setting = settings.expand('Abrufintervall (Sekunden)')
    assert audit(page, f'v12-setting-open-{page.device}', page.mobile) == []
    settings.propose(setting, '10')
    assert audit(page, f'v12-setting-confirm-{page.device}', page.mobile) == []
    settings.confirm()
    expect(page.locator('main')).to_contain_text('Gespeichert', timeout=10000)
    assert mailhelp.writer.created == [] and page.errors == []
