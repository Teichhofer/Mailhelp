"""First-run configuration uses synthetic credentials and read-only service doubles."""
import json
import os
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import urlencode

import httpx
import pytest
import yaml

from mailhelp.config import Settings, WebSettings, load_all
from mailhelp.config.loader import provider_secret_names
from mailhelp.config.models import TargetSettings
from mailhelp.runtime import initial_setup as module
from mailhelp.runtime.bootstrap import create_initial, ensure_web_secret, run_initial_setup
from mailhelp.runtime.initial_setup import InitialSetup
from mailhelp.runtime.web_password import WebPassword
from mailhelp.web.auth import PairingLimited, PairingRefused
from mailhelp.web.http import Request
from tests.fakes.initial_harness import InitialHarness, initial


def request(h, method, path, form=None, *, token=True, content="application/x-www-form-urlencoded"):
    path, _, query = path.partition("?")
    return h.app(Request(method, path, {"host": "127.0.0.1:8765", "content-type": content,
        "cookie": "mh_session=" + h.token if token else ""}, query, urlencode(form or {}).encode()))


def test_todoist_personal_token_does_not_require_an_unrelated_oauth_client():
    targets = TargetSettings(google_calendar="primary", todoist_project="inbox")
    assert provider_secret_names(targets) == ["TODOIST_TOKEN", "GOOGLE_OAUTH_CLIENT_ID",
                                            "GOOGLE_OAUTH_CLIENT_SECRET", "GOOGLE_OAUTH_REFRESH_TOKEN"]


def test_empty_directory_is_protected_and_starts_no_adapters(initial):
    h = initial
    assert not (h.directory / "config.yaml").exists()
    for path in ["/", "/einrichtung/start", "/einrichtung/schritt/1", "/hilfe/google-playground"]:
        assert request(h, "GET", path, token=False).status == 303
    for path in ["/einrichtung/speichern", "/einrichtung/pruefen", "/auth/microsoft/device"]:
        assert request(h, "POST", path, h.form(1), token=False).status == 403
    assert request(h, "GET", "/mail/" + "a"*24).status == 404
    assert request(h, "GET", "/einrichtung/schritt/5").status == 303
    assert b"Web-Zugang" in request(h, "GET", "/").body
    assert h.code not in (h.store.directory / "web-pairing.json").read_text()
    assert h.checks.calls == []


@pytest.mark.parametrize("local", [False, True])
def test_five_steps_finish_validate_and_restart_without_external_writes(initial, local):
    h = initial
    h.advance(local)
    for step in range(1,6):
        response = request(h, "GET", f"/einrichtung/schritt/{step}")
        assert response.status == 200
        assert b"synthetic-client-secret" not in response.body
        assert b"synthetic-imap-password" not in response.body
    response = request(h, "POST", "/einrichtung/speichern", h.form(5, confirm="yes"))
    assert response.status == 200 and response.after_send
    response.after_send()
    assert h.stopped.is_set() and h.setup.state().status == "done"
    cfg, keys, topics, _, prompts, _ = load_all(h.directory, {})
    assert cfg.web.enabled and not cfg.telegram.enabled and topics
    assert cfg.llm.provider == ("ollama" if local else "openrouter")
    assert keys.imap[1].username == "user@example.test"
    assert prompts.ollama.model == "synthetic:latest"
    assert h.checks.calls[:3] == ["imap", "llm", "targets"]
    for path in h.store.directory.glob("*.json"):
        content = path.read_text()
        assert "synthetic-password" not in content and "synthetic-client-secret" not in content


def test_draft_replay_conflict_failure_and_unknown_step(initial):
    h = initial
    form = h.form(1, password="synthetic-password")
    state = h.setup.save(h.actor, form)
    assert h.setup.save(h.actor, form) == state
    with pytest.raises(ValueError, match="Idempotenz"):
        h.setup.save(h.actor, {**form, "timezone": "UTC"})
    with pytest.raises(ValueError, match="conflict"):
        h.setup.save(h.actor, {**h.form(1), "version":"0"})
    for invalid in [{**h.form(2), "step":"0"}, {**h.form(2), "key":"!"}, h.form(4)]:
        with pytest.raises(ValueError):
            h.setup.save(h.actor, invalid)
    assert request(h, "POST", "/einrichtung/speichern", h.form(5)).status == 409
    assert request(h, "POST", "/einrichtung/speichern", {}).status == 403
    assert request(h, "POST", "/einrichtung/speichern", h.form(2), content="application/json").status == 415
    assert request(h, "POST", "/einrichtung/pruefen", h.form(9)).status == 400
    assert request(h, "POST", "/einrichtung/speichern", h.form(1, password="tiny")).status == 409


def test_probes_folders_and_model_choices_use_synthetic_services(initial):
    h = initial
    h.advance(True)
    folders = request(h, "POST", "/einrichtung/pruefen", h.form(2))
    assert folders.status == 200 and b'<option value="Entw' in folders.body
    models = request(h, "POST", "/einrichtung/pruefen", h.form(3, model="synthetic:latest"))
    assert models.status == 200 and b'<option value="synthetic:latest"' in models.body
    assert "Geprüft" in request(h, "POST", "/einrichtung/pruefen", h.form(4)).body.decode()
    h.checks.imap = lambda *a: (_ for _ in ()).throw(RuntimeError("secret-from-server"))
    failed = request(h, "POST", "/einrichtung/pruefen", h.form(2))
    assert failed.status == 200 and b"Pr\xc3\xbcfung fehlgeschlagen" in failed.body
    assert b"secret-from-server" not in failed.body


def test_revocation_during_a_check_shows_nothing_and_finish_is_refused(initial):
    h = initial
    h.advance()
    before = h.setup.state()
    h.checks.imap = lambda *a: h.auth.revoke(h.session.id)
    assert request(h, "POST", "/einrichtung/pruefen", h.form(2)).status == 403
    assert h.setup.state() == before
    with pytest.raises(PermissionError):
        h.setup.finish(h.actor, before.version, "f"*32)


def test_external_env_change_rejects_a_save(initial):
    h = initial
    h.advance()
    (h.directory/'.env').write_text((h.directory/'.env').read_text()+'\nOTHER=changed\n')
    with pytest.raises(ValueError, match="conflict"):
        h.setup.save(h.actor,h.form(2))


def test_interrupted_activation_can_resume_and_replay(initial,monkeypatch):
    h=initial
    h.advance()
    original=module.atomic_replace
    def interrupt(path, content):
        if path.name=='config.yaml':
            raise OSError('synthetic disk failure')
        original(path,content)
    monkeypatch.setattr(module,'atomic_replace',interrupt)
    with pytest.raises(OSError):
        h.setup.finish(h.actor,h.setup.state().version,'e'*32)
    assert h.setup.state().status=='draft'
    monkeypatch.setattr(module,'atomic_replace',original)
    version=h.setup.state().version
    h.setup.finish(h.actor,version,'e'*32)
    h.setup.finish(h.actor,version,'e'*32)
    with pytest.raises(ValueError):
        h.setup.finish(h.actor,version,'d'*32)


@pytest.mark.slow
def test_password_hash_login_rate_limit_reset_and_versions(initial):
    h=initial
    passwords=WebPassword(h.store)
    assert not passwords.verify('unset')
    passwords.set('synthetic-password',0)
    assert passwords.verify('synthetic-password') and not passwords.verify('x'*1025)
    with pytest.raises(ValueError): passwords.set('new-password-value',0)
    with pytest.raises(PermissionError): passwords.set('new-password-value',1,lambda:False)
    for value in ['short','bad\npassword-value']:
        with pytest.raises(ValueError): passwords.set(value,1)
    token=h.auth.password_login('synthetic-password','Password browser')
    assert h.auth.authenticate(token)
    for _ in range(20):
        with pytest.raises(PairingRefused):h.auth.password_login('wrong','Intruder')
    with pytest.raises(PairingLimited):h.auth.password_login('synthetic-password','Locked')
    passwords.reset()
    assert not passwords.verify('synthetic-password') and not h.auth.active(h.session.id)


@pytest.mark.parametrize('uri',[
    'https://mail.example.test/auth/google/callback','http://localhost:8765/auth/google/callback',
    'http://127.0.0.1:8765/auth/google/callback','http://[::1]:8765/auth/google/callback'])
def test_google_webclient_explicit_redirect_accepts_https_and_loopback(uri):
    assert WebSettings(google_redirect_uri=uri).google_redirect_uri==uri


@pytest.mark.parametrize('uri',['http://mail.example.test/auth/google/callback','https://u:p@host/auth/google/callback',
    'https://host/auth/google/callback?code=x','https://host/auth/google/callback#x','https://host/wrong',
    '/auth/google/callback','ftp://host/auth/google/callback'])
def test_google_webclient_refuses_unsafe_or_ambiguous_redirects(uri):
    with pytest.raises(ValueError):WebSettings(google_redirect_uri=uri)


def test_finish_rechecks_all_inputs_and_session_before_atomic_activation(initial):
    h=initial
    with pytest.raises(ValueError):h.setup.finish(h.actor,0,'bad-key')
    with pytest.raises(ValueError):h.setup.finish(h.actor,0,'f'*32)
    with pytest.raises(ValueError):h.setup.save(h.actor,h.form(1))
    h.advance(True)
    with pytest.raises(ValueError):h.setup.save(h.actor,h.form(1,password='password\nwith-newline'))
    h.setup.save(h.actor,h.form(1))  # Existing password can be retained when changing only the zone.
    state=h.setup.state()
    state.model='not-installed'
    h.setup._save(state)
    with pytest.raises(ValueError,match='llm.ollama_model_missing'):h.setup.finish(h.actor,state.version,'d'*32)
    state.model='synthetic:latest'
    h.setup._save(state)
    WebPassword(h.store).reset()
    assert not (h.directory/'config.yaml').exists()


def test_finish_does_not_overwrite_new_configuration_or_concurrent_draft(initial):
    h=initial
    h.advance()
    version=h.setup.state().version
    (h.directory/'config.yaml').write_text('external: change\n')
    with pytest.raises(ValueError,match='existiert'):h.setup.finish(h.actor,version,'f'*32)
    (h.directory/'config.yaml').unlink()
    def change(*args):
        state=h.setup.state();state.version+=1;h.setup._save(state)
        return {}
    h.checks.targets=change
    with pytest.raises(ValueError,match='conflict'):h.setup.finish(h.actor,version,'f'*32)


def test_empty_or_broken_form_is_rejected_without_publishing_config(initial):
    h=initial
    headers={'host':'127.0.0.1:8765','content-type':'application/x-www-form-urlencoded','cookie':'mh_session='+h.token}
    assert h.app(Request('POST','/einrichtung/speichern',headers,body=b'bad=\xff')).status==400
    assert h.app(Request('POST','/einrichtung/speichern',headers,body=('&'.join(f'k{i}=x' for i in range(41))).encode())).status==400


def test_configuration_cannot_be_published_when_its_password_record_disappeared(initial):
    h=initial
    h.advance()
    h.store.save('web-password',{'schema_version':1,'version':0,'salt':'','digest':''})
    with pytest.raises(ValueError,match='password.missing'):
        h.setup.finish(h.actor,h.setup.state().version,'e'*32)
    assert not (h.directory/'config.yaml').exists()


def test_authenticated_step_save_advances_the_wizard(initial):
    h=initial
    response=request(h,'POST','/einrichtung/speichern',h.form(1,password='synthetic-password',timezone='UTC'))
    assert response.status==303 and response.headers['Location']=='/einrichtung/start'
    assert h.setup.state().step==2
