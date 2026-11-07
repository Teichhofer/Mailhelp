"""The real authenticated, CSRF-protected web series flow, with synthetic state."""
import re
from html import unescape

import pytest

from mailhelp.models import ProposalStatus
from tests.fakes.series_fakes import series
from tests.fakes.shared_review import setup


def seed(web, complete=False):
    items = series(complete=complete)
    for item in items:
        web.dialog.persist(item)
    return items, f'/serie/{items[0].source_mail_id}/{items[0].series_key}'


def form(web, url):
    html = web.browser.request('GET', url).body.decode()
    target = re.search(r'<form method="post" action="(/serie/[a-f0-9]{32})"[^>]*>', html)[1]
    csrf = unescape(re.search(r'<input type="hidden" name="csrf" value="([^"]+)"', html)[1])
    return target, {'csrf': csrf}, html


def test_incomplete_series_does_not_offer_external_creation(web):
    _, url = seed(web)
    _, _, html = form(web, url)
    assert 'value="confirm"' not in html
    assert 'datetime.date' not in html and '23.01.2027' in html
    assert web.writer.created == 0


def test_web_time_edit_and_explicit_version_list_confirmation(web):
    items, url = seed(web)
    target, fields, _ = form(web, url)
    assert web.browser.request('POST', target, {**fields, 'action': 'answer', 'start': '19:00'}).status == 303
    web.run()
    assert all(web.dialog.repository.load_current(item.source_mail_id, item.id).version == 2 for item in items)
    assert web.writer.created == 0
    target, fields, html = form(web, url)
    assert 'Alle 3 Termine anlegen' in html and 'Version 2' in html
    assert web.browser.request('POST', target, {**fields, 'action': 'confirm'}).status == 303
    web.run()
    assert web.writer.created == 3


def test_missing_csrf_and_changed_version_cannot_create_a_series(web):
    items, url = seed(web, complete=True)
    target, fields, _ = form(web, url)
    assert web.browser.request('POST', target, {'action': 'confirm'}).status == 403
    web.dialog.persist(items[-1].model_copy(update={'version': 2}))
    assert web.browser.request('POST', target, {**fields, 'action': 'confirm'}).status == 303
    web.run()
    assert web.commands.queued() == []
    assert web.writer.created == 0


@pytest.mark.parametrize('fields', [{'start': '', 'end': '22:00'}, {'start': 'x' * 4001}])
def test_invalid_time_fields_are_rejected_before_enqueue(web, fields):
    _, url = seed(web)
    target, csrf, _ = form(web, url)
    assert web.browser.request('POST', target, {**csrf, 'action': 'answer', **fields}).status == 422
    assert web.commands.queued() == [] and web.writer.created == 0


@pytest.mark.parametrize('case', ['missing', 'closed', 'too_many'])
def test_missing_or_unmanageable_series_is_not_rendered(web, case):
    items, url = seed(web)
    if case == 'missing':
        url = f'/serie/{items[0].source_mail_id}/' + '0' * 64
        expected = 404
    else:
        if case == 'closed':
            for item in items: web.dialog.persist(item.model_copy(update={'status': ProposalStatus.REJECTED}))
        else:
            for index in range(3, 101): web.dialog.persist(items[0].model_copy(update={'id': f'p{index}'}))
        expected = 422
    assert web.browser.request('GET', url).status == expected
    assert web.writer.created == 0


@pytest.mark.parametrize('case', ['missing_offer', 'wrong_actor', 'empty', 'action', 'too_many_fields'])
def test_bad_series_forms_are_refused_without_enqueue(web, case):
    items, url = seed(web)
    target, fields, _ = form(web, url)
    fields['action'] = 'confirm'
    expected = 422
    if case == 'missing_offer':
        target = '/serie/' + '0' * 32
        expected = 404
    elif case == 'wrong_actor':
        from mailhelp.review.series_offers import SeriesOffer, create_offer
        token = create_offer(web.store, SeriesOffer(actor='web:another-session', items=items))
        target = f'/serie/{token}'
        expected = 404
    elif case == 'empty': fields.update({f'omit_{index}': 'yes' for index in range(3)})
    elif case == 'action': fields['action'] = 'invalid'
    else:
        fields.update({f'field{index}': 'x' for index in range(121)})
        expected = 400
    assert web.browser.request('POST', target, fields).status == expected
    assert web.commands.queued() == [] and web.writer.created == 0


@pytest.mark.parametrize('action', ['select', 'confirm'])
def test_exclusion_requires_the_updated_list_to_be_explicitly_confirmed(web, action):
    items, url = seed(web, complete=True)
    target, fields, _ = form(web, url)
    response = web.browser.request('POST', target, {**fields, 'action': action, 'omit_2': 'yes'})
    assert response.status == 200 and b'Alle 2 Termine anlegen' in response.body
    assert web.commands.queued() == [] and web.writer.created == 0
    target = re.search(r'action="(/serie/[a-f0-9]{32})"', response.body.decode())[1]
    # An excluded term may change without changing the explicitly selected list.
    web.dialog.persist(items[-1].model_copy(update={'version': 2}))
    assert web.browser.request('POST', target, {**fields, 'action': 'confirm'}).status == 303
    web.run()
    assert web.writer.created == 2


def test_time_interval_and_same_offer_conflict_do_not_create_entries(web):
    _, url = seed(web)
    target, fields, _ = form(web, url)
    fields.update(action='answer', start='19:00', end='21:30')
    assert web.browser.request('POST', target, fields).status == 303
    assert web.browser.request('POST', target, {**fields, 'end': '22:00'}).status == 409
    web.run()
    assert web.writer.created == 0


def test_full_queue_does_not_authorize_an_external_series_write(web, monkeypatch):
    from mailhelp.review.inbox import CommandInboxFull
    _, url = seed(web, complete=True)
    target, fields, _ = form(web, url)
    def full(command):
        raise CommandInboxFull('synthetic full queue')
    monkeypatch.setattr(web.commands, 'submit', full)
    assert web.browser.request('POST', target, {**fields, 'action': 'confirm'}).status == 409
    assert web.writer.created == 0


def test_session_revoked_after_enqueue_cannot_create_any_series_member(web):
    _, url = seed(web, complete=True)
    target, fields, _ = form(web, url)
    session = web.auth.authenticate(web.browser.cookies['mh_session'])
    assert web.browser.request('POST', target, {**fields, 'action': 'confirm'}).status == 303
    web.auth.revoke(session.id)
    web.run()
    assert web.writer.created == 0
    assert web.browser.request('GET', url).status == 303
