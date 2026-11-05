"""Planung 4.1, Schritt 9.2: the fast development run never starts real child processes."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parents[1]
MARKERS = {"slow", "process", "e2e"}


def marks(node: ast.expr) -> set[str]:
    """Names of ``pytest.mark.<name>`` used in a decorator or ``pytestmark`` value."""
    return {item.attr for item in ast.walk(node)
            if isinstance(item, ast.Attribute) and isinstance(item.value, ast.Attribute)
            and item.value.attr == "mark"}


def module_marks(tree: ast.Module) -> set[str]:
    return set().union(*(marks(item.value) for item in tree.body if isinstance(item, ast.Assign)
                         and any(isinstance(target, ast.Name) and target.id == "pytestmark"
                                 for target in item.targets)))


def starts_processes(node: ast.AST) -> bool:
    return any(isinstance(item, ast.Call) and isinstance(item.func, ast.Name)
               and item.func.id == "ProcessHarness" for item in ast.walk(node))


def test_markers_are_registered_and_enforced():
    import tomllib
    options = tomllib.loads((TESTS.parent / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["pytest"][
        "ini_options"]
    assert {line.split(":", 1)[0] for line in options["markers"]} == MARKERS
    assert "--strict-markers" in options["addopts"]


def test_every_process_harness_test_and_every_e2e_module_is_marked():
    unmarked = []
    for path in sorted(TESTS.rglob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        inherited = module_marks(tree)
        if path.parent.name == "e2e" and "e2e" not in inherited:
            unmarked.append(f"{path.name}: e2e")
        for node in tree.body:
            if (isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
                    and starts_processes(node)
                    and "process" not in inherited | set().union(*map(marks, node.decorator_list))):
                unmarked.append(f"{path.name}::{node.name}: process")
    assert unmarked == []


@pytest.mark.parametrize(("source", "expected"), [
    ("pytestmark = pytest.mark.process", {"process"}),
    ("pytestmark = [pytest.mark.e2e, pytest.mark.slow]", {"e2e", "slow"}),
    ("other = pytest.mark.slow", set()),
])
def test_module_marks_are_read_from_pytestmark_only(source, expected):
    assert module_marks(ast.parse(source)) == expected


def test_only_a_harness_call_counts_as_starting_processes():
    assert starts_processes(ast.parse("harness = ProcessHarness(directory, path)"))
    assert not starts_processes(ast.parse("text = 'ProcessHarness'"))
