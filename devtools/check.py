"""Cross-platform quality tasks: python -m devtools.check tdd|fast|full|ui|prompts|mutation."""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
FAST = "not (slow or process or e2e)"
LATENCY_TESTS = ("tests/services/test_v42_load.py", "tests/services/test_v441_load.py")


def commands(task: str, workers: str, tests: list[str] | None = None) -> list[list[str]]:
    tasks = {
        "tdd": [["pytest", *(tests or []), "--no-cov", "-q"]],
        "fast": [["pytest", "-n", workers, "--dist", "worksteal", "-m", FAST, "--no-cov", "-q"]],
        "full": [["hatchling", "build"], ["pytest",
                                           *([] if workers == "auto" else ["-n", workers, "--dist", "loadgroup"]),
                                           "--cov=mailhelp", "--cov=devtools", "--cov-branch",
                                           "--cov-fail-under=100", *("--ignore=" + path for path in LATENCY_TESTS)],
                 ["pytest", *LATENCY_TESTS, "--no-cov", "-q", "-s"]],
        "ui": [["pytest", "ui_tests", "-m", "smoke", "--no-cov", "-q"]],
        "prompts": [["pytest", "tests/evaluation/test_prompt_gate.py", "--no-cov", "-q"]],
        "mutation": [["mutmut", "run", "*"], ["mutmut", "export-cicd-stats"]],
    }
    return [[sys.executable, "-m", *args] for args in tasks[task]]


def mutation_score(report: dict) -> float:
    """Timeouts, untested and skipped mutants never count as killed."""
    total, killed = report["total"], report["killed"]
    if type(total) is not int or type(killed) is not int or not 0 <= killed <= total or total == 0:
        raise ValueError("Ungültiger oder leerer Mutationsbericht")
    return 100 * killed / total


def core_mutation_scores(root: Path) -> dict[str, float]:
    scores = {}
    for name, pattern in (
        ("domain", "mutants/src/mailhelp/domain/*.meta"),
        ("storage", "mutants/src/mailhelp/storage.py.meta"),
        ("confirmed", "mutants/src/mailhelp/external/confirmed.py.meta"),
    ):
        codes = [code for path in root.glob(pattern)
                 for code in json.loads(path.read_text(encoding="utf-8"))["exit_code_by_key"].values()]
        if not codes or any(type(code) is not int or code not in {0, 1} for code in codes):
            raise ValueError(f"Unvollständige Mutationsprüfung: {name}")
        scores[name] = mutation_score({"total": len(codes), "killed": codes.count(1)})
    return scores


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", choices=("tdd", "fast", "full", "ui", "prompts", "mutation"))
    parser.add_argument("tests", nargs="*", help="Explicit files or node IDs for the TDD task")
    parser.add_argument("--workers", default="auto")
    parser.add_argument("--max-seconds", type=float)
    args = parser.parse_args(argv)
    if args.max_seconds is not None and (not math.isfinite(args.max_seconds) or args.max_seconds <= 0):
        parser.error("--max-seconds muss endlich und positiv sein")
    if (args.task == "tdd") != bool(args.tests):
        parser.error("tdd benötigt eine ausdrückliche Testauswahl; andere Aufgaben akzeptieren keine Testpfade")
    if args.task == "mutation" and sys.platform != "linux":
        parser.error("mutmut benötigt Linux; diesen Befehl in WSL ausführen")
    started = time.perf_counter()
    environment = None
    if args.task == "full":
        environment = {**os.environ, "COVERAGE_FILE": str(ROOT / ".test-tmp" / f"coverage-{uuid4()}" / ".coverage")}
    for command in commands(args.task, args.workers, args.tests):
        result = subprocess.run(command, cwd=ROOT, check=False, env=environment)
        if result.returncode:
            return result.returncode
    elapsed = time.perf_counter() - started
    if args.task in {"fast", "tdd"}:
        limit = 15.0 if args.task == "tdd" and args.max_seconds is None else args.max_seconds
        report = {"seconds": elapsed, "limit_seconds": limit, "workers": args.workers if args.task == "fast" else "1",
                  "platform": sys.platform, "tests": args.tests, "passed": limit is None or elapsed < limit}
        path = ROOT / ".test-tmp" / f"{args.task}-report.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"{args.task}: {elapsed:.2f} s; Grenze: {limit} s")
        return 0 if report["passed"] else 1
    if args.task == "mutation":
        report = json.loads((ROOT / "mutants/mutmut-cicd-stats.json").read_text(encoding="utf-8"))
        score = mutation_score(report)
        print(f"Getötete Mutanten: {score:.2f} %; erforderlich: 90 %")
        unresolved = any(report.get(name, 0) for name in (
            "no_tests", "skipped", "suspicious", "timeout", "check_was_interrupted_by_user", "segfault"))
        complete = report["killed"] + report.get("survived", 0) == report["total"]
        if score < 90 or not complete or unresolved:
            return 1
        scores = core_mutation_scores(ROOT)
        print(json.dumps(scores, sort_keys=True))
        return 0 if all(value >= 90 for value in scores.values()) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
