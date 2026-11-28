"""Conservative offline gate: changed model inputs require a reviewed evaluation baseline.

8.9.2 (Planung 8.9 AP2): the active baseline is chosen explicitly in ``quality-reports/active-baseline.json``;
historical baselines keep their fingerprints. A baseline of the kind ``model_approved_baseline`` is only valid
with its stored before/after reports of real model outputs that pass the quality gate of their contract again,
offline, and with a named approval. Updating fingerprints alone or an audit never switches the active baseline.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

INPUTS = ("prompts.yaml", "topics.yaml", "decisions_prompts.yaml",
          "tests/fixtures/mail_corpus_v3/corpus.json")
ACTIVE = "quality-reports/active-baseline.json"
LEGACY = "quality-reports/prompt-baseline.json"
# The reviewed configuration contract of 4.1 stays historical: its content is pinned, so a mere update of its
# fingerprints can no longer accept changed prompts.
LEGACY_DIGEST = "a9b4b349741610799ea8b065e1aa1a48f140a4cd05d89e27f7c5c69e50355ade"


# Prompt steps that never see a mail and are not part of the evaluated analysis (5.3: help chat).
NOT_EVALUATED = ("settings_help", "decision_rule_learning")


def _evaluated(name: str, text: str) -> str:
    """The file as the evaluation sees it: steps outside the mail analysis are left out."""
    if name != "prompts.yaml":
        return text
    for step in NOT_EVALUATED:
        text = re.sub(rf"(?ms)^  {step}:\n.*?(?=^  [a-z_]+:\n|^\S|\Z)", "", text)
    # Development-only profiles are excluded by PromptConfig and never enter a production analysis.
    text = re.sub(r"(?ms)^demo_profiles:\n.*?(?=^\S|\Z)", "", text)
    return text


def fingerprints(root: Path, names: tuple[str, ...] = INPUTS) -> dict[str, str]:
    # Normalize only platform line endings, preserving every instruction and model parameter.
    return {name: hashlib.sha256(_evaluated(name, (root / name).read_text(encoding="utf-8")).encode()).hexdigest()
            for name in names}


def _load(root: Path, name: str) -> Any:
    return json.loads((root / name).read_text(encoding="utf-8"))


def active_baseline(root: Path) -> str:
    """The path of the explicitly selected baseline; without a selection the reviewed contract of 4.1."""
    return str(_load(root, ACTIVE)["active"]) if (root / ACTIVE).exists() else LEGACY


def _verify_approval(root: Path, baseline: dict[str, Any]) -> None:
    from mailhelp.llm.quality_metrics import gate

    approval = baseline.get("approved") or {}
    if not (str(approval.get("by", "")).strip() and str(approval.get("date", "")).strip()):
        raise ValueError("Eine modellgeprüfte Baseline braucht eine benannte Freigabe")
    quality = _load(root, baseline["quality_baseline"])
    evaluation = baseline["evaluation"]
    before, after = _load(root, evaluation["before"]), _load(root, evaluation["after"])
    reasons = gate(after, quality, before)
    if reasons:
        raise ValueError("Die gespeicherten Modellberichte bestehen das Qualitätsgate nicht: " + "; ".join(reasons))
    # The approved run used exactly the prompts of this checkout.
    import yaml

    from mailhelp.config import PromptConfig
    prompts = PromptConfig.model_validate(yaml.safe_load((root / "prompts.yaml").read_text(encoding="utf-8")))
    if _load(root, evaluation["after_run"])["prompt_fingerprint"] != hashlib.sha256(
            prompts.model_dump_json().encode()).hexdigest():
        raise ValueError("Der freigegebene Modelllauf verwendete andere Prompts als dieser Stand")


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def verify_baseline(root: Path) -> None:
    path = active_baseline(root)
    baseline = _load(root, path)
    if path == LEGACY and _digest(baseline) != LEGACY_DIGEST:
        raise ValueError("Die historische Baseline ist eingefroren; Änderungen brauchen eine modellgeprüfte Baseline")
    if path != LEGACY and baseline.get("kind") != "model_approved_baseline":
        raise ValueError("Als aktive Baseline gilt nur eine modellgeprüfte Baseline mit gespeicherten Berichten")
    names = tuple(baseline["fingerprints"])
    if not set(INPUTS[:3]) <= set(names) or baseline["fingerprints"] != fingerprints(root, names):
        raise ValueError("Prompt-/Themen-/Korpusänderung benötigt eine neue geprüfte Evaluierungs-Baseline; "
                         "simulierte Antworten belegen keine Modellqualität")
    if baseline.get("kind") == "model_approved_baseline":
        _verify_approval(root, baseline)
