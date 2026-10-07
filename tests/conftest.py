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

TEST_TEMP_ROOT = Path(
    os.environ.get("MAILHELP_TEST_TEMP")
    or Path(tempfile.gettempdir()) / "mailhelp-tests"
).resolve()
TOOL_TEMP_ROOT = Path(__file__).resolve().parents[1] / ".test-tmp"
COVERAGE_DATA = TOOL_TEMP_ROOT / ".coverage"
_SESSION_PASSED = pytest.StashKey[bool]()


def redirect_temporary_files(root: Path) -> None:
    """Point pytest, ``tempfile`` and child processes at *root*."""
    root.mkdir(parents=True, exist_ok=True)
    tempfile.tempdir = str(root)
    for name in ("TMP", "TEMP", "TMPDIR"):
        os.environ[name] = str(root)


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
        if not any(folder.iterdir()):
            folder.rmdir()
    if not any(root.iterdir()):
        root.rmdir()


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
    redirect_temporary_files(TEST_TEMP_ROOT)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    session.config.stash[_SESSION_PASSED] = exitstatus == 0


def pytest_unconfigure(config: pytest.Config) -> None:
    # Runs after the coverage report, so the data file is no longer needed.
    if not config.stash.get(_SESSION_PASSED, False):
        return
    factory = getattr(config, "_tmp_path_factory", None)
    run_directory = getattr(factory, "_basetemp", None)
    remove_run_files(TEST_TEMP_ROOT, run_directory, COVERAGE_DATA)
