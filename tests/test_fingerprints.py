"""Configuration fingerprints: only analysis-relevant changes hold back running mails."""
from __future__ import annotations

import hashlib
import json

import pytest

from mailhelp.config import Topic
from mailhelp.fingerprints import (adopt_legacy_configuration, config_fingerprint, legacy_fingerprints,
                                   legacy_policies, topic_policy)
from mailhelp.models import MailState, RelevanceDialog
from mailhelp.orchestrator import Orchestrator
from mailhelp.storage import JsonStore
from test_application import settings as app_settings
from test_core import prompt_config

TOPICS = [Topic(id="schule", name="Schule", enabled=True, description="Schule")]


def before_2_0(dump: dict) -> dict:
    """A configuration as releases before 2.0 knew it (no 2.0 sections and fields)."""
    for name in ("push", "daily_briefing", "smart_reply", "personal_info"):
        dump.pop(name, None)
    dump["imap"].pop("drafts_folder")
    dump["telegram"].pop("enabled")
    return dump


def fingerprint_1_1(settings, prompts, topics) -> str:
    """The algorithm of release 1.1 (all settings except then non-existing sections)."""
    dump = before_2_0(settings.model_dump(mode="json", exclude={"web", "metrics", "vision"}))
    dump["retention"] = {key: value for key, value in dump["retention"].items()
                         if key in {"full_mail_days", "debug_llm_days"}}
    return hashlib.sha256(json.dumps([dump, prompts.model_dump(), [t.model_dump() for t in topics]],
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
    dump = before_2_0(settings.model_dump(mode="json", exclude=operational | {"vision"}))
    return hashlib.sha256(json.dumps([dump, prompts.model_dump(), [t.model_dump() for t in topics]],
                                     sort_keys=True).encode()).hexdigest()


def test_the_vision_prompt_keeps_the_1_3_fingerprint(tmp_path):
    """Upgrading to 1.4 adds vision_ocr; prepared 1.3 mails must not be held back."""
    from mailhelp.config import PromptConfig
    settings, prompts = app_settings(tmp_path), prompt_config()
    before = fingerprint_1_3(settings, prompts, TOPICS)
    assert config_fingerprint(settings, prompts, TOPICS) == before
    data = prompts.model_dump()
    data["prompts"]["vision_ocr"] = {"system_prompt": "Lies den Text."}
    with_vision = PromptConfig.model_validate(data)
    assert config_fingerprint(settings, with_vision, TOPICS) == before
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
        assert added == 2
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
