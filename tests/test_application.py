from __future__ import annotations

from pathlib import Path
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import pytest

from mailhelp.application import Application, _safe_name, build_application
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
    def __init__(self, outcomes): self.outcomes=iter(outcomes); self.last_uidvalidity=None; self.calls=[]; self.uid_calls=[]
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
    store=Store({"imap-"+_safe_name("INBOX"):{"uidvalidity":7,"uid":3},"telegram-offset":{"offset":8}})
    service=app(tmp_path,Imap([(7,[mail1,mail2])]),Telegram([{"update_id":8},{"update_id":10}]),Orch(fail=True),store=store)
    service._poll_imap(); service._poll_telegram()
    assert service.imap.calls==[("INBOX",3,7)] and service.orchestrator.seen==[4,5]
    assert store.values["imap-"+_safe_name("INBOX")]["uid"]==3 and store.values["telegram-offset"]["offset"]==11
    assert any(e[0][2]=="mail_failed" for e in service.logger.events)

    class FirstFails(Orch):
        def process(self, mail):
            self.seen.append(mail.uid)
            if mail.uid == 4: raise RuntimeError("mail")
            return ProcessingResult(ProcessingOutcome.COMPLETED,{})
    mixed_store=Store({"imap-"+_safe_name("INBOX"):{"uidvalidity":7,"uid":3}})
    mixed=app(tmp_path,Imap([(7,[mail1,mail2])]),Telegram([]),FirstFails(),store=mixed_store)
    mixed._poll_imap()
    assert mixed.orchestrator.seen==[4,5]
    assert mixed_store.values["imap-"+_safe_name("INBOX")]["uid"]==3

    class FirstReturnsFailure(Orch):
        def process(self, mail):
            self.seen.append(mail.uid)
            outcome=ProcessingOutcome.FAILED if mail.uid==4 else ProcessingOutcome.COMPLETED
            return ProcessingResult(outcome,{"error":{"type":"RuntimeError","message":"mail"}} if mail.uid==4 else {})
    durable_store=Store({"imap-"+_safe_name("INBOX"):{"uidvalidity":7,"uid":3}})
    durable=app(tmp_path,Imap([(7,[mail1,mail2])]),Telegram([]),FirstReturnsFailure(),store=durable_store)
    results=durable._poll_imap()
    assert [result.outcome for result in results]==[ProcessingOutcome.FAILED,ProcessingOutcome.COMPLETED]
    assert durable_store.values["imap-"+_safe_name("INBOX")]["uid"]==5
    assert any(e[0][2]=="mail_failed" and e[1]["uid"]==4 for e in durable.logger.events)

    failing=app(tmp_path,Imap([RuntimeError("imap"),(9,[]),(10,[])]),Telegram(RuntimeError("tg")),Orch(),folders=("bad","new","none"))
    failing._poll_imap(); failing._poll_telegram()
    assert len(failing.logger.events)==2
    assert failing.store.values["imap-"+_safe_name("new")]["uidvalidity"]==9
    assert failing.store.values["imap-"+_safe_name("none")]["uidvalidity"]==10

    stopped=app(tmp_path,Imap([(1,[mail1,mail2])]),Telegram([]),Orch(stop=True),folders=("INBOX","Other"))
    stopped._poll_imap(); assert stopped.orchestrator.seen==[4]
    stopped.stop(); assert stopped.stop_event.is_set() and stopped.orchestrator.stop_called


def test_empty_checkpoint_and_run_paths(tmp_path):
    key="imap-"+_safe_name("INBOX")
    store=Store({key:{"uidvalidity":4,"uid":12}})
    same=app(tmp_path,Imap([(4,[])]),Telegram([]),Orch(),store=store); same._poll_imap()
    assert store.values[key]["uid"]==12
    none=app(tmp_path,Imap([(None,[])]),Telegram([]),Orch()); none._poll_imap(); assert not none.store.saved
    none.stop_event.set(); none.run()
    running=app(tmp_path,Imap([(1,[])]),Telegram([]),Orch())
    running._poll_imap=lambda: running.stop_event.set(); running.run()
    complete=app(tmp_path,Imap([(1,[])]),Telegram([]),Orch())
    complete._poll_imap=lambda: None
    complete._poll_telegram=lambda: complete.stop_event.set()
    complete.run()

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
    due=MailState(id="a"*24,config_fingerprint="0"*64,imap={"folder":"INBOX","uidvalidity":7,"uid":4})
    future=MailState(id="b"*24,config_fingerprint="0"*64,imap={"folder":"INBOX","uidvalidity":7,"uid":5},deferred_until=datetime.now(timezone.utc)+timedelta(hours=1))
    completed=MailState(id="c"*24,config_fingerprint="0"*64,imap={"folder":"INBOX","uidvalidity":7,"uid":6})
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


def test_composition_cleanup_and_build_failure(tmp_path, monkeypatch):
    closed=[]
    class Resource:
        def __init__(self,*args,**kwargs): pass
        def close(self): closed.append(type(self).__name__)
    class FakeImap(Resource): pass
    class FakeOpen(Resource): pass
    class FakeTelegram(Resource):
        def send(self,*args): pass
    class FakeWriter(Resource): pass
    monkeypatch.setattr("mailhelp.application.ImapReader",FakeImap)
    monkeypatch.setattr("mailhelp.application.OpenRouterClient",FakeOpen)
    monkeypatch.setattr("mailhelp.application.TelegramClient",FakeTelegram)
    monkeypatch.setattr("mailhelp.application.HttpWriter",FakeWriter)
    cfg=settings(tmp_path); sec=Secrets(imap_username="u",imap_password="p",openrouter_api_key="o",telegram_bot_token="t",todoist_token="d",google_access_token="g")
    topic=[Topic(id="x",name="x",enabled=True,description="x")]
    with build_application(cfg,sec,topic,prompt_config(),"f"*64,base_directory=tmp_path) as made:
        assert made.todoist and (tmp_path/"data/.lock").exists()
        assert made.dialog.relevance_handler is made.orchestrator
        assert made.orchestrator.config_fingerprint == "f"*64
    assert len(closed)==5 and not (tmp_path/"data/.lock").exists()

    cfg.data_directory=Path("relative"); cfg.logging.directory=Path("relative-logs")
    class BrokenTelegram(Resource):
        def __init__(self,*args,**kwargs): raise RuntimeError("build")
    monkeypatch.setattr("mailhelp.application.TelegramClient",BrokenTelegram)
    with pytest.raises(RuntimeError,match="build"):
        with build_application(cfg,sec,topic,prompt_config(),"f"*64,base_directory=tmp_path): pass
    assert not (tmp_path/"relative/.lock").exists()
