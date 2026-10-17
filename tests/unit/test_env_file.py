"""Line-preserving, atomic .env updates (3.3.11); synthetic values only."""
from __future__ import annotations

import pytest

from mailhelp.config import _dotenv
from mailhelp.env_file import EnvFileConflict, file_hash, set_value, set_values, validate


def test_replaces_or_appends_one_name_and_keeps_every_other_line(tmp_path):
    path = tmp_path / ".env"
    path.write_bytes(b"# Kommentar\r\nIMAP_1_USERNAME=alt\nOTHER=x\n  IMAP_1_USERNAME = doppelt\n"
                     b"IMAP_1_USERNAME_X=y\n")
    set_value(path, "IMAP_1_USERNAME", "neu@example.test", file_hash(path))
    assert path.read_text(encoding="utf-8") == ("# Kommentar\nIMAP_1_USERNAME=neu@example.test\nOTHER=x\n"
                                                "IMAP_1_USERNAME=neu@example.test\nIMAP_1_USERNAME_X=y\n")
    set_value(path, "ISERV_1_PASSWORD", " geheim ", file_hash(path))
    set_value(path, "OPENROUTER_API_KEY", "'quoted'", file_hash(path))
    set_value(path, "TELEGRAM_BOT_TOKEN", 'a"b', file_hash(path))
    values = _dotenv(path)
    assert values["ISERV_1_PASSWORD"] == " geheim " and values["OPENROUTER_API_KEY"] == "'quoted'"
    assert values["TELEGRAM_BOT_TOKEN"] == 'a"b' and values["OTHER"] == "x"


def test_a_missing_file_is_created(tmp_path):
    path = tmp_path / "config" / ".env"
    path.parent.mkdir()
    set_value(path, "ISERV_2_USERNAME", "eltern", file_hash(path))
    assert path.read_text(encoding="utf-8") == "ISERV_2_USERNAME=eltern\n"


def test_a_changed_file_is_never_overwritten(tmp_path):
    path = tmp_path / ".env"
    path.write_text("A=1\n", encoding="utf-8")
    stale = file_hash(path)
    path.write_text("A=2\n", encoding="utf-8")
    with pytest.raises(EnvFileConflict):
        set_value(path, "A", "3", stale)
    assert path.read_text(encoding="utf-8") == "A=2\n"


@pytest.mark.parametrize(("name", "value"), [
    ("lower", "x"), ("1ABC", "x"), ("MAILHELP_WEB_SECRET", "x" * 40), ("A" * 65, "x"),
    ("NAME", ""), ("NAME", "a\nB=1"), ("NAME", "a\rb"), ("NAME", "a\x00b"), ("NAME", "a\x7fb"), ("NAME", "x" * 4097)])
def test_names_and_values_are_validated(name, value):
    with pytest.raises(ValueError):
        validate(name, value)


def test_a_credential_pair_is_validated_before_either_value_is_saved(tmp_path):
    path = tmp_path / ".env"
    path.write_text("# keep\nISERV_1_USERNAME=old\nISERV_1_PASSWORD=old-password\n")
    before = path.read_bytes()
    for values in ({}, {"ISERV_1_USERNAME": "new", "ISERV_1_PASSWORD": "bad\nvalue"}):
        with pytest.raises(ValueError):
            set_values(path, values, file_hash(path))
        assert path.read_bytes() == before
    set_values(path, {"ISERV_1_USERNAME": "new", "ISERV_1_PASSWORD": "new-password"}, file_hash(path))
    assert _dotenv(path) == {"ISERV_1_USERNAME": "new", "ISERV_1_PASSWORD": "new-password"}
