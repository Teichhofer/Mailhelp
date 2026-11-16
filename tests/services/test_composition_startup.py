"""Composition, local and vision models, state directories and startup restore."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from mailhelp.app.application import Application
from mailhelp.app.composition import _state_directory, build_application, build_logger
from mailhelp.config import Secrets, Topic
from mailhelp.mailbox.imap import FetchedMail
from mailhelp.mailbox.mailbox_run import _checkpoint_name
from mailhelp.telegram.commands import STARTUP
from tests.fakes.factories import build_mail_state
from tests.fakes.log_fakes import RecordingLogger as Log
from tests.fakes.shared_application import Imap, Orch, Store, Telegram, app, settings
from tests.fakes.shared_core import prompt_config

# Since 2.3 the writers are built in mailhelp.external.providers.
MOVED_WRITERS = ("HttpWriter", "GoogleOAuthTokenProvider")


@pytest.mark.parametrize(("mode","starttls"), [("ssl",False),("starttls",True),("plain",False)])
def test_composition_cleanup_and_build_failure(tmp_path, monkeypatch, mode, starttls):
    closed=[]
    class Resource:
        def __init__(self,*args,**kwargs): pass
        def close(self): closed.append(type(self).__name__)
        def check_access(self,*args): pass
    class FakeImap(Resource):
        kwargs={}
        def __init__(self,*args,**kwargs): type(self).kwargs=kwargs
    class FakeOpen(Resource): service_name = "OpenRouter"
    class FakeDecision(Resource): pass
    class FakeTelegram(Resource):
        def send(self,*args): pass
    class FakeWriter(Resource):
        calls=[]
        def __init__(self,*args,**kwargs):
            type(self).calls.append((args,kwargs))
    class FakeOAuth(Resource):
        calls=[]
        def __init__(self,*args,**kwargs): type(self).calls.append((args,kwargs))
    monkeypatch.setattr("mailhelp.app.composition.ImapReader",FakeImap)
    monkeypatch.setattr("mailhelp.app.composition.OpenRouterClient",FakeOpen)
    monkeypatch.setattr("mailhelp.app.composition.DecisionClient",FakeDecision)
    monkeypatch.setattr("mailhelp.app.composition.TelegramClient",FakeTelegram)
    monkeypatch.setattr("mailhelp.external.providers.HttpWriter",FakeWriter)
    monkeypatch.setattr("mailhelp.external.providers.GoogleOAuthTokenProvider",FakeOAuth)
    cfg=settings(tmp_path)
    cfg.imap.connection_mode=mode
    cfg.logging.file.enabled = False
    cfg.logging.file.level = "CRITICAL"
    cfg.logging.console.enabled = False
    cfg.logging.console.level = "ERROR"
    cfg.logging.modules = {"access_check": "CRITICAL"}
    sec=Secrets(imap={1:{"username":"u","password":"p"}},openrouter_api_key="o",telegram_bot_token="t",todoist_token="d",todoist_client_id="ti",todoist_client_secret="ts",google_oauth_client_id="i",google_oauth_client_secret="s",google_oauth_refresh_token="r")
    topic=[Topic(id="x",name="x",enabled=True,description="x")]
    diagnostics = mode == "ssl"
    supplied_logger = build_logger(cfg, sec, tmp_path) if mode == "starttls" else None
    overridden_logger = build_logger(cfg, sec, tmp_path, log_directory=tmp_path / "override-logs")
    assert overridden_logger.app == tmp_path / "override-logs/application.jsonl"
    with build_application(
        cfg, sec, topic, prompt_config(), "f" * 64,
        base_directory=tmp_path, access_diagnostics=diagnostics,
        logger=supplied_logger,
    ) as made:
        assert made.todoist and (tmp_path/"data/test/.lock").exists()
        assert made.sender_store.directory == tmp_path
        assert made.orchestrator.sender_store is made.sender_store
        assert made.dialog.relevance_handler is made.orchestrator
        assert made.dialog.revision_service is made.analyzer
        from mailhelp.llm.decisions import JevRelevanceAnalyzer, load_relevance_prompts, relevance_fingerprint
        assert made.orchestrator.config_fingerprint == (
            "f" * 64 if diagnostics else relevance_fingerprint("f" * 64, load_relevance_prompts(tmp_path)))
        assert isinstance(made.analyzer, JevRelevanceAnalyzer) is not diagnostics
        assert FakeImap.kwargs["starttls"] is starttls
        assert FakeImap.kwargs["batch_size"] == 25
        assert FakeImap.kwargs["factory"].__name__ == ("IMAP4_SSL" if mode=="ssl" else "IMAP4")
        assert FakeOAuth.calls[-1][0][:3] == ("i", "s", "r")
        calendar_args, calendar_kwargs = FakeWriter.calls[-1]
        assert calendar_args[0] == "google_calendar"
        assert isinstance(calendar_args[1], FakeOAuth) and calendar_args[2] == "c"
        assert calendar_kwargs["calendar_timezone"] == "UTC"
        assert made.logger.file_enabled is diagnostics
        assert made.logger.console_enabled is diagnostics
        assert made.logger.level == ("DEBUG" if diagnostics else "CRITICAL")
        assert made.logger.console_level == ("DEBUG" if diagnostics else "ERROR")
        assert made.logger.module_levels == ({} if diagnostics else {"access_check": "CRITICAL"})
        if supplied_logger is not None:
            assert made.logger is supplied_logger
    assert len(closed) == (6 if diagnostics else 7) and (tmp_path/"data/test/.lock").exists()

    closed.clear()
    class BrokenImap(Resource):
        def __init__(self,*args,**kwargs): raise RuntimeError("authentication failed")
    monkeypatch.setattr("mailhelp.app.composition.ImapReader",BrokenImap)
    with build_application(
        cfg, sec, topic, prompt_config(), "f" * 64,
        base_directory=tmp_path, access_diagnostics=True,
    ) as made:
        assert made.check_access() == {
            "IMAP": "IMAP: INBOX: authentication failed", "OpenRouter": None,
            "Telegram": None, "Todoist": None, "Google Kalender": None,
        }
    assert len(closed) == 5
    with pytest.raises(RuntimeError, match="authentication failed"):
        with build_application(
            cfg, sec, topic, prompt_config(), "f" * 64,
            base_directory=tmp_path,
        ):
            pass

    cfg.data_directory=Path("relative")
    cfg.logging.directory=Path("relative-logs")
    monkeypatch.setattr("mailhelp.app.composition.ImapReader",FakeImap)
    class BrokenTelegram(Resource):
        def __init__(self,*args,**kwargs): raise RuntimeError("build")
    monkeypatch.setattr("mailhelp.app.composition.TelegramClient",BrokenTelegram)
    with pytest.raises(RuntimeError,match="build"):
        with build_application(cfg,sec,topic,prompt_config(),"f"*64,base_directory=tmp_path): pass
    assert (tmp_path/"relative/test/.lock").exists()


def test_local_ollama_mode_replaces_openrouter(tmp_path, monkeypatch):
    from mailhelp.llm.ollama import LocalLlm

    class Resource:
        def __init__(self, *args, **kwargs): pass
        def close(self): pass
        def check_access(self, *args): pass

    class FakeOllama(Resource):
        service_name = "Ollama (lokal, experimentell)"
        calls = []
        def __init__(self, *args, **kwargs): type(self).calls.append((args, kwargs))

    class NoOpenRouter(Resource):
        def __init__(self, *args, **kwargs):
            raise AssertionError("OpenRouter darf im lokalen Modus nicht gebaut werden")

    class FakeTelegram(Resource):
        def send(self, *args): pass

    monkeypatch.setattr("mailhelp.app.composition.ImapReader", Resource)
    monkeypatch.setattr("mailhelp.app.composition.OpenRouterClient", NoOpenRouter)
    monkeypatch.setattr("mailhelp.app.composition.OllamaClient", FakeOllama)
    monkeypatch.setattr("mailhelp.app.composition.TelegramClient", FakeTelegram)
    monkeypatch.setattr("mailhelp.external.providers.HttpWriter", Resource)
    monkeypatch.setattr("mailhelp.external.providers.GoogleOAuthTokenProvider", Resource)
    cfg = settings(tmp_path)
    cfg.logging.file.enabled = cfg.logging.console.enabled = False
    sec = Secrets(imap={1: {"username": "u", "password": "p"}}, openrouter_api_key="o",
                  telegram_bot_token="t", todoist_token="d", todoist_client_id="ti",
                  todoist_client_secret="ts", google_oauth_client_id="i",
                  google_oauth_client_secret="s", google_oauth_refresh_token="r")
    logger = build_logger(cfg, sec, tmp_path)
    events = []
    logger.event = lambda level, module, event, **fields: events.append((level, event, fields))
    local = LocalLlm("192.168.1.20", 11434, "qwen2.5:7b-instruct")
    with build_application(cfg, sec, [Topic(id="x", name="x", enabled=True, description="x")],
                           prompt_config(), "f" * 64, base_directory=tmp_path,
                           logger=logger, local_llm=local) as made:
        assert isinstance(made.openrouter, FakeOllama)
        assert made.analyzer.client is made.openrouter
        assert "Ollama (lokal, experimentell)" in made.check_access()
    (args, kwargs), = FakeOllama.calls
    assert args == (local, 1800, 1, cfg.limits.llm_calls_per_minute)
    assert (kwargs["initial_backoff"], kwargs["max_backoff"]) == (2, 10)
    assert ("WARNING", "local_llm_experimental", {
        "host": "192.168.1.20", "port": 11434, "model": "qwen2.5:7b-instruct",
        "num_ctx": 65536}) in events
    # A prompts.yaml from before 1.4 has no vision step: no image is sent.
    assert made.orchestrator.vision is None
    assert ("WARNING", "vision_prompt_missing", {}) in events


@pytest.mark.parametrize("enabled", [True, False])
def test_vision_ocr_is_wired_only_when_enabled_and_prompted(tmp_path, monkeypatch, enabled):
    from mailhelp.config import PromptConfig
    from mailhelp.processing.vision import VisionExtractor

    class Resource:
        def __init__(self, *args, **kwargs): pass
        def close(self): pass

    for name in ("ImapReader", "OpenRouterClient", "TelegramClient", "HttpWriter",
                 "GoogleOAuthTokenProvider"):
        monkeypatch.setattr(f"mailhelp.{'external.providers' if name in MOVED_WRITERS else 'app.composition'}.{name}", Resource)
    cfg = settings(tmp_path)
    cfg.logging.file.enabled = cfg.logging.console.enabled = False
    cfg.vision.enabled = enabled
    sec = Secrets(imap={1: {"username": "u", "password": "p"}}, openrouter_api_key="o",
                  telegram_bot_token="t", todoist_token="d", todoist_client_id="ti",
                  todoist_client_secret="ts", google_oauth_client_id="i",
                  google_oauth_client_secret="s", google_oauth_refresh_token="r")
    logger = build_logger(cfg, sec, tmp_path)
    events = []
    logger.event = lambda level, module, event, **fields: events.append(event)
    data = prompt_config().model_dump()
    data["prompts"]["vision_ocr"] = {"system_prompt": "Lies den Text."}
    with build_application(cfg, sec, [Topic(id="x", name="x", enabled=True, description="x")],
                           PromptConfig.model_validate(data), "f" * 64, base_directory=tmp_path,
                           logger=logger, access_diagnostics=True) as made:
        vision = made.orchestrator.vision
    if enabled:
        assert isinstance(vision, VisionExtractor)
        assert vision.reader is made.analyzer and vision.settings is cfg.vision
    else:
        assert vision is None
    assert "vision_prompt_missing" not in events


def test_state_directory_separates_every_durable_state_and_lock(tmp_path):
    test_settings=settings(tmp_path)
    production_settings=settings(tmp_path)
    production_settings.test_mode=False
    assert _state_directory(test_settings,tmp_path)==tmp_path/"data/test"
    assert _state_directory(production_settings,tmp_path)==tmp_path/"data/production"

    state_names=(
        _checkpoint_name("0"*24,"INBOX"), "mail-same", "telegram-offset",
        "telegram-dialog", "proposal-same", "proposal-same-v1", "llm-budget",
    )
    from mailhelp.persistence.storage import JsonStore
    with JsonStore(_state_directory(test_settings,tmp_path)) as test_store:
        with JsonStore(_state_directory(production_settings,tmp_path)) as production_store:
            for name in state_names:
                test_store.save(name,{"mode":"test"})
                production_store.save(name,{"mode":"production"})
            assert (test_store.directory/".lock").exists()
            assert (production_store.directory/".lock").exists()
            assert test_store.names()==production_store.names()
            assert all(test_store.load(name)=={"mode":"test"} for name in state_names)
            assert all(production_store.load(name)=={"mode":"production"} for name in state_names)


def test_historical_start_is_persisted_account_scoped_and_uidvalidity_logged(tmp_path):
    boundary=datetime(2025,1,2,3,4,tzinfo=UTC)
    cfg=settings(tmp_path)
    cfg.imap.historical_start=boundary
    fake=Imap([(8,[])])
    fake.account_id="1"*24
    fake.determine_calls=[]
    def initial_boundary(folder, start):
        fake.determine_calls.append((folder,start))
        fake.last_uidvalidity=8
        return 41
    fake.determine_start_uid=initial_boundary
    store=Store()
    service=Application(cfg,store,Log(),fake,object(),object(),Telegram([]),object(),object(),Orch(),__import__('threading').Event())
    service.mailbox.poll()
    key=_checkpoint_name("1"*24,"INBOX")
    assert fake.determine_calls==[("INBOX",boundary)]
    assert fake.calls==[("INBOX",41,8,None,())] and store.values[key]["start_uid"]==41

    before_boundary=FetchedMail("INBOX",9,1,b"must-not-be-delivered")
    restarted=Imap([(9,[before_boundary]),(9,[])])
    restarted.account_id="1"*24
    restarted.determine_start_uid=lambda *_: setattr(restarted,"last_uidvalidity",9) or 42
    again=Application(cfg,store,Log(),restarted,object(),object(),Telegram([]),object(),object(),Orch(),__import__('threading').Event())
    again.mailbox.poll()
    assert restarted.calls==[("INBOX",41,8,None,()),("INBOX",42,9,None,())]
    assert again.orchestrator.seen==[]
    assert store.values[key]["start_uid"]==42
    assert any(event[0][2]=="uidvalidity_changed" for event in again.logger.events)

    changed=Imap([(3,[])])
    changed.account_id="2"*24
    changed.determine_start_uid=lambda *_: setattr(changed,"last_uidvalidity",3) or 7
    other=Application(cfg,store,Log(),changed,object(),object(),Telegram([]),object(),object(),Orch(),__import__('threading').Event())
    other.mailbox.poll()
    assert _checkpoint_name("2"*24,"INBOX") in store.values

    no_history_store=Store({_checkpoint_name("0"*24,"INBOX"):{"uidvalidity":1,"uid":9,"start_uid":0}})
    no_history=app(tmp_path,Imap([(2,[])]),Telegram([]),Orch(),store=no_history_store)
    no_history.mailbox.poll()
    assert no_history_store.values[_checkpoint_name("0"*24,"INBOX")]["uid"]==0

    broken=Imap([(10,[]) ])
    broken.account_id="1"*24
    broken.determine_start_uid=lambda *_: (_ for _ in ()).throw(RuntimeError("boundary"))
    failed=Application(cfg,store,Log(),broken,object(),object(),Telegram([]),object(),object(),Orch(),__import__('threading').Event())
    failed.mailbox.poll()
    assert failed.logger.events[-1][0][2]=="poll_failed"

    drifting=Imap([(10,[])])
    drifting.account_id="1"*24
    drifting.determine_start_uid=lambda *_: setattr(drifting,"last_uidvalidity",11) or 5
    drifted=Application(cfg,store,Log(),drifting,object(),object(),Telegram([]),object(),object(),Orch(),__import__('threading').Event())
    drifted.mailbox.poll()
    assert len(drifting.calls)==1 and "während der Grenzermittlung" in drifted.logger.events[-1][1]["error"]

    foreign=build_mail_state("f"*24,uid=1,sender=None,config_fingerprint="0"*64,imap={"account_id":"9"*24,"uidvalidity":1})
    other.store.values["mail-foreign"]=foreign.model_dump(mode="json")
    assert other.mailbox.resume_pending()==[] and changed.uid_calls==[]


def test_ignore_historical_start_reopens_older_uids_without_repeating_completed(tmp_path):
    boundary = datetime(2025, 1, 2, 3, 4, tzinfo=UTC)
    cfg = settings(tmp_path)
    cfg.imap.historical_start = boundary
    key = _checkpoint_name("0" * 24, "INBOX")
    store = Store({key: {
        "uidvalidity": 7, "uid": 45, "start_uid": 41,
        "completed_uid_ranges": [(42, 45)],
    }})
    older = FetchedMail("INBOX", 7, 20, b"older")
    reader = Imap([(7, [older])])
    reader.determine_start_uid = lambda *_args: pytest.fail(
        "historical boundary must be ignored"
    )
    service = Application(cfg, store, Log(), reader, object(), object(),
                          Telegram([]), object(), object(), Orch(),
                          __import__('threading').Event())

    assert len(service.mailbox.poll(
        max_mails=1, ignore_historical_start=True
    )) == 1
    assert reader.calls == [("INBOX", 0, 7, 1, ((42, 45),))]
    assert store.values[key]["start_uid"] == 0
    assert store.values[key]["completed_uid_ranges"] == [(20, 20), (42, 45)]

@pytest.mark.parametrize('editing', [False, True])
def test_startup_restores_durable_proposal_once_and_last_decision_resumes_imap(tmp_path, editing):
    from mailhelp.persistence.storage import JsonStore
    from mailhelp.telegram import Decision, DecisionAction
    from tests.fakes.shared_telegram_dialog import controller, proposal
    item = proposal(open_questions=['Welches Datum?'])
    with JsonStore(tmp_path / 'state') as store:
        c, _, _ = controller(store)
        c.persist(item)
        if editing:
            c.decision_service.decide(Decision(mail_id=item.source_mail_id, proposal_id=item.id,
                               version=1, action=DecisionAction.EDIT), c.user_id, c.chat_id)
    with JsonStore(tmp_path / 'state') as store:
        c, telegram, _ = controller(store)
        service = app(tmp_path, Imap([(1, [])]), telegram, Orch(), store=store)
        service.dialog = c
        polls = []
        c.poll_once = lambda timeout=None: polls.append(timeout)
        service.run(max_mails=1)
        assert polls == []
        assert service.imap.calls and c.awaiting_decision()
        assert telegram.sent[0][1] == STARTUP
        assert len(telegram.sent) == 4  # greeting, overview, proposal/question, summary
        if editing:
            assert telegram.sent[2][1].startswith('❓ ')
        else:
            assert telegram.sent[2][2]['inline_keyboard'][0][0]['text'] == 'Klären'
        c.decision_service.decide(Decision(mail_id=item.source_mail_id, proposal_id=item.id,
                           version=1, action=DecisionAction.REJECT), c.user_id, c.chat_id)
        assert not c.awaiting_decision()
        assert not any(args[2] == 'startup_decisions_failed' for args, _ in service.logger.events)


def test_startup_redisplay_failure_does_not_stop_polling_or_expose_provider_content(tmp_path):
    from unittest.mock import Mock
    service = app(tmp_path, Imap([]), Telegram([]), Orch())
    def poll_once(timeout=None):
        service.stop_event.set()
    service.dialog = SimpleNamespace(awaiting_decision=lambda: True, awaiting_relevance_decision=lambda: True, poll_once=poll_once,
        show_open_decisions=Mock(side_effect=RuntimeError('synthetic-sensitive-content')))
    service.run()
    service.dialog.show_open_decisions.assert_called_once_with()
    errors = [(args, fields) for args, fields in service.logger.events if args[2] == 'startup_decisions_failed']
    assert errors == [(('ERROR', 'telegram', 'startup_decisions_failed'), {'error_class': 'RuntimeError'})]
    assert 'synthetic-sensitive-content' not in str(service.logger.events)
