"""The fault-injection tools also clean up after assertions and preserve child coverage."""
from multiprocessing import active_children

import pytest
from coverage import CoverageData
from safety_harness import Gate, ProcessHarness, seed


def test_gate_releases_and_joins_worker_even_when_assertion_fails():
    gate = Gate()
    with pytest.raises(ValueError, match="parent failure"):
        with gate.during(gate.hold):
            raise ValueError("parent failure")
    assert gate.release.is_set()


def test_process_is_reaped_when_expected_checkpoint_is_not_reached(tmp_path):
    directory = tmp_path / "app"
    seed(directory)
    before = {child.pid for child in active_children()}
    with pytest.raises(AssertionError):
        ProcessHarness(directory, tmp_path / "provider.json").run("unknown checkpoint")
    assert {child.pid for child in active_children()} == before


def test_killed_process_flushes_statement_and_branch_coverage_at_checkpoint(tmp_path):
    directory = tmp_path / "app"
    seed(directory)
    data_file = tmp_path / "child-coverage"
    ProcessHarness(directory, tmp_path / "provider.json", str(data_file)).run("A2")
    files = list(tmp_path.glob("child-coverage.*"))
    assert files
    data = CoverageData(basename=str(files[0]))
    data.read()
    measured = next(path for path in data.measured_files() if path.replace("\\", "/").endswith("external/confirmed.py"))
    assert data.lines(measured) and data.arcs(measured) and data.has_arcs()
