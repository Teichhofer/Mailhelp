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


@pytest.mark.parametrize("job", ["tests", "ui-tests"])
def test_failed_tests_become_public_annotations(job):
    """8.7.11: job logs need a login; the failed test ids must be readable from the public annotations,
    and the piped run must keep the exit code of the check (pipefail)."""
    steps = [step for name, _runners, step in _steps(ROOT / ".github" / "workflows" / "ci.yml") if name == job]
    log = '"$RUNNER_TEMP/check.log"'  # outside the checkout, which tests inspect
    run = next(step for step in steps if f"| tee {log}" in str(step.get("run", "")))
    assert run["shell"] == "bash" and "set -o pipefail" in run["run"]
    report = steps[steps.index(run) + 1]
    assert report["if"] == "failure()" and "::error::" in report["run"] and f"' {log} |" in report["run"]
    assert "^(FAILED|ERROR) " in report["run"]
    if job == "tests":  # the file of a missing line or branch, not only the total
        line = "src/mailhelp/x.py      10      0      4      1    96%   12->14"
        pattern = re.search(r"\|(\^\[\^ \]\+\\\.py[^']*)'", report["run"]).group(1)
        assert re.search(pattern, line) and not re.search(pattern, "TOTAL   42510      0  11936      0   100%")


def test_the_browser_suite_renders_with_roboto_before_it_runs():
    """8.7.11: Ubuntu's DejaVu fallback made rows taller and a table link 43 px high only in CI."""
    steps = [step for name, _runners, step in _steps(ROOT / ".github" / "workflows" / "ci.yml") if name == "ui-tests"]
    runs = [str(step.get("run", "")) for step in steps]
    font = next(index for index, run in enumerate(runs) if "fonts-roboto" in run)
    suite = next(index for index, run in enumerate(runs) if "pytest ui_tests" in run)
    assert font < suite and "fc-match system-ui | grep -q Roboto" in runs[font]
    config = (ROOT / ".github" / "fontconfig" / "50-mailhelp-roboto.conf").read_text(encoding="utf-8")
    assert all(f"<family>{name}</family><prefer><family>Roboto</family>" in config for name in ("sans-serif", "system-ui"))


def test_regression_a_hung_browser_suite_ends_long_before_the_runner_limit():
    """8.7.13: a hung browser test held the ui-tests job for six hours; the step now has its own limit and the
    failure annotations still run afterwards."""
    steps = [step for name, _runners, step in _steps(ROOT / ".github" / "workflows" / "ci.yml") if name == "ui-tests"]
    suite = next(step for step in steps if "pytest ui_tests" in str(step.get("run", "")))
    assert 30 <= suite["timeout-minutes"] <= 60
    assert steps[steps.index(suite) + 1]["if"] == "failure()"


def test_dockerfiles_share_a_current_python_312_patch_image():
    bases = {path: re.search(r"^FROM (\S+)$", path.read_text(encoding="utf-8"), re.M).group(1)
             for path in DOCKERFILES}
    assert len(set(bases.values())) == 1, bases
    match = re.fullmatch(r"python:3\.12\.(\d+)-slim", next(iter(bases.values())))
    assert match is not None and int(match.group(1)) >= 16, bases


PAGES_MINIMUM = {"actions/configure-pages": 6, "actions/upload-pages-artifact": 5, "actions/deploy-pages": 5}


def test_regression_pages_actions_use_node24_majors():
    """8.6.2: ``deploy-pages@v4`` (Node.js 20, forced onto Node.js 24) repeatedly failed with
    "No artifacts named github-pages were found"; the publication uses the current majors."""
    used = {}
    for _job, _runners, step in _steps(ROOT / ".github" / "workflows" / "pages.yml"):
        action, _, version = str(step.get("uses", "")).partition("@v")
        if action in PAGES_MINIMUM:
            used[action] = int(version.split(".")[0])
    assert used.keys() == PAGES_MINIMUM.keys()
    assert all(used[action] >= minimum for action, minimum in PAGES_MINIMUM.items()), used
