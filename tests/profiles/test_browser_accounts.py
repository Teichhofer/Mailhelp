"""Configured accounts share the existing versioned setup drafts."""
from types import SimpleNamespace

import pytest
import yaml

from mailhelp.config import TargetProfileSettings
from mailhelp.runtime.browser_accounts import attach_accounts
from mailhelp.runtime.service_coordinator import ServiceCoordinator
from mailhelp.web import oauth_site


def test_account_routes_use_current_credentials_and_versioned_profile_drafts(configured,monkeypatch):
    c=configured
    web=c.web
    c.cfg.target_profiles=[TargetProfileSettings(id=2,label='Work',google_calendar='primary',todoist_project='inbox')]
    (c.tmp_path/'config.yaml').write_text(yaml.safe_dump(c.cfg.model_dump(mode='json')))
    (c.tmp_path/'.env').write_text('GOOGLE_OAUTH_CLIENT_ID=synthetic-client\nGOOGLE_OAUTH_CLIENT_SECRET=private-secret\n')
    c.app.services=SimpleNamespace()
    attach_accounts(c.app,web.site,c.tmp_path)
    service=c.app.services.oauth
    assert service.config(2,'google').client_id=='synthetic-client'
    assert not service.authorize('telegram:1:2')
    monkeypatch.setattr(oauth_site,'google_calendars',lambda *a:[('chosen','Chosen calendar')])
    for number in [1,2]:
        response=web.browser.request('GET',f'/auth/google/kalender?profile={number}')
        assert response.status==200
        form=web.form(f'/auth/google/kalender?profile={number}',action='/auth/google/kalender')
        form['calendar']='chosen'
        assert web.browser.request('POST','/auth/google/kalender',form).status==303
        state=c.runtime.setup.state()
        assert ('targets.google_calendar' in state.patch) if number==1 else state.patch['target_profiles'][0]['google_calendar']=='chosen'
        c.runtime.setup.discard('web:'+web.auth.sessions()[0].id,state.version,'discard-key-'+str(number))
    assert web.browser.request('GET','/auth/google/kalender?profile=99').status==409


def test_password_settings_are_versioned_and_authorized(web):
    browser=web.browser
    path='/einstellungen/web-passwort'
    page=browser.request('GET',path)
    assert page.status==200 and b'mailhelp --reset-web-password' in page.body
    form=web.form(path,action=path)
    assert browser.request('POST',path,{**form,'password':'synthetic-password'}).status==303
    assert browser.request('POST',path,{**form,'password':'different-password'}).status==409
    assert browser.request('POST',path,{**form,'csrf':'wrong','password':'synthetic-password'}).status==403


def test_service_coordinator_starts_and_stops_oauth_with_web():
    calls=[]
    web=SimpleNamespace(start=lambda:calls.append('web-start'),stop=lambda:calls.append('web-stop'))
    oauth=SimpleNamespace(start_worker=lambda:calls.append('oauth-start'),stop=lambda:calls.append('oauth-stop'))
    service=ServiceCoordinator(web=web,oauth=oauth)
    service.start_web(SimpleNamespace(event=lambda *a,**kw:None),lambda _:None)
    service.stop_web()
    assert calls==['web-start','oauth-start','oauth-stop','web-stop']
