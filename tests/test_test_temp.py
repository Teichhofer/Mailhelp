"""Temporary test files stay in .test-tmp and are removed after success."""
import os
import tempfile

import pytest

from conftest import TEST_TEMP_ROOT, redirect_temporary_files, remove_run_files


def test_temporary_files_are_created_in_the_project_temp_folder(tmp_path):
    assert tmp_path.is_relative_to(TEST_TEMP_ROOT)
    assert tempfile.gettempdir() == str(TEST_TEMP_ROOT)
    assert os.environ["TEMP"] == os.environ["TMP"] == os.environ["TMPDIR"] == str(TEST_TEMP_ROOT)
    with tempfile.NamedTemporaryFile() as handle:
        assert os.path.dirname(handle.name) == str(TEST_TEMP_ROOT)


def test_redirect_creates_missing_root(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", tempfile.tempdir)
    for name in ("TMP", "TEMP", "TMPDIR"):
        monkeypatch.setenv(name, os.environ[name])
    root = tmp_path / "neu" / "temp"
    redirect_temporary_files(root)
    assert root.is_dir() and tempfile.gettempdir() == str(root)
    assert os.environ["TMPDIR"] == str(root)


def test_success_removes_run_files_but_keeps_earlier_failure_artifacts(tmp_path):
    root = tmp_path / "root"
    run = root / "pytest-of-user" / "pytest-7"
    (run / "test_a0").mkdir(parents=True)
    (run / "test_a0" / "state.json").write_text("{}")
    failed = root / "pytest-of-user" / "pytest-6" / "test_b0"
    failed.mkdir(parents=True)
    (failed / "evidence.json").write_text("{}")
    (root / "empty" / "nested").mkdir(parents=True)
    cache = root / "pytest-cache"
    cache.mkdir()
    (cache / "README.md").write_text("cache")
    coverage = root / ".coverage"
    coverage.write_text("data")
    (root / ".coverage.host.1").write_text("parallel")
    (root / ".coverage-dir").mkdir()

    remove_run_files(root, run, coverage)

    assert not run.exists() and not (root / "empty").exists()
    assert not coverage.exists() and not (root / ".coverage.host.1").exists()
    assert not (root / ".coverage-dir").exists()  # empty folder, not data
    assert (failed / "evidence.json").exists() and (cache / "README.md").exists()


def test_success_removes_the_root_once_nothing_is_left(tmp_path):
    root = tmp_path / "root"
    run = root / "pytest-of-user" / "pytest-1"
    run.mkdir(parents=True)
    (run / "file").write_text("x")
    (root / ".coverage").write_text("data")
    remove_run_files(root, run, root / ".coverage")
    assert not root.exists()
    # Repeating the cleanup, also without run directory, is harmless.
    remove_run_files(root, None, root / ".coverage")
    assert not root.exists()


def test_dangling_run_link_is_removed_and_live_links_are_kept(tmp_path):
    root = tmp_path / "root"
    run = root / "pytest-of-user" / "pytest-2"
    run.mkdir(parents=True)
    target = tmp_path / "outside"
    target.mkdir()
    try:
        (root / "pytest-of-user" / "pytest-current").symlink_to(
            run, target_is_directory=True)
        (root / "live").symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("Symbolische Links sind in dieser Umgebung nicht erlaubt")
    remove_run_files(root, run, root / ".coverage")
    assert not (root / "pytest-of-user").exists()
    assert (root / "live").is_symlink() and target.is_dir()


def test_temp_root_defaults_to_system_temp_and_can_be_overridden(tmp_path, monkeypatch):
    import importlib.util
    from pathlib import Path

    def load():
        spec = importlib.util.spec_from_file_location(
            "conftest_copy", Path(__file__).with_name("conftest.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "system"))
    monkeypatch.delenv("MAILHELP_TEST_TEMP", raising=False)
    assert load().TEST_TEMP_ROOT == (tmp_path / "system" / "mailhelp-tests").resolve()
    monkeypatch.setenv("MAILHELP_TEST_TEMP", str(tmp_path / "eigen"))
    module = load()
    assert module.TEST_TEMP_ROOT == (tmp_path / "eigen").resolve()
    assert module.COVERAGE_DATA.parent.name == ".test-tmp"


def test_regression_locked_cache_does_not_fail_successful_cleanup(tmp_path, monkeypatch):
    from pathlib import Path
    root = tmp_path / "root"
    run = root / "run"
    run.mkdir(parents=True)
    cache = root / "cache"
    cache.mkdir()
    coverage = root / ".coverage"
    coverage.write_text("synthetic")
    original = Path.iterdir
    def locked(path):
        if path == cache:
            raise PermissionError("synthetic locked cache")
        return original(path)
    monkeypatch.setattr(Path, "iterdir", locked)
    remove_run_files(root, run, coverage)
    assert not run.exists() and not coverage.exists()
    assert cache.exists()
