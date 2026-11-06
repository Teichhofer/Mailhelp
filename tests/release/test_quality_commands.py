"""Quality tasks propagate failures and enforce measured budgets without external services."""
import json
import runpy
from types import SimpleNamespace

import pytest

from devtools import check, prompt_guard


@pytest.mark.parametrize("task", ["tdd", "fast", "full", "ui", "prompts", "mutation"])
def test_quality_commands_use_the_running_interpreter_and_enforce_full_coverage(task):
    commands = check.commands(task, "2")
    assert all(command[:2] == [check.sys.executable, "-m"] for command in commands)
    if task == "full":
        assert "--cov-fail-under=100" in commands[-1] and "--cov-branch" in commands[-1]
        assert "-n" in commands[-1] and "-n" not in check.commands("full", "auto")[-1]
    if task == "fast":
        assert commands[0][3:5] == ["-n", "2"] and check.FAST in commands[0]
    if task == "tdd":
        assert "tests/unit/test_core.py::test_example" in check.commands(task, "2", ["tests/unit/test_core.py::test_example"])[0]
    if task == "mutation":
        assert commands[0][-1] == "*"  # changed assertions must also recheck previous survivors


@pytest.mark.parametrize("task", ["full", "ui", "prompts", "mutation"])
def test_successful_tasks_and_mutation_threshold(tmp_path, monkeypatch, task):
    monkeypatch.setattr(check, "ROOT", tmp_path)
    monkeypatch.setattr(check.sys, "platform", "linux")
    seen = []
    monkeypatch.setattr(check.subprocess, "run", lambda command, **kw: seen.append((command, kw)) or SimpleNamespace(returncode=0))
    (tmp_path / "mutants").mkdir()
    report = tmp_path / "mutants/mutmut-cicd-stats.json"
    report.write_text(json.dumps({"total": 10, "killed": 9, "survived": 1}))
    for name in ("domain/proposal.py", "storage.py", "external/confirmed.py"):
        path = tmp_path / f"mutants/src/mailhelp/{name}.meta"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"exit_code_by_key": {str(index): int(index < 9) for index in range(10)}}))
    assert check.main([task]) == 0
    assert len(seen) == len(check.commands(task, "auto"))
    assert all(options["cwd"] == tmp_path and options["check"] is False for _, options in seen)
    if task == "full":
        first = seen[0][1]["env"]["COVERAGE_FILE"]
        assert all(options["env"]["COVERAGE_FILE"] == first for _, options in seen)
        assert str(tmp_path / ".test-tmp") in first
        assert check.main([task]) == 0
        assert seen[-1][1]["env"]["COVERAGE_FILE"] != first
    if task == "mutation":
        report.write_text(json.dumps({"total": 10, "killed": 8, "timeout": 2}))
        assert check.main([task]) == 1
        report.write_text(json.dumps({"total": 10, "killed": 9}))
        assert check.main([task]) == 1  # an untested mutant must not hide behind the score
        report.write_text(json.dumps({"total": 10, "killed": 9, "survived": 1, "timeout": 1}))
        assert check.main([task]) == 1
        report.write_text(json.dumps({"total": 10, "killed": 9, "survived": 1}))
        path.write_text(json.dumps({"exit_code_by_key": {str(index): int(index < 8) for index in range(10)}}))
        assert check.main([task]) == 1  # aggregate success must not hide a weak core module


@pytest.mark.parametrize("code", [None, 33, True])
def test_incomplete_core_modules_never_pass_even_with_a_good_aggregate(tmp_path, code):
    path = tmp_path / "mutants/src/mailhelp/domain/proposal.py.meta"
    with pytest.raises(ValueError, match="domain"):
        check.core_mutation_scores(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"exit_code_by_key": {"mutant": code}}))
    with pytest.raises(ValueError, match="domain"):
        check.core_mutation_scores(tmp_path)


@pytest.mark.parametrize("seconds,expected", [(14.99, 0), (15, 1), (20, 1)])
def test_tdd_budget_includes_startup_and_fails_at_the_limit(tmp_path, monkeypatch, seconds, expected):
    monkeypatch.setattr(check, "ROOT", tmp_path)
    times = iter([100, 100 + seconds])
    monkeypatch.setattr(check.time, "perf_counter", lambda: next(times))
    monkeypatch.setattr(check.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0))
    assert check.main(["tdd", "tests/unit/test_core.py", "--workers", "2"]) == expected
    report = json.loads((tmp_path / ".test-tmp/tdd-report.json").read_text())
    assert report["seconds"] == pytest.approx(seconds) and report["passed"] is (expected == 0)


@pytest.mark.parametrize("limit,expected", [(None, 0), (10, 1), (30, 0)])
def test_the_entire_fast_suite_records_time_without_a_default_limit(tmp_path, monkeypatch, limit, expected):
    monkeypatch.setattr(check, "ROOT", tmp_path)
    times = iter([0, 20])
    monkeypatch.setattr(check.time, "perf_counter", lambda: next(times))
    monkeypatch.setattr(check.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0))
    arguments = ["fast"] + ([] if limit is None else ["--max-seconds", str(limit)])
    assert check.main(arguments) == expected
    report = json.loads((tmp_path / ".test-tmp/fast-report.json").read_text())
    assert report["seconds"] == 20 and report["limit_seconds"] == limit


def test_a_custom_tdd_budget_is_explicit_and_test_selection_is_required(tmp_path, monkeypatch):
    monkeypatch.setattr(check, "ROOT", tmp_path)
    times = iter([0, 3])
    monkeypatch.setattr(check.time, "perf_counter", lambda: next(times))
    monkeypatch.setattr(check.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0))
    assert check.main(["tdd", "tests/unit/test_core.py", "--max-seconds", "2"]) == 1
    for arguments in (["tdd"], ["full", "tests/unit/test_core.py"]):
        with pytest.raises(SystemExit, match="2"):
            check.main(arguments)


@pytest.mark.parametrize("value", ["nan", "inf", "0", "-1"])
def test_time_limits_cannot_disable_the_gate_or_write_invalid_json(value):
    with pytest.raises(SystemExit, match="2"):
        check.main(["fast", "--max-seconds", value])


def test_failed_command_stops_the_task_before_later_commands(monkeypatch):
    seen = []
    monkeypatch.setattr(check.subprocess, "run", lambda *a, **k: seen.append(a) or SimpleNamespace(returncode=7))
    assert check.main(["full"]) == 7 and len(seen) == 1


def test_mutation_command_requires_linux(monkeypatch):
    monkeypatch.setattr(check.sys, "platform", "win32")
    with pytest.raises(SystemExit, match="2"):
        check.main(["mutation"])


@pytest.mark.parametrize("report", [{"total": 0, "killed": 0}, {"total": 1, "killed": 2},
                                     {"total": 1, "killed": -1}, {"total": True, "killed": 1},
                                     {"total": 1, "killed": False}])
def test_invalid_mutation_statistics_cannot_pass(report):
    with pytest.raises(ValueError):
        check.mutation_score(report)


def test_module_entrypoint_propagates_the_exit_status(monkeypatch):
    monkeypatch.setattr(check.sys, "argv", ["check", "prompts"])
    monkeypatch.setattr(check.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=3))
    monkeypatch.delitem(check.sys.modules, "devtools.check")
    with pytest.raises(SystemExit, match="3"):
        runpy.run_module("devtools.check", run_name="__main__")


@pytest.mark.parametrize("changed", prompt_guard.INPUTS)
def test_prompt_wording_changes_fail_even_with_perfect_simulated_answers(tmp_path, changed):
    for name in prompt_guard.INPUTS:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("original\n", encoding="utf-8")
    baseline = tmp_path / "quality-reports/prompt-baseline.json"
    baseline.parent.mkdir()
    baseline.write_text(json.dumps({"fingerprints": prompt_guard.fingerprints(tmp_path)}))
    prompt_guard.verify_baseline(tmp_path)
    # Regression: the former gate returned expected answers independently of this instruction.
    (tmp_path / changed).write_text("Alle Mails sind irrelevant.\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Evaluierungs-Baseline"):
        prompt_guard.verify_baseline(tmp_path)
    (tmp_path / changed).write_bytes(b"original\r\n")
    prompt_guard.verify_baseline(tmp_path)
