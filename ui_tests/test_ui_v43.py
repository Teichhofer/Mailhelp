"""Accessible series editing, exceptions and explicit creation on real browsers."""
import pytest
from playwright.sync_api import expect

from checks import audit
from conftest import Page, sign_in
from tests.fakes.series_fakes import series


def seed(mailhelp):
    items = series()
    for item in items:
        mailhelp.dialog.persist(item)
    return items, f'{mailhelp.url}/serie/{items[0].source_mail_id}/{items[0].series_key}'


def flow(page, mailhelp, url):
    page.goto(url)
    expect(page.get_by_role('heading', name='Terminserie: Sitzung')).to_be_visible()
    assert page.get_by_role('button', name='Alle 3 Termine anlegen').count() == 0
    page.get_by_label('Beginn', exact=True).fill('19:00')
    page.get_by_role('button', name='Zeit für die Auswahl speichern').click()
    # 4.4: the series result is shown on every member card; one visible copy suffices.
    message = page.get_by_text('3 Serientermine gespeichert; separat bestätigen.', exact=False)
    message = message.filter(visible=True).first
    expect(message).to_be_visible(timeout=15000)
    assert mailhelp.writer.created == []
    page.goto(url)
    page.locator('input[name="omit_2"]').check()
    page.get_by_role('button', name='Auswahl aktualisieren').click()
    expect(page.get_by_role('button', name='Alle 2 Termine anlegen')).to_be_visible()
    page.get_by_role('button', name='Alle 2 Termine anlegen').click()
    # Shown on the member card and, with JavaScript, also announced in the toast.
    done = page.get_by_text('2 Serientermine bearbeitet.', exact=False).filter(visible=True).first
    expect(done).to_be_visible(timeout=15000)
    assert len(mailhelp.writer.created) == 2


@pytest.mark.smoke
def test_series_group_time_answer_selection_and_confirmation(page, mailhelp):
    items, url = seed(mailhelp)
    sign_in(page, mailhelp)
    page.goto(mailhelp.url)
    group = page.locator('.series-group').filter(has_text='Serie: Sitzung')
    group.locator(':scope > summary').press('Space')
    expect(group.get_by_role('link', name='Serie bearbeiten und bestätigen')).to_be_visible()
    page.goto(url)
    assert audit(page, f'serie-43-{page.device}', page.mobile) == []
    flow(page, mailhelp, url)
    current = mailhelp.dialog.repository.load_current(items[-1].source_mail_id, items[-1].id)
    assert current.status.value == 'pending_confirmation'
    assert page.errors == []


def test_series_without_javascript(browser, mailhelp):
    _, url = seed(mailhelp)
    context = browser.new_context(java_script_enabled=False, locale='de-DE')
    page = Page(context.new_page(), 'no-javascript')
    try:
        sign_in(page, mailhelp)
        flow(page, mailhelp, url)
    finally:
        context.close()
