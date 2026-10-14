"""Shared synthetic fixtures and doubles; no test-module dependencies."""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from mailhelp.application import Application
from mailhelp.config import Settings
from mailhelp.imap import FetchedMail, UIDValidityChanged
from mailhelp.mailbox_run import MailboxRunService
from mailhelp.models import MailRunState
from mailhelp.orchestrator import ProcessingOutcome, ProcessingResult


class Store:
    def __init__(self, values=None):
        self.values=values or {}
        self.saved=[]
    def load(self, name, default=None): return self.values.get(name, default)
    def save(self, name, value):
        self.saved.append((name,value))
        self.values[name]=value
    def names(self, prefix=""): return sorted(name for name in self.values if name.startswith(prefix))
    def load_model(self, name, model, default=None):
        value=self.values.get(name)
        return default if value is None else model.model_validate(value)

from log_fakes import RecordingLogger as Log


class Imap:
    def __init__(self, outcomes):
        self.outcomes=iter(outcomes)
        self.last_uidvalidity=None
        self.account_id="0"*24
        self.calls=[]
        self.uid_calls=[]
    def fetch_since(self,*args):
        self.calls.append(args)
        value=next(self.outcomes)
        if isinstance(value,Exception): raise value
        self.last_uidvalidity=value[0]
        if args[2] is not None and value[0] != args[2]:
            raise UIDValidityChanged(args[0], args[2], value[0])
        return value[1]
    def fetch_uid(self,*args):
        self.uid_calls.append(args)
        return FetchedMail(args[0],args[2],args[1],b"Subject: resumed\n\nBody")

class Telegram:
    def __init__(self, value):
        self.value=value
        self.offsets=[]
        self.sent=[]
    def poll(self, offset, timeout=None):
        self.offsets.append(offset)
        if isinstance(self.value,Exception): raise self.value
        return self.value
    def send(self, chat_id, text): self.sent.append((chat_id,text))

class Orch:
    def __init__(self, fail=False, stop=None, config_fingerprint="0"*64):
        self.fail=fail
        self.stop_event=SimpleNamespace(set=lambda:None)
        self.stop_called=False
        self.seen=[]
        self._stop=stop
        self.config_fingerprint=config_fingerprint
        self.reconciliation=SimpleNamespace(max_candidates=8)
    def stop(self): self.stop_called=True
    def process(self, mail):
        self.seen.append(mail.uid)
        if self._stop: self._stop.set()
        if self.fail: raise RuntimeError("mail")
        return ProcessingResult(ProcessingOutcome.COMPLETED, {})

def settings(tmp_path, folders=("INBOX",), global_newest_first=False):
    return Settings(timezone="UTC",poll_interval_seconds=5,test_mode=True,data_directory=tmp_path/"data",imap={"host":"h","port":993,"folders":list(folders),"global_newest_first":global_newest_first},telegram={"user_id":1,"chat_id":2},targets={"todoist_project":"p","google_calendar":"c"},limits={"max_mail_bytes":1024,"llm_calls_per_minute":2},retries={"provider_retry":0,"json_repair":0,"schema_repair":0},timeouts={**{name:{"timeout_seconds":30.0,"retries":0,"initial_backoff_seconds":0.0,"max_backoff_seconds":1.0} for name in ("imap","telegram","openrouter","todoist","google_calendar")},"telegram_poll_seconds":30},logging={"directory":str(tmp_path/"logs"),"console":{"enabled":False},"file":{"filename":"application.jsonl","max_bytes":10000,"backup_count":1,"retention_days":30},"llm":{"filename":"llm/requests.jsonl","max_bytes":10000,"backup_count":1,"retention_days":30}})

def app(tmp_path, imap, telegram, orch, folders=("INBOX",), store=None,
        global_newest_first=False):
    from threading import Event
    event=Event()
    orch._stop=event if orch._stop else None
    return Application(settings(tmp_path,folders,global_newest_first),store or Store(),Log(),imap,object(),object(),telegram,object(),object(),orch,event)

def _persisted_run(entries):
    return MailRunState(
        run_id="00000000-0000-0000-0000-000000000001", max_mails=100,
        created_at=datetime.now(UTC), entries=entries,
        counters=MailboxRunService.run_counters(entries),
    )


def with_sources(application):
    """An application double whose first enabled mailbox reads with its ``imap`` (3.1)."""
    from mailhelp.mailbox_run import MailboxSource
    application.sources = [MailboxSource(application.settings.imap.enabled_mailboxes()[0], application.imap)]
    return application
