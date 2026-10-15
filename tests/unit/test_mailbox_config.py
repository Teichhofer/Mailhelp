"""Mailboxes in config.yaml (Planung 3.1, phase 1): both formats, secrets and fingerprints."""
from __future__ import annotations

from types import SimpleNamespace as NS

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
    ({"mailboxes": [{"id": number, "host": "h", "port": 993, "folders": ["INBOX"]} for number in range(1, 12)]},
     "höchstens 10 Postfächer"),
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


def test_without_mailbox_1_only_the_3_1_fingerprint_exists(tmp_path):
    cfg = mailboxes(tmp_path, {"id": 2, **FORMER})
    current, policy, legacy, policies = fingerprints(cfg)
    assert (current, policy) == fingerprints(former(tmp_path))[:2]
    assert len(legacy) == len(policies) == 1
    assert legacy <= fingerprints(former(tmp_path))[2]
    assert policies <= fingerprints(former(tmp_path))[3]


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


def test_learning_and_decision_tests_read_named_or_all_mailboxes(tmp_path, capsys):
    from mailhelp.cli import _parser, _selected_mailboxes
    one = former(tmp_path)
    two = mailboxes(tmp_path, {"id": 1, **FORMER}, {"id": 4, "label": "Arbeit", **FORMER, "host": "b.test"},
                    {"id": 5, **FORMER, "host": "c.test", "enabled": False})
    parser = _parser()

    def selected(cfg, *arguments):
        found = _selected_mailboxes(parser, parser.parse_args(list(arguments)), cfg)
        return None if found is None else [mailbox.id for mailbox in found]

    assert selected(one) is None
    assert selected(one, "--learn", "3") == [1]
    assert selected(two, "--learn", "3", "--mailbox", "4") == [4]
    assert selected(two, "--decision-test", "2", "--mailbox", "1") == [1]
    # "alle" (or "all") reads every enabled mailbox; disabled ones stay out.
    for word in ("alle", "ALL", " Alle "):
        assert selected(two, "--learn", "3", "--mailbox", word) == [1, 4]
    assert selected(one, "--decision-test", "2", "--mailbox", "alle") == [1]
    for cfg, arguments, message in (
            (two, ["--learn", "3"], "--mailbox NUMMER oder --mailbox alle angeben"),
            (two, ["--learn", "3", "--mailbox", "5"], "kein aktiviertes Postfach"),
            (two, ["--mailbox", "4"], "nur zusammen mit --learn"),
            (two, ["--mailbox", "alle"], "nur zusammen mit --learn")):
        with pytest.raises(SystemExit):
            selected(cfg, *arguments)
        assert message in capsys.readouterr().err
    with pytest.raises(SystemExit):
        parser.parse_args(["--learn", "3", "--mailbox", "zwei"])
    assert "Nummer eines Postfachs oder „alle“ erwartet" in capsys.readouterr().err


def test_the_decision_test_reads_the_selected_mailboxes(tmp_path, monkeypatch):
    from mailhelp.decision_test import DecisionTestMode, _comparison_reader, _initial_report
    from mailhelp.ollama import LocalLlm
    cfg = mailboxes(tmp_path, {"id": 1, **FORMER}, {"id": 2, **FORMER, "host": "b.test", "folders": ["Projekte"],
                                                    "primary_folder": "Projekte", "historical_start": None})
    first, second = cfg.imap.mailbox(1), cfg.imap.mailbox(2)
    opened = []
    monkeypatch.setattr("mailhelp.decision_test.ImapReader", lambda *args, **kwargs: opened.append(args[:3]) or
                        type("Reader", (), {"close": lambda self: None})())
    secrets = Secrets(imap={1: {"username": "a", "password": "p"}, 2: {"username": "b", "password": "q"}},
                      openrouter_api_key="o")
    from contextlib import ExitStack
    with ExitStack() as stack:
        _comparison_reader(cfg, secrets, None, stack, second)
    assert opened == [("b.test", 143, "b")]

    def report(selected, ignore=False):
        return _initial_report(cfg, [], prompt_config(), 1, type("P", (), {"model_dump": lambda self, **k: {}})(),
                               LocalLlm("localhost", 11434, "lokal"), None, None, False, ignore, None, selected)
    assert report([second])["historical_start"] is None and report([second])["mailboxes"] == [2]
    assert report([first, second])["historical_start"] == {"1": first.historical_start.isoformat(), "2": None}
    assert report([first, second], ignore=True)["historical_start"] == {"1": None, "2": None}
    mode = DecisionTestMode(None, None, None, cfg, [], {}, tmp_path / "r.json", None, mailbox=second)
    assert mode.mailbox is second and mode.sources == [(second, None)]
    assert DecisionTestMode(None, None, None, cfg, [], {}, tmp_path / "r.json", None).mailbox == first


class Box:
    """Read double of one mailbox for the shared selection of learning and decision tests."""

    def __init__(self, account, messages, unreadable=()):
        from mailhelp.imap import FolderNotReadable
        self.account, self.messages, self.unreadable, self.error = account, messages, set(unreadable), FolderNotReadable
        self.account_id = account
        self.fetched = []

    def list_folders(self):
        return []

    def discover_since(self, folder, **_options):
        from datetime import UTC, datetime, timedelta

        from mailhelp.imap import MailCandidate
        if folder in self.unreadable:
            raise self.error(folder)
        stamp = datetime(2026, 10, 1, tzinfo=UTC)
        return [MailCandidate(folder, 7, uid, self.account, stamp + timedelta(hours=hour))
                for name, uid, hour in self.messages if name == folder]

    def fetch_uid(self, folder, uid, uidvalidity):
        from mailhelp.imap import FetchedMail
        self.fetched.append((folder, uid))
        # The raw mail depends on the UID only: equal UIDs in two mailboxes are the same mail.
        return FetchedMail(folder, uidvalidity, uid, f"Subject: Nr. {uid}\n\nx".encode(), self.account)

    def fetch_since(self, folder, after_uid, uidvalidity, limit, ranges):
        from mailhelp.imap import FetchedMail
        done = {low for low, _high in ranges}
        return [FetchedMail(folder, 7, uid, b"x", self.account) for name, uid, _hour in self.messages
                if name == folder and uid not in done][:limit]


def test_learning_selects_the_newest_mail_of_all_chosen_mailboxes(tmp_path):
    from mailhelp.learning import LearningMode, LearningSource
    private = Box("a", [("INBOX", 1, 1), ("INBOX", 2, 4), ("Sent", 3, 4)])
    work = Box("b", [("INBOX", 1, 3), ("INBOX", 2, 5)], unreadable={"Archiv"})
    output = []
    sources = [LearningSource(private, ["INBOX", "Sent"]), LearningSource(work, ["INBOX", "Archiv"])]
    mode = LearningMode(private, None, ["INBOX"], None, [], tmp_path / "t.yaml", [], tmp_path / "i.yaml",
                        output_fn=output.append, global_newest_first=True, sources=sources)
    mails = mode._fetch(4)
    # b2 (5 h); then a3 before a2 at 4 h (greater UID); then b1 (3 h).
    assert [(mail.account_id, mail.uid) for mail in mails] == [("b", 2), ("a", 3), ("a", 2), ("b", 1)]
    assert any("Archiv" in line for line in output)
    # Without global ordering the mailboxes are read one after the other until the count is reached.
    mode.global_newest_first = False
    assert [(mail.account_id, mail.uid) for mail in mode._fetch(4)] == [("a", 1), ("a", 2), ("a", 3), ("b", 1)]
    assert len(mode._fetch(10)) == 5


def test_the_decision_test_selects_unique_mail_of_all_chosen_mailboxes(tmp_path):
    from mailhelp.decision_test import DecisionTestMode
    cfg = mailboxes(tmp_path, {"id": 1, **FORMER, "folders": ["INBOX"], "primary_folder": "INBOX"},
                    {"id": 2, **FORMER, "host": "b.test", "folders": ["INBOX", "Archiv"], "primary_folder": "INBOX"})
    private = Box("a", [("INBOX", 1, 1), ("INBOX", 2, 3)])
    work = Box("b", [("INBOX", 1, 2)], unreadable={"Archiv"})
    report = {"mails": [], "selection_errors": []}
    mode = DecisionTestMode(private, None, None, cfg, [], report, tmp_path / "r.json", NS(secrets=()),
                            sources=[(cfg.imap.mailbox(1), private), (cfg.imap.mailbox(2), work)])
    mode._pipeline = lambda record, name, mail, analyzer: None
    mode._save = lambda force=False: None
    mode.run(5)
    # Newest first over both mailboxes; mail 1 of mailbox 1 equals the one already taken from mailbox 2.
    assert private.fetched == [("INBOX", 2), ("INBOX", 1)] and work.fetched == [("INBOX", 1)]
    assert [item["uid"] for item in report["mails"]] == [2, 1] and report["selected_mail_count"] == 2
    assert report["selection_errors"] == [{"folder": "Archiv", "error_type": "FolderNotReadable"}]


def test_two_mailboxes_may_not_share_one_account(tmp_path):
    from mailhelp.config import _distinct_accounts
    cfg = mailboxes(tmp_path, {"id": 1, **FORMER}, {"id": 2, **FORMER, "host": "IMAP.example.test."})
    with pytest.raises(ValueError, match="Postfächer 1 und 2 verwenden dasselbe Konto"):
        _distinct_accounts(cfg.imap, {1: {"username": "u"}, 2: {"username": "U "}})
    _distinct_accounts(cfg.imap, {1: {"username": "u"}, 2: {"username": "v"}})
