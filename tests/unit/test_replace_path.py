"""8.7.11: fresh files and directories are put in place with a bounded retry against brief Windows locks.

Regressions from the parallel full check on Windows ("[WinError 5] Zugriff verweigert"): ``install`` of a
demo visitor area (the demo start answered 503 and ``test_the_shipped_demo_asks_nothing`` saw an empty
page), the demo export, and ``JsonStore.save`` of ``briefing_state`` in ``test_briefing_time``.
"""
from __future__ import annotations

import os

import pytest

from mailhelp.persistence import storage
from mailhelp.persistence.storage import replace_path
from mailhelp.runtime import demo_dataset
from mailhelp.runtime.demo_dataset import install, packaged


def _locked(times, blocked):
    original = os.replace

    def replace(source, target):
        if str(source).endswith(".neu") and len(blocked) < times:
            blocked.append(str(source))
            raise PermissionError(5, "Zugriff verweigert")
        return original(source, target)
    return replace


def test_regression_install_survives_a_briefly_locked_directory(tmp_path, monkeypatch):
    blocked = []
    monkeypatch.setattr(storage.os, "replace", _locked(3, blocked))
    monkeypatch.setattr(storage.time, "sleep", lambda _seconds: None)
    target = tmp_path / "visitors" / "area"
    manifest = install(packaged(), target)
    assert len(blocked) == 3 and sorted(manifest.files) == sorted(
        path.relative_to(target).as_posix() for path in target.rglob("*.json"))
    assert [path.name for path in target.parent.iterdir()] == ["area"]  # no staging left behind


def test_a_persistent_lock_is_reported_and_install_leaves_nothing(tmp_path, monkeypatch):
    blocked = []
    monkeypatch.setattr(storage.os, "replace", _locked(99, blocked))
    monkeypatch.setattr(storage.time, "sleep", lambda _seconds: None)
    target = tmp_path / "visitors" / "area"
    with pytest.raises(PermissionError):
        install(packaged(), target)
    assert len(blocked) == 8 and list(target.parent.iterdir()) == []


def test_the_pauses_are_bounded_and_grow(tmp_path, monkeypatch):
    pauses, calls = [], []

    def refuse(src, dst):
        calls.append((src, dst))
        raise PermissionError(5, "Zugriff verweigert")
    monkeypatch.setattr(storage.os, "replace", refuse)
    with pytest.raises(PermissionError):
        replace_path(tmp_path / "source", tmp_path / "target", pause=pauses.append)
    assert len(calls) == 8 and pauses == [0.01 * 2 ** n for n in range(7)] and sum(pauses) < 1.3


def test_other_errors_are_not_retried(tmp_path):
    pauses = []
    with pytest.raises(FileNotFoundError):
        replace_path(tmp_path / "missing", tmp_path / "target", pause=pauses.append)
    assert pauses == []


def test_a_free_directory_is_published_at_once(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.json").write_text("{}", encoding="utf-8")
    pauses = []
    replace_path(source, tmp_path / "target", pause=pauses.append)
    assert pauses == [] and (tmp_path / "target" / "a.json").is_file() and not source.exists()
    assert demo_dataset.replace_path is replace_path  # one shared helper


def test_regression_store_save_and_atomic_replace_survive_a_briefly_locked_target(tmp_path, monkeypatch):
    original, blocked = os.replace, []

    def locked_once(source, target):
        name = os.path.basename(str(target))
        if name in ("briefing_state.json", "config.yaml") and name not in blocked:
            blocked.append(name)
            raise PermissionError(5, "Zugriff verweigert")
        return original(source, target)
    monkeypatch.setattr(storage.os, "replace", locked_once)
    monkeypatch.setattr(storage.time, "sleep", lambda _seconds: None)
    with storage.JsonStore(tmp_path / "data") as store:
        store.save("briefing_state", {"sent": ["morning"]})
        assert store.load("briefing_state") == {"sent": ["morning"]}
    storage.atomic_replace(tmp_path / "config.yaml", "a: 1\n")
    assert blocked == ["briefing_state.json", "config.yaml"]
    assert (tmp_path / "config.yaml").read_text(encoding="utf-8") == "a: 1\n"
    assert sorted(path.name for path in (tmp_path / "data").iterdir() if path.suffix == ".tmp") == []


def test_regression_an_evaluation_report_survives_a_briefly_locked_target(tmp_path, monkeypatch):
    """``test_decision_test`` failed in the full check: ``write_report`` hit "[WinError 5]" on ``full.json``."""
    from mailhelp.llm.evaluation import write_report
    original, blocked = os.replace, []

    def locked_once(source, target):
        if not blocked:
            blocked.append(os.path.basename(str(target)))
            raise PermissionError(5, "Zugriff verweigert")
        return original(source, target)
    monkeypatch.setattr(storage.os, "replace", locked_once)
    monkeypatch.setattr(storage.time, "sleep", lambda _seconds: None)
    write_report(tmp_path / "full.json", {"cases": 1})
    assert blocked == ["full.json"] and (tmp_path / "full.json").read_text(encoding="utf-8") == '{\n  "cases": 1\n}\n'
    assert not (tmp_path / "full.json.tmp").exists()
