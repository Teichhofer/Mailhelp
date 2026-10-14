"""Mailboxes in config.yaml (Planung 3.1, phase 1): both formats, secrets and fingerprints."""
from __future__ import annotations

import pytest
import yaml
from pydantic import SecretStr, ValidationError
from shared_application import settings as app_settings
from shared_core import prompt_config

from mailhelp.cli import _show_imap_credentials
from mailhelp.config import ImapCredentials, ImapSettings, Secrets, Settings, Topic, imap_secret_values
from mailhelp.fingerprints import config_fingerprint, legacy_fingerprints, legacy_policies, topic_policy
from mailhelp.imap import account_id, mailbox_account_id, reader_arguments
from mailhelp.learning import add_discovered_folders
from mailhelp.yaml_edit import _paths, set_list, set_scalars

TOPICS = [Topic(id="schule", name="Schule", enabled=True, description="Schule")]
FORMER = {"host": "imap.example.test", "port": 143, "folders": ["Posteingang", "Archiv"],
          "primary_folder": "Posteingang", "connection_mode": "starttls",
          "historical_start": "2026-09-15T00:00:00+02:00", "drafts_folder": "Entwürfe"}


def configuration(tmp_path, imap: dict) -> Settings:
    data = app_settings(tmp_path).model_dump(mode="json")
    data["imap"] = imap
    return Settings.model_validate(data)


def former(tmp_path, **changes) -> Settings:
    return configuration(tmp_path, {"batch_size": 30, "global_newest_first": True, **FORMER, **changes})


def mailboxes(tmp_path, *entries: dict) -> Settings:
    return configuration(tmp_path, {"batch_size": 30, "global_newest_first": True, "mailboxes": list(entries)})


def test_the_former_imap_section_is_mailbox_1_with_its_defaults(tmp_path):
    imap = configuration(tmp_path, {"host": "h", "port": 993, "folders": ["INBOX", "Spam"]}).imap
    assert imap.legacy_format
    (mailbox,) = imap.configured_mailboxes()
    assert (mailbox.id, mailbox.label, mailbox.enabled) == (1, "Postfach", True)
    assert (mailbox.primary_folder, mailbox.connection_mode, mailbox.drafts_folder) == ("INBOX", "ssl", "Drafts")
    assert mailbox.required_folders == ("INBOX",) and mailbox.optional_folders == ("Spam",)
    assert mailbox.secret_names == ("IMAP_1_USERNAME", "IMAP_1_PASSWORD")
    assert imap.mailbox(1) == mailbox and imap.mailbox(2) is None
    assert imap.enabled_mailboxes() == [mailbox]


def test_the_3_1_format_holds_the_same_mailbox(tmp_path):
    imap = mailboxes(tmp_path, {"id": 1, "label": "Privat", **FORMER}).imap
    assert not imap.legacy_format
    assert imap.configured_mailboxes() == [*imap.mailboxes] and imap.mailbox(1).label == "Privat"
    assert imap.configured_mailboxes()[0].model_dump(exclude={"label"}) == (
        former(tmp_path).imap.configured_mailboxes()[0].model_dump(exclude={"label"}))
    # A dump of either format validates again (the web interface validates dumps).
    for value in (imap, former(tmp_path).imap):
        assert ImapSettings.model_validate(value.model_dump(mode="json")) == value


@pytest.mark.parametrize(("imap", "message"), [
    ({"mailboxes": [{"id": 1, "host": "h", "port": 993, "folders": ["INBOX"]}], "host": "h"},
     "schließen sich aus: host"),
    ({"host": "h", "port": 993}, "mailboxes oder folders"),
    ({"host": "h", "port": 993, "folders": None}, "mailboxes oder folders"),
    ({"host": "h", "port": 993, "folders": ["INBOX"], "primary_folder": "Archiv"}, "primary_folder"),
    ({"mailboxes": [{"id": 1, "host": "h", "port": 993, "folders": ["INBOX"], "primary_folder": "X"}]},
     "primary_folder"),
    ({"mailboxes": [{"id": 1, "host": "h", "port": 993, "folders": ["INBOX", "INBOX"]}]}, "doppelt"),
    ({"mailboxes": [{"id": 1, "host": "h", "port": 993, "folders": ["INBOX"], "enabled": False}]},
     "mindestens ein Postfach"),
    ({"mailboxes": [{"id": 1, "host": "h", "port": 993, "folders": ["INBOX"]},
                    {"id": 2, "host": "h", "port": 993, "folders": ["INBOX"]}]}, "höchstens 1 Postfach"),
    ({"mailboxes": []}, "at least 1"),
])
def test_invalid_mailbox_configurations_are_rejected(imap, message):
    with pytest.raises(ValidationError, match=message):
        ImapSettings.model_validate(imap)


@pytest.mark.parametrize("mailbox", [{"id": 0}, {"id": 100}, {"label": ""}, {"label": "a\nb"},
                                     {"label": "x" * 41}, {"unknown": 1}])
def test_mailbox_fields_are_closed_and_bounded(mailbox):
    with pytest.raises(ValidationError):
        ImapSettings.model_validate({"mailboxes": [{"id": 1, "host": "h", "port": 993, "folders": ["INBOX"],
                                                    **mailbox}]})


def test_duplicate_mailbox_numbers_are_rejected(monkeypatch):
    monkeypatch.setattr("mailhelp.config.MAX_MAILBOXES", 10)
    mailbox = {"id": 1, "host": "h", "port": 993, "folders": ["INBOX"]}
    with pytest.raises(ValidationError, match="doppelt"):
        ImapSettings.model_validate({"mailboxes": [mailbox, {**mailbox, "host": "other"}]})


def test_secrets_use_numbered_names_and_the_former_names_for_mailbox_1(tmp_path):
    legacy, numbered = former(tmp_path).imap, mailboxes(tmp_path, {"id": 1, **FORMER}).imap
    env = {"IMAP_USERNAME": "alt", "IMAP_PASSWORD": "alt-pw"}
    assert imap_secret_values(legacy, env) == ({1: {"username": "alt", "password": "alt-pw"}}, [])
    # The 3.1 format still starts with the names an existing .env contains ...
    assert imap_secret_values(numbered, env) == ({1: {"username": "alt", "password": "alt-pw"}}, [])
    # ... but numbered names take precedence and are the ones reported as missing.
    env.update(IMAP_1_USERNAME="neu", IMAP_1_PASSWORD="neu-pw")
    assert imap_secret_values(legacy, env)[0] == {1: {"username": "neu", "password": "neu-pw"}}
    assert imap_secret_values(numbered, {}) == ({}, ["IMAP_1_USERNAME", "IMAP_1_PASSWORD"])
    assert imap_secret_values(legacy, {"IMAP_USERNAME": "alt"}) == ({}, ["IMAP_PASSWORD"])
    second = mailboxes(tmp_path, {"id": 2, **FORMER}).imap
    assert imap_secret_values(second, env) == ({}, ["IMAP_2_USERNAME", "IMAP_2_PASSWORD"])


def test_loaded_secrets_carry_credentials_by_mailbox_and_redact_every_value(tmp_path):
    secrets = Secrets(imap={1: {"username": "u", "password": "imap-pw"}}, openrouter_api_key="or-key")
    assert secrets.imap_credentials(1).username == "u"
    assert set(secrets.known_values()) == {"imap-pw", "or-key"}
    with pytest.raises(ValidationError):
        Secrets(imap={}, openrouter_api_key="o")
    mailbox = mailboxes(tmp_path, {"id": 1, **FORMER}).imap.mailboxes[0]
    address, options = reader_arguments(mailbox, secrets.imap_credentials(1))
    assert address == ("imap.example.test", 143, "u", "imap-pw") and options["starttls"]
    assert mailbox_account_id(mailbox, secrets.imap_credentials(1)) == account_id("imap.example.test", 143, "u")


def test_terminal_output_names_each_mailbox_only_when_there_are_several(capsys):
    one = Secrets.model_construct(imap={1: ImapCredentials(username="a", password=SecretStr("p"))})
    _show_imap_credentials(one)
    assert "Postfach" not in capsys.readouterr().out
    two = Secrets.model_construct(imap={2: ImapCredentials(username="b", password=SecretStr("q")),
                                        1: ImapCredentials(username="a", password=SecretStr("p"))})
    _show_imap_credentials(two)
    lines = capsys.readouterr().out.splitlines()
    assert lines[1:] == ['Postfach 1 – IMAP-Benutzername: "a"', 'Postfach 1 – IMAP-Passwort: "p"',
                         'Postfach 2 – IMAP-Benutzername: "b"', 'Postfach 2 – IMAP-Passwort: "q"']


def fingerprints(cfg: Settings) -> tuple:
    prompts = prompt_config()
    return (config_fingerprint(cfg, prompts, TOPICS), topic_policy(cfg, prompts),
            legacy_fingerprints(cfg, prompts, TOPICS), legacy_policies(cfg, prompts))


def test_both_formats_have_the_same_current_and_former_fingerprints(tmp_path):
    assert fingerprints(former(tmp_path)) == fingerprints(mailboxes(tmp_path, {"id": 1, "label": "Privat",
                                                                                **FORMER}))


def test_mailboxes_are_operational_for_the_fingerprint(tmp_path):
    current, policy, *_ = fingerprints(former(tmp_path))
    changed = former(tmp_path, host="other.example.test", folders=["INBOX"], primary_folder="INBOX")
    assert fingerprints(changed)[:2] == (current, policy)
    # The former fingerprints describe the former imap section and therefore follow it.
    assert fingerprints(changed)[2] != fingerprints(former(tmp_path))[2]


def test_without_mailbox_1_no_former_fingerprint_exists(tmp_path):
    cfg = mailboxes(tmp_path, {"id": 2, **FORMER})
    current, policy, legacy, policies = fingerprints(cfg)
    assert (current, policy) == fingerprints(former(tmp_path))[:2]
    assert legacy == set() and policies == set()


CONFIG = """# Postfächer
imap:
  batch_size: 25
  mailboxes:
  - id: 1               # privat
    label: Privat
    host: imap.example.test
    port: 993
    folders:
    - INBOX
    drafts_folder: Drafts
targets: {calendar_provider: google}
"""


# The same mailbox with list items indented below their key instead of level with it.
INDENTED = """imap:
  mailboxes:
    - id: 1   # privat
      host: imap.example.test
      port: 993
      folders:
        - INBOX
      drafts_folder: Drafts
    - label: Zweites
      id: 2
"""


@pytest.mark.parametrize("text", [CONFIG, INDENTED])
def test_values_inside_list_items_are_edited_in_place(text):
    assert {"imap.mailboxes.0.id", "imap.mailboxes.0.drafts_folder", "imap.mailboxes.0.folders"} <= {
        path for _, path, _ in _paths(text.splitlines())}
    changed = set_scalars(text, {"imap.mailboxes.0.id": 1, "imap.mailboxes.0.drafts_folder": "Entwürfe",
                                 "imap.mailboxes.0.port": 143})
    assert "# privat" in changed
    expected = yaml.safe_load(text)
    expected["imap"]["mailboxes"][0].update(drafts_folder="Entwürfe", port=143)
    assert yaml.safe_load(changed) == expected
    folders = set_list(changed, "imap.mailboxes.0.folders", ["INBOX", "Archiv"])
    expected["imap"]["mailboxes"][0]["folders"] = ["INBOX", "Archiv"]
    assert yaml.safe_load(folders) == expected
    # A key the item does not have yet is added inside that item, not after the list.
    added = set_scalars(folders, {"imap.mailboxes.0.connection_mode": "starttls"})
    expected["imap"]["mailboxes"][0]["connection_mode"] = "starttls"
    assert yaml.safe_load(added) == expected


def test_keys_of_flow_mappings_are_not_editable_lines():
    assert "targets.calendar_provider" not in {path for _, path, _ in _paths(CONFIG.splitlines())}


def test_learning_adds_folders_to_the_mailbox_of_the_3_1_format(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(CONFIG, encoding="utf-8")
    assert add_discovered_folders(path, ["INBOX"], ["INBOX", "Archiv"], "imap.mailboxes.0.folders") == [
        "INBOX", "Archiv"]
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["imap"]["mailboxes"][0]["folders"] == ["INBOX", "Archiv"]
    for missing in ("imap.mailboxes.3.folders", "imap.mailboxes.x.folders", "imap.batch_size.folders"):
        with pytest.raises(RuntimeError, match="IMAP-Abschnitt"):
            add_discovered_folders(path, ["INBOX"], ["Neu"], missing)
