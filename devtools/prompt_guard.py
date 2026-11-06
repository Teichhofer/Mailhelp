"""Conservative offline gate: changed model inputs require a reviewed evaluation baseline."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

INPUTS = ("prompts.yaml", "topics.yaml", "decisions_prompts.yaml",
          "tests/fixtures/mail_corpus_v3/corpus.json")


def fingerprints(root: Path) -> dict[str, str]:
    # Normalize only platform line endings, preserving every instruction and model parameter.
    return {name: hashlib.sha256((root / name).read_text(encoding="utf-8").encode()).hexdigest()
            for name in INPUTS}


def verify_baseline(root: Path) -> None:
    baseline = json.loads((root / "quality-reports/prompt-baseline.json").read_text(encoding="utf-8"))
    if baseline["fingerprints"] != fingerprints(root):
        raise ValueError("Prompt-/Themen-/Korpusänderung benötigt eine neue geprüfte Evaluierungs-Baseline; "
                         "simulierte Antworten belegen keine Modellqualität")
