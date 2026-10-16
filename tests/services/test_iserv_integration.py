"""IServ parent letters in configuration, analysis and the run loop (3.3.7); synthetic data only."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
import yaml
from pydantic import ValidationError
from shared_application import Imap, Orch, Store, Telegram, app
from shared_application import settings as app_settings
from shared_core import prompt_config
from shared_decision_test import secrets
from shared_services import AnalyzerStub, Notify
from shared_web_server import write_config

from mailhelp.config import IServAccountSettings, Settings, Topic, load_all
from mailhelp.fingerprints import config_fingerprint
from mailhelp.imap import FetchedMail
from mailhelp.metrics import MetricsRecorder, MetricsSettings
from mailhelp.models import MailState
from mailhelp.orchestrator import Orchestrator, ProcessingOutcome
from mailhelp.storage import JsonStore

TOPIC = Topic(id="t", name="T", enabled=True, description="t")
ACCOUNT = "e" * 24


def with_iserv(settings: Settings, **account) -> Settings:
    data = settings.model_dump(mode="json")
    data["iserv"] = {"accounts": [{"id": 1, "server": "https://Schule.example/", **account}]}
    return Settings.model_validate(data)


@pytest.mark.parametrize("server", ["http://schule.example", "https://u:p@schule.example", "https://",
                                    "ftp://schule.example", "https://user@schule.example/iserv"])
def test_server_must_be_https_without_credentials(server):
    with pytest.raises(ValidationError, match="https://"):
        IServAccountSettings(id=1, server=server)


@pytest.mark.parametrize("server", ["https://Schule.example/iserv/parentletter/parent/index",
                                    "https://schule.example/?x=1#a", " schule.example ", "Schule.example/iserv/"])
def test_regression_a_pasted_link_or_bare_host_becomes_the_school_origin(server):
    """Regression: a link copied from the browser or a host without https:// was rejected."""
    assert IServAccountSettings(id=1, server=server).server == "https://schule.example"


def test_accounts_need_distinct_ids_and_an_enabled_mailbox(tmp_path):
    settings = with_iserv(app_settings(tmp_path), historical_start="2026-10-01T00:00:00+02:00")
    account = settings.iserv.accounts[0]
    assert account.server == "https://schule.example" and account.secret_names == (
        "ISERV_1_USERNAME", "ISERV_1_PASSWORD")
    assert account.historical_start is not None and settings.iserv.enabled_accounts() == [account]
    data = settings.model_dump(mode="json")
    data["iserv"]["accounts"].append(dict(data["iserv"]["accounts"][0]))
    with pytest.raises(ValidationError, match="verschiedene id"):
        Settings.model_validate(data)
    with pytest.raises(ValidationError, match="kein aktives Postfach"):
        with_iserv(app_settings(tmp_path), mailbox=2)
    assert with_iserv(app_settings(tmp_path), mailbox=2, enabled=False).iserv.enabled_accounts() == []


def test_secrets_of_enabled_accounts_are_required_and_redacted(tmp_path):
    env = write_config(tmp_path)
    data = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
    data["iserv"] = {"accounts": [{"id": 1, "server": "https://schule.example"},
                                  {"id": 2, "server": "https://andere.example", "enabled": False}]}
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ValueError, match="ISERV_1_USERNAME, ISERV_1_PASSWORD"):
        load_all(tmp_path, env)
    env |= {"ISERV_1_USERNAME": "eltern@example.test", "ISERV_1_PASSWORD": "iserv-geheim"}
    settings, loaded, *_ = load_all(tmp_path, env)
    assert loaded.iserv[1].username == "eltern@example.test" and 2 not in loaded.iserv
    assert "iserv-geheim" in loaded.known_values()


def test_iserv_accounts_never_change_the_analysis_fingerprint(tmp_path):
    settings, prompts = app_settings(tmp_path), prompt_config()
    assert config_fingerprint(with_iserv(settings), prompts, [TOPIC]) == config_fingerprint(settings, prompts, [TOPIC])


def test_parent_letters_are_relevant_without_check_or_sender_filter(tmp_path):
    from mailhelp.models import IrrelevantSenders
    letter = FetchedMail("Elternbriefe", 1, 5, b"From: Elternbriefe <elternbriefe@schule.example>\n"
                         b"Subject: Wandertag\n\nAm Freitag ist Wandertag.", ACCOUNT)
    with JsonStore(tmp_path / "state") as store:
        senders = JsonStore(tmp_path / "config")
        senders.save("irrelevant-senders", IrrelevantSenders(domains=["schule.example"]).model_dump())
        orchestrator = Orchestrator(AnalyzerStub("irrelevant"), store, Notify(), 1, [TOPIC], 1000,
                                    sender_store=senders)
        orchestrator.always_relevant = frozenset({ACCOUNT})
        state = orchestrator.process(letter).state
        assert state["relevance"] == {"decision": "relevant", "topic_ids": [],
                                      "reason": "IServ-Elternbrief: immer relevant"}
        assert orchestrator.analyzer.last_relevance_source == "iserv"
        other = FetchedMail("INBOX", 1, 6, b"From: x@schule.example\nSubject: Werbung\n\nKauf", "0" * 24)
        assert orchestrator.process(other).state["relevance"]["reason"] == "Absender-Vorfilter"


def test_no_reply_drafts_for_mail_outside_the_imap_mailboxes():
    from mailhelp.experience import ExperienceRuntime
    assert ExperienceRuntime.draft_policy(SimpleNamespace(mailbox_numbers={}), ACCOUNT) == (False, "")


def test_status_page_knows_the_iserv_contact(tmp_path):
    metrics = MetricsRecorder(tmp_path / "llm.jsonl", MetricsSettings(), "standard")
    metrics.observe("letters_listed", {"service": "iserv"})
    assert set(metrics.runtime()["contacts"]) == {"IServ-Elternbriefe"}
    metrics = MetricsRecorder(tmp_path / "llm2.jsonl", MetricsSettings(), "standard")
    metrics.observe("access_confirmed", {"service": "iserv"})
    assert set(metrics.runtime()["contacts"]) == {"IServ-Elternbriefe"}


class Reader:
    def __init__(self, error=None):
        self.error, self.account_id, self.calls = error, ACCOUNT, []
        self.account = SimpleNamespace(id=1)

    def check_access(self):
        self.calls.append("check")
        if self.error:
            raise self.error

    def fetch_uid(self, folder, uid, uidvalidity):
        self.calls.append((folder, uid, uidvalidity))
        return FetchedMail(folder, uidvalidity, uid, b"Subject: Brief\n\nText", ACCOUNT)


def iserv_service(reader):
    polls = []
    source = SimpleNamespace(account=SimpleNamespace(label="Grundschule"), reader=reader)
    return SimpleNamespace(sources=[source], poll=lambda limit=None: polls.append(limit) or []), polls


def test_the_cycle_reads_letters_after_the_mailboxes(tmp_path):
    service = app(tmp_path, Imap([]), Telegram([]), Orch())
    service.iserv, polls = iserv_service(Reader())
    service._poll_telegram = lambda timeout=None: True
    service._idle = lambda delay: None
    assert service._cycle(None, False) and polls == [None]
    assert not service._cycle(3, False) and polls == [None, 3]
    service.stop_event.set()
    assert not service._cycle(None, False) and polls == [None, 3]


def test_access_checks_include_every_iserv_account(tmp_path, monkeypatch):
    service = app(tmp_path, Imap([]), Telegram([]), Orch())
    service.iserv, _ = iserv_service(Reader(RuntimeError("IServ-Anmeldung fehlgeschlagen")))
    monkeypatch.setattr(type(service), "_check_telegram_access", lambda self: None)
    for name in ("openrouter", "todoist", "calendar"):
        setattr(service, name, SimpleNamespace(check_access=lambda: None, service_name="KI", service=name))
    service.sources[0].reader.check_access = lambda folders: None
    results = service.check_access()
    assert results["IServ Grundschule"] == "IServ-Anmeldung fehlgeschlagen"
    events = []
    contexts = []
    service.logger = SimpleNamespace(event=lambda level, module, event, **context:
                                     (events.append((module, event)), contexts.append(context)))
    service.confirm_access()
    assert ("iserv", "access_check_failed") in events
    assert contexts[-1]["account"] == 1
    service.iserv.sources[0].reader.error = None
    service.confirm_access()
    assert events[-1] == ("iserv", "access_confirmed") and contexts[-1]["account"] == 1


def test_unfinished_letters_resume_through_their_reader(tmp_path):
    pending = MailState(id="a" * 24, config_fingerprint="0" * 64,
                        imap={"account_id": ACCOUNT, "folder": "Elternbriefe", "uidvalidity": 1, "uid": 9})
    orch, reader = Orch(), Reader()
    service = app(tmp_path, Imap([]), Telegram([]), orch, store=Store({"mail-a": pending.model_dump(mode="json")}))
    service.mailbox.resume_readers = {ACCOUNT: reader}
    assert service.mailbox.resume_pending()[0].outcome is ProcessingOutcome.COMPLETED
    assert reader.calls == [("Elternbriefe", 9, 1)] and orch.seen == [9]


def test_composition_builds_and_closes_the_iserv_readers(tmp_path, monkeypatch):
    from mailhelp.application import build_application

    class Resource:
        account_id = "0" * 24

        def __init__(self, *args, **kwargs): pass
        def close(self): pass
    for target in ("mailhelp.composition.ImapReader", "mailhelp.composition.TelegramClient",
                   "mailhelp.external.providers.HttpWriter", "mailhelp.external.providers.GoogleOAuthTokenProvider"):
        monkeypatch.setattr(target, Resource)
    cfg = with_iserv(app_settings(tmp_path), label="Grundschule")
    keys = secrets().model_dump()
    keys["iserv"] = {1: {"username": "eltern@example.test", "password": "geheim"}}
    from mailhelp.config import Secrets
    with build_application(cfg, Secrets.model_validate(keys), [TOPIC], prompt_config(), "f" * 64, tmp_path,
                           use_jev_relevance=False) as built:
        reader = built.iserv.sources[0].reader
        assert built.orchestrator.always_relevant == frozenset({reader.account_id})
        assert built.orchestrator.mailbox_number(reader.account_id) == 1
        assert built.mailbox.resume_readers == {reader.account_id: reader}
        assert built.iserv.sources[0].start is None
        letter = MailState(id="b" * 24, config_fingerprint="0" * 64, imap={
            "account_id": reader.account_id, "folder": "Elternbriefe", "uidvalidity": 1, "uid": 3})
        built.store.save("mail-" + "b" * 24, letter.model_dump(mode="json"))
        assert built.dialog.presenter.mailbox_of(SimpleNamespace(source_mail_id="b" * 24)) == "Grundschule"
    assert reader.client.is_closed
