"""8.0: encrypted secrets with the key outside the state directory (synthetic secrets only)."""
import json
import os

import pytest

from inboxstride_auth.secret_store import SecretStore, SecretStoreError, add_key, create_key

TOKEN = "synthetic-refresh-token-1"


@pytest.fixture
def paths(tmp_path):
    key = tmp_path / "keys" / "auth.key"
    key.parent.mkdir()
    create_key(key)
    return tmp_path / "state", key


def test_secrets_are_stored_encrypted_and_read_back(paths):
    store = SecretStore(*paths)
    assert store.get("refresh:a") is None and store.names() == [] and not store.delete("refresh:a")
    store.put("refresh:a", TOKEN)
    store.put("client", "synthetic-client-secret")
    raw = (paths[0] / "secrets.json").read_text(encoding="utf-8")
    assert TOKEN not in raw and "synthetic-client-secret" not in raw
    assert store.get("refresh:a") == TOKEN and store.names() == ["client", "refresh:a"]
    assert store.delete("refresh:a") and store.names() == ["client"]


def test_a_backup_of_the_state_alone_decrypts_nothing(paths, tmp_path):
    SecretStore(*paths).put("refresh:a", TOKEN)
    other = tmp_path / "other.key"
    create_key(other)
    with pytest.raises(SecretStoreError, match="keinem Schlüssel"):
        SecretStore(paths[0], other).get("refresh:a")
    with pytest.raises(SecretStoreError, match="keinem Schlüssel"):
        SecretStore(paths[0], other).rotate()


def test_a_new_key_takes_over_after_rotation(paths):
    state, key = paths
    SecretStore(state, key).put("refresh:a", TOKEN)
    old = key.read_text(encoding="ascii")
    add_key(key)
    rotated = SecretStore(state, key)
    assert rotated.rotate() == 1 and rotated.get("refresh:a") == TOKEN
    key.write_text(key.read_text(encoding="ascii").split()[0] + "\n", encoding="ascii")  # the old key is gone
    assert SecretStore(state, key).get("refresh:a") == TOKEN and old.split()[0] not in key.read_text("ascii")


def test_unsafe_or_unusable_keys_are_refused(paths, tmp_path):
    state, key = paths
    with pytest.raises(SecretStoreError, match="Zustandsverzeichnis"):
        SecretStore(state, state / "inside.key")
    with pytest.raises(SecretStoreError, match="fehlt"):
        SecretStore(state, tmp_path / "missing.key")
    broken = tmp_path / "broken.key"
    broken.write_text("kein-schluessel\n", encoding="ascii")
    # 8.6.3: private like a real key file, otherwise Linux refuses it as readable before checking its content.
    broken.chmod(0o600)
    with pytest.raises(SecretStoreError, match="ungültig"):
        SecretStore(state, broken)
    with pytest.raises(FileExistsError):
        create_key(key)  # an existing key is never overwritten


def test_on_linux_a_key_readable_by_others_is_refused_and_files_stay_private(paths, monkeypatch):
    state, key = paths
    monkeypatch.setattr("inboxstride_auth.secret_store.POSIX", True)
    modes = []
    monkeypatch.setattr(os, "chmod", lambda path, mode: modes.append(mode))
    mode = os.stat(key).st_mode
    monkeypatch.setattr("inboxstride_auth.secret_store.stat.S_IMODE", lambda _mode: 0o644)
    with pytest.raises(SecretStoreError, match="lesbar"):
        SecretStore(state, key)
    monkeypatch.setattr("inboxstride_auth.secret_store.stat.S_IMODE", lambda _mode: 0o600)
    SecretStore(state, key).put("refresh:a", TOKEN)
    assert modes == [0o600] and mode


@pytest.mark.parametrize("content", ["{", '{"schema_version": 2, "secrets": {}}', '{"schema_version": 1}', "[]"])
def test_a_damaged_secret_file_is_reported_without_content(paths, content):
    state, key = paths
    store = SecretStore(state, key)
    (state / "secrets.json").write_text(content, encoding="utf-8")
    with pytest.raises(SecretStoreError, match="beschädigt"):
        store.names()


def test_a_failed_write_leaves_the_previous_file(paths, monkeypatch):
    state, key = paths
    store = SecretStore(state, key)
    store.put("refresh:a", TOKEN)
    before = (state / "secrets.json").read_text(encoding="utf-8")

    def broken(*args):
        raise OSError("disk full")
    monkeypatch.setattr(os, "replace", broken)
    with pytest.raises(OSError, match="disk full"):
        store.put("refresh:b", TOKEN)
    assert (state / "secrets.json").read_text(encoding="utf-8") == before
    assert [name for name in os.listdir(state) if name.startswith(".")] == []
    assert json.loads(before)["schema_version"] == 1
