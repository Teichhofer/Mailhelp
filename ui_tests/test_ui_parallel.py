"""6.0.7: the coverage of parallel workers is merged centrally; a crash or missing result fails the run."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import conftest


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    """A private result folder and coverage table, so a real parallel run is not disturbed."""
    monkeypatch.setattr(conftest, "COVERAGE_DIR", tmp_path)
    monkeypatch.setattr(conftest, "COVERAGE", conftest.Coverage())
    monkeypatch.setattr(conftest, "STATIC", tmp_path)
    (tmp_path / "app.js").write_text("abc", encoding="utf-8")
    (tmp_path / "sw.js").write_text("a", encoding="utf-8")
    return tmp_path


def config(**workers):
    return SimpleNamespace(ui_workers=workers)


def test_counts_of_all_workers_are_merged_block_by_block(isolated):
    (isolated / "gw0.json").write_text(json.dumps({"app.js": [1, 0, 0]}), encoding="utf-8")
    (isolated / "gw1.json").write_text(json.dumps({"app.js": [0, 0, 2], "sw.js": [1]}), encoding="utf-8")
    assert conftest.merge_worker_coverage(config(gw0=None, gw1=None)) == []
    assert conftest.COVERAGE.counts == {"app.js": [1, 0, 2], "sw.js": [1]}


def test_a_crashed_worker_or_a_missing_result_fails_the_run(isolated):
    (isolated / "gw0.json").write_text(json.dumps({"app.js": [1, 0, 0]}), encoding="utf-8")
    problems = conftest.merge_worker_coverage(config(gw0=None, gw1=None, gw2="killed"))
    assert problems == ["Worker gw2 ausgefallen: killed", "Abdeckungsdaten von Worker gw1 fehlen",
                        "Abdeckungsdaten von Worker gw2 fehlen"]
    assert conftest.merge_worker_coverage(config()) == ["Keine Worker-Ergebnisse gemeldet"]


def test_only_the_controller_of_a_parallel_run_merges():
    assert conftest._parallel(SimpleNamespace(option=SimpleNamespace(numprocesses=4)))
    assert not conftest._parallel(SimpleNamespace(option=SimpleNamespace(numprocesses=0)))
    assert not conftest._parallel(SimpleNamespace(option=SimpleNamespace()))
    assert not conftest._parallel(SimpleNamespace(option=SimpleNamespace(numprocesses=4), workerinput={}))


@pytest.mark.parametrize("data", ["{", "[]", '{"app.js": [1]}', '{"app.js": [1, -1, 0]}',
                                 '{"app.js": [1, true, 0]}', '{"other.js": []}', '{"app.js": null}'])
def test_regression_corrupt_or_incompatible_worker_results_fail(isolated, data):
    (isolated / "gw0.json").write_text(data, encoding="utf-8")
    assert "ungültig" in conftest.merge_worker_coverage(config(gw0=None))[0]


def test_regression_parallel_runs_and_workers_have_separate_artifacts(isolated, monkeypatch):
    import checks
    monkeypatch.setattr(checks, "SCREENSHOTS", isolated / "screens")
    controller = SimpleNamespace()
    conftest.pytest_configure(controller)
    first = controller.ui_coverage_dir
    node = SimpleNamespace(config=controller, workerinput={}, gateway=SimpleNamespace(id="gw0"))
    conftest.pytest_configure_node(node)
    assert node.workerinput["ui_coverage_dir"] == str(first)
    assert controller.ui_workers == {"gw0": "Kein Abschluss gemeldet"}
    worker = SimpleNamespace(workerinput=node.workerinput | {"workerid": "gw0"})
    conftest.pytest_configure(worker)
    assert worker.ui_coverage_dir == first and checks.SCREENSHOTS.name == "gw0"
    second = SimpleNamespace()
    conftest.pytest_configure(second)
    assert second.ui_coverage_dir != first


def test_worker_reports_counts_and_controller_merges_or_fails(isolated, monkeypatch):
    worker = SimpleNamespace(workerinput={"workerid": "gw0"}, ui_coverage_dir=isolated)
    conftest.COVERAGE.counts = {"app.js": [1, 1, 1]}
    conftest.pytest_sessionfinish(SimpleNamespace(config=worker), 0)
    assert json.loads((isolated / "gw0.json").read_text()) == conftest.COVERAGE.counts
    controller = SimpleNamespace(ui_workers={"gw0": None}, ui_coverage_dir=isolated,
                                 option=SimpleNamespace(numprocesses=1, keyword="", markexpr=""))
    session = SimpleNamespace(config=controller, testscollected=1, exitstatus=0)
    monkeypatch.setattr(conftest.COVERAGE, "uncovered", lambda: {})
    conftest.pytest_sessionfinish(session, 0)
    assert session.exitstatus == 0
    (isolated / "gw0.json").unlink()
    conftest.pytest_sessionfinish(session, 0)
    assert session.exitstatus == pytest.ExitCode.TESTS_FAILED
