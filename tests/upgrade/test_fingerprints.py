"""Configuration fingerprints: only analysis-relevant changes hold back running mails."""
from __future__ import annotations

import hashlib
import json

import pytest
from shared_application import settings as app_settings
from shared_core import prompt_config

from mailhelp.config import Topic
from mailhelp.fingerprints import (
    adopt_legacy_configuration,
    config_fingerprint,
    legacy_fingerprints,
    legacy_policies,
    topic_policy,
)
from mailhelp.models import MailState, RelevanceDialog
from mailhelp.orchestrator import Orchestrator
from mailhelp.storage import JsonStore

TOPICS = [Topic(id="schule", name="Schule", enabled=True, description="Schule")]


def imap_before_3_1(settings) -> dict:
    """The imap section as every release before 3.1 dumped it (one mailbox, no ``mailboxes``)."""
    imap = settings.imap
    return {"host": imap.host, "port": imap.port, "folders": imap.folders, "primary_folder": imap.primary_folder,
            "connection_mode": imap.connection_mode or "ssl", "historical_start": None,
            "batch_size": imap.batch_size, "global_newest_first": imap.global_newest_first,
            "drafts_folder": imap.drafts_folder or "Drafts"}


def before_2_0(dump: dict, settings) -> dict:
    """A configuration as releases before 2.0 knew it (no 2.0 sections and fields)."""
    dump["imap"] = imap_before_3_1(settings)
    for name in ("push", "daily_briefing", "smart_reply", "personal_info", "activity_report", "notifications", "target_profiles"):
        dump.pop(name, None)
    dump["imap"].pop("drafts_folder")
    dump.get("retention", {}).pop("activity_report_days", None)
    dump["telegram"].pop("enabled")
    # 2.3: original attachments and further write targets.
    dump.pop("attachments", None)
    dump.pop("event_defaults", None)
    dump.pop("proposal_reconciliation", None)
    for name in ("calendar_provider", "task_provider", "caldav_calendar_url", "caldav_task_url",
                 "outlook_calendar", "microsoft_todo_list", "microsoft_tenant"):
        dump["targets"].pop(name)
    return dump


def fingerprint_1_1(settings, prompts, topics) -> str:
    """The algorithm of release 1.1 (all settings except then non-existing sections)."""
    dump = before_2_0(settings.model_dump(mode="json", exclude={"web", "metrics", "vision"}), settings)
    dump["retention"] = {key: value for key, value in dump["retention"].items()
                         if key in {"full_mail_days", "debug_llm_days"}}
    return hashlib.sha256(json.dumps([dump, prompts.model_dump(), [t.model_dump(exclude={"mailboxes"}) for t in topics]],
                                     sort_keys=True).encode()).hexdigest()


@pytest.mark.parametrize("change", [
    lambda s: setattr(s, "poll_interval_seconds", 999),
    lambda s: setattr(s.logging.console, "level", "DEBUG"),
    lambda s: setattr(s.retention, "full_mail_days", 1),
    lambda s: setattr(s.timeouts.imap, "timeout_seconds", 99.0),
    lambda s: setattr(s.metrics, "ollama_power_watts", 50.0),
    lambda s: setattr(s.web, "session_days", 5),
    lambda s: setattr(s.retries, "revision_attempts", 1),
    lambda s: setattr(s.vision, "enabled", False),
    lambda s: setattr(s.vision, "max_images_per_mail", 1),
])
def test_operational_settings_do_not_change_the_fingerprint(tmp_path, change):
    settings, prompts = app_settings(tmp_path), prompt_config()
    before = (config_fingerprint(settings, prompts, TOPICS), topic_policy(settings, prompts))
    change(settings)
    assert (config_fingerprint(settings, prompts, TOPICS), topic_policy(settings, prompts)) == before


def test_analysis_settings_still_change_the_fingerprint(tmp_path):
    settings, prompts = app_settings(tmp_path), prompt_config()
    before = config_fingerprint(settings, prompts, TOPICS)
    settings.timezone = "Europe/Berlin"
    assert config_fingerprint(settings, prompts, TOPICS) != before
    assert config_fingerprint(settings, prompts, [*TOPICS, Topic(id="x", name="X", enabled=True,
                                                                description="x")]) != config_fingerprint(
        settings, prompts, TOPICS)


def fingerprint_1_3(settings, prompts, topics) -> str:
    """The algorithm of release 1.3: no vision section and no vision_ocr prompt existed."""
    operational = {"web", "metrics", "retention", "logging", "learning", "poll_interval_seconds",
                   "timeouts", "retries"}
    dump = before_2_0(settings.model_dump(mode="json", exclude=operational | {"vision"}), settings)
    return hashlib.sha256(json.dumps([dump, prompts.model_dump(), [t.model_dump(exclude={"mailboxes"}) for t in topics]],
                                     sort_keys=True).encode()).hexdigest()


def test_the_vision_prompt_keeps_the_1_3_fingerprint(tmp_path):
    """Upgrading to 1.4 adds vision_ocr; prepared 1.3 mails must not be held back."""
    from mailhelp.config import PromptConfig
    settings, prompts = app_settings(tmp_path), prompt_config()
    before = fingerprint_1_3(settings, prompts, TOPICS)
    assert before in legacy_fingerprints(settings, prompts, TOPICS)
    data = prompts.model_dump()
    data["prompts"]["vision_ocr"] = {"system_prompt": "Lies den Text."}
    with_vision = PromptConfig.model_validate(data)
    assert config_fingerprint(settings, with_vision, TOPICS) == config_fingerprint(settings, prompts, TOPICS)
    assert before in legacy_fingerprints(settings, with_vision, TOPICS)
    assert topic_policy(settings, with_vision) == topic_policy(settings, prompts)
    assert legacy_policies(settings, with_vision) == legacy_policies(settings, prompts)
    assert legacy_fingerprints(settings, with_vision, TOPICS) == legacy_fingerprints(
        settings, prompts, TOPICS)


def orchestrator(store, settings, prompts):
    run = Orchestrator(object(), store, object(), 2, TOPICS, 1024,
                       config_fingerprint=config_fingerprint(settings, prompts, TOPICS))
    run.topic_policy = topic_policy(settings, prompts)
    return run


def test_a_mail_waiting_under_1_1_continues_after_the_upgrade(tmp_path):
    """Regression: the changed fingerprint held back a 1.1 relevance question forever."""
    settings, prompts = app_settings(tmp_path), prompt_config()
    old = fingerprint_1_1(settings, prompts, TOPICS)
    assert old in legacy_fingerprints(settings, prompts, TOPICS)
    with JsonStore(tmp_path / "data") as store:
        waiting = MailState(id="a" * 24, config_fingerprint=old, awaiting_relevance=True,
                            relevance_dialog=RelevanceDialog(mail_id="a" * 24),
                            imap={"account_id": "0" * 24, "folder": "INBOX", "uidvalidity": 1, "uid": 1})
        store.save(f"mail-{waiting.id}", waiting.model_dump(mode="json"))
        run = orchestrator(store, settings, prompts)
        assert not run.accepts_configuration(old)
        added = adopt_legacy_configuration(store, run.config_fingerprint,
                                           legacy_fingerprints(settings, prompts, TOPICS), run.topic_policy,
                                           legacy_policies(settings, prompts), TOPICS)
        assert added == 4
        assert run.accepts_configuration(old) and run.topics_for(old) == TOPICS
        # A second start registers nothing again.
        assert adopt_legacy_configuration(store, run.config_fingerprint,
                                          legacy_fingerprints(settings, prompts, TOPICS), run.topic_policy,
                                          legacy_policies(settings, prompts), TOPICS) == 0


def test_2_0_features_keep_every_former_fingerprint(tmp_path):
    """Regression: 2.0 sections leaked into the legacy fingerprints and held back 1.1 mails."""
    settings, prompts = app_settings(tmp_path), prompt_config()
    old, policies = fingerprint_1_1(settings, prompts, TOPICS), legacy_policies(settings, prompts)
    settings.push.enabled = settings.smart_reply = settings.daily_briefing.enabled = True
    settings.web.enabled, settings.telegram.enabled = True, False
    settings.imap.drafts_folder = "Entwürfe"
    settings.personal_info = "Max Mustermann\nElternbeirat"
    assert old in legacy_fingerprints(settings, prompts, TOPICS)
    assert legacy_policies(settings, prompts) == policies


def test_beta_topic_records_get_the_new_policy(tmp_path):
    settings, prompts = app_settings(tmp_path), prompt_config()
    beta_policy = next(iter(legacy_policies(settings, prompts)))
    with JsonStore(tmp_path / "data") as store:
        store.save("processing-topics-" + "b" * 64, {"schema_version": 1, "policy": beta_policy,
                                                     "topics": [t.model_dump() for t in TOPICS]})
        store.save("processing-topics-" + "c" * 64, {"schema_version": 1, "policy": "other",
                                                     "topics": []})
        run = orchestrator(store, settings, prompts)
        adopt_legacy_configuration(store, run.config_fingerprint, set(), run.topic_policy,
                                   legacy_policies(settings, prompts), TOPICS)
        assert run.accepts_configuration("b" * 64)
        assert not run.accepts_configuration("c" * 64)


def fingerprint_3_0(settings, prompts, topics) -> str:
    """The algorithm of 1.2 to 3.0: operational sections excluded, the imap section included."""
    operational = {"web", "metrics", "retention", "logging", "learning", "poll_interval_seconds", "timeouts",
                   "retries", "vision", "attachments", "push", "daily_briefing", "smart_reply", "personal_info",
                   "activity_report", "notifications", "event_defaults", "proposal_reconciliation", "target_profiles"}
    dump = settings.model_dump(mode="json", exclude=operational)
    dump["imap"] = imap_before_3_1(settings)
    dump["imap"].pop("drafts_folder")
    dump["telegram"].pop("enabled")
    dump.get("retention", {}).pop("activity_report_days", None)
    for name in ("calendar_provider", "task_provider", "caldav_calendar_url", "caldav_task_url",
                 "outlook_calendar", "microsoft_todo_list", "microsoft_tenant"):
        dump["targets"].pop(name)
    step_prompts = prompts.model_dump(exclude={"prompts": {"vision_ocr", "draft_reply", "activity_relevance",
                                                           "activity_events", "diagnostic_test",
                                                           "open_proposal_match"}})
    return hashlib.sha256(json.dumps([dump, step_prompts, [t.model_dump(exclude={"mailboxes"}) for t in topics]],
                                     sort_keys=True).encode()).hexdigest()


def test_a_mail_waiting_under_3_0_continues_with_mailboxes(tmp_path):
    """Planung 3.1: imap became operational; a 3.0 relevance question must not be held back."""
    from mailhelp.config import Settings
    settings, prompts = app_settings(tmp_path), prompt_config()
    old = fingerprint_3_0(settings, prompts, TOPICS)
    assert config_fingerprint(settings, prompts, TOPICS) != old
    # The operator switches to the 3.1 format in the same step as the upgrade.
    data = settings.model_dump(mode="json")
    data["imap"] = {"batch_size": 25, "global_newest_first": False,
                    "mailboxes": [{"id": 1, "label": "Privat", "host": "h", "port": 993, "folders": ["INBOX"]}]}
    upgraded = Settings.model_validate(data)
    with JsonStore(tmp_path / "data") as store:
        run = orchestrator(store, upgraded, prompts)
        assert not run.accepts_configuration(old)
        adopt_legacy_configuration(store, run.config_fingerprint, legacy_fingerprints(upgraded, prompts, TOPICS),
                                   run.topic_policy, legacy_policies(upgraded, prompts), TOPICS)
        assert run.accepts_configuration(old) and run.topics_for(old) == TOPICS


def configuration_3_1(settings, prompts):
    """Independent 3.1 contract: Google/Todoist targets were still in the hash."""
    excluded = {"web", "metrics", "retention", "logging", "learning", "poll_interval_seconds", "timeouts",
                "retries", "vision", "attachments", "push", "daily_briefing", "smart_reply", "personal_info",
                "activity_report", "notifications", "event_defaults", "proposal_reconciliation", "target_profiles",
                "imap"}
    dump = settings.model_dump(mode="json", exclude=excluded)
    dump["telegram"].pop("enabled")
    dump["targets"] = {key: dump["targets"][key] for key in ("google_calendar", "todoist_project")}
    steps = prompts.model_dump(exclude={"prompts": {"vision_ocr", "draft_reply", "activity_relevance",
                                                  "activity_events", "diagnostic_test", "open_proposal_match"}})
    return dump, steps


@pytest.mark.parametrize("jev", [False, True])
def test_3_1_pending_mail_upgrade_and_restart_preserve_proposal_targets(tmp_path, jev):
    """Regression: removing targets must neither hold old mails nor retarget their proposals."""
    from shared_profiles import ACCOUNT_ONE, ACCOUNT_TWO
    from shared_profiles import settings as profile_settings
    from shared_services import AnalyzerStub, Notify

    from mailhelp.decisions import load_relevance_prompts, relevance_fingerprint
    from mailhelp.imap import FetchedMail

    settings, prompts = profile_settings(tmp_path), prompt_config()
    old_settings, old_prompts = configuration_3_1(settings, prompts)
    old_policy = hashlib.sha256(json.dumps([old_settings, old_prompts], sort_keys=True).encode()).hexdigest()
    old_base = hashlib.sha256(json.dumps([old_settings, old_prompts,
                                         [t.model_dump(exclude={"mailboxes"}) for t in TOPICS]],
                                        sort_keys=True).encode()).hexdigest()
    jev_prompts = load_relevance_prompts(tmp_path) if jev else None

    def wrap(value):
        return relevance_fingerprint(value, jev_prompts) if jev_prompts is not None else value

    old = wrap(old_base)
    assert old_base in legacy_fingerprints(settings, prompts, TOPICS)
    assert old_policy in legacy_policies(settings, prompts)
    with JsonStore(tmp_path / "data") as store:
        run = Orchestrator(AnalyzerStub("relevant"), store, Notify(), 1, TOPICS, settings.limits,
                           targets=settings.targets)
        run.configure_mailboxes(settings, prompts, {ACCOUNT_ONE: 1}, jev_prompts)
        result = run.process(FetchedMail("INBOX", 1, 1,
            b"From: synthetic@example.test\r\nSubject: Synthetic\r\n\r\nBody", account_id=ACCOUNT_ONE))
        waiting = MailState.model_validate(result.state)
        waiting.config_fingerprint = old
        before = waiting.model_dump(mode="json")
        store.save("mail-" + waiting.id, before)
        store.save("processing-topics-" + old,
                   {"schema_version": 1, "policy": old_policy, "topics": [t.model_dump() for t in TOPICS]})
        current = run.fingerprint_for(ACCOUNT_ONE)
        assert old != current and not run.accepts_configuration(old, ACCOUNT_ONE)
        adopt_legacy_configuration(store, current, {wrap(item) for item in legacy_fingerprints(settings, prompts, TOPICS)},
                                   topic_policy(settings, prompts), legacy_policies(settings, prompts), TOPICS)
        assert run.accepts_configuration(old, ACCOUNT_ONE)
        assert run.topics_for(old, ACCOUNT_ONE) == TOPICS
        assert store.load("mail-" + waiting.id) == before

    # Persisted equivalence survives restart and subsequent changes to either target.
    settings.targets.google_calendar = "new-calendar"
    settings.targets.todoist_project = "new-project"
    with JsonStore(tmp_path / "data") as store:
        restarted = orchestrator(store, settings, prompts)
        restarted.configure_mailboxes(settings, prompts, {ACCOUNT_ONE: 1}, jev_prompts)
        adopt_legacy_configuration(store, current, {wrap(item) for item in legacy_fingerprints(settings, prompts, TOPICS)},
                                   topic_policy(settings, prompts), legacy_policies(settings, prompts), TOPICS)
        assert restarted.accepts_configuration(old, ACCOUNT_ONE)
        assert restarted.fingerprint_for(ACCOUNT_ONE) == current
        saved = store.load_model("mail-" + waiting.id, MailState)
        rebuilt = restarted.build_proposals(saved)[0]
        original = saved.proposals[0]
        assert (rebuilt.target, rebuilt.target_provider, rebuilt.target_profile) == (
            original.target, original.target_provider, original.target_profile)
        assert rebuilt.target != settings.targets.todoist_project
        assert store.load("mail-" + waiting.id) == before
        # Equivalence never exempts a different analysis or newly restricted topic scope.
        settings.timezone = "America/New_York"
        assert not restarted.accepts_configuration(old, ACCOUNT_ONE)
        settings.timezone = old_settings["timezone"]
        restarted.topics = [TOPICS[0].model_copy(update={"mailboxes": [2]})]
        assert not restarted.accepts_configuration(old, ACCOUNT_ONE)
        # Restricting the existing topic to mailbox 1 leaves its old analysis equivalent.
        restarted.topics = [TOPICS[0].model_copy(update={"mailboxes": [1]})]
        assert restarted.accepts_configuration(old, ACCOUNT_ONE)
        # A new local topic must hold only mailbox 2, including upgraded 3.1 mails.
        restarted.mailbox_numbers[ACCOUNT_TWO] = 2
        restarted.topics = [*TOPICS, Topic(id="work", name="Arbeit", enabled=True,
                                        description="Arbeit", mailboxes=[2])]
        assert restarted.accepts_configuration(old, ACCOUNT_ONE)
        assert not restarted.accepts_configuration(old, ACCOUNT_TWO)
