"""First-run and OAuth routes exercise the same authentication and CSRF boundaries as review."""
import json
import re
from urllib.parse import parse_qs

import httpx
import pytest

from mailhelp.runtime import google_calendars as calendar_module
from mailhelp.runtime import oauth_web
from mailhelp.runtime.local_pairing import signature
from mailhelp.runtime.web_password import WebPassword
from mailhelp.web import oauth_site as module
from mailhelp.web.http import Request
from mailhelp.web.login_site import PAIR_COOKIE
from tests.fakes.initial_harness import initial
from tests.fakes.shared_web_auth import Browser


def browser(h,signed=True):
    result=Browser(h.app)
    if signed:result.cookies['mh_session']=h.token
    return result


def test_login_page_both_code_channels_password_and_csrf(initial):
    h=initial
    b=browser(h,False)
    page=b.request('GET','/anmelden')
    assert page.status==200 and b'mailhelp --pair' in page.body
    nonce=b.cookies[PAIR_COOKIE]
    csrf=h.auth.csrf_token('pair:'+nonce)
    WebPassword(h.store).set('synthetic-password',0)
    assert b'name="password"' in b.request('GET','/anmelden').body
    assert b.request('POST','/anmelden/passwort',{'csrf':'bad','password':'synthetic-password'}).status==403
    assert b.request('POST','/anmelden/passwort',{'csrf':csrf,'password':'bad'}).status==429
    assert b.request('POST','/anmelden/passwort',{'csrf':csrf,'password':'synthetic-password'}).status==303
    assert b.request('GET','/einrichtung/start').status==200
    other=browser(h,False)
    assert other.request('POST','/anmelden/passwort',{}).status==303


def test_console_code_request_is_host_authenticated(initial):
    h=initial
    b=browser(h,False)
    b.request('GET','/anmelden')
    csrf=h.auth.csrf_token('pair:'+b.cookies[PAIR_COOKIE])
    assert b'Lokalen Code' in b.request('POST','/anmelden/code',{'csrf':csrf}).body
    assert b.request('POST','/api/local-pair',{'message':'forged','signature':'bad'}).status==403
    assert b.request('POST','/api/local-pair',{},content_type='text/plain').status==415
    import time
    text=f'{int(time.time())}:'+'a'*32
    response=b.request('POST','/api/local-pair',{'message':text,'signature':signature(h.auth._key.decode(),text)})
    assert response.status==200
    code=json.loads(response.body)['code']
    assert b.request('POST','/anmelden',{'csrf':csrf,'code':code}).status==303


def test_guide_and_google_callback_enforce_state_and_original_session(initial):
    h=initial
    h.advance()
    b=browser(h)
    guide=b.request('GET','/hilfe/google-playground')
    assert guide.status==200 and b'Use your own OAuth credentials' in guide.body
    assert b'GOOGLE_OAUTH_REFRESH_TOKEN' in guide.body
    assert b.request('GET','/auth/google/start?profile=99').status==409
    assert b.request('GET','/auth/google/start?profile=0').status==409
    assert b.request('GET','/auth/google/start').status==200
    form={'csrf':h.auth.csrf_token(h.session.id),'profile':'1','key':'google-valid-key',
          'revision':h.oauth.revision(1,'google')}
    assert b.request('POST','/auth/google/start',{**form,'csrf':'foreign'}).status==403
    assert b.request('POST','/auth/google/start',{**form,'revision':'stale'}).status==409
    start=b.request('POST','/auth/google/start',form)
    assert start.status==303
    state=parse_qs(start.headers['Location'].split('?',1)[1])['state'][0]
    h.oauth.transport=httpx.MockTransport(lambda req:httpx.Response(200,json={'refresh_token':'new-google-refresh'}))
    interstitial=browser(h,False).request('GET',f'/auth/google/callback?state={state}&code=synthetic-code')
    assert interstitial.status==200 and b'Google-Anmeldung abschlie' in interstitial.body
    assert 'new-google-refresh' not in (h.directory/'.env').read_text()
    callback=b.request('GET',f'/auth/google/callback?state={state}&code=synthetic-code')
    assert callback.status==303 and b'Anmeldung gespeichert' in b.request('GET',callback.headers['Location']).body
    for query in ['', 'state=invalid&code=x',f'state={state}&error=access_denied',f'state={state}&code=',
                  f'state={state}&code='+'x'*4097]:
        assert b.request('GET','/auth/google/callback?'+query).status==409


def test_device_modal_progress_automatic_refresh_and_failures(initial):
    h=initial
    h.advance()
    h.setup.save(h.actor,h.form(4,MICROSOFT_CLIENT_ID='synthetic-ms-client'))
    b=browser(h)
    assert b.request('GET','/auth/microsoft').status==200
    form={'csrf':h.auth.csrf_token(h.session.id),'profile':'1','key':'ms-start-key',
          'revision':h.oauth.revision(1,'microsoft')}
    response=b.request('POST','/auth/microsoft/device',form)
    assert response.status==303
    identity=response.headers['Location'].rsplit('/',1)[1]
    h.oauth.transport=httpx.MockTransport(lambda req:httpx.Response(200,json={
        'device_code':'private-device','user_code':'ABCD-EFGH','verification_uri':'https://microsoft.com/devicelogin',
        'expires_in':300,'interval':1}))
    h.oauth.tick(identity)
    page=b.request('GET',response.headers['Location'])
    assert b'ABCD-EFGH' in page.body and b'Code kopieren' in page.body and b'http-equiv="refresh"' in page.body
    assert b'private-device' not in page.body
    assert b.request('GET','/auth/microsoft/poll?id='+identity).status==200
    assert b.request('GET','/auth/microsoft/poll').status==409
    assert b.request('GET','/auth/status/'+'f'*64).status==409
    assert b.request('POST','/auth/microsoft/device',{'csrf':form['csrf']}).status==409


def test_calendar_choice_is_read_only_versioned_and_uses_profile(initial,monkeypatch):
    h=initial
    h.advance()
    b=browser(h)
    monkeypatch.setattr(module,'google_calendars',lambda *a:[('selected','Chosen calendar')])
    page=b.request('GET','/auth/google/kalender')
    assert page.status==200 and b'Chosen calendar' in page.body
    form={'csrf':h.auth.csrf_token(h.session.id),'profile':'1','calendar':'selected','key':'f'*32,
          'version':str(h.setup.state().version),'revision':h.oauth.revision(1,'google')}
    assert b.request('POST','/auth/google/kalender',{**form,'revision':'stale'}).status==409
    assert b.request('POST','/auth/google/kalender',{**form,'calendar':'unknown'}).status==409
    assert b.request('POST','/auth/google/kalender',form).status==303
    assert h.setup.state().config['targets']['google_calendar']=='selected'
    assert b.request('GET','/auth/google/kalender?profile=2').status==409
    monkeypatch.setattr(module,'google_calendars',lambda *a:(_ for _ in ()).throw(RuntimeError('private-body')))
    assert b'private-body' not in b.request('GET','/auth/google/kalender').body
