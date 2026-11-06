"""The fault-injection tools also clean up after assertions and preserve child coverage."""
import time
from multiprocessing import active_children

import pytest
from coverage import CoverageData

from tests.fakes.safety_harness import LIMIT, Gate, ProcessHarness, await_result, configured_limit, seed


def test_gate_releases_and_joins_worker_even_when_assertion_fails():
    gate = Gate()
    with pytest.raises(ValueError, match="parent failure"):
        with gate.during(gate.hold):
            raise ValueError("parent failure")
    assert gate.release.is_set()


@pytest.mark.process
def test_process_is_reaped_when_expected_checkpoint_is_not_reached(tmp_path):
    directory = tmp_path / "app"
    seed(directory)
    before = {child.pid for child in active_children()}
    with pytest.raises(AssertionError):
        ProcessHarness(directory, tmp_path / "provider.json").run("unknown checkpoint")
    assert {child.pid for child in active_children()} == before


@pytest.mark.process
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


class Connection:
    def __init__(self, ready_after=None):
        self.ready_after, self.polls = ready_after, 0

    def poll(self, timeout):
        self.polls += 1
        return self.ready_after is not None and self.polls >= self.ready_after


class Child:
    def __init__(self, alive=True, exitcode=None):
        self.alive, self.exitcode = alive, exitcode

    def is_alive(self):
        return self.alive


def test_waiting_continues_while_a_slow_child_lives():
    """Regression 4.1.4: a fixed 20-second bound failed healthy children under Windows load."""
    connection = Connection(ready_after=5)
    await_result(connection, Child(), limit=5)
    assert connection.polls == 5


def test_a_child_dying_without_result_fails_at_once():
    started = time.monotonic()
    with pytest.raises(AssertionError, match="exited with 3 before a result"):
        await_result(Connection(), Child(alive=False, exitcode=3), limit=60)
    assert time.monotonic() - started < 5


def test_a_result_sent_just_before_exit_is_not_lost():
    class LastWord(Connection):
        def poll(self, timeout):
            self.polls += 1
            return timeout == 0
    started = time.monotonic()
    await_result(LastWord(), Child(alive=False, exitcode=0), limit=60)
    assert time.monotonic() - started < 5


def test_a_hanging_child_fails_at_the_upper_bound():
    with pytest.raises(AssertionError, match="did not reach checkpoint"):
        await_result(Connection(), Child(), limit=0)


def test_the_upper_bound_is_generous_and_configurable():
    assert configured_limit({}) == 120 and LIMIT >= 60
    assert configured_limit({"MAILHELP_TEST_PROCESS_SECONDS": "300"}) == 300


def test_unexpected_child_exit_reports_exitcode_and_the_last_received_result(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from coverage import Coverage

    import tests.fakes.safety_harness as harness_module
    process = SimpleNamespace(start=lambda: None, join=lambda timeout: None,
                              is_alive=lambda: False, exitcode=3)
    parent = SimpleNamespace(recv=lambda: ("done", []), close=lambda: None)
    child = SimpleNamespace(close=lambda: None)
    context = SimpleNamespace(Pipe=lambda: (parent, child), Process=lambda **kwargs: process)
    monkeypatch.setattr("multiprocessing.get_context", lambda mode: context)
    monkeypatch.setattr(Coverage, "current", lambda: None)
    monkeypatch.setattr(harness_module, "await_result", lambda *args: None)
    harness = ProcessHarness.__new__(ProcessHarness)
    harness.directory, harness.provider, harness.coverage_file = tmp_path, tmp_path / "synthetic.json", None
    with pytest.raises(AssertionError, match="3.*done"):
        harness.run()
