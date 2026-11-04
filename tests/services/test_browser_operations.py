"""Self-test authorization, bounded key replay, monthly costs and real HTTP handler swapping."""
from datetime import UTC, datetime
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from learning_harness import learning
from shared_web_server import call

from mailhelp.runtime.diagnostics import DiagnosticsService
from mailhelp.runtime.metrics import MetricsRecorder, MetricsSettings
from mailhelp.web import Response, WebServer
from mailhelp.web.reload_site import ReloadSite


def test_selftest_runs_independent_read_only_components_and_skips_write_tests(learning):
    h=learning; calls=[]
    def check(name):
        def run(actor):calls.append(name);return 'ready',''
        return run
    service=DiagnosticsService(h.store,h.auth.active,{'imap':check('imap'),'calendar':check('calendar'),
        'telegram_test':lambda _:pytest.fail('No explicit permission for messages'),
        'tasks':lambda _:(_ for _ in ()).throw(ConnectionError('secret'))})
    actor=h.initial.session.id
    thread=service.run_all(actor,0,'a'*80)
    thread.join(10)
    assert not thread.is_alive() and calls==['imap','calendar']
    assert service.state().results['tasks'].code=='network'
    assert service.run_all(actor,0,'a'*80) is None
    for version,key in [(1,'a'*80),(0,'otherkey01'),(service.state().version,'bad')]:
        with pytest.raises(ValueError):service.run_all(actor,version,key)
    service._busy.add('imap')
    with pytest.raises(ValueError):service.run_all(actor,service.state().version,'otherkey02')
    h.auth.revoke_all()
    with pytest.raises(PermissionError):service.run_all(actor,service.state().version,'otherkey03')


def test_selftest_stops_when_session_is_revoked_between_checks(learning):
    h=learning; calls=[]
    def first(actor):h.auth.revoke_all();return 'ready',''
    service=DiagnosticsService(h.store,h.auth.active,{'first':first,'second':lambda _:calls.append('second')})
    thread=service.run_all(h.initial.session.id,0,'selftest01')
    thread.join(10)
    assert not calls and not thread.is_alive()


def test_selftest_page_starts_in_background_and_reports_stale_version(learning,monkeypatch):
    h=learning
    service=DiagnosticsService(h.store,h.auth.active,{'imap':lambda _:('ready','')})
    threads=[]
    original=service.run_all
    def start(*args):
        thread=original(*args)
        threads.append(thread)
        return thread
    monkeypatch.setattr(service,'run_all',start)
    h.site.setup_page.runtime=NS(diagnostics=service,update_profile_checks=lambda:None)
    ReloadSite(h.site,Mock())
    assert h.browser.request('GET','/dienst/selbsttest').status==200
    form={'csrf':h.auth.csrf_token(h.initial.session.id),'version':'invalid','key':'selftest01'}
    assert h.browser.request('POST','/dienst/selbsttest',form).status==409
    assert h.browser.request('POST','/dienst/selbsttest',form|{'version':'0'}).status==303
    threads[0].join(10)
    assert not threads[0].is_alive()


def test_selftest_stops_and_drains_before_closing_runtime_resources(learning):
    from threading import Event, Thread
    h=learning;entered,release=Event(),Event();calls=[]
    def held(actor):entered.set();assert release.wait(10);return 'ready',''
    service=DiagnosticsService(h.store,h.auth.active,{'first':held,'second':lambda _:calls.append('unexpected')})
    worker=service.run_all(h.initial.session.id,0,'selftest01')
    assert entered.wait(10)
    with pytest.raises(ValueError):service.run_all(h.initial.session.id,service.state().version,'selftest02')
    stopper=Thread(target=service.stop)
    stopper.start();assert service.stopped.wait(10)
    release.set();stopper.join(10);worker.join(10)
    assert not stopper.is_alive() and not worker.is_alive() and not calls
    service.stop()


def test_month_cost_uses_configured_month_including_boundary_and_unknown_prices(tmp_path,monkeypatch):
    metrics=MetricsRecorder(tmp_path/'metrics.jsonl',MetricsSettings())
    rows=[{'started_at':'2026-10-31T23:30:00+00:00','cost_usd':'0.15','provider':'cloud'},
          {'started_at':'2026-10-31T22:30:00+00:00','cost_usd':'9.99','provider':'cloud'},
          {'started_at':'2026-11-01T12:00:00+00:00','cost_usd':None,'provider':'cloud'},
          {'started_at':'2026-11-01T12:00:00+00:00','cost_usd':None,'provider':'ollama'}]
    monkeypatch.setattr(metrics,'report',lambda **_:{'records':rows})
    assert metrics.month_cost(datetime(2026,11,4,tzinfo=UTC),'Europe/Berlin')==('0.15',1)
    monkeypatch.setattr(metrics,'report',lambda **_:{'records':[]})
    assert metrics.month_cost(datetime(2026,11,4,tzinfo=UTC),'UTC')==('0',0)


def test_existing_listening_socket_swaps_handler_atomically(running):
    server,_=running(lambda _:Response.text(200,'old'))
    address=server.address
    server.replace_handler(lambda _:Response.text(200,'new'))
    assert server.address==address and call(server,'GET','/')[2]==b'new'
    server.stop()
    server.replace_handler(lambda _:Response.text(200,'not running'))
    assert server.handler(None).body==b'not running'


def test_application_loop_runs_and_finishes_the_selected_generation(monkeypatch):
    from threading import Event

    from mailhelp.runtime.application import Application
    root=Mock(stop_event=Event())
    new=Mock(_fatal_error=None)
    new._cycle.return_value=False
    root.reload.current=new
    assert Application.run(root) is None
    root.reload.advance.assert_called_once()
    new._cycle.assert_called_once_with(None,False)
    new._finish.assert_called_once_with(None)
    root.reload.close.assert_called_once()


@pytest.mark.parametrize('activity',[None,False,True])
@pytest.mark.parametrize('thread',[False,True])
def test_generation_waits_for_old_report_and_background_clients(activity,thread):
    from mailhelp.runtime.experience import ExperienceRuntime
    service=ExperienceRuntime.__new__(ExperienceRuntime)
    report=Mock()
    service.activity=None if activity is None else NS(thread=report if activity else None)
    service.thread=Mock() if thread else None
    service.wait_stopped()
    assert report.join.call_count==int(activity is True)
    if thread:service.thread.join.assert_called_once_with()
