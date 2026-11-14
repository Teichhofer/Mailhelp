"""Processing actions work without JavaScript on desktop and telephone."""
from playwright.sync_api import expect

from conftest import sign_in
from tests.fakes.processing_retry import errored


def test_failed_mail_can_be_filed_without_javascript(page,mailhelp):
    state=errored()
    mailhelp.store.save('mail-'+state.id,state.model_dump(mode='json'))
    mailhelp.site.refresh_overview()
    sign_in(page,mailhelp)
    page.cdp.send('Emulation.setScriptExecutionDisabled', {'value':True})
    page.goto(mailhelp.url+'/mail/'+state.id)
    expect(page.get_by_role('button',name='Erneut versuchen',exact=True)).to_be_visible()
    expect(page.get_by_role('button',name='Ablegen',exact=True)).to_be_visible()
    page.get_by_role('button',name='Ablegen',exact=True).click()
    expect(page.get_by_text('Nicht verarbeitet – bewusst abgelegt.',exact=True)).to_be_visible()
    expect(page.get_by_role('button',name='Ablegen',exact=True)).to_have_count(0)
    page.cdp.send('Emulation.setScriptExecutionDisabled', {'value':False})
