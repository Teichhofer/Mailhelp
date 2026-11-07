"""4.4: pending cards never prevent work on another card."""
from threading import Event
from urllib.parse import parse_qs

import pytest
from playwright.sync_api import expect

from conftest import item, sign_in
from tests.scenarios.web_scenario import mail_id


@pytest.mark.parametrize('kind,result', [('reject', 'Vorschlag verworfen.'), ('confirm', 'Angelegt.')])
def test_a_second_card_can_be_selected_and_submitted_while_the_first_is_pending(page, mailhelp, monkeypatch,
                                                                             kind, result):
    sign_in(page, mailhelp)
    release, entered = Event(), Event()
    execute = mailhelp.dialog.review.execute
    def held(command):
        entered.set()
        assert release.wait(30)
        return execute(command)
    monkeypatch.setattr(mailhelp.dialog.review, 'execute', held)
    posts = []
    page.on('request', lambda request: posts.append(parse_qs(request.post_data))
            if request.method == 'POST' and request.url.endswith('/aktion') else None)
    try:
        first = item(page, f'#v-{mail_id(1)}-elternabend')
        first.locator(f'form:has(input[name="kind"][value="{kind}"]) button').click()
        assert entered.wait(5)
        expect(page.locator('[data-card-command-status]').first).to_contain_text('Wird verarbeitet')
        second = item(page, f'#v-{mail_id(1)}-formular')
        second.get_by_role('button', name='Verwerfen', exact=True).click()
        expect(page.locator('[data-card-command-status]')).to_have_count(3 if page.device == 'desktop' else 2)
        assert len(posts) == 2 and posts[0]['proposal_id'] == ['elternabend']
        assert posts[1]['proposal_id'] == ['formular']
        release.set()
        expect(page.locator('[data-command-result] .notice:visible').filter(has_text=result).first).to_be_visible(
            timeout=15000)
        page.reload()
        expect(page.locator('[data-command-result] .notice:visible').filter(has_text='Vorschlag verworfen.').first
               ).to_be_visible()
        assert len(posts) == 2 and page.errors == []
    finally:
        release.set()


def test_one_card_disables_all_its_actions_until_a_result_arrives(page, mailhelp, monkeypatch):
    sign_in(page, mailhelp)
    release = Event()
    execute = mailhelp.dialog.review.execute
    def held(command):
        assert release.wait(30)
        return execute(command)
    monkeypatch.setattr(mailhelp.dialog.review, 'execute', held)
    try:
        card = item(page, f'#v-{mail_id(1)}-elternabend')
        card.get_by_role('button', name='Verwerfen', exact=True).click()
        expect(card.get_by_role('button', name='Im Kalender anlegen')).to_be_disabled()
        release.set()
        expect(page.locator('[data-command-result] .notice:visible').filter(has_text='Vorschlag verworfen.').first
               ).to_be_visible(timeout=15000)
        assert mailhelp.writer.created == []
    finally:
        release.set()
