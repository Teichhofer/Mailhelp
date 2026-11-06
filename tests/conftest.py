"""Keep temporary test files in dedicated temp folders and clean up after success.

Working files (``tmp_path``, ``tempfile`` and child processes) go to
``<System-Temp>/mailhelp-tests`` or ``MAILHELP_TEST_TEMP``.  They are kept out
of the project folder on purpose: below ``Documents`` Windows scanners can
briefly lock freshly written files, which made atomic state writes in tests fail
intermittently.  Tool data (pytest cache, coverage data) lives in the project's
``.test-tmp`` folder, configured in ``pyproject.toml``.

``tmp_path`` directories of passed tests are removed by pytest itself
(``tmp_path_retention_policy = "failed"``); those of failed tests stay for
analysis.  After a completely successful session the remaining run-related
files (run directory, coverage data) and folders left empty are deleted too.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

# Plugins that others import come first, so pytest rewrites their assertions before the import.
pytest_plugins = ("tests.fakes.offline_http", "tests.fakes.shared_web_auth", "tests.fakes.shared_web_actions", "tests.fakes.shared_web_server", "tests.fakes.shared_setup", "tests.fakes.shared_profiles")

TEST_TEMP_ROOT = Path(
    os.environ.get("MAILHELP_TEST_TEMP")
    or Path(tempfile.gettempdir()) / "mailhelp-tests"
).resolve()
TOOL_TEMP_ROOT = Path(__file__).resolve().parents[1] / ".test-tmp"
COVERAGE_DATA = TOOL_TEMP_ROOT / ".coverage"
_SESSION_PASSED = pytest.StashKey[bool]()
_PREVIOUS_TEMP = pytest.StashKey[dict]()


# MAILHELP_TEST_TEMP passes the root itself to pytest -n workers; deriving it again from the
# already redirected TMP would nest a second "mailhelp-tests" folder (Planung 4.1, 9.8).
TEMP_VARIABLES = ("TMP", "TEMP", "TMPDIR", "MAILHELP_TEST_TEMP")


def redirect_temporary_files(root: Path) -> dict[str, str | None]:
    """Point pytest, ``tempfile`` and child processes at *root*; returns the previous values."""
    previous = {"tempdir": tempfile.tempdir, **{name: os.environ.get(name) for name in TEMP_VARIABLES}}
    root.mkdir(parents=True, exist_ok=True)
    tempfile.tempdir = str(root)
    for name in TEMP_VARIABLES:
        os.environ[name] = str(root)
    return previous


def restore_temporary_files(previous: dict[str, str | None]) -> None:
    """Undo :func:`redirect_temporary_files`.

    A later pytest run in the same process (``pytest.main``, mutmut) creates its capture
    files before its own ``pytest_configure``; it must not use a folder this run removed.
    """
    tempfile.tempdir = previous["tempdir"]
    for name in TEMP_VARIABLES:
        if previous[name] is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous[name]


def prune_empty(root: Path) -> None:
    """Remove dangling links and empty folders below *root*, then *root*."""
    if not root.is_dir():
        return
    # pytest leaves a dangling ``pytest-current`` link to the removed run.
    for link in [item for item in root.rglob("*") if item.is_symlink()]:
        if not link.exists():
            link.unlink()
    folders = (item for item in root.rglob("*")
               if item.is_dir() and not item.is_symlink())
    # Deepest folders first, so parents emptied in this pass are removed too.
    for folder in sorted(folders, key=lambda item: len(item.parts), reverse=True):
        try:
            if not any(folder.iterdir()):
                folder.rmdir()
        except OSError:
            # Another run or a Windows scanner may own this directory.
            continue
    try:
        if not any(root.iterdir()):
            root.rmdir()
    except OSError:
        pass


def remove_run_files(root: Path, run_directory: Path | None,
                     coverage_data: Path) -> None:
    """Delete this run's temporary files and every folder left empty."""
    if run_directory is not None:
        shutil.rmtree(run_directory, ignore_errors=True)
    for path in coverage_data.parent.glob(coverage_data.name + "*"):
        if path.is_file():
            path.unlink(missing_ok=True)
    prune_empty(root)
    prune_empty(coverage_data.parent)


def pytest_configure(config: pytest.Config) -> None:
    config.stash[_PREVIOUS_TEMP] = redirect_temporary_files(TEST_TEMP_ROOT)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    session.config.stash[_SESSION_PASSED] = exitstatus == 0


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item], config: pytest.Config) -> None:
    # Keep process/container stress sequential even in an otherwise parallel full run.
    if getattr(config.option, "loadgroup", False) or getattr(config.option, "dist", "no") == "loadgroup":
        for item in items:
            if item.get_closest_marker("process") or item.get_closest_marker("e2e"):
                item.add_marker(pytest.mark.xdist_group("mailhelp_process"))
    # Fail fast at the direct invariant, before exercising every incidental application path.
    # This changes only mutation-test order, never selection or ordinary test order.
    if "MUTANT_UNDER_TEST" in os.environ:
        items.sort(key=lambda item: ("test_mutation_invariants.py" not in item.nodeid,
                                     not item.nodeid.startswith("tests/unit/")))


def is_xdist_worker(config: pytest.Config) -> bool:
    """Parallel workers (pytest -n) share the controller's run and coverage files."""
    return hasattr(config, "workerinput")


def pytest_unconfigure(config: pytest.Config) -> None:
    # Runs after the coverage report, so the data file is no longer needed. Under
    # pytest-xdist only the controller cleans up: a finished worker would otherwise
    # delete coverage data and run folders that others still use (Planung 4.1, 9.8).
    if _PREVIOUS_TEMP in config.stash:
        restore_temporary_files(config.stash[_PREVIOUS_TEMP])
    if not config.stash.get(_SESSION_PASSED, False) or is_xdist_worker(config):
        return
    factory = getattr(config, "_tmp_path_factory", None)
    run_directory = getattr(factory, "_basetemp", None)
    coverage_data = Path(os.environ.get("COVERAGE_FILE", str(COVERAGE_DATA)))
    remove_run_files(TEST_TEMP_ROOT, run_directory, coverage_data)
