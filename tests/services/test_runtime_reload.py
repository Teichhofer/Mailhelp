"""Generation swap failure isolation, request replay and real shared-store construction."""

from contextlib import ExitStack, contextmanager
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from learning_harness import learning
from shared_review import mail_state

from mailhelp.runtime import composition
from mailhelp.runtime.lifecycle import Lifecycle
from mailhelp.runtime.reload import ReloadService
from mailhelp.web.reload_site import ReloadSite


def service(h):
    old = h.app
    old.web_site = h.site
    old.web = Mock(handler=h.web)
    old.lifecycle = Lifecycle(lambda: None, h.jobs.active)
    old.resources = Mock()
    old.logger = Mock()
    old.stop_event = Mock()
    old._wait_for_user = True
    return ReloadService(old, h.directory, h.worker.secrets)


def test_reload_requests_are_versioned_idempotent_and_authorized(learning):
    h = learning
    r = service(h)
    rev = r.revision()
    r.request(h.actor, 0, "request01", rev)
    r.request(h.actor, 0, "request01", rev)
    assert r.state().version == 1 and r.state().status == "pending"
    for args in [
        (h.actor, 1, "request01", rev),
        (h.actor, 0, "request02", rev),
        (h.actor, 1, "request02", "0" * 64),
        (h.actor, 1, "bad", rev),
        ("invalid", 1, "request02", rev),
        (h.actor, 1, "request02", rev),
    ]:
        with pytest.raises(ValueError):
            r.request(*args)
    h.auth.revoke_all()
    with pytest.raises(ValueError):
        r.request(h.actor, 1, "request03", rev)


@pytest.mark.parametrize("late", [False, True])
def test_revocation_during_prepare_never_changes_running_generation(learning, monkeypatch, late):
    h = learning
    r = service(h)
    old = r.current
    calls = []
    monkeypatch.setattr(r, "helpers", lambda app, start: calls.append(start))
    r.request(h.actor, 0, "request01", r.revision())

    def build(app, stack):
        h.auth.revoke_all()
        return NS(web=Mock(handler=object())), r.secrets

    monkeypatch.setattr(r, "_build", build)
    if not late:
        h.auth.revoke_all()
    r.advance()
    assert r.current is old and r.state().status == "failed"
    old.web.replace_handler.assert_not_called()
    assert calls == ([False, True] if late else [])
    assert old.lifecycle.state == "running"
    r.close()


def test_generation_swap_closes_old_connections_only_after_commit(learning, monkeypatch):
    h = learning
    r = service(h)
    old = r.current
    events = []
    monkeypatch.setattr(r, "helpers", lambda app, start: events.append((app, start)))
    new = NS(web=Mock(handler="new-handler"), web_site=h.site)
    monkeypatch.setattr(r, "_build", lambda app, stack: (new, r.secrets))
    old.resources.close.side_effect = lambda: events.append("closed")
    r.advance()
    assert events == []
    r.request(h.actor, 0, "request01", r.revision())
    r.advance()
    assert r.current is new and new.web is old.web
    assert new._wait_for_user is True
    old.web.replace_handler.assert_called_once_with("new-handler")
    assert events == [(old, False), "closed", (new, True)]
    assert r.state().status == "done"
    r.advance()
    r.close()


def test_unfinished_analysis_blocks_generation_change_without_stranding_mail(learning, monkeypatch):
    h = learning
    r = service(h)
    state = mail_state()
    h.store.save("mail-" + state.id, state.model_dump(mode="json"))
    monkeypatch.setattr(r, "_build", lambda *_: pytest.fail("Must finish old analysis first"))
    r.request(h.actor, 0, "request01", r.revision())
    r.advance()
    assert r.state().status == "pending" and "Unfertige" in r.state().message


def test_config_race_and_preparation_error_keep_previous_generation(learning, monkeypatch):
    h = learning
    r = service(h)
    calls = []
    monkeypatch.setattr(r, "helpers", lambda app, start: calls.append(start))
    r.request(h.actor, 0, "request01", r.revision())

    def fail(*_):
        raise OSError("synthetic-secret")

    monkeypatch.setattr(r, "_build", fail)
    r.advance()
    assert calls == [False, True] and r.state().status == "failed"
    assert "synthetic-secret" not in r.state().model_dump_json()
    r.request(h.actor, r.state().version, "request02", r.revision())
    (h.directory / "topics.yaml").write_text("changed", encoding="utf8")
    r.advance()
    assert r.state().status == "failed" and calls == [False, True]


@pytest.mark.parametrize("what", ["data", "mode", "web", "secret", "ollama_missing", "ollama", "imap_failed", "cloud"])
def test_prepared_configuration_guards_and_local_model_selection(learning, monkeypatch, what):
    from mailhelp.config import load_all
    from mailhelp.runtime import reload

    h = learning
    r = service(h)
    values = list(load_all(h.directory, h.initial.setup.environment()))
    if what == "data":
        values[0] = values[0].model_copy(update={"data_directory": h.directory / "elsewhere"})
    if what == "mode":
        values[0] = values[0].model_copy(update={"test_mode": not values[0].test_mode})
    if what == "web":
        values[0] = values[0].model_copy(update={"web": values[0].web.model_copy(update={"port": 8888})})
    if what == "secret":
        values[1] = values[1].model_copy(update={"mailhelp_web_secret": "changed"})
    if what.startswith("ollama"):
        values[0] = values[0].model_copy(update={"llm": values[0].llm.model_copy(update={"provider": "ollama"})})
        if what == "ollama_missing":
            values[4] = values[4].model_copy(update={"ollama": None})
    monkeypatch.setattr(reload, "load_all", lambda *_: values)
    captured = {}

    @contextmanager
    def build(*args, **kwargs):
        captured.update(kwargs)
        reader = type("_FailedAccessAdapter", (), {})() if what == "imap_failed" else object()
        yield NS(sources=[NS(reader=reader)],openrouter=Mock(),telegram=Mock(),_active_writers=lambda:[])

    monkeypatch.setattr(composition, "build_application", build)
    with ExitStack() as stack:
        if what in {"ollama", "cloud"}:
            new, sec = r._build(r.current, stack)
            assert captured["shared_store"] is h.store and captured["reload_service"] is r
            assert (captured["local_llm"] is not None) == (what == "ollama")
        else:
            with pytest.raises(ValueError):
                r._build(r.current, stack)


def test_helpers_stop_before_swap_and_start_afterwards():
    app = Mock()
    ReloadService.helpers(app, False)
    app.services.stop_operator.assert_called_once()
    app.services.stop_receiver.assert_called_once()
    app.services.oauth.stop.assert_called_once()
    app.services.learning.stop.assert_called_once()
    app.experience.stop.assert_called_once()
    ReloadService.helpers(app, True)
    app._start_receiver.assert_called_once()
    app._start_operator.assert_called_once()
    app.services.oauth.start_worker.assert_called_once()
    app.services.learning.start.assert_called_once()
    app.experience.start.assert_called_once()
    app.services.diagnostics.stop.assert_called_once()
    app.services.oauth = app.services.learning = app.experience = app.services.diagnostics = None
    ReloadService.helpers(app, True)
    ReloadService.helpers(app, False)
    # Without diagnostics the operator and receiver are still stopped.
    assert app.services.stop_operator.call_count == app.services.stop_receiver.call_count == 2


def test_reload_browser_routes_bind_versions_and_csrf(learning):
    h = learning
    r = service(h)
    ReloadSite(h.site, r)
    assert h.browser.request("GET", "/dienst/neu-laden").status == 200
    assert h.browser.request("POST", "/dienst/neu-laden", {}).status == 403
    form = {
        "csrf": h.auth.csrf_token(h.initial.session.id),
        "version": 0,
        "key": "browserkey01",
        "revision": r.revision(),
    }
    assert h.browser.request("POST", "/dienst/neu-laden", form).status == 303
    assert b'http-equiv="refresh"' in h.browser.request("GET", "/dienst/neu-laden").body
    assert h.browser.request("POST", "/dienst/neu-laden", form | {"version": 3}).status == 409


@pytest.mark.parametrize('cleanup_error',[False,True])
def test_committed_generation_starts_even_if_old_resource_cleanup_fails(learning,monkeypatch,cleanup_error):
    h=learning;r=service(h);old=r.current;events=[]
    new=NS(web=Mock(handler=object()),web_site=h.site)
    monkeypatch.setattr(r,'_build',lambda app,stack:(new,r.secrets))
    if cleanup_error:old.resources.close.side_effect=OSError('cleanup')
    def helpers(app,start):
        events.append((app,start))
        if app is new and not cleanup_error:raise OSError('background')
    monkeypatch.setattr(r,'helpers',helpers)
    r.request(h.actor,0,'request01',r.revision());r.advance()
    assert r.current is new and (new,True) in events
    if cleanup_error:assert r.state().status=='done'
    else:assert r.state().status=='failed' and 'aktiv' in r.state().message


def test_real_composition_replaces_generations_with_one_live_store(learning,monkeypatch):
    from mailhelp.config import load_all
    from mailhelp.external import providers
    h=learning;closed=[]
    class Resource:
        service='synthetic'
        policy=NS(retries=0)
        def __init__(self,*args,**kwargs):pass
        def check_access(self,*args):pass
        def close(self):closed.append(self)
    class Reader(Resource):
        account_id='0'*24
    monkeypatch.setattr(composition,'ImapReader',Reader)
    monkeypatch.setattr(composition,'OpenRouterClient',Resource)
    monkeypatch.setattr(providers,'HttpWriter',Resource)
    monkeypatch.setattr(providers,'GoogleOAuthTokenProvider',Resource)
    cfg,sec,topics,_,prompts,fp=load_all(h.directory,h.initial.setup.environment())
    with composition.build_application(cfg,sec,topics,prompts,fp,h.directory,shared_store=h.store,
                                       use_jev_relevance=False) as app:
        r=app.reload
        monkeypatch.setattr(r,'helpers',lambda *_:None)
        old_reader=app.imap
        h.store.save('generation-proof',{'value':'kept'})
        path=h.directory/'topics.yaml'
        path.write_text(path.read_text(encoding='utf8')+'\n',encoding='utf8')
        r.request(h.actor,0,'reloadreal01',r.revision())
        r.advance()
        assert r.state().status=='done' and r.current is not app
        assert r.current.store is app.store is h.store and old_reader in closed
        assert r.current.reload is r
        assert r.current.web.handler is not h.web
        assert h.store.load('generation-proof')=={'value':'kept'}
        r.close()
