"""Temporary test files stay in .test-tmp and are removed after success."""
import os
import tempfile

import pytest

from conftest import TEST_TEMP_ROOT, redirect_temporary_files, remove_run_files


def test_temporary_files_are_created_in_the_project_temp_folder(tmp_path):
    assert tmp_path.is_relative_to(TEST_TEMP_ROOT)
    assert tempfile.gettempdir() == str(TEST_TEMP_ROOT)
    assert os.environ["TEMP"] == os.environ["TMP"] == os.environ["TMPDIR"] == str(TEST_TEMP_ROOT)
    # Parallel workers read the root from here instead of nesting it below TMP.
    assert os.environ["MAILHELP_TEST_TEMP"] == str(TEST_TEMP_ROOT)
    with tempfile.NamedTemporaryFile() as handle:
        assert os.path.dirname(handle.name) == str(TEST_TEMP_ROOT)


def test_redirect_creates_missing_root(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", tempfile.tempdir)
    for name in ("TMP", "TEMP", "TMPDIR", "MAILHELP_TEST_TEMP"):
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
            "conftest_copy", Path(__file__).parents[1] / "conftest.py")
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


def test_parallel_workers_leave_shared_run_and_coverage_files_to_the_controller(tmp_path, monkeypatch):
    """Planung 4.1, Schritt 9.8: a finished pytest -n worker must not delete coverage data."""
    import types

    import conftest
    coverage = tmp_path / ".coverage.host.123"
    coverage.write_text("data", encoding="utf-8")
    removed = []
    monkeypatch.setattr(conftest, "remove_run_files", lambda *args: removed.append(args))
    monkeypatch.setattr(conftest, "COVERAGE_DATA", tmp_path / ".coverage")

    def config(**extra):
        value = types.SimpleNamespace(stash={conftest._SESSION_PASSED: True}, **extra)
        return value

    conftest.pytest_unconfigure(config(workerinput={"workerid": "gw0"}))
    assert removed == [] and coverage.exists()
    conftest.pytest_unconfigure(config())
    assert len(removed) == 1
    assert conftest.is_xdist_worker(config(workerinput={})) and not conftest.is_xdist_worker(config())


def test_regression_a_finished_run_restores_temp_settings_for_the_next_in_process_run(tmp_path, monkeypatch):
    """Regression 4.1.9: mutmut's second pytest run captured output into a removed folder."""
    import types

    import conftest
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "before"))
    monkeypatch.setenv("TMP", "previous-tmp")
    monkeypatch.delenv("TMPDIR", raising=False)
    monkeypatch.setenv("TEMP", "previous-temp")
    monkeypatch.delenv("MAILHELP_TEST_TEMP", raising=False)
    config = types.SimpleNamespace(stash={})
    monkeypatch.setattr(conftest, "TEST_TEMP_ROOT", tmp_path / "run")
    conftest.pytest_configure(config)
    assert tempfile.tempdir == str(tmp_path / "run") and os.environ["TMPDIR"] == str(tmp_path / "run")
    conftest.pytest_unconfigure(config)  # a failed or unfinished session: files stay, settings return
    assert tempfile.tempdir == str(tmp_path / "before")
    assert os.environ["TMP"] == "previous-tmp" and os.environ["TEMP"] == "previous-temp"
    assert "TMPDIR" not in os.environ and "MAILHELP_TEST_TEMP" not in os.environ


def test_regression_concurrent_full_runs_do_not_delete_each_others_coverage(tmp_path, monkeypatch):
    import types

    import conftest
    one = tmp_path / "tools" / "one" / ".coverage"
    two = tmp_path / "tools" / "two" / ".coverage"
    for path in (one, two):
        path.parent.mkdir(parents=True)
        path.write_text("synthetic coverage")
    monkeypatch.setenv("COVERAGE_FILE", str(one))
    monkeypatch.setattr(conftest, "COVERAGE_DATA", tmp_path / "tools" / ".coverage")
    monkeypatch.setattr(conftest, "TEST_TEMP_ROOT", tmp_path / "states")
    config = types.SimpleNamespace(stash={conftest._SESSION_PASSED: True})
    conftest.pytest_unconfigure(config)
    assert not one.exists()
    assert two.read_text() == "synthetic coverage"


def test_mutations_run_direct_invariants_first_without_deselecting_any_test(monkeypatch):
    from types import SimpleNamespace

    import conftest
    names = ["tests/services/test_safety.py::test_a", "tests/unit/test_core.py::test_a",
             "tests/unit/test_mutation_invariants.py::test_a", "tests/unit/test_core.py::test_b"]
    items = [SimpleNamespace(nodeid=name) for name in names]
    config = SimpleNamespace(option=SimpleNamespace(dist="no"))
    monkeypatch.delenv("MUTANT_UNDER_TEST", raising=False)
    conftest.pytest_collection_modifyitems(items, config)
    assert [item.nodeid for item in items] == names
    monkeypatch.setenv("MUTANT_UNDER_TEST", "stats")
    conftest.pytest_collection_modifyitems(items, config)
    assert [item.nodeid for item in items] == [names[2], names[1], names[3], names[0]]
    assert {item.nodeid for item in items} == set(names)


@pytest.mark.parametrize("worker", [False, True])
def test_parallel_full_runs_keep_process_and_e2e_tests_in_one_sequential_group(monkeypatch, worker):
    from types import SimpleNamespace

    import conftest
    class Item:
        def __init__(self, marker): self.marker, self.assigned = marker, []
        def get_closest_marker(self, name): return self.marker == name
        def add_marker(self, marker): self.assigned.append(marker)
    items = [Item("process"), Item("e2e"), Item("unit")]
    monkeypatch.delenv("MUTANT_UNDER_TEST", raising=False)
    config = SimpleNamespace(option=SimpleNamespace(loadgroup=worker, dist="no" if worker else "loadgroup"))
    conftest.pytest_collection_modifyitems(items, config)
    assert all(len(item.assigned) == 1 and item.assigned[0].name == "xdist_group"
               and item.assigned[0].args == ("mailhelp_process",) for item in items[:2])
    assert items[2].assigned == []
