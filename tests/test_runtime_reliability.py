"""Regression coverage for configuration-relative paths and provider boundaries."""
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
import sys
import zoneinfo

import httpx
import pytest

from mailhelp.application import _state_directory
from mailhelp.cli import main
from mailhelp.integrations import HttpWriter, execute_confirmed
from mailhelp.paths import runtime_path
from test_core import proposal


@pytest.mark.parametrize("absolute", [False, True])
@pytest.mark.parametrize("override", [False, True])
def test_clear_uses_same_paths_as_runtime_from_another_cwd(tmp_path, monkeypatch, absolute, override):
    config = tmp_path / "config"
    working = tmp_path / "working"
    config.mkdir()
    working.mkdir()
    monkeypatch.chdir(working)
    data = config / "data" if absolute else Path("data")
    logs = config / "logs" if absolute else Path("logs")
    settings = SimpleNamespace(data_directory=data, test_mode=False,
                               logging=SimpleNamespace(directory=logs))
    state = _state_directory(settings, config)
    state.mkdir(parents=True)
    (state / "saved.json").write_text("{}", encoding="utf-8")
    log_path = runtime_path(Path("override") if override else logs, config)
    log_path.mkdir()
    (log_path / "application.jsonl").write_text("{}", encoding="utf-8")
    # These names in cwd must never be selected by the destructive command.
    for name in ("data/production", "logs", "override"):
        directory = working / name
        directory.mkdir(parents=True)
        (directory / "keep.txt").write_text("keep", encoding="utf-8")
    monkeypatch.setattr("mailhelp.cli.load_all", lambda _: (settings, None, [], [], None, "f"))
    args = ["mailhelp", "--config-directory", str(config), "--clear", "--yes"]
    if override:
        args += ["--log-directory", "override"]
    monkeypatch.setattr(sys, "argv", args)
    assert main() == 0
    assert not state.exists()
    assert not log_path.exists()
    assert len(list(working.rglob("keep.txt"))) == 3


@pytest.mark.parametrize("cursors", [[""], ["same", "same"], ["a", "b", "a"]])
def test_bad_todoist_pagination_never_enters_write_state(cursors):
    requests = []
    persisted = []
    def handler(request):
        assert request.method == "GET"
        requests.append(request)
        return httpx.Response(200, json={"results": [], "next_cursor": cursors[len(requests)-1]})
    writer = HttpWriter("todoist", "synthetic", "project", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ValueError, match="next_cursor"):
            execute_confirmed(proposal(status="confirmed"), writer, persisted.append)
        assert len(requests) == len(cursors)
        assert persisted == []
    finally:
        writer.close()


def test_todoist_restart_after_bad_pagination_can_reconcile():
    responses = iter([{"results": [], "next_cursor": ""},
                      {"results": [{"id": "existing", "description": "[key]"}], "next_cursor": None}])
    for expected_failure in (True, False):
        writer = HttpWriter("todoist", "synthetic", "project", transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=next(responses))))
        try:
            if expected_failure:
                with pytest.raises(ValueError, match="next_cursor"):
                    writer.reconcile("key")
            else:
                assert writer.reconcile("key")["id"] == "existing"
        finally:
            writer.close()


def test_bundled_timezone_data_works_without_system_database():
    original = zoneinfo.TZPATH
    try:
        zoneinfo.reset_tzpath(())
        berlin = zoneinfo.ZoneInfo.no_cache("Europe/Berlin")
        assert datetime(2026, 1, 1, tzinfo=berlin).utcoffset() == timedelta(hours=1)
        assert datetime(2026, 7, 1, tzinfo=berlin).utcoffset() == timedelta(hours=2)
    finally:
        zoneinfo.reset_tzpath(original)
