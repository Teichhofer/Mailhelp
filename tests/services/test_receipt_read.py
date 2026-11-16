"""Regression 6.1.5: a receipt replaced while the overview reads it must not end in HTTP 500."""
from pathlib import Path

import pytest

from mailhelp.review import incoming


def flaky(failures):
    original = Path.read_bytes
    calls = []

    def read_bytes(self):
        calls.append(self)
        if len(calls) <= failures:
            raise PermissionError(13, "sharing violation")
        return original(self)
    return read_bytes, calls


def test_regression_a_briefly_blocked_receipt_is_read_after_a_retry(tmp_path, monkeypatch):
    """Regression 6.1.5: GET / answered 500 (PermissionError) when Windows blocked the receipt file
    for a moment while the main thread replaced it (seen in a serial browser run)."""
    path = tmp_path / "receipt.json"
    path.write_bytes(b"{}")
    read_bytes, calls = flaky(2)
    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    monkeypatch.setattr(incoming.time, "sleep", lambda seconds: None)
    assert incoming.read_file(path) == b"{}" and len(calls) == 3


def test_a_persistent_block_is_still_reported_and_a_missing_file_is_none(tmp_path, monkeypatch):
    path = tmp_path / "receipt.json"
    path.write_bytes(b"{}")
    read_bytes, calls = flaky(9)
    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    monkeypatch.setattr(incoming.time, "sleep", lambda seconds: None)
    with pytest.raises(PermissionError):
        incoming.read_file(path)
    assert len(calls) == 4
    monkeypatch.undo()
    assert incoming.read_file(tmp_path / "fehlt.json") is None
    state = {"n": 0}

    def gone_after_block(self):
        state["n"] += 1
        if state["n"] <= 3:
            raise PermissionError(13, "sharing violation")
        raise FileNotFoundError(self)
    monkeypatch.setattr(Path, "read_bytes", gone_after_block)
    monkeypatch.setattr(incoming.time, "sleep", lambda seconds: None)
    assert incoming.read_file(path) is None
