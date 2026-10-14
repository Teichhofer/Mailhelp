"""Trusted profile binding, adapter isolation and repeatable proposal upgrades."""
from types import SimpleNamespace as NS

import httpx
import pytest
from shared_core import prompt_config
from shared_decision_test import secrets
from shared_profiles import TOPICS, settings
from shared_telegram_dialog import Telegram, controller, proposal

from mailhelp import profile_binding
from mailhelp.adapter import UncertainWriteError
from mailhelp.external.confirmed import execute_confirmed
from mailhelp.external.contracts import ExternalUnavailable, PreparedWrite, TargetWriter
from mailhelp.external.providers import Writers, microsoft_tokens
from mailhelp.external.roles import writer_for
from mailhelp.mailbox_settings import event_defaults_for, mailbox_topic_policy
from mailhelp.models import MailState, Proposal
from mailhelp.persistence.ledger import ActionLedgerService
from mailhelp.persistence.migrations import migrate_document
from mailhelp.precheck import DuplicatePreCheckService
from mailhelp.profile_usage import profile_references
from mailhelp.storage import JsonStore
from mailhelp.target_profiles import ProfileWriters, UnavailableWriter, build_profile_writers


class Adapter(TargetWriter):
    def __init__(self, number=1, target="inbox", service="todoist", fail=None):
        self.target_profile, self.target, self.service, self.fail = number, target, service, fail
        self.role, self.label, self.calls, self.found, self.closed = "tasks", "Synthetic", [], None, False
    def check_access(self):
        if self.fail:
            raise self.fail
    def reconcile(self, key):
        self.calls.append(("reconcile", key))
        self.check_access()
        return self.found
    def prepare(self, item, key):
        self.calls.append(("prepare", item.target_profile))
        def operation():
            self.calls.append(("write", key))
            if self.fail:
                raise self.fail
            return {"id": str(self.target_profile)}
        return PreparedWrite(operation)
    def close(self):
        self.closed = True


def test_profile_selection_confirmation_and_uncertain_reconciliation():
    one, two = Adapter(), Adapter(2)
    p = proposal(target_profile=2, status="confirmed")
    slots = {"todoist": one, "todoist:2": two}
    assert writer_for(slots, p) is two
    persisted = []
    created, _ = execute_confirmed(p, two, persisted.append)
    assert created.external_id == "2" and not one.calls
    assert [item.status for item in persisted] == ["writing", "created"]
    assert execute_confirmed(p, one, persisted.append)[1] == {"target_mismatch": True}
    for status in ("pending_confirmation", "needs_clarification"):
        with pytest.raises(ValueError):
            execute_confirmed(p.model_copy(update={"status": status}), two, persisted.append)
    two.calls = []
    two.prepare = lambda *args: PreparedWrite(lambda: (_ for _ in ()).throw(UncertainWriteError("unknown")))
    uncertain, _ = execute_confirmed(p, two, persisted.append)
    assert uncertain.status == "uncertain"
    restarted, _ = execute_confirmed(uncertain, two, persisted.append)
    assert restarted.status == "uncertain" and [call[0] for call in two.calls] == ["reconcile", "reconcile"]
    two.found = {"id": "2"}
    assert execute_confirmed(restarted, two, persisted.append)[0].status == "created"
    assert ActionLedgerService.action_key(p) != ActionLedgerService.action_key(p.model_copy(update={"target_profile": 1}))


def test_binding_checks_removed_profile_and_retarget_invalidates_permissions(tmp_path):
    cfg = settings(tmp_path)
    p = proposal(target="default", target_provider="microsoft_todo", target_profile=2,
        explicit_create_fallback_confirmed=True)
    adapter = Adapter(2, "default", "microsoft_todo")
    assert profile_binding.available(cfg, {"todoist:2": adapter}, p)
    assert not profile_binding.available(cfg, {}, p)
    assert not profile_binding.available(cfg, {"todoist:2": UnavailableWriter("tasks", "default", 2)}, p)
    assert not profile_binding.available(cfg, {"todoist:2": Adapter(2, "wrong")}, p)
    assert not profile_binding.available(cfg, {"todoist:2": Adapter(2, "default", "todoist")}, p)
    assert profile_binding.available(cfg, {"todoist:2": object()}, p)
    cfg.target_profiles = []
    assert not profile_binding.available(cfg, {"todoist:2": adapter}, p)
    assert profile_binding.label(cfg, p) == "Entferntes Zielprofil"
    assert profile_binding.available(cfg, {}, proposal()) and profile_binding.label(cfg, proposal()) == ""
    assert profile_binding.summary(cfg, {}) == ""
    cfg = settings(tmp_path)
    assert profile_binding.label(cfg, p) == "Microsoft To Do · Arbeit"
    assert "nicht verfügbar" in profile_binding.summary(cfg, {})
    assert "konfiguriert" in profile_binding.summary(cfg, {"google_calendar": adapter})
    chosen = profile_binding.retarget(cfg, p, 1, profile_binding.policy_hash(cfg))
    assert chosen.version == 2 and chosen.target_profile == 1 and chosen.status == "pending_confirmation"
    assert not chosen.explicit_create_fallback_confirmed and not chosen.external_id
    with pytest.raises(ValueError):
        profile_binding.retarget(cfg, p, 1, "0" * 64)
    for changed in (p.model_copy(update={"status": "confirmed"}),
                    p.model_copy(update={"pending_sources": [{"mail_id": "b" * 24, "proposal_id": "p2"}]}),
                    p.model_copy(update={"matching_candidates": [{"mail_id": "b" * 24, "proposal_id": "p2"}]})):
        assert profile_binding.choices(cfg, changed) == []
    event = proposal(kind="event", start="2026-10-15", end="2026-10-16", all_day=True,
        target="inbox", target_provider="google", classification="non_binding")
    moved = profile_binding.retarget(cfg, event, 2, profile_binding.policy_hash(cfg))
    assert moved.target == "default" and moved.status == "needs_clarification"
    assert profile_binding.label(cfg, moved) == "Outlook-Kalender · Arbeit"


def test_adapters_are_built_once_and_failures_do_not_disable_other_profiles(tmp_path, monkeypatch):
    cfg = settings(tmp_path)
    private, work = Adapter(), Adapter(2)
    calls = []
    def build(settings, credentials, directory, *, profile_id):
        calls.append(profile_id)
        if profile_id == 2:
            raise ValueError("secret URL https://private.test")
        return Writers(private, work)
    monkeypatch.setattr("mailhelp.target_profiles.build_writers", build)
    secret = secrets().model_copy(update={"profiles": {2: {"microsoft_client_id": secrets().microsoft_client_id}}})
    logger = NS(event=lambda *args, **kwargs: calls.append(kwargs))
    pairs = build_profile_writers(cfg, secret, tmp_path)
    assert pairs.calendar is private and pairs.tasks is work and len(pairs.slots) == 4
    assert isinstance(pairs.profiles[2].calendar, UnavailableWriter)
    pairs.close()
    assert private.closed and work.closed
    pairs = build_profile_writers(cfg, secret.model_copy(update={"profiles": {2: {}}}), tmp_path, logger=logger)
    assert calls[-1]["error"] == "LookupError" and "private" not in str(calls[-1])
    cfg.imap.mailboxes[0].enabled = False
    cfg.target_profiles = []
    cfg.imap.mailboxes[1].target_profile = 1
    assert build_profile_writers(cfg, secret, tmp_path).default_profile == 1
    unavailable = UnavailableWriter("calendar", "gone", 2)
    for operation in (unavailable.check_access, lambda: unavailable.reconcile("key"),
                      lambda: unavailable.prepare(proposal(), "key"),
                      lambda: unavailable.fetch_events_in_window(None, None), unavailable.fetch_active_tasks):
        with pytest.raises(ExternalUnavailable):
            operation()
    unavailable.close()
    assert DuplicatePreCheckService(writers={}).check_proposal(proposal(target_profile=2)).duplicate_check_failed


def test_upgrade_is_atomic_repeatable_and_profile_references_ignore_snapshots(tmp_path):
    cfg = settings(tmp_path)
    old = proposal().model_dump(mode="json")
    old.update(schema_version=2)
    old.pop("target_profile")
    nested = {"proposals": [dict(old)], "nested": {"other": 1}}
    assert migrate_document("MailState", nested) and nested["proposals"][0]["target_profile"] == 1
    assert not migrate_document("MailState", nested) and not migrate_document("Something", old)
    with JsonStore(tmp_path / "data") as store:
        store.save("proposal-" + "a" * 24 + "-p1", old)
        migrated = store.load_model("proposal-" + "a" * 24 + "-p1", Proposal)
        assert migrated.target_profile == 1 and store.load("proposal-" + "a" * 24 + "-p1")["schema_version"] == 3
        store.save("proposal-copy-v1", proposal(target_profile=2).model_dump(mode="json"))
        store.save("proposal-current", proposal(target_profile=2).model_dump(mode="json"))
        store.save("proposal-finished", proposal(target_profile=2, status="created").model_dump(mode="json"))
        refs = profile_references(store, cfg, 2)
        assert len(refs) == 2 and refs[0].startswith("Postfach 2")
        assert event_defaults_for(cfg, store, proposal()) == cfg.event_defaults
        mail = MailState(id="a" * 24, config_fingerprint="f" * 64,
            imap={"account_id": "2" * 24, "folder": "INBOX", "uidvalidity": 1, "uid": 1})
        cfg.imap.mailboxes[1].event_defaults = cfg.imap.mailboxes[1].model_validate(
            {**cfg.imap.mailboxes[1].model_dump(), "event_defaults": {"video_duration_minutes": 90}}).event_defaults
        store.save("mail-" + mail.id, mail.model_dump(mode="json"))
        assert event_defaults_for(cfg, store, proposal(), {"2" * 24: (2, "Work")}).video_duration_minutes == 90
        assert event_defaults_for(cfg, store, proposal(), {"2" * 24: 99}) == cfg.event_defaults
        assert mailbox_topic_policy(cfg, prompt_config(), 1) != mailbox_topic_policy(cfg, prompt_config(), 2)


def test_microsoft_oauth_keeps_profile_vaults_separate(tmp_path):
    cfg, creds = settings(tmp_path), secrets()
    one = microsoft_tokens(cfg, creds, tmp_path, 10)
    two = microsoft_tokens(cfg, creds, tmp_path, 10, profile_id=2)
    assert one._tokens.path != two._tokens.path
    one.close()
    two.close()
