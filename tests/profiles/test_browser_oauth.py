"""Durable browser OAuth using only synthetic provider responses."""
import json
import os
from urllib.parse import parse_qs

import httpx
import pytest
from initial_harness import InitialHarness

from mailhelp.config import Settings
from mailhelp.runtime.env_file import file_hash
from mailhelp.runtime.google_calendars import google_calendars
from mailhelp.runtime.oauth_web import BrowserOAuth, OAuthJob, oauth_config

DEVICE = {"device_code":"private-device-secret", "user_code":"ABCD-EFGH",
          "verification_uri":"https://microsoft.com/devicelogin", "expires_in":300,"interval":1}
TOKEN = {"access_token":"private-access", "refresh_token":"new-refresh", "token_type":"Bearer", "expires_in":3600}


@pytest.fixture
def oauth(tmp_path,monkeypatch):
    for name in list(os.environ):
        if name.startswith(("GOOGLE_","MICROSOFT_","IMAP_","OPENROUTER_","TODOIST_","MAILHELP_WEB_")):
            monkeypatch.delenv(name)
    h=InitialHarness(tmp_path)
    h.advance()
    h.setup.save(h.actor,h.form(4,MICROSOFT_CLIENT_ID='synthetic-microsoft-client'))
    h.time=[1000.0]
    h.oauth.clock=lambda:h.time[0]
    h.calls=[]
    def provider(req):
        h.calls.append(req)
        return httpx.Response(200,json=DEVICE if req.url.path.endswith('/devicecode') else TOKEN)
    h.oauth.transport=httpx.MockTransport(provider)
    yield h
    h.close()


def start(h,provider='google',key=None):
    h.sequence+=1
    return h.oauth.start(provider,h.actor,1,key or f'{h.sequence:032x}',h.oauth.revision(1,provider))


def test_google_state_pkce_callback_replay_and_private_credentials(oauth):
    h=oauth
    job=start(h)
    query=parse_qs(job.uri.split('?',1)[1])
    assert query['state']==[job.id] and query['code_challenge_method']==['S256']
    assert 'calendar.calendarlist.readonly' in query['scope'][0]
    assert h.oauth.start('google',h.actor,1,job.key,'stale-repeat')==job
    with pytest.raises(ValueError): h.oauth.start('microsoft',h.actor,1,job.key,h.oauth.revision(1,'microsoft'))
    with pytest.raises(PermissionError):h.oauth.google_callback(job.id,'web:wrong','code')
    completed=h.oauth.google_callback(job.id,h.actor,'authorization-code')
    assert completed.status=='done' and len(h.calls)==1
    assert h.oauth.google_callback(job.id,h.actor,'authorization-code').status=='done'
    assert len(h.calls)==1 and 'GOOGLE_OAUTH_REFRESH_TOKEN=new-refresh' in (h.directory/'.env').read_text()
    content=(h.store.directory/'web-oauth.json').read_text()
    assert 'new-refresh' not in content and 'authorization-code' not in content
    assert 'code_verifier=' in h.calls[0].content.decode()
    assert h.setup.state().env_revision==file_hash(h.directory/'.env')


@pytest.mark.parametrize('answer',[
    (400,{'error':'invalid_grant'}),(200,{}),(200,{'refresh_token':''}),
    (200,{'refresh_token':123}),(200,'invalid-json')])
def test_google_failed_or_malformed_exchange_never_saves_tokens(oauth,answer):
    h=oauth
    job=start(h)
    status,body=answer
    h.oauth.transport=httpx.MockTransport(lambda r:httpx.Response(status,json=body) if body!='invalid-json'
                                          else httpx.Response(200,text='bad'))
    assert h.oauth.google_callback(job.id,h.actor,'code').status=='failed'
    assert 'new-refresh' not in (h.directory/'.env').read_text()


def test_google_revoked_during_exchange_does_not_commit(oauth):
    h=oauth
    job=start(h)
    def revoke(req):
        h.auth.revoke(h.session.id)
        return httpx.Response(200,json=TOKEN)
    h.oauth.transport=httpx.MockTransport(revoke)
    assert h.oauth.google_callback(job.id,h.actor,'code').status=='failed'
    assert 'new-refresh' not in (h.directory/'.env').read_text()


def test_google_unrelated_env_change_during_exchange_fails_safely(oauth):
    h=oauth
    job=start(h)
    path=h.directory/'.env'
    path.write_text(path.read_text()+'\nOTHER_VALUE=changed\n')
    assert h.oauth.google_callback(job.id,h.actor,'code').status=='failed'
    assert 'new-refresh' not in path.read_text()


def test_completed_oauth_receipt_survives_another_start(oauth):
    h=oauth
    job=start(h)
    h.oauth.google_callback(job.id,h.actor,'code')
    start(h,'microsoft')
    repeated=h.oauth.start('google',h.actor,1,job.key,'already-completed-revision')
    assert repeated.id==job.id and repeated.status=='done'


def test_google_expiry_wrong_provider_stale_form_and_missing_clients(oauth):
    h=oauth
    with pytest.raises(PermissionError): h.oauth.start('google','web:wrong',1,'valid-key','revision')
    with pytest.raises(PermissionError): h.oauth.start('google',h.actor,1,'x','revision')
    with pytest.raises(ValueError): h.oauth.start('google',h.actor,1,'valid-key','stale')
    job=start(h,'microsoft')
    with pytest.raises(ValueError): h.oauth.google_callback(job.id,h.actor,'code')
    job=start(h)
    with pytest.raises(ValueError): h.oauth.google_callback(job.id,h.actor,'')
    h.time[0]=job.expires
    with pytest.raises(ValueError): h.oauth.google_callback(job.id,h.actor,'code')
    h.oauth.tick(job.id)
    assert h.oauth.job(job.id,h.actor).status=='expired'
    h.oauth.tick(job.id)
    env=h.directory/'.env'
    env.write_text('MAILHELP_WEB_SECRET='+'s'*40+'\n')
    with pytest.raises(ValueError,match='Clientdaten'):start(h)


@pytest.mark.parametrize('error,status,interval',[
    ('authorization_pending','pending',1),('slow_down','pending',6),('access_denied','failed',1),
    ('expired_token','failed',1),('bad-json','failed',1),('missing-field','failed',1),
    ('invalid-token','failed',1),('missing-refresh','failed',1),('wrong-type','failed',1)])
def test_microsoft_poll_results(oauth,error,status,interval):
    h=oauth
    job=start(h,'microsoft')
    h.oauth.tick(job.id)
    pending=h.oauth.job(job.id,h.actor)
    assert pending.status=='pending' and pending.user_code=='ABCD-EFGH'
    h.oauth.tick(job.id)
    assert len(h.calls)==1  # No early polling.
    def reply(req):
        if error=='bad-json': return httpx.Response(400,text='invalid')
        if error=='missing-field': return httpx.Response(400,json={})
        if error=='invalid-token': return httpx.Response(200,json={})
        if error=='missing-refresh':return httpx.Response(200,json={**TOKEN,'refresh_token':None})
        if error=='wrong-type':return httpx.Response(200,json={**TOKEN,'token_type':'Other'})
        return httpx.Response(400,json={'error':error})
    h.oauth.transport=httpx.MockTransport(reply)
    h.time[0]=pending.next_poll
    h.oauth.tick(job.id)
    updated=h.oauth.job(job.id,h.actor)
    assert (updated.status,updated.interval)==(status,interval)


def test_microsoft_restart_success_and_rotated_token_file(oauth):
    h=oauth
    job=start(h,'microsoft')
    h.oauth.tick(job.id)
    previous=h.oauth
    h.oauth=BrowserOAuth(h.directory,h.store,previous.authorize,previous.config,previous.sign,
                        transport=previous.transport,clock=previous.clock,changed=h.setup.credentials_changed)
    h.time[0]+=2
    h.oauth.tick(job.id)
    assert h.oauth.job(job.id,h.actor).status=='done'
    assert json.loads((h.directory/'microsoft-token.json').read_text())['refresh_token']=='new-refresh'
    assert 'private-device-secret' not in (h.store.directory/'web-oauth.json').read_text()


@pytest.mark.parametrize('mutation',['revoked','config','device-uri','network','exchanging','committing'])
def test_restart_recovery_refuses_unauthorized_or_unclear_jobs(oauth,mutation):
    h=oauth
    job=start(h,'microsoft')
    if mutation=='revoked':h.auth.revoke(h.session.id)
    elif mutation=='config':
        (h.directory/'.env').write_text((h.directory/'.env').read_text()+'\nMICROSOFT_CLIENT_ID=changed\n')
    elif mutation=='device-uri':
        h.oauth.transport=httpx.MockTransport(lambda req:httpx.Response(200,json={**DEVICE,'verification_uri':'https://evil.test'}))
    elif mutation=='network':
        def fail(req):raise httpx.ConnectError('private-server-body')
        h.oauth.transport=httpx.MockTransport(fail)
    elif mutation=='exchanging':job.status='exchanging';h.oauth._update(job)
    else:
        job.status,job.token='committing','recovered-token'
        h.oauth._update(job)
    h.oauth.tick(job.id)
    assert h.oauth.state().jobs[0].status==('blocked' if mutation in {'revoked','config'} else 'done' if mutation=='committing' else 'failed')


def test_jobs_bound_queue_capacity_and_valid_profile(oauth):
    h=oauth
    job=start(h)
    state=h.oauth.state()
    state.jobs=[job.model_copy(update={'id':f'{i:064x}','key':f'{i:032x}'}) for i in range(100)]
    h.oauth._save(state)
    with pytest.raises(ValueError,match='offene'):start(h,key='new-valid-key')
    with pytest.raises(KeyError):h.oauth.config(99,'google')
    state.jobs[0].status='done'
    h.oauth._save(state)
    accepted=start(h,key='capacity-fresh-key')
    assert accepted.key=='capacity-fresh-key' and len(h.oauth.state().jobs)==100


def test_finish_existing_token_recovery_is_idempotent(oauth):
    h=oauth
    job=start(h)
    job.status,job.token='committing','synthetic-refresh'
    h.oauth._update(job)
    h.oauth.tick(job.id)
    assert h.oauth.job(job.id,h.actor).status=='done'


def test_token_arriving_after_oauth_expiry_is_not_committed(oauth):
    h=oauth
    job=start(h)
    def late(req):
        h.time[0]=job.expires
        return httpx.Response(200,json=TOKEN)
    h.oauth.transport=httpx.MockTransport(late)
    assert h.oauth.google_callback(job.id,h.actor,'code').status=='failed'
    assert 'new-refresh' not in (h.directory/'.env').read_text()


@pytest.mark.parametrize('io_failure',[False,True])
def test_background_device_worker_progresses_or_preserves_a_failed_io_commit(oauth,io_failure):
    from threading import Event
    h=oauth
    job=start(h,'microsoft')
    called=Event()
    def provider(req):
        called.set()
        h.oauth.stopped.set()
        if io_failure:raise OSError('synthetic disk unavailable')
        return httpx.Response(200,json=DEVICE)
    h.oauth.transport=httpx.MockTransport(provider)
    worker=h.oauth.start_worker()
    try:
        assert called.wait(5)
    finally:
        h.oauth.stop()
    assert not worker.is_alive()
    assert h.oauth.job(job.id,h.actor).status==('starting' if io_failure else 'pending')


def test_stopping_a_not_yet_started_worker_is_safe(oauth):
    oauth.oauth.stop()


def test_microsoft_client_secret_and_profile_names(oauth):
    h=oauth
    raw=h.setup.state()
    raw.config['target_profiles']=[{'id':2,'label':'Work','google_calendar':'primary','todoist_project':'inbox'}]
    h.setup._save(raw)
    h.setup.save(h.actor,h.form(4,MICROSOFT_CLIENT_SECRET='private-client-secret'))
    job=h.oauth.start('microsoft',h.actor,2,'work-key-1',h.oauth.revision(2,'microsoft'))
    h.oauth.tick(job.id)
    h.time[0]+=2
    h.oauth.tick(job.id)
    assert json.loads((h.directory/'microsoft-token-2.json').read_text())['refresh_token']=='new-refresh'
    assert b'client_secret=private-client-secret' in h.calls[-1].content
    assert 'MICROSOFT_2_REFRESH_TOKEN=new-refresh' in (h.directory/'.env').read_text()


@pytest.mark.parametrize('mode',['pages','loop','limit','bad-item','invalid-page','http-error'])
def test_calendar_choices_use_read_only_requests_and_validate_pages(oauth,mode):
    h=oauth
    calls=[]
    def provider(req):
        calls.append(req)
        if req.url.host=='oauth2.googleapis.com':return httpx.Response(200,json=TOKEN)
        assert req.method=='GET'
        if mode=='http-error':return httpx.Response(403,json={'error':'denied'})
        items=[{'id':'primary','summary':'Personal','accessRole':'owner'},
               {'id':'read','summary':'Read only','accessRole':'reader'}]
        if mode=='bad-item':items[0]['id']=1
        page=req.url.params['pageToken']
        body={'items':items}
        if mode in {'loop','limit'}:body['nextPageToken']=str(len(calls)) if mode=='limit' else 'same'
        elif mode=='invalid-page':body['nextPageToken']=1
        elif not page:body['nextPageToken']='second'
        return httpx.Response(200,json=body)
    transport=httpx.MockTransport(provider)
    if mode=='pages':
        assert google_calendars(h.directory,1,h.oauth.config(1,'google'),transport)==[('primary','Personal')]*2
    else:
        with pytest.raises((ValueError,httpx.HTTPError)):
            google_calendars(h.directory,1,h.oauth.config(1,'google'),transport)
