"""Synthetic .env edits, crash recovery and web-session authorization."""
import hashlib
import hmac
import os

import pytest
import yaml
from shared_application import settings

from mailhelp.config import _dotenv
from mailhelp.configuration import ConfigurationConflict
from mailhelp.credentials import RECEIPTS, CredentialEdits, CredentialService, CredentialUnauthorized
from mailhelp.storage import JsonStore

SESSION = "a" * 16


@pytest.fixture
def credential_service(tmp_path, monkeypatch):
    for name in tuple(os.environ):
        if name.startswith(("IMAP_", "GOOGLE_OAUTH_", "TODOIST_", "CALDAV_", "MICROSOFT_",
                            "OPENROUTER_", "TELEGRAM_BOT_")):
            monkeypatch.delenv(name)
    cfg = settings(tmp_path)
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(cfg.model_dump(mode="json")), encoding="utf-8")
    sign = lambda value: hmac.new(b"synthetic-receipt-key", value.encode(), hashlib.sha256).hexdigest()
    return CredentialService(tmp_path, JsonStore(tmp_path / "state"), lambda session: session == SESSION, sign)


def edit(service, *, key="synthetic-key", name="IMAP_PASSWORD", value="synthetic-new", snapshot=None):
    snapshot = snapshot or service.snapshot()
    return SESSION, key, name, value, snapshot.revision, snapshot.config_revision


@pytest.mark.parametrize("before", ["", "# Keep comment\nOTHER=keep\n", "OTHER=keep",
                                  'IMAP_PASSWORD=old\nIMAP_PASSWORD=duplicate\nOTHER=keep\r\n'])
def test_save_changes_only_one_key_and_keeps_values_out_of_receipts(credential_service, before):
    service = credential_service
    path = service.directory / ".env"
    path.write_bytes(before.encode())
    config = (service.directory / "config.yaml").read_bytes()
    value = '  synthetic-$pass\\word"with\'quotes-ä  '
    arguments = edit(service, value=value)
    service.save(*arguments)
    assert _dotenv(path)["IMAP_PASSWORD"] == value
    assert path.read_text(encoding="utf-8").count("IMAP_PASSWORD=") == 1
    if "OTHER" in before:
        assert _dotenv(path)["OTHER"] == "keep"
    if before.startswith("#"):
        assert path.read_bytes().startswith(b"# Keep comment\n")
    assert (service.directory / "config.yaml").read_bytes() == config
    receipt = service.store.load_model(RECEIPTS, CredentialEdits)
    assert receipt.entries[0].status == "done"
    assert value not in (service.store.directory / (RECEIPTS + ".json")).read_text()
    restarted = CredentialService(service.directory, JsonStore(service.store.directory), service.authorize, service.sign)
    assert next(field for field in restarted.snapshot().fields if field.name == "IMAP_PASSWORD").present
    restarted.save(*arguments)
    assert _dotenv(path)["IMAP_PASSWORD"] == value


@pytest.mark.parametrize("provider", ["google", "caldav", "outlook"])
def test_snapshot_is_scoped_to_mailboxes_and_profiles_and_reports_inheritance(credential_service, monkeypatch, provider):
    service = credential_service
    path = service.directory / "config.yaml"
    cfg = yaml.safe_load(path.read_text())
    cfg["imap"] = {"mailboxes": [{"id": 1, "label": "Privat", "host": "h", "port": 993, "folders": ["INBOX"]},
                                  {"id": 2, "label": "Arbeit", "host": "h", "port": 993, "folders": ["INBOX"]}]}
    cfg["target_profiles"] = [{"id": 2, "label": "Profil <2>", "calendar_provider": provider,
                               "google_calendar": "primary",
                               "caldav_calendar_url": "https://calendar.test/calendar",
                               "caldav_task_url": "https://calendar.test/tasks",
                               "task_provider": "microsoft_todo" if provider == "outlook" else "caldav"}]
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    monkeypatch.setenv("IMAP_USERNAME", "synthetic-user")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "synthetic-google-id")
    monkeypatch.setenv("MICROSOFT_CLIENT_ID", "synthetic-microsoft-id")
    monkeypatch.setenv("IMAP_2_PASSWORD", "synthetic-mailbox-password")
    fields = {field.name: field for field in service.snapshot().fields}
    assert "IMAP_USERNAME" in fields and "IMAP_2_PASSWORD" in fields
    assert fields["IMAP_2_PASSWORD"].overridden and fields["IMAP_2_PASSWORD"].present
    assert "CALDAV_2_PASSWORD" in fields or "MICROSOFT_2_CLIENT_SECRET" in fields
    if provider == "google":
        assert fields["GOOGLE_OAUTH_2_CLIENT_ID"].inherited
    if provider == "outlook":
        assert fields["MICROSOFT_2_CLIENT_ID"].inherited and "MICROSOFT_2_REFRESH_TOKEN" in fields
    assert "synthetic-mailbox-password" not in repr(fields)
    assert "MAILHELP_WEB_SECRET" not in fields


@pytest.mark.parametrize("change", [{"key": "short"}, {"key": "x" * 81}, {"key": "bad.key-name"},
                                    {"value": ""}, {"value": " "}, {"value": "x" * 4001},
                                    *({"value": "a" + char + "b"} for char in ("\n", "\r", "\t", "\x00", "\x7f", "\x85", "\u2028", "\u2029")),
                                    {"value": "bad\ud800"}, {"name": "MAILHELP_WEB_SECRET"},
                                    {"name": "PATH"}, {"name": "IMAP_99_PASSWORD"}])
def test_invalid_edits_never_write_a_secret_or_receipt(credential_service, change):
    service = credential_service
    with pytest.raises(ValueError):
        service.save(*edit(service, **change))
    assert not (service.directory / ".env").exists()
    assert service.store.load(RECEIPTS) is None


def test_newer_values_and_reused_keys_are_protected(credential_service):
    service = credential_service
    first = edit(service)
    stale = edit(service, key="stale-other-key", name="OPENROUTER_API_KEY")
    service.save(*first)
    with pytest.raises(ConfigurationConflict):
        service.save(*stale)
    different = (*first[:3], "different-value", *first[4:])
    with pytest.raises(ConfigurationConflict):
        service.save(*different)
    path = service.directory / ".env"
    path.write_text("IMAP_PASSWORD=manually-newer\n")
    service.save(*first)  # A replay of a completed command never restores its old value.
    assert _dotenv(path)["IMAP_PASSWORD"] == "manually-newer"


@pytest.mark.parametrize("at_write", [False, True])
def test_revoked_sessions_cannot_write_before_or_after_preparation(credential_service, at_write):
    service = credential_service
    calls = iter([True, False] if at_write else [False])
    service.authorize = lambda session: next(calls)
    with pytest.raises(CredentialUnauthorized):
        service.save(*edit(service))
    assert not (service.directory / ".env").exists()


def test_configuration_changes_make_a_form_stale(credential_service):
    service = credential_service
    arguments = edit(service)
    with (service.directory / "config.yaml").open("a") as stream:
        stream.write("# changed\n")
    with pytest.raises(ConfigurationConflict):
        service.save(*arguments)
    assert not (service.directory / ".env").exists()


@pytest.mark.parametrize("changed_file", ["config.yaml", ".env"])
def test_changes_during_preparation_are_not_overwritten(credential_service, monkeypatch, changed_file):
    service = credential_service
    save = service.store.save
    def concurrent(name, value):
        save(name, value)
        with (service.directory / changed_file).open("a") as stream:
            stream.write("# concurrent edit\n")
    monkeypatch.setattr(service.store, "save", concurrent)
    with pytest.raises(ConfigurationConflict):
        service.save(*edit(service))
    if changed_file == ".env":
        assert (service.directory / ".env").read_text() == "# concurrent edit\n"
    else:
        assert not (service.directory / ".env").exists()


@pytest.mark.parametrize("after_write", [False, True])
def test_retry_after_a_write_failure_or_crash_does_not_repeat_a_completed_replace(credential_service, monkeypatch, after_write):
    import mailhelp.credentials as module
    service = credential_service
    arguments = edit(service)
    atomic, save = module.atomic_replace, service.store.save
    writes = []
    def replace(path, content):
        if not after_write:
            raise OSError("synthetic failure")
        writes.append(path)
        atomic(path, content)
    def interrupted(name, value):
        if value["entries"][-1]["status"] == "done":
            raise OSError("synthetic failure after file replacement")
        save(name, value)
    monkeypatch.setattr(module, "atomic_replace", replace)
    if after_write:
        monkeypatch.setattr(service.store, "save", interrupted)
    with pytest.raises(OSError):
        service.save(*arguments)
    assert service.store.load_model(RECEIPTS, CredentialEdits).entries[0].status == "prepared"
    restarted = CredentialService(service.directory, JsonStore(service.store.directory), service.authorize, service.sign)
    def resumed_replace(path, content):
        writes.append(path)
        atomic(path, content)
    monkeypatch.setattr(module, "atomic_replace", resumed_replace)
    restarted.save(*arguments)
    restarted.save(*arguments)
    assert len(writes) == 1
    assert _dotenv(service.directory / ".env")["IMAP_PASSWORD"] == "synthetic-new"
    assert restarted.store.load_model(RECEIPTS, CredentialEdits).entries[0].status == "done"


def test_receipt_retention_stays_bounded_and_evicted_forms_remain_stale(credential_service, monkeypatch):
    monkeypatch.setattr("mailhelp.credentials.MAX_RECEIPTS", 2)
    service = credential_service
    old = edit(service, key="old-key-1")
    service.save(*old)
    for number in (2, 3):
        service.save(*edit(service, key=f"new-key-{number}", value=f"synthetic-{number}"))
    assert len(service.store.load_model(RECEIPTS, CredentialEdits).entries) == 2
    with pytest.raises(ConfigurationConflict):
        service.save(*old)
