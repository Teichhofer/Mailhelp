"""8.6: GitHub workflows follow the Python 3.12 channel and never upload a missing artifact.

Regression for the Mutation audit of 23 November 2026: ``ubuntu-latest`` moved to Ubuntu 26.04,
where ``actions/setup-python`` has no build of the pinned ``3.12.10``; the job failed in setup and
``upload-artifact`` with ``if: always()`` added a misleading "No files were found" error.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
DOCKERFILES = (ROOT / "Dockerfile", ROOT / "ops" / "auth" / "Dockerfile")


def _steps(workflow: Path):
    """Every step of every job, with the runners the job uses."""
    document = yaml.safe_load(workflow.read_text(encoding="utf-8"))
    for name, job in document["jobs"].items():
        runs_on = job.get("runs-on", "")
        runners = (job.get("strategy", {}).get("matrix", {}).get("os", [])
                   if "matrix.os" in str(runs_on) else [runs_on])
        for step in job.get("steps", []):
            yield name, runners, step


def test_workflows_exist():
    assert {path.name for path in WORKFLOWS} >= {"ci.yml", "mutation.yml", "release.yml", "weekly.yml"}


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda path: path.name)
def test_regression_setup_python_uses_the_minor_channel_on_ubuntu_latest(workflow):
    for job, runners, step in _steps(workflow):
        if not str(step.get("uses", "")).startswith("actions/setup-python@"):
            continue
        assert "ubuntu-latest" in runners or "windows-latest" in runners, (workflow.name, job)
        version = str(step["with"]["python-version"])
        assert version == "3.12", (workflow.name, job, version)


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda path: path.name)
def test_regression_always_uploaded_artifacts_ignore_missing_files(workflow):
    for job, _runners, step in _steps(workflow):
        if (str(step.get("uses", "")).startswith("actions/upload-artifact@")
                and "always()" in str(step.get("if", ""))):
            assert step["with"].get("if-no-files-found") == "ignore", (workflow.name, job)


def test_every_workflow_python_step_is_checked():
    # Guard against the checks above silently matching nothing.
    found = [step for workflow in WORKFLOWS for _job, _runners, step in _steps(workflow)
             if str(step.get("uses", "")).startswith("actions/setup-python@")]
    assert len(found) == 7


def test_dockerfiles_share_a_current_python_312_patch_image():
    bases = {path: re.search(r"^FROM (\S+)$", path.read_text(encoding="utf-8"), re.M).group(1)
             for path in DOCKERFILES}
    assert len(set(bases.values())) == 1, bases
    match = re.fullmatch(r"python:3\.12\.(\d+)-slim", next(iter(bases.values())))
    assert match is not None and int(match.group(1)) >= 16, bases
