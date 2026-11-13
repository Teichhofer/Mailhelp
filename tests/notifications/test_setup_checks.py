"""Read-only setup probes with HTTP/IMAP doubles and credential validation."""
from types import SimpleNamespace

import httpx
import pytest

from mailhelp.config import Settings
from mailhelp.runtime import setup_checks as module
from mailhelp.runtime.setup_checks import SetupChecks, setup_secrets
from tests.fakes.initial_harness import initial


def test_imap_probe_uses_special_use_roles_and_closes_on_failure(initial,monkeypatch):
    h=initial
    h.advance()
    calls=[]
    class Reader:
        def __init__(self,*args,**kwargs):calls.append((args,kwargs))
        def list_folders(self):return [SimpleNamespace(name='INBOX',role='inbox'),SimpleNamespace(name='Entwürfe',role='drafts')]
        def check_access(self,folders):calls.append(folders)
        def close(self):calls.append('closed')
    monkeypatch.setattr(module,'ImapReader',Reader)
    cfg=Settings.model_validate(h.setup.state().config)
    checks=SetupChecks(h.directory)
    result=checks.imap(cfg,h.setup.environment())
    assert {key:result[key] for key in ('folders','inbox','drafts')}=={'folders':['INBOX','Entwürfe'],'inbox':'INBOX','drafts':'Entwürfe'}
    assert calls[-1]=='closed' and calls[0][0][2]=='user@example.test'
    monkeypatch.setattr(Reader,'list_folders',lambda self:[])
    assert checks.imap(cfg,h.setup.environment())['drafts']==''
    monkeypatch.setattr(Reader,'check_access',lambda *a:(_ for _ in ()).throw(OSError('synthetic')))
    with pytest.raises(OSError):checks.imap(cfg,h.setup.environment())
    assert calls[-1]=='closed'
    with pytest.raises(ValueError):checks.imap(cfg,{})


@pytest.mark.parametrize('mode',['ready','credits-denied','credits-unauthorized','missing-model','bad-limit','http-error'])
def test_openrouter_reports_key_budget_and_model_availability_without_charging(initial,mode):
    h=initial
    h.advance()
    cfg=Settings.model_validate(h.setup.state().config)
    prompts=h.setup.prompts(h.setup.state())
    names={route.model for name in prompts.prompts for route in prompts.resolved_routes(name)[0]}
    calls=[]
    def provider(req):
        calls.append(req)
        assert req.method=='GET' and req.headers['Authorization']=='Bearer synthetic-router-key'
        if req.url.path.endswith('/key'):
            return httpx.Response(200,json={'data':{'limit_remaining':'bad' if mode=='bad-limit' else None}})
        if req.url.path.endswith('/models'):
            return httpx.Response(200,json={'data':[{'id':name} for name in names] if mode!='missing-model' else []})
        if mode in {'credits-denied','credits-unauthorized','http-error'}:
            return httpx.Response({'credits-denied':403,'credits-unauthorized':401,'http-error':503}[mode])
        return httpx.Response(200,json={'data':{'total_credits':10,'total_usage':2}})
    checks=SetupChecks(h.directory,httpx.MockTransport(provider))
    if mode in {'missing-model','bad-limit','http-error'}:
        with pytest.raises((ValueError,httpx.HTTPError)):checks.llm(cfg,h.setup.environment(),prompts)
    else:
        result=checks.llm(cfg,h.setup.environment(),prompts)
        assert result['balance']==(8 if mode=='ready' else None)
        assert set(result['models'])==names
    with pytest.raises(ValueError,match='llm.key_missing'):checks.llm(cfg,{},prompts)


@pytest.mark.parametrize('models',[[],[{'name':123}],[{'name':''}],[{'name':'synthetic:latest'}]])
def test_ollama_installed_model_list(initial,models):
    h=initial
    h.advance(True)
    cfg=Settings.model_validate(h.setup.state().config)
    checks=SetupChecks(h.directory,httpx.MockTransport(lambda req:httpx.Response(200,json={'models':models})))
    if models==[{'name':'synthetic:latest'}]:
        assert checks.llm(cfg,{},h.setup.prompts(h.setup.state()))=={'models':['synthetic:latest']}
    else:
        with pytest.raises(ValueError):checks.llm(cfg,{},h.setup.prompts(h.setup.state()))


def test_targets_only_check_access_and_close_all_resources(initial,monkeypatch):
    h=initial
    h.advance()
    cfg=Settings.model_validate(h.setup.state().config)
    env=h.setup.environment()
    assert setup_secrets(cfg,env).google_oauth_refresh_token.get_secret_value()=='synthetic-refresh'
    with pytest.raises(ValueError,match='target.secret_missing'):setup_secrets(cfg,{})
    calls=[]
    def check():calls.append('check')
    writers=SimpleNamespace(calendar=SimpleNamespace(check_access=check),tasks=SimpleNamespace(check_access=check),
                            close=lambda:calls.append('close'))
    monkeypatch.setattr(module,'build_writers',lambda *a,**kw:writers)
    assert SetupChecks(h.directory).targets(cfg,env)['ready'] is True
    assert calls==['check','check','close']
    writers.tasks.check_access=lambda:(_ for _ in ()).throw(RuntimeError('private-provider-body'))
    with pytest.raises(RuntimeError):SetupChecks(h.directory).targets(cfg,env)
    assert calls[-1]=='close'
    cfg.llm.provider='ollama'
    del env['OPENROUTER_API_KEY']
    assert setup_secrets(cfg,env).openrouter_api_key.get_secret_value()==''
