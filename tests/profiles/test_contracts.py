"""Inheritance, validation, secrets, scope and upgrade boundaries of version 3.2."""
from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError
from shared_core import prompt_config
from shared_profiles import TOPICS, settings

from mailhelp.config import Secrets, Settings, Topic, validated_file
from mailhelp.fingerprints import config_fingerprint, topic_policy
from mailhelp.mailbox_settings import (
    active_profiles,
    effective_settings,
    effective_topics,
    mailbox_fingerprint,
    mailbox_topic_policy,
    profile_label,
)
from mailhelp.models import IrrelevantSenders
from mailhelp.sender_filter import change_irrelevant_senders, is_irrelevant_sender, save_sender_filter
from mailhelp.storage import JsonStore
from mailhelp.target_profiles import load_profile_secrets, secret_name


def test_sparse_inheritance_survives_dump_and_settings_changes(tmp_path):
    cfg = settings(tmp_path)
    raw = cfg.model_dump(mode="json")
    raw["imap"]["mailboxes"][1].update(personal_info="Arbeitssignatur", smart_reply=False,
        notifications={"quiet_hours": {"enabled": True}, "categories": {"decisions": []}},
        event_defaults={"video_duration_minutes": 90}, retention={"full_mail_days": 7})
    cfg = Settings.model_validate(raw)
    for current in (cfg, Settings.model_validate(cfg.model_dump(mode="json"))):
        work = effective_settings(current, 2)
        assert work.targets.calendar_provider == "outlook"
        assert work.personal_info == "Arbeitssignatur" and not work.smart_reply
        assert work.notifications.quiet_hours.enabled and work.notifications.categories.decisions == []
        assert work.event_defaults.video_duration_minutes == 90
        assert work.event_defaults.in_person_duration_minutes == 180 and work.retention.full_mail_days == 7
        assert effective_settings(current, 1).targets == cfg.targets
    cfg.event_defaults.in_person_duration_minutes = 120
    assert effective_settings(cfg, 2).event_defaults.in_person_duration_minutes == 120
    assert active_profiles(cfg).keys() == {1, 2}
    assert profile_label(cfg, 1) == "Standard" and profile_label(cfg, 2) == "Arbeit"
    assert profile_label(cfg, 99) == "Entferntes Zielprofil"
    with pytest.raises(LookupError):
        effective_settings(cfg, 99)


@pytest.mark.parametrize(("change", "path"), [
    ("missing", "imap.mailboxes.1.target_profile"),
    ("retention", "imap.mailboxes.1.retention"),
    ("duplicate", "<root>"),
    ("quiet", "imap.mailboxes.1.notifications.quiet_hours"),
])
def test_invalid_cross_references_are_configuration_errors(tmp_path, change, path):
    raw = settings(tmp_path).model_dump(mode="json")
    if change == "missing":
        raw["target_profiles"] = []
    elif change == "retention":
        raw["imap"]["mailboxes"][1]["retention"] = {"full_mail_days": "unlimited"}
    elif change == "duplicate":
        raw["target_profiles"] *= 2
    else:
        raw["imap"]["mailboxes"][1]["notifications"] = {"quiet_hours": {"enabled": True, "start": "07:30"}}
    with pytest.raises(ValueError, match=path.replace(".", r"\.")):
        validated_file(Path("config.yaml"), Settings, raw)


@pytest.mark.parametrize("period", ["disabled", 1, 30])
def test_mailbox_retention_cannot_lengthen_the_global_policy(tmp_path, period):
    raw = settings(tmp_path).model_dump(mode="json")
    raw["imap"]["mailboxes"][1]["retention"] = {"full_mail_days": period}
    assert Settings.model_validate(raw).imap.mailbox(2).retention.full_mail_days == period


def test_fingerprints_isolate_mailbox_changes(tmp_path):
    cfg, prompts = settings(tmp_path), prompt_config()
    original = config_fingerprint(cfg, prompts, TOPICS)
    assert mailbox_fingerprint(cfg, prompts, TOPICS, 1) == mailbox_fingerprint(cfg, prompts, TOPICS, 2) == original
    raw = cfg.model_dump(mode="json")
    raw["target_profiles"][0]["outlook_calendar"] = "another"
    raw["imap"]["mailboxes"][1]["personal_info"] = "Andere Rolle"
    assert mailbox_fingerprint(Settings.model_validate(raw), prompts, TOPICS, 2) == original
    scoped = TOPICS + [Topic(id="work", name="Arbeit", enabled=True, description="Arbeit", mailboxes=[2])]
    assert effective_topics(scoped, 1) == TOPICS and effective_topics(scoped, 2) == scoped
    assert mailbox_fingerprint(cfg, prompts, scoped, 1) == original
    assert mailbox_fingerprint(cfg, prompts, scoped, 2) != original
    raw["imap"]["mailboxes"][1]["event_defaults"] = {"video_duration_minutes": 90}
    changed = Settings.model_validate(raw)
    assert mailbox_fingerprint(changed, prompts, TOPICS, 1) == original
    assert mailbox_fingerprint(changed, prompts, TOPICS, 2) != original


@pytest.mark.parametrize(("field", "value"), [
    ("google_calendar", "another-calendar"), ("todoist_project", "another-project"),
    ("calendar_provider", "outlook"), ("task_provider", "microsoft_todo"),
    ("caldav_calendar_url", "https://calendar.example.test/events"),
    ("caldav_task_url", "https://calendar.example.test/tasks"),
    ("outlook_calendar", "another-outlook-calendar"), ("microsoft_todo_list", "another-list"),
    ("microsoft_tenant", "another-tenant"),
])
def test_all_targets_are_operational_for_global_and_mailbox_fingerprints(tmp_path, field, value):
    """Regression: standard Google/Todoist targets used to hold back pending mails."""
    cfg, prompts = settings(tmp_path), prompt_config()

    def hashes():
        return (config_fingerprint(cfg, prompts, TOPICS), topic_policy(cfg, prompts),
                *(mailbox_fingerprint(cfg, prompts, TOPICS, number) for number in (1, 2)),
                *(mailbox_topic_policy(cfg, prompts, number) for number in (1, 2)))

    before = hashes()
    setattr(cfg.targets, field, value)
    setattr(cfg.target_profiles[0], field, value)
    cfg.target_profiles[0].label = "Umbenannt"
    cfg.imap.mailboxes[1].target_profile = 1
    assert hashes() == before


@pytest.mark.parametrize("ids", [[0], [100], [1, 1]])
def test_topic_scope_is_closed_and_uses_stable_numbers(ids):
    with pytest.raises(ValidationError):
        TOPICS[0].model_validate({**TOPICS[0].model_dump(), "mailboxes": ids})


def test_profile_secrets_share_clients_but_never_tokens(tmp_path):
    cfg = settings(tmp_path)
    values, missing = load_profile_secrets(cfg, {"MICROSOFT_CLIENT_ID": "shared-client",
        "MICROSOFT_REFRESH_TOKEN": "private-token", "MICROSOFT_2_REFRESH_TOKEN": "work-token"})
    assert missing == [] and values[2] == {"microsoft_client_id": "shared-client", "microsoft_refresh_token": "work-token"}
    assert secret_name("GOOGLE_OAUTH_REFRESH_TOKEN", 2) == "GOOGLE_OAUTH_2_REFRESH_TOKEN"
    assert secret_name("TODOIST_TOKEN", 2) == "TODOIST_2_TOKEN"
    values, missing = load_profile_secrets(cfg, {})
    assert missing == ["MICROSOFT_2_CLIENT_ID"] and values == {2: {}}
    cfg.target_profiles[0].task_provider = "todoist"
    values, missing = load_profile_secrets(cfg, {"TODOIST_TOKEN": "private", "TODOIST_CLIENT_ID": "shared",
        "TODOIST_CLIENT_SECRET": "secret", "MICROSOFT_2_CLIENT_ID": "work-client"})
    assert "TODOIST_2_TOKEN" in missing and "todoist_token" not in values[2]
    secrets = Secrets(imap={1: {"username": "synthetic", "password": "imap-secret"}}, openrouter_api_key="llm",
        todoist_token="private", profiles={2: {"todoist_token": "work"}})
    assert secrets.for_profile(1) is secrets and secrets.for_profile(2).todoist_token == SecretStr("work")
    assert not secrets.for_profile(2).google_oauth_refresh_token.get_secret_value()
    assert "work" in secrets.known_values()
    with pytest.raises(LookupError):
        secrets.for_profile(3)


def test_scoped_sender_allow_and_lazy_upgrade_are_atomic(tmp_path):
    store = JsonStore(tmp_path)
    old = {"schema_version": 1, "addresses": [], "domains": ["example.test"]}
    store.save("irrelevant-senders", old)
    blocked = store.load_model("irrelevant-senders", IrrelevantSenders)
    assert store.load("irrelevant-senders") == old
    blocked = change_irrelevant_senders(blocked, True, ["chief@example.test"], [], 2, allow=True)
    assert is_irrelevant_sender("chief@example.test", blocked, 1)
    assert not is_irrelevant_sender("chief@example.test", blocked, 2)
    assert is_irrelevant_sender("other@example.test", blocked, 2)
    save_sender_filter(store, blocked)
    assert (tmp_path / "irrelevant-senders.json.v1").is_file()
    save_sender_filter(store, blocked)
    assert store.load_model("irrelevant-senders", IrrelevantSenders) == blocked
    own = change_irrelevant_senders(blocked, True, ["digest@work.test"], [], 2)
    assert is_irrelevant_sender("digest@work.test", own, 2) and not is_irrelevant_sender("digest@work.test", own, 1)
    own = change_irrelevant_senders(own, False, ["digest@work.test"], [], 2)
    assert not is_irrelevant_sender("digest@work.test", own, 2)
    for invalid in ({"mailboxes": {"0": {}}}, {"mailboxes": {"2": {"allow": ["UPPER@test.test"]}}}):
        with pytest.raises(ValidationError):
            IrrelevantSenders.model_validate(invalid)
