"""JSON-Schema snapshots of every persisted model (Planung 2.1, T5).

A changed stored format needs a deliberate decision: a new snapshot, a
migration if old files no longer validate, and a state set in ``states/``.
Run this file directly to write new snapshots after such a decision::

    python tests/upgrade/test_schema_snapshots.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from mailhelp.models import Proposal
from mailhelp.persistence import schemas

SNAPSHOTS = Path(__file__).parent / "schemas"
MODELS = {name: getattr(schemas, name) for name in schemas.__all__} | {"Proposal": Proposal}


def current(model) -> str:
    return json.dumps(model.model_json_schema(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


@pytest.mark.parametrize("name", sorted(MODELS))
def test_stored_format_is_unchanged(name):
    snapshot = SNAPSHOTS / f"{name}.json"
    assert snapshot.read_text(encoding="utf-8") == current(MODELS[name]), (
        f"Gespeichertes Format von {name} geändert: Migration und Upgrade-Zustand prüfen, "
        "dann Snapshot neu schreiben (siehe Moduldokumentation).")


def test_every_snapshot_belongs_to_a_persisted_model():
    assert sorted(path.stem for path in SNAPSHOTS.glob("*.json")) == sorted(MODELS)


if __name__ == "__main__":
    SNAPSHOTS.mkdir(exist_ok=True)
    for name, model in MODELS.items():
        (SNAPSHOTS / f"{name}.json").write_text(current(model), encoding="utf-8", newline="\n")
    sys.exit(0)
