"""Learning start, progress and explicit review in an actual browser, including no JavaScript."""
from types import SimpleNamespace

import pytest
from playwright.sync_api import expect

from checks import audit
from mailhelp.web.server import WebServer
from tests.fakes.initial_harness import InitialHarness
from tests.fakes.learning_harness import LearningHarness
from tests.fakes.rule_learning import RuleHarness, record


@pytest.fixture
def learning_server(tmp_path):
    initial=InitialHarness(tmp_path)
    h=LearningHarness(initial)
    server=WebServer('127.0.0.1',0,h.web,SimpleNamespace(event=lambda *a,**kw:None))
    server.start()
    host,port=server.address
    h.web.allowed_hosts=frozenset({f'{host}:{port}'})
    h.url=f'http://{host}:{port}'
    h.auth.channel='console'
    h.code=h.auth.issue_code()
    try:yield h
    finally:server.stop();initial.close()


@pytest.mark.parametrize("javascript", [True, False])
def test_learning57_overview_opens_both_functions_without_a_paid_call(page, learning_server, javascript):
    h = learning_server
    rules = RuleHarness(h.directory, h.store, h.jobs.active)
    h.site.rule_learning.service = rules.service
    rules.log(record())
    if not javascript:
        page.cdp.send("Emulation.setScriptExecutionDisabled", {"value": True})
    page.goto(h.url + "/lernen")
    page.get_by_label('Code aus der Mailhelp-Konsole').fill(h.code)
    page.get_by_role('button', name='Gerät koppeln', exact=True).click()
    page.goto(h.url + "/lernen")
    expect(page.get_by_role("heading", name="Lernen", exact=True)).to_be_visible()
    if javascript:
        assert audit(page, "learning57-overview-" + page.device, page.mobile) == []
    else:
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.get_by_role("link", name="Aus dem Postfach lernen öffnen", exact=True).click()
    expect(page.get_by_role("heading", name="Aus dem Postfach lernen", exact=True)).to_be_visible()
    page.get_by_role("link", name="Zur Lernübersicht", exact=True).click()
    page.get_by_role("link", name="Aus Entscheidungen lernen öffnen", exact=True).click()
    expect(page.get_by_role("heading", name="Aus Entscheidungen lernen", exact=True)).to_be_visible()
    assert h.client.calls == [] and rules.analyzer.calls == []


def estimate(page,h,count='2',budget='1'):
    """Realistic values (Planung Lernen): 0.5 USD per million tokens and a budget of 1 USD."""
    page.goto(h.url+'/lernen/postfach')
    page.get_by_label('Anzahl Mails',exact=True).fill(count)
    page.get_by_label('Preisobergrenze USD je Million Tokens',exact=True).fill('0.5')
    page.get_by_label('Budget USD',exact=True).fill(budget)
    page.get_by_role('button',name='Schätzung anzeigen',exact=True).click()
    expect(page.get_by_text('Typische Schätzung:',exact=False)).to_be_visible()


def flow(page,h,audit_review=True):
    page.goto(h.url+'/lernen/postfach')
    page.get_by_label('Code aus der Mailhelp-Konsole').fill(h.code)
    page.get_by_role('button',name='Gerät koppeln',exact=True).click()
    estimate(page,h)
    page.get_by_role('button',name='Lesenden Lernlauf kostenpflichtig starten',exact=True).click()
    expect(page.get_by_role('button',name='Pausieren',exact=True)).to_be_visible()
    page.get_by_role('button',name='Pausieren',exact=True).click()
    expect(page.get_by_role('button',name='Fortsetzen',exact=True)).to_be_visible()
    page.get_by_role('button',name='Fortsetzen',exact=True).click()
    while h.worker.tick():pass
    page.reload()
    expect(page.get_by_role('heading',name='<Newsletter>',exact=True)).to_be_visible()
    page.get_by_label('Titel',exact=True).fill('Camping-Buchungen')
    page.get_by_label('Beschreibung',exact=True).fill('Synthetische Buchungsbestätigungen')
    page.get_by_label('Übernahme',exact=True).select_option('relevant')
    page.get_by_role('button',name='Auswahl als Entwurf speichern',exact=True).click()
    expect(page.get_by_label('Titel',exact=True)).to_have_value('Camping-Buchungen')
    if audit_review:
        assert audit(page,'learning-review',page.viewport_size['width']<=390)==[]
    page.get_by_role('button',name='Ausgewählte Themen, Filter und Ordner ausdrücklich übernehmen',exact=True).click()
    expect(page.get_by_text('Auswahl gemeinsam gespeichert.',exact=False)).to_be_visible()
    expect(page.get_by_role('link',name='Konfiguration neu laden',exact=True)).to_be_visible()
    assert h.jobs.state().status=='done'


def test_learning_start_pause_review_and_explicit_adoption(page,learning_server):
    flow(page,learning_server)
    assert audit(page,'learning-complete-'+page.device,page.mobile)==[]
    # Regression (Planung Lernen): a further run starts after the first was adopted.
    estimate(page,learning_server,count='20',budget='0.01')
    expect(page.get_by_text('Bitte mindestens 0.200000 USD angeben.',exact=False)).to_be_visible()
    expect(page.get_by_role('button',name='Lesenden Lernlauf kostenpflichtig starten',exact=True)).to_have_count(0)
    estimate(page,learning_server,count='20')
    page.get_by_role('button',name='Lesenden Lernlauf kostenpflichtig starten',exact=True).click()
    expect(page.get_by_role('button',name='Pausieren',exact=True)).to_be_visible()
    assert learning_server.jobs.state().status=='running'


def test_learning_flow_without_javascript(browser,learning_server):
    context=browser.new_context(java_script_enabled=False,viewport={'width':390,'height':844})
    try:
        page=context.new_page()
        flow(page,learning_server,audit_review=False)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    finally:context.close()
