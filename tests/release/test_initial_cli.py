"""CLI handoff to first-run setup and host-only password recovery."""
import json
import re
import socket
import sys
from types import SimpleNamespace

import pytest
import yaml

from mailhelp import cli
from mailhelp.runtime import bootstrap, local_pairing
from mailhelp.runtime.web_password import WebPassword
from tests.fakes.initial_harness import initial


def test_first_run_terminal_output_is_delivered_even_without_a_tty(monkeypatch):
    class BufferedPipe:
        def __init__(self):self.pending='';self.delivered=''
        def write(self,text):self.pending+=text
        def flush(self):self.delivered+=self.pending;self.pending=''
    pipe=BufferedPipe()
    monkeypatch.setattr(sys,'stdout',pipe)
    bootstrap.console('synthetic-authentication-marker')
    assert pipe.delivered=='synthetic-authentication-marker\n' and not pipe.pending


def test_empty_start_finishes_setup_without_replacing_the_process(tmp_path,monkeypatch):
    calls=[]
    monkeypatch.setattr(sys,'argv',['mailhelp','--config-directory',str(tmp_path)])
    monkeypatch.setattr(bootstrap,'run_initial_setup',lambda directory,shutdown:calls.append(directory) or 75)
    monkeypatch.setattr(cli,'_restart',lambda:pytest.fail('No process restart after setup'))
    def loaded(directory):
        assert calls==[tmp_path]
        raise RuntimeError('normal mode reached')
    monkeypatch.setattr(cli,'load_all',loaded)
    with pytest.raises(RuntimeError,match='normal mode reached'):cli.main()
    assert calls==[tmp_path]


def test_host_password_reset_requires_no_provider_credentials(initial,monkeypatch,capsys):
    h=initial
    WebPassword(h.store).set('synthetic-password',0)
    (h.directory/'config.yaml').write_text(yaml.safe_dump(h.setup.state().config))
    h.store.__exit__(None,None,None)
    monkeypatch.setattr(sys,'argv',['mailhelp','--reset-web-password','--config-directory',str(h.directory)])
    assert cli.main()==0 and 'zurückgesetzt' in capsys.readouterr().out
    assert not WebPassword(h.store).state().digest and not h.auth.active(h.session.id)


def test_bootstrap_secret_generation_and_existing_secret(initial,monkeypatch):
    h=initial
    assert bootstrap.ensure_web_secret(h.directory)==h.auth._key.decode()
    monkeypatch.setenv('MAILHELP_WEB_SECRET','too-short')
    with pytest.raises(ValueError):bootstrap.ensure_web_secret(h.directory)
    monkeypatch.setenv('MAILHELP_WEB_SECRET','s'*32+'\n')
    with pytest.raises(ValueError):bootstrap.ensure_web_secret(h.directory)


@pytest.mark.parametrize('done',[False,True])
def test_real_bootstrap_listener_stops_cleanly_and_never_logs_the_terminal_code(tmp_path,monkeypatch,done):
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1',0))
        port=reservation.getsockname()[1]
    monkeypatch.setenv('MAILHELP_SETUP_HOST','127.0.0.1')
    monkeypatch.setenv('MAILHELP_SETUP_PORT',str(port))
    monkeypatch.setenv('MAILHELP_SETUP_ALLOWED_HOSTS','')
    monkeypatch.delenv('MAILHELP_WEB_SECRET',raising=False)
    original=bootstrap.create_initial
    captured={}
    def create(*args,**kwargs):
        result=original(*args,**kwargs)
        captured['setup']=result[2]
        return result
    monkeypatch.setattr(bootstrap,'create_initial',create)
    shutdown=SimpleNamespace(stop=None)
    emitted=[]
    def emit(text):
        emitted.append(text)
        if 'Authentifizierungscode:' in text:
            if done:
                state=captured['setup'].state()
                state.status='done'
                captured['setup']._save(state)
            shutdown.stop()
    assert bootstrap.run_initial_setup(tmp_path,shutdown,emit=emit)==(75 if done else 0)
    code=re.search(r'Authentifizierungscode: (\d{4})',emitted[-1]).group(1)
    logs=''.join(path.read_text() for path in (tmp_path/'logs').rglob('*.jsonl'))
    assert code not in logs


def test_pair_command_can_request_a_new_terminal_code_while_setup_is_running(initial,monkeypatch,capsys):
    h=initial
    calls=[]
    class Client:
        def __init__(self,**kw):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,url,data):
            calls.append((url,data))
            return SimpleNamespace(raise_for_status=lambda:None,json=lambda:{'code':'1234'})
    monkeypatch.setattr(local_pairing.httpx,'Client',Client)
    local_pairing.request_local_code(h.directory)
    assert calls[0][0]=='http://127.0.0.1:8765/api/local-pair'
    assert 'Einmalcode: 1234' in capsys.readouterr().out


def test_reopening_initial_setup_keeps_the_draft_and_rejects_other_target_profiles(initial,monkeypatch):
    from threading import Event

    from mailhelp.config import WebSettings
    from mailhelp.logging import NullLogger
    h=initial
    h.advance()
    captured={}
    monkeypatch.setattr(bootstrap,'OAuthSite',lambda site,service,context,save:captured.update(context=context,save=save))
    bootstrap.create_initial(h.directory,h.store,WebSettings(enabled=True),Event(),NullLogger())
    assert captured['context'](1)==('primary',h.setup.state().version)
    with pytest.raises(ValueError):captured['context'](2)
    captured['save'](h.actor,1,'selected',h.setup.state().version,'c'*32)
    assert h.setup.state().config['targets']['google_calendar']=='selected'


def test_busy_setup_port_is_reported_without_a_traceback(tmp_path,monkeypatch,capsys):
    from mailhelp.web.server import WebServerError
    monkeypatch.setattr(sys,'argv',['mailhelp','--config-directory',str(tmp_path)])
    def busy(*args):raise WebServerError('Einrichtungsport belegt')
    monkeypatch.setattr(bootstrap,'run_initial_setup',busy)
    assert cli.main()==1
    assert capsys.readouterr().err.strip()=='Einrichtungsport belegt'


def test_invalid_cli_options_do_not_start_a_waiting_setup_server(tmp_path,monkeypatch):
    monkeypatch.setattr(sys,'argv',['mailhelp','--config-directory',str(tmp_path),'--ollama-model','synthetic'])
    def unexpected(*args):pytest.fail('Invalid CLI options must not open the setup server')
    monkeypatch.setattr(bootstrap,'run_initial_setup',unexpected)
    monkeypatch.setattr(cli,'load_all',lambda directory:(SimpleNamespace(llm=SimpleNamespace(provider='openrouter')),
        None,[],[],SimpleNamespace(ollama=None),'fingerprint'))
    with pytest.raises(SystemExit):cli.main()


@pytest.mark.slow
@pytest.mark.parametrize('local',[False,True])
def test_completed_wizard_restarts_into_first_real_poll_with_simulated_services(initial,monkeypatch,local):
    from mailhelp.external import providers
    from mailhelp.runtime import composition
    h=initial
    h.advance(local)
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1',0))
        port=reservation.getsockname()[1]
    state=h.setup.state()
    state.config['web'].update(port=port,allowed_hosts=[f'localhost:{port}',f'127.0.0.1:{port}'])
    h.setup._save(state)
    h.setup.finish(h.actor,state.version,'b'*32)
    h.store.__exit__(None,None,None)
    seen=[]
    class Resource:
        service='synthetic'
        def __init__(self,*args,**kwargs):pass
        def check_access(self,*args):pass
        def close(self):pass
        def complete(self,*args,**kwargs):pytest.fail('No mail means no model call')
        def create(self,*args,**kwargs):pytest.fail('No confirmation means no external write')
    class Reader(Resource):
        account_id='0'*24
        last_uidvalidity=7
        def determine_start_uid(self,*args):return 0
        def discover_since(self,folder,*args):seen.append(folder);return []
        def list_folders(self):return [SimpleNamespace(name='INBOX',flags=frozenset(),role='inbox')]
    monkeypatch.setattr(composition,'ImapReader',Reader)
    monkeypatch.setattr(composition,'OpenRouterClient',Resource)
    monkeypatch.setattr(composition,'OllamaClient',Resource)
    monkeypatch.setattr(providers,'HttpWriter',Resource)
    monkeypatch.setattr(providers,'GoogleOAuthTokenProvider',Resource)
    def no_network(*args,**kwargs):pytest.fail('Unexpected external network')
    monkeypatch.setattr(socket.socket,'connect',no_network)
    monkeypatch.setattr(sys,'argv',['mailhelp','--config-directory',str(h.directory),'--max-mails','1'])
    assert cli.main()==0
    assert seen==['INBOX'] and list((h.directory/'data/production').glob('imap-*.json'))
