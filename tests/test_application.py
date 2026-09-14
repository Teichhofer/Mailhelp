from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import pytest

from mailhelp.application import Application, _safe_name, build_application
from mailhelp.config import Secrets, Settings, Topic
from mailhelp.imap import FetchedMail
from test_core import prompt_config


class Store:
    def __init__(self, values=None): self.values=values or {}; self.saved=[]
    def load(self, name, default=None): return self.values.get(name, default)
    def save(self, name, value): self.saved.append((name,value)); self.values[name]=value


class Log:
    def __init__(self): self.events=[]
    def event(self,*args,**kwargs): self.events.append((args,kwargs))


class Imap:
    def __init__(self, outcomes): self.outcomes=iter(outcomes); self.last_uidvalidity=None; self.calls=[]
    def fetch_since(self,*args):
        self.calls.append(args); value=next(self.outcomes)
        if isinstance(value,Exception): raise value
        self.last_uidvalidity=value[0]; return value[1]


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


def settings(tmp_path, folders=("INBOX",)):
    return Settings(timezone="UTC",poll_interval_seconds=5,test_mode=True,data_directory=tmp_path/"data",imap={"host":"h","port":993,"folders":list(folders)},telegram={"user_id":1,"chat_id":2},targets={"todoist_project":"p","google_calendar":"c"},limits={"max_mail_bytes":100,"llm_calls_per_minute":2},retries={"network":0,"validation":0},logging={"directory":str(tmp_path/"logs")})


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
    assert store.values["imap-"+_safe_name("INBOX")]["uid"]==5 and store.values["telegram-offset"]=={"offset":11}
    assert any(e[0][2]=="mail_failed" for e in service.logger.events)

    failing=app(tmp_path,Imap([RuntimeError("imap"),(9,[]),(10,[])]),Telegram(RuntimeError("tg")),Orch(),folders=("bad","new","none"))
    failing._poll_imap(); failing._poll_telegram()
    assert len(failing.logger.events)==2
    assert failing.store.values["imap-"+_safe_name("new")]=={"uidvalidity":9,"uid":0}
    assert failing.store.values["imap-"+_safe_name("none")]=={"uidvalidity":10,"uid":0}

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
    with build_application(cfg,sec,topic,prompt_config(),tmp_path) as made:
        assert made.todoist and (tmp_path/"data/.lock").exists()
    assert len(closed)==5 and not (tmp_path/"data/.lock").exists()

    cfg.data_directory=Path("relative"); cfg.logging["directory"]="relative-logs"
    class BrokenTelegram(Resource):
        def __init__(self,*args,**kwargs): raise RuntimeError("build")
    monkeypatch.setattr("mailhelp.application.TelegramClient",BrokenTelegram)
    with pytest.raises(RuntimeError,match="build"):
        with build_application(cfg,sec,topic,prompt_config(),tmp_path): pass
    assert not (tmp_path/"relative/.lock").exists()
