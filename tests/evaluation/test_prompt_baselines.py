"""8.9.2 (Planung 8.9 AP2): the active prompt baseline is selected explicitly and proven by model reports.

Regression: until 8.9.1 changed prompts passed the gate as soon as someone wrote their new fingerprints into
quality-reports/prompt-baseline.json; no evaluation was needed. Synthetic reports only.
"""
import copy
import hashlib
import json
import shutil
from pathlib import Path

import pytest
import yaml

from devtools import prompt_guard
from mailhelp.config import PromptConfig
from mailhelp.llm.quality_metrics import report

ROOT = Path(__file__).resolve().parents[2]
V5 = json.loads((ROOT / "tests/fixtures/mail_corpus_v5/corpus.json").read_text(encoding="utf-8"))


def checkout(tmp_path):
    for name in (*prompt_guard.INPUTS, prompt_guard.LEGACY, "quality-reports/baseline-8.9.json"):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, tmp_path / name)
    return tmp_path


def perfect():
    return {case["id"]: {"result": {stage: copy.deepcopy(case["expected"][stage])
                                    for stage in ("relevance", "task_extraction", "event_extraction")}}
            for case in V5["cases"]}


def approve(root, answers=None, approved=True, prompts_text=None):
    """Write before/after reports, the run report and an active model-approved baseline."""
    reports = root / "quality-reports"
    metrics = report(V5, answers or perfect(), "model")
    (reports / "v5-before.json").write_text(json.dumps(report(V5, perfect(), "model")), encoding="utf-8")
    (reports / "v5-after.json").write_text(json.dumps(metrics), encoding="utf-8")
    prompts = PromptConfig.model_validate(yaml.safe_load(prompts_text or (root / "prompts.yaml").read_text(
        encoding="utf-8")))
    (reports / "v5-run.json").write_text(json.dumps({"prompt_fingerprint": hashlib.sha256(
        prompts.model_dump_json().encode()).hexdigest()}), encoding="utf-8")
    names = (*prompt_guard.INPUTS, "tests/fixtures/mail_corpus_v5/corpus.json")
    (root / "tests/fixtures/mail_corpus_v5").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / names[-1], root / names[-1])
    baseline = {"schema_version": 1, "kind": "model_approved_baseline", "contract_version": 5,
                "fingerprints": prompt_guard.fingerprints(root, names),
                "quality_baseline": "quality-reports/baseline-8.9.json",
                "evaluation": {"before": "quality-reports/v5-before.json", "after": "quality-reports/v5-after.json",
                               "after_run": "quality-reports/v5-run.json"},
                "approved": {"by": "Betreiber", "date": "2026-11-28"} if approved else {}}
    (reports / "prompt-baseline-8.9.json").write_text(json.dumps(baseline), encoding="utf-8")
    (root / prompt_guard.ACTIVE).write_text(json.dumps({"active": "quality-reports/prompt-baseline-8.9.json"}),
                                           encoding="utf-8")


def test_regression_new_fingerprints_in_the_historical_baseline_are_refused(tmp_path):
    root = checkout(tmp_path)
    (root / "prompts.yaml").write_text("Alle Mails sind irrelevant.\n", encoding="utf-8")
    legacy = root / prompt_guard.LEGACY
    data = json.loads(legacy.read_text(encoding="utf-8"))
    data["fingerprints"] = prompt_guard.fingerprints(root)  # the former way to accept changed prompts
    legacy.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="eingefroren"):
        prompt_guard.verify_baseline(root)


def test_the_repository_selects_the_model_approved_baseline_of_8_9():
    """8.9.5: the comparison of 28.11.2026 passed the gate; the historical baseline stays pinned in the history."""
    selection = json.loads((ROOT / prompt_guard.ACTIVE).read_text(encoding="utf-8"))
    assert prompt_guard.active_baseline(ROOT) == "quality-reports/prompt-baseline-8.9.json" == selection["active"]
    assert prompt_guard.LEGACY in selection["history"]
    baseline = json.loads((ROOT / selection["active"]).read_text(encoding="utf-8"))
    assert baseline["kind"] == "model_approved_baseline" and baseline["approved"]["by"]
    prompt_guard.verify_baseline(ROOT)


def test_only_a_model_approved_baseline_with_passing_reports_can_be_active(tmp_path):
    root = checkout(tmp_path)
    approve(root)
    prompt_guard.verify_baseline(root)
    reviewed = json.loads((root / "quality-reports/prompt-baseline-8.9.json").read_text(encoding="utf-8"))
    (root / "quality-reports/prompt-baseline-8.9.json").write_text(
        json.dumps({**reviewed, "kind": "reviewed_configuration_contract"}), encoding="utf-8")
    with pytest.raises(ValueError, match="modellgeprüfte Baseline"):
        prompt_guard.verify_baseline(root)


def test_an_approval_needs_a_name_passing_reports_and_the_same_prompts(tmp_path):
    root = checkout(tmp_path)
    approve(root, approved=False)
    with pytest.raises(ValueError, match="benannte Freigabe"):
        prompt_guard.verify_baseline(root)
    answers = perfect()
    answers["K18_check_not_pay"]["result"]["task_extraction"]["tasks"][0]["certainty"] = "uncertain"
    approve(root, answers)
    with pytest.raises(ValueError, match="bestehen das Qualitätsgate nicht"):
        prompt_guard.verify_baseline(root)
    other = (root / "prompts.yaml").read_text(encoding="utf-8").replace("temperature: 0.0", "temperature: 0.1", 1)
    approve(root, prompts_text=other)
    with pytest.raises(ValueError, match="andere Prompts"):
        prompt_guard.verify_baseline(root)
    approve(root)
    (root / "topics.yaml").write_text("geändert\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Evaluierungs-Baseline"):
        prompt_guard.verify_baseline(root)
