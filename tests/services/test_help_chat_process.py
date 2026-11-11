"""Hard termination before, during and after an answer must never replay a paid request."""
from multiprocessing import get_context

import pytest
from coverage import Coverage

from tests.fakes.safety_harness import LIMIT, await_result
from tests.scenarios.help_chat_process import run


def execute(directory, point):
    active = Coverage.current()
    coverage_file = active.config.data_file if active is not None else None
    context = get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(target=run, args=(str(directory), point, child, coverage_file))
    process.start()
    child.close()
    try:
        await_result(parent, process)
        result = parent.recv()
        if point is not None:
            assert result == point
            process.kill()
        process.join(LIMIT)
        assert not process.is_alive()
        assert (process.exitcode != 0) if point is not None else process.exitcode == 0
        return result
    finally:
        if process.is_alive():
            process.kill()
            process.join(LIMIT)
        parent.close()


@pytest.mark.process
@pytest.mark.parametrize("point,expected_calls,status", [
    ("queued", 0, "interrupted"), ("running", 1, "interrupted"), ("completed", 1, "completed"),
])
def test_a_hard_killed_chat_is_recovered_in_fresh_processes_without_another_call(tmp_path, point, expected_calls, status):
    execute(tmp_path, point)
    assert execute(tmp_path, None) == (int(point != "completed"), status, expected_calls)
    assert execute(tmp_path, None) == (0, status, expected_calls)
