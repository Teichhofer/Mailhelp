"""Configured accounts share the existing versioned setup drafts."""
from types import SimpleNamespace

import pytest
import yaml

from mailhelp.app.browser_accounts import attach_accounts
from mailhelp.app.service_coordinator import ServiceCoordinator
from mailhelp.config import TargetProfileSettings
from mailhelp.web import oauth_site


@pytest.mark.parametrize("resource, field", [("kalender", "google_calendar"), ("aufgabenlisten", "google_tasks_list")])
def test_account_routes_use_current_credentials_and_versioned_profile_drafts(configured,monkeypatch,resource,field):
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
    monkeypatch.setattr(oauth_site,'google_calendars',lambda *a, **kw:[('chosen','Chosen calendar')])
    for number in [1,2]:
        response=web.browser.request('GET',f'/auth/google/{resource}?profile={number}')
        assert response.status==200
        form=web.form(f'/auth/google/{resource}?profile={number}',action=f'/auth/google/{resource}')
        form['calendar']='chosen'
        saved=web.browser.request('POST',f'/auth/google/{resource}',form)
        # Regression 7.2.6: the configured app shows its draft at /einrichtung; /einrichtung/start
        # exists only in the initial setup and answered 404 after every selection.
        assert saved.status==303 and saved.headers['Location']=='/einrichtung'
        assert web.browser.request('GET',saved.headers['Location']).status==200
        state=c.runtime.setup.state()
        assert ('targets.'+field in state.patch) if number==1 else state.patch['target_profiles'][0][field]=='chosen'
        c.runtime.setup.discard('web:'+web.auth.sessions()[0].id,state.version,'discard-key-'+str(number))
    assert web.browser.request('GET',f'/auth/google/{resource}?profile=99').status==409


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
