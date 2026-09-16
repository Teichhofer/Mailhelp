from __future__ import annotations

from pathlib import Path
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import pytest

from mailhelp.application import Application, _checkpoint_name, _safe_name, _state_directory, build_application
from mailhelp.config import Secrets, Settings, Topic
from mailhelp.imap import FetchedMail
from mailhelp.models import MailState
from mailhelp.orchestrator import ProcessingOutcome, ProcessingResult
from test_core import prompt_config


class Store:
    def __init__(self, values=None): self.values=values or {}; self.saved=[]
    def load(self, name, default=None): return self.values.get(name, default)
    def save(self, name, value): self.saved.append((name,value)); self.values[name]=value
    def names(self, prefix=""): return sorted(name for name in self.values if name.startswith(prefix))
    def load_model(self, name, model, default=None):
        value=self.values.get(name)
        return default if value is None else model.model_validate(value)


class Log:
    def __init__(self): self.events=[]
    def event(self,*args,**kwargs): self.events.append((args,kwargs))


class Imap:
    def __init__(self, outcomes): self.outcomes=iter(outcomes); self.last_uidvalidity=None; self.account_id="0"*24; self.calls=[]; self.uid_calls=[]
    def fetch_since(self,*args):
        self.calls.append(args); value=next(self.outcomes)
        if isinstance(value,Exception): raise value
        self.last_uidvalidity=value[0]; return value[1]
    def fetch_uid(self,*args):
        self.uid_calls.append(args)
        return FetchedMail(args[0],args[2],args[1],b"Subject: resumed\n\nBody")


class Telegram:
    def __init__(self, value): self.value=value; self.offsets=[]
    def poll(self, offset):
        self.offsets.append(offset)
        if isinstance(self.value,Exception): raise self.value
        return self.value


class Orch:
    def __init__(self, fail=False, stop=None): self.fail=fail; self.stop_event=SimpleNamespace(set=lambda:None); self.stop_called=False; self.seen=[]; self._stop=stop
    def stop(self): self.stop_called=True
    def process(self, mail):
        self.seen.append(mail.uid)
        if self._stop: self._stop.set()
        if self.fail: raise RuntimeError("mail")
        return ProcessingResult(ProcessingOutcome.COMPLETED, {})


def settings(tmp_path, folders=("INBOX",)):
    return Settings(timezone="UTC",poll_interval_seconds=5,test_mode=True,data_directory=tmp_path/"data",imap={"host":"h","port":993,"folders":list(folders)},telegram={"user_id":1,"chat_id":2},targets={"todoist_project":"p","google_calendar":"c"},limits={"max_mail_bytes":1024,"llm_calls_per_minute":2},retries={"validation":0},timeouts={**{name:{"timeout_seconds":30.0,"retries":0,"initial_backoff_seconds":0.0,"max_backoff_seconds":1.0} for name in ("imap","telegram","openrouter","todoist","google_calendar")},"telegram_poll_seconds":30},logging={"directory":str(tmp_path/"logs"),"level":"INFO"})


def app(tmp_path, imap, telegram, orch, folders=("INBOX",), store=None):
    from threading import Event
    event=Event(); orch._stop=event if orch._stop else None
    return Application(settings(tmp_path,folders),store or Store(),Log(),imap,object(),object(),telegram,object(),object(),orch,event)


def test_polling_errors_resume_and_stop(tmp_path):
    mail1=FetchedMail("INBOX",7,4,b"x"); mail2=FetchedMail("INBOX",7,5,b"x")
    store=Store({_checkpoint_name("0"*24, "INBOX"):{"uidvalidity":7,"uid":3},"telegram-offset":{"offset":8}})
    service=app(tmp_path,Imap([(7,[mail1,mail2])]),Telegram([{"update_id":8},{"update_id":10}]),Orch(fail=True),store=store)
    service._poll_imap(); service._poll_telegram()
    assert service.imap.calls==[("INBOX",3,7)] and service.orchestrator.seen==[4,5]
    assert store.values[_checkpoint_name("0"*24, "INBOX")]["uid"]==3 and store.values["telegram-offset"]["offset"]==11
    assert any(e[0][2]=="mail_failed" for e in service.logger.events)

    class FirstFails(Orch):
        def process(self, mail):
            self.seen.append(mail.uid)
            if mail.uid == 4: raise RuntimeError("mail")
            return ProcessingResult(ProcessingOutcome.COMPLETED,{})
    mixed_store=Store({_checkpoint_name("0"*24, "INBOX"):{"uidvalidity":7,"uid":3}})
    mixed=app(tmp_path,Imap([(7,[mail1,mail2])]),Telegram([]),FirstFails(),store=mixed_store)
    mixed._poll_imap()
    assert mixed.orchestrator.seen==[4,5]
    assert mixed_store.values[_checkpoint_name("0"*24, "INBOX")]["uid"]==3

    class FirstReturnsFailure(Orch):
        def process(self, mail):
            self.seen.append(mail.uid)
            outcome=ProcessingOutcome.FAILED if mail.uid==4 else ProcessingOutcome.COMPLETED
            return ProcessingResult(outcome,{"error":{"type":"RuntimeError","message":"mail"}} if mail.uid==4 else {})
    durable_store=Store({_checkpoint_name("0"*24, "INBOX"):{"uidvalidity":7,"uid":3}})
    durable=app(tmp_path,Imap([(7,[mail1,mail2])]),Telegram([]),FirstReturnsFailure(),store=durable_store)
    results=durable._poll_imap()
    assert [result.outcome for result in results]==[ProcessingOutcome.FAILED,ProcessingOutcome.COMPLETED]
    assert durable_store.values[_checkpoint_name("0"*24, "INBOX")]["uid"]==5
    assert any(e[0][2]=="mail_failed" and e[1]["uid"]==4 for e in durable.logger.events)

    failing=app(tmp_path,Imap([RuntimeError("imap"),(9,[]),(10,[])]),Telegram(RuntimeError("tg")),Orch(),folders=("bad","new","none"))
    failing._poll_imap(); failing._poll_telegram()
    assert len(failing.logger.events)==2
    assert failing.store.values[_checkpoint_name("0"*24, "new")]["uidvalidity"]==9
    assert failing.store.values[_checkpoint_name("0"*24, "none")]["uidvalidity"]==10

    stopped=app(tmp_path,Imap([(1,[mail1,mail2])]),Telegram([]),Orch(stop=True),folders=("INBOX","Other"))
    stopped._poll_imap(); assert stopped.orchestrator.seen==[4]
    stopped.stop(); assert stopped.stop_event.is_set() and stopped.orchestrator.stop_called


def test_empty_checkpoint_and_run_paths(tmp_path):
    key=_checkpoint_name("0"*24, "INBOX")
    store=Store({key:{"uidvalidity":4,"uid":12}})
    same=app(tmp_path,Imap([(4,[])]),Telegram([]),Orch(),store=store); same._poll_imap()
    assert store.values[key]["uid"]==12
    none=app(tmp_path,Imap([(None,[])]),Telegram([]),Orch()); none._poll_imap()
    assert none.store.saved[0][1]["start_uid"] == 0
    none.stop_event.set(); none.run()
    running=app(tmp_path,Imap([(1,[])]),Telegram([]),Orch())
    running._poll_imap=lambda: running.stop_event.set(); running.run()
    complete=app(tmp_path,Imap([(1,[])]),Telegram([]),Orch())
    complete._poll_imap=lambda: None
    complete._poll_telegram=lambda: complete.stop_event.set()
    complete.run()

    import mailhelp.application as application_module
    original = application_module.RetentionService
    class BrokenRetention:
        def __init__(self, *args): pass
        def run(self): raise RuntimeError("private detail")
    application_module.RetentionService = BrokenRetention
    failed_cleanup=app(tmp_path,Imap([(1,[])]),Telegram([]),Orch())
    failed_cleanup._poll_imap=lambda: failed_cleanup.stop_event.set()
    failed_cleanup.run()
    application_module.RetentionService = original
    assert failed_cleanup.logger.events[0][0][2]=="cleanup_failed"
    assert failed_cleanup.logger.events[0][1]["failure_count"]==1
    assert datetime.fromisoformat(failed_cleanup.logger.events[0][1]["processed_at"]).tzinfo is not None

    class Dialog:
        def __init__(self, error=None): self.calls=0; self.error=error
        def poll_once(self):
            self.calls += 1
            if self.error: raise self.error
    dialog_app=app(tmp_path,Imap([(1,[])]),Telegram([]),Orch()); dialog_app.dialog=Dialog(); dialog_app._poll_telegram(); assert dialog_app.dialog.calls==1
    failed_dialog=app(tmp_path,Imap([(1,[])]),Telegram([]),Orch()); failed_dialog.dialog=Dialog(RuntimeError("dialog")); failed_dialog._poll_telegram()
    assert failed_dialog.logger.events[0][0][2]=="poll_failed"


def test_resume_due_pending_states_and_isolate_failures(tmp_path):
    class LegacyStore:
        def load(self,name,default=None): return default
        def save(self,name,value): pass
    legacy=app(tmp_path,Imap([]),Telegram([]),Orch(),store=LegacyStore())
    assert legacy._resume_pending()==[]
    due=MailState(id="a"*24,config_fingerprint="0"*64,imap={"account_id":"0"*24,"folder":"INBOX","uidvalidity":7,"uid":4})
    future=MailState(id="b"*24,config_fingerprint="0"*64,imap={"account_id":"0"*24,"folder":"INBOX","uidvalidity":7,"uid":5},deferred_until=datetime.now(timezone.utc)+timedelta(hours=1))
    completed=MailState(id="c"*24,config_fingerprint="0"*64,imap={"account_id":"0"*24,"folder":"INBOX","uidvalidity":7,"uid":6})
    completed.steps.completion="completed"
    store=Store({"mail-a":due.model_dump(mode="json"),"mail-b":future.model_dump(mode="json"),"mail-c":completed.model_dump(mode="json"),"mail-missing":None})
    imap=Imap([]); orch=Orch(); service=app(tmp_path,imap,Telegram([]),orch,store=store)
    results=service._resume_pending()
    assert imap.uid_calls==[("INBOX",4,7)] and orch.seen==[4]
    assert results[0].outcome is ProcessingOutcome.COMPLETED

    failed_orch=Orch()
    failed_orch.process=lambda mail: ProcessingResult(ProcessingOutcome.FAILED,{"error":{"type":"RuntimeError","message":"resume"}})
    failed_service=app(tmp_path,Imap([]),Telegram([]),failed_orch,store=Store({"mail-a":due.model_dump(mode="json")}))
    assert failed_service._resume_pending()[0].outcome is ProcessingOutcome.FAILED
    assert failed_service.logger.events[0][0][2]=="resume_failed"

    class BrokenImap(Imap):
        def fetch_uid(self,*args): raise RuntimeError("gone")
    broken=app(tmp_path,BrokenImap([]),Telegram([]),Orch(),store=Store({"mail-a":due.model_dump(mode="json")}))
    broken._resume_pending()
    assert broken.logger.events[0][0][2]=="resume_failed"
    broken.stop_event.set(); broken._resume_pending()


@pytest.mark.parametrize(("mode","starttls"), [("ssl",False),("starttls",True),("plain",False)])
def test_composition_cleanup_and_build_failure(tmp_path, monkeypatch, mode, starttls):
    closed=[]
    class Resource:
        def __init__(self,*args,**kwargs): pass
        def close(self): closed.append(type(self).__name__)
    class FakeImap(Resource):
        kwargs={}
        def __init__(self,*args,**kwargs): type(self).kwargs=kwargs
    class FakeOpen(Resource): pass
    class FakeTelegram(Resource):
        def send(self,*args): pass
    class FakeWriter(Resource):
        calls=[]
        def __init__(self,*args,**kwargs):
            type(self).calls.append((args,kwargs))
    monkeypatch.setattr("mailhelp.application.ImapReader",FakeImap)
    monkeypatch.setattr("mailhelp.application.OpenRouterClient",FakeOpen)
    monkeypatch.setattr("mailhelp.application.TelegramClient",FakeTelegram)
    monkeypatch.setattr("mailhelp.application.HttpWriter",FakeWriter)
    cfg=settings(tmp_path); cfg.imap.connection_mode=mode
    sec=Secrets(imap_username="u",imap_password="p",openrouter_api_key="o",telegram_bot_token="t",todoist_token="d",google_oauth_client_id="i",google_oauth_client_secret="s",google_oauth_refresh_token="r")
    topic=[Topic(id="x",name="x",enabled=True,description="x")]
    with build_application(cfg,sec,topic,prompt_config(),"f"*64,base_directory=tmp_path) as made:
        assert made.todoist and (tmp_path/"data/test/.lock").exists()
        assert made.dialog.relevance_handler is made.orchestrator
        assert made.dialog.revision_service is made.analyzer
        assert made.orchestrator.config_fingerprint == "f"*64
        assert FakeImap.kwargs["starttls"] is starttls
        assert FakeImap.kwargs["factory"].__name__ == ("IMAP4_SSL" if mode=="ssl" else "IMAP4")
        assert FakeWriter.calls[-1][1]["calendar_timezone"] == "UTC"
    assert len(closed)==5 and not (tmp_path/"data/test/.lock").exists()

    cfg.data_directory=Path("relative"); cfg.logging.directory=Path("relative-logs")
    class BrokenTelegram(Resource):
        def __init__(self,*args,**kwargs): raise RuntimeError("build")
    monkeypatch.setattr("mailhelp.application.TelegramClient",BrokenTelegram)
    with pytest.raises(RuntimeError,match="build"):
        with build_application(cfg,sec,topic,prompt_config(),"f"*64,base_directory=tmp_path): pass
    assert not (tmp_path/"relative/test/.lock").exists()


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
    from mailhelp.storage import JsonStore
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
    boundary=datetime(2025,1,2,3,4,tzinfo=timezone.utc)
    cfg=settings(tmp_path); cfg.imap.historical_start=boundary
    fake=Imap([(8,[])]); fake.account_id="1"*24
    fake.determine_calls=[]
    fake.determine_start_uid=lambda folder,start: fake.determine_calls.append((folder,start)) or 41
    store=Store(); service=Application(cfg,store,Log(),fake,object(),object(),Telegram([]),object(),object(),Orch(),__import__('threading').Event())
    service._poll_imap()
    key=_checkpoint_name("1"*24,"INBOX")
    assert fake.determine_calls==[("INBOX",boundary)]
    assert fake.calls==[("INBOX",41,None)] and store.values[key]["start_uid"]==41

    restarted=Imap([(9,[])]); restarted.account_id="1"*24
    restarted.determine_start_uid=lambda *_: pytest.fail("persisted boundary was reinterpreted")
    again=Application(cfg,store,Log(),restarted,object(),object(),Telegram([]),object(),object(),Orch(),__import__('threading').Event())
    again._poll_imap()
    assert restarted.calls==[("INBOX",0,8)]
    assert any(event[0][2]=="uidvalidity_changed" for event in again.logger.events)

    changed=Imap([(3,[])]); changed.account_id="2"*24
    changed.determine_start_uid=lambda *_: 7
    other=Application(cfg,store,Log(),changed,object(),object(),Telegram([]),object(),object(),Orch(),__import__('threading').Event())
    other._poll_imap()
    assert _checkpoint_name("2"*24,"INBOX") in store.values

    foreign=MailState(id="f"*24,config_fingerprint="0"*64,imap={"account_id":"9"*24,"folder":"INBOX","uidvalidity":1,"uid":1})
    other.store.values["mail-foreign"]=foreign.model_dump(mode="json")
    assert other._resume_pending()==[] and changed.uid_calls==[]
