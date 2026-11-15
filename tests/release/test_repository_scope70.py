"""7.0.2 (R1): the repository contains Mailhelp only; outside work and local leftovers stay untracked."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
UNTRACKED_DIRECTORIES = ("output/", "tmp/", ".tools/")
UNTRACKED_FILES = {"irrelevant-senders.json", "irrelevant-senders.json.v1", "irrelevant-senders.corrupt",
                   ".coverage-spec-audit", "coverage-audit.json", "spec-audit-coverage.json"}


def tracked() -> list[str]:
    try:
        result = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("no git checkout (for example an unpacked release)")
    return result.stdout.splitlines()


def test_no_outside_work_or_local_state_is_tracked():
    files = tracked()
    assert not [name for name in files if name.startswith(UNTRACKED_DIRECTORIES)]
    assert not UNTRACKED_FILES & set(files)
    # The synthetic example stays: it documents the format of the sender list.
    assert "irrelevant-senders.example.json" in files


def test_the_ignore_file_keeps_them_out():
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    for entry in (*UNTRACKED_DIRECTORIES, *UNTRACKED_FILES):
        assert "/" + entry in ignored
