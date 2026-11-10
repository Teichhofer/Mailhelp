"""Conservative offline gate: changed model inputs require a reviewed evaluation baseline."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

INPUTS = ("prompts.yaml", "topics.yaml", "decisions_prompts.yaml",
          "tests/fixtures/mail_corpus_v3/corpus.json")


# Prompt steps that never see a mail and are not part of the evaluated analysis (5.3: help chat).
NOT_EVALUATED = ("settings_help",)


def _evaluated(name: str, text: str) -> str:
    """The file as the evaluation sees it: steps outside the mail analysis are left out."""
    if name != "prompts.yaml":
        return text
    for step in NOT_EVALUATED:
        text = re.sub(rf"(?ms)^  {step}:\n.*?(?=^  [a-z_]+:\n|^\S|\Z)", "", text)
    return text


def fingerprints(root: Path) -> dict[str, str]:
    # Normalize only platform line endings, preserving every instruction and model parameter.
    return {name: hashlib.sha256(_evaluated(name, (root / name).read_text(encoding="utf-8")).encode()).hexdigest()
            for name in INPUTS}


def verify_baseline(root: Path) -> None:
    baseline = json.loads((root / "quality-reports/prompt-baseline.json").read_text(encoding="utf-8"))
    if baseline["fingerprints"] != fingerprints(root):
        raise ValueError("Prompt-/Themen-/Korpusänderung benötigt eine neue geprüfte Evaluierungs-Baseline; "
                         "simulierte Antworten belegen keine Modellqualität")
