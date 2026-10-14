"""Drafts cannot authorize an external action, survive restarts and reject stale files."""
import json
from types import SimpleNamespace as NS

import pytest
import yaml
from shared_application import settings
from shared_core import prompt_config

from mailhelp.configuration import ConfigurationConflict, ConfigurationService, file_hash
from mailhelp.diagnostics import DiagnosticsService
from mailhelp.fingerprints import config_fingerprint
from mailhelp.notification_config import NotificationSettings
from mailhelp.review.results import ResultStatus
from mailhelp.setup import SetupService
from mailhelp.storage import JsonStore

ACTOR = "web:" + "a" * 16


def diagnose(setup, name="imap"):
    service = DiagnosticsService(setup.config.store, lambda actor: actor in setup.active,
                                 {name: lambda actor: ("ready", "")}, revision=setup.service.fingerprint)
    service.run(ACTOR, name, service.state().version, f"test-{service.state().version:08d}")


@pytest.fixture
def setup(tmp_path):
    cfg = settings(tmp_path)
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg.model_dump(mode="json")), encoding="utf-8")
    active, updated = {ACTOR}, []
    config = ConfigurationService(tmp_path, JsonStore(tmp_path / "state"), cfg,
                                  lambda actor: actor in active, updated.append)
    return NS(cfg=cfg, path=path, config=config, service=SetupService(config), active=active, updated=updated)


def test_saved_draft_is_not_active_and_requires_fresh_confirmation_after_restart(setup):
    before = setup.path.read_bytes()
    state = setup.service.save(ACTOR, 0, "save-0001", 2, {"imap.drafts_folder": "Entwürfe"})
    diagnose(setup)
    assert state.step == 2 and state.version == 1
    assert setup.path.read_bytes() == before and setup.updated == []
    restarted = SetupService(setup.config)
    assert restarted.state() == state
    assert restarted.save(ACTOR, 0, "save-0001", 2, {"imap.drafts_folder": "Entwürfe"}) == state
    setup.active.clear()
    with pytest.raises(PermissionError):
        restarted.command(ACTOR, 1, "apply-001", state.base_hash)
    setup.active.add(ACTOR)
    command = restarted.command(ACTOR, 1, "apply-001", state.base_hash)
    setup.active.clear()
    assert setup.config.execute(command).status == ResultStatus.UNAUTHORIZED
    assert setup.path.read_bytes() == before
    setup.active.add(ACTOR)
    assert setup.config.execute(command).status == ResultStatus.DONE
    assert yaml.safe_load(setup.path.read_text(encoding="utf-8"))["imap"]["drafts_folder"] == "Entwürfe"
    assert setup.updated[0].imap.drafts_folder == setup.cfg.imap.drafts_folder  # Requires restart.


def test_stale_versions_files_and_idempotency_conflicts_never_overwrite(setup):
    state = setup.service.save(ACTOR, 0, "save-0001", 1, {"timezone": "Europe/Berlin"})
    with pytest.raises(ValueError, match="Idempotenzkonflikt"):
        setup.service.save(ACTOR, 0, "save-0001", 1, {"timezone": "UTC"})
    with pytest.raises(ConfigurationConflict):
        setup.service.save(ACTOR, 0, "save-0002", 1, {})
    with pytest.raises(ConfigurationConflict):
        setup.service.command(ACTOR, 0, "apply-001", state.base_hash)
    with pytest.raises(ConfigurationConflict):
        setup.service.command(ACTOR, 1, "apply-001", "0" * 64)
    setup.path.write_text(setup.path.read_text(encoding="utf-8") + "# concurrent change\n", encoding="utf-8")
    with pytest.raises(ConfigurationConflict):
        setup.service.save(ACTOR, 1, "save-0002", 1, {})
    refreshed = setup.service.save(ACTOR, 1, "refresh-1", 6, {}, refresh=True)
    assert refreshed.patch == state.patch and refreshed.base_hash != state.base_hash
    command = setup.service.command(ACTOR, 2, "apply-001", refreshed.base_hash)
    assert setup.config.execute(command).status == ResultStatus.DONE
    assert "# concurrent change" in setup.path.read_text(encoding="utf-8")


def test_upgrade_profile_keeps_channel_choices_and_never_changes_analysis_fingerprint(setup):
    before = config_fingerprint(setup.cfg, prompt_config(), [])
    state = setup.service.save(ACTOR, 0, "save-0001", 5, {"notifications.quiet_hours.enabled": True})
    assert state.patch["notifications.telegram_content"] == "summary"
    assert state.patch["notifications.categories.decisions"] == ["telegram"]
    command = setup.service.command(ACTOR, state.version, "apply-001", state.base_hash)
    assert setup.config.execute(command).status == ResultStatus.DONE
    assert setup.config.active.notifications.quiet_hours.enabled
    assert config_fingerprint(setup.config.active, prompt_config(), []) == before
    setup.config.active.notifications = NotificationSettings()
    assert config_fingerprint(setup.config.active, prompt_config(), []) == before


def test_lists_can_be_added_without_losing_config_comments(setup):
    raw = yaml.safe_load(setup.path.read_text(encoding="utf-8"))
    del raw["notifications"]
    setup.path.write_text("# preserve me\n" + yaml.safe_dump(raw), encoding="utf-8")
    state = setup.service.save(ACTOR, 0, "save-0001", 5, {"notifications.categories.decisions": []})
    command = setup.service.command(ACTOR, 1, "apply-001", state.base_hash)
    assert setup.config.execute(command).status == ResultStatus.DONE
    saved = setup.path.read_text(encoding="utf-8")
    assert "# preserve me" in saved and yaml.safe_load(saved)["notifications"]["categories"]["decisions"] == []


def test_draft_rejects_secrets_invalid_steps_keys_and_revoked_sessions(setup):
    for step, patch, key in ((0, {}, "save-0001"), (7, {}, "save-0001"),
                              (1, {"IMAP_PASSWORD": "secret"}, "save-0001"),
                              (1, {"timezone": "invalid"}, "save-0001"), (1, {}, "bad")):
        with pytest.raises(ValueError):
            setup.service.save(ACTOR, 0, key, step, patch)
    setup.active.clear()
    with pytest.raises(PermissionError):
        setup.service.save(ACTOR, 0, "save-0001", 1, {})
    assert setup.service.state().version == 0


def test_existing_profile_and_bounded_operation_history(setup):
    cfg = setup.cfg.model_copy(update={"notifications": NotificationSettings()})
    setup.path.write_text(yaml.safe_dump(cfg.model_dump(mode="json")), encoding="utf-8")
    state = setup.service.state()
    state.operations = {f"web:key-{index}": "x" for index in range(500)}
    setup.service.store.save("setup-state", state.model_dump(mode="json"))
    state = setup.service.save(ACTOR, 0, "save-0001", 5, {"notifications.telegram_content": "summary"})
    assert state.patch == {"notifications.telegram_content": "summary"}
    assert len(state.operations) == 500


def test_connection_changes_require_a_successful_check_of_the_exact_current_draft(setup):
    state = setup.service.save(ACTOR, 0, "save-0001", 2, {"imap.drafts_folder": "Entwürfe"})
    with pytest.raises(ValueError, match="Diagnose"):
        setup.service.command(ACTOR, state.version, "apply-001", state.base_hash)
    diagnose(setup)
    state = setup.service.save(ACTOR, state.version, "save-0002", 2, {"imap.drafts_folder": "Archiv"})
    with pytest.raises(ValueError, match="Diagnose"):
        setup.service.command(ACTOR, state.version, "apply-001", state.base_hash)
    diagnose(setup)
    assert setup.service.command(ACTOR, state.version, "apply-001", state.base_hash).patch["imap.drafts_folder"] == "Archiv"
    setup.path.write_text(setup.path.read_text(encoding="utf-8") + "# changed\n", encoding="utf-8")
    with pytest.raises(ConfigurationConflict):
        setup.service.draft_settings()
