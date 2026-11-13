"""Real-browser first-run and device-code flows; all external services are synthetic."""
from types import SimpleNamespace

import httpx
import pytest
from playwright.sync_api import expect

from checks import audit
from mailhelp.runtime.env_file import file_hash, set_values
from mailhelp.web.server import WebServer
from tests.fakes.initial_harness import InitialHarness


@pytest.fixture
def initial_server(tmp_path):
    h=InitialHarness(tmp_path)
    server=WebServer('127.0.0.1',0,h.app,SimpleNamespace(event=lambda *a,**kw:None))
    server.start()
    host,port=server.address
    h.app.allowed_hosts=frozenset({f'{host}:{port}'})
    h.url=f'http://{host}:{port}'
    h.code=h.auth.issue_code()
    try:
        yield h
    finally:
        server.stop()
        h.close()


def login(page,h):
    page.goto(h.url+'/einrichtung/start')
    page.get_by_label('Code aus der Mailhelp-Konsole').fill(h.code)
    page.get_by_role('button',name='Gerät koppeln',exact=True).click()
    expect(page.get_by_role('heading',name='Mailhelp einrichten: Web-Zugang und Zeitzone')).to_be_visible()


def test_initial_wizard_from_empty_directory_to_saved_configuration(page,initial_server):
    h=initial_server
    login(page,h)
    expect(page.locator('input[name="timezone"]')).to_have_value('Europe/Berlin')
    page.get_by_label('Web-Passwort (mindestens 12 Zeichen)').fill('synthetic-browser-password')
    page.get_by_role('button',name='Speichern und weiter',exact=True).click()
    page.get_by_label('IMAP-Server',exact=True).fill('imap.example.test')
    page.get_by_label('IMAP_USERNAME',exact=True).fill('synthetic@example.test')
    page.get_by_label('IMAP_PASSWORD',exact=True).fill('synthetic-imap-password')
    page.get_by_role('button',name='Prüfen',exact=True).click()
    expect(page.get_by_role('combobox',name='Entwurfsordner',exact=True)).to_have_value('Entwürfe')
    page.get_by_role('button',name='Speichern und weiter',exact=True).click()
    page.get_by_label('OPENROUTER_API_KEY',exact=True).fill('synthetic-router-key')
    page.get_by_role('button',name='Prüfen',exact=True).click()
    page.get_by_role('button',name='Speichern und weiter',exact=True).click()
    for name,value in {'GOOGLE_OAUTH_CLIENT_ID':'synthetic-client','GOOGLE_OAUTH_CLIENT_SECRET':'private-secret',
                       'GOOGLE_OAUTH_REFRESH_TOKEN':'private-refresh','TODOIST_TOKEN':'private-todoist'}.items():
        page.get_by_label(name,exact=True).fill(value)
    page.get_by_role('button',name='Speichern und weiter',exact=True).click()
    expect(page.get_by_role('heading',name='Mailhelp einrichten: Abschluss')).to_be_visible()
    assert audit(page,'initial-complete-'+page.device,page.mobile)==[]
    page.get_by_role('checkbox',name='Konfiguration speichern und Normalbetrieb starten').check()
    page.get_by_role('button',name='Speichern und starten',exact=True).click()
    expect(page.get_by_role('heading',name='Einrichtung abgeschlossen')).to_be_visible()
    assert (h.directory/'config.yaml').is_file() and h.stopped.is_set()
    assert h.setup.state().status=='done' and h.checks.calls[-3:]==['imap','llm','targets']


def test_initial_wizard_manual_timezone_survives_back_navigation(page,initial_server):
    h=initial_server
    login(page,h)
    page.get_by_label('Zeitzone',exact=True).fill('UTC')
    page.get_by_label('Web-Passwort (mindestens 12 Zeichen)').fill('synthetic-browser-password')
    page.get_by_role('button',name='Speichern und weiter',exact=True).click()
    page.goto(h.url+'/einrichtung/schritt/1')
    expect(page.get_by_label('Zeitzone',exact=True)).to_have_value('UTC')
    page.get_by_role('button',name='Speichern und weiter',exact=True).click()
    expect(page.get_by_role('heading',name='Mailhelp einrichten: Postfach')).to_be_visible()


@pytest.mark.smoke
def test_initial_wizard_without_javascript(browser,initial_server):
    h=initial_server
    context=browser.new_context(java_script_enabled=False,service_workers='block')
    page=context.new_page()
    try:
        login(page,h)
        page.get_by_label('Zeitzone',exact=True).fill('UTC')
        page.get_by_label('Web-Passwort (mindestens 12 Zeichen)').fill('synthetic-password-no-js')
        page.get_by_role('button',name='Speichern und weiter',exact=True).click()
        expect(page.get_by_role('heading',name='Mailhelp einrichten: Postfach')).to_be_visible()
    finally:
        context.close()


def test_initial_microsoft_code_copy_and_playground_help(page,initial_server):
    h=initial_server
    login(page,h)
    h.advance()
    set_values(h.directory/'.env',{'MICROSOFT_CLIENT_ID':'synthetic-ms-client'},file_hash(h.directory/'.env'))
    h.oauth.transport=httpx.MockTransport(lambda r:httpx.Response(200,json={
        'device_code':'private-device','user_code':'ABCD-EFGH','verification_uri':'https://microsoft.com/devicelogin',
        'expires_in':300,'interval':5}))
    page.goto(h.url+'/auth/microsoft')
    page.get_by_role('button',name='Anmeldung starten',exact=True).click()
    identity=page.url.rsplit('/',1)[1]
    h.oauth.tick(identity)
    page.reload()
    expect(page.get_by_role('dialog',name='Microsoft-Anmeldung')).to_be_visible()
    page.context.grant_permissions(['clipboard-read','clipboard-write'])
    page.get_by_role('button',name='Code kopieren',exact=True).click()
    assert page.evaluate('navigator.clipboard.readText()')=='ABCD-EFGH'
    assert 'private-device' not in page.content()
    page.goto(h.url+'/hilfe/google-playground')
    expect(page.get_by_role('heading',name='Google OAuth 2.0 Playground',exact=True)).to_be_visible()
    expect(page.get_by_text('Use your own OAuth credentials',exact=False)).to_be_visible()
    page.collect()
    from conftest import COVERAGE
    assert not COVERAGE.uncovered().get('setup.js')
