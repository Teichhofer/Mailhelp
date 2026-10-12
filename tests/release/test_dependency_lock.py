"""requirements.lock pins the complete dependency closure of pyproject.toml.

A dependency added to ``pyproject.toml`` without its transitive packages in the
lock file would be installed unpinned in CI and Docker (in 2.0 ``pywebpush``
was missing at first).  The closure is read from the installed distributions,
so it covers the markers of the running platform.
"""
from __future__ import annotations

import tomllib
from importlib.metadata import distribution
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).parents[2]
# The browser tests install their extra separately (see .github/workflows/ci.yml).
LOCKED_EXTRAS = ("test", "lint")


# requirements-lint.lock keeps the static-check tools out of the Docker image.
LOCK_FILES = ("requirements.lock", "requirements-lint.lock")


def locked() -> dict[str, str]:
    pins = {}
    lines = [line for name in LOCK_FILES for line in (ROOT / name).read_text(encoding="utf-8").splitlines()]
    for line in lines:
        line = line.split("#", 1)[0].strip()
        if line:
            requirement = Requirement(line)
            (specifier,) = requirement.specifier
            assert specifier.operator == "==", line
            pins[canonicalize_name(requirement.name)] = specifier.version
    return pins


def roots() -> list[Requirement]:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    names = project["dependencies"] + [item for extra in LOCKED_EXTRAS
                                       for item in project["optional-dependencies"][extra]]
    return [Requirement(name) for name in names]


def closure(requirements: list[Requirement]) -> dict[str, str]:
    """Installed name → version of every requirement reachable on this platform."""
    found: dict[str, str] = {}
    pending = [(requirement, "") for requirement in requirements]
    while pending:
        requirement, extra = pending.pop()
        if requirement.marker is not None and not requirement.marker.evaluate({"extra": extra}):
            continue
        name = canonicalize_name(requirement.name)
        if name in found:
            continue
        found[name] = distribution(name).version
        for text in distribution(name).requires or []:
            child = Requirement(text)
            pending.extend((child, wanted) for wanted in ("", *requirement.extras))
    return found


def test_every_direct_dependency_is_pinned_exactly_as_in_pyproject():
    pins = locked()
    for requirement in roots():
        (specifier,) = requirement.specifier
        assert pins.get(canonicalize_name(requirement.name)) == specifier.version, requirement


def test_the_lock_file_contains_the_whole_installed_closure():
    installed = closure(roots())
    pins = locked()
    missing = sorted(name for name in installed if name not in pins)
    differing = sorted(f"{name} {installed[name]} != {pins[name]}" for name in installed
                       if name in pins and installed[name] != pins[name])
    assert (missing, differing) == ([], [])
