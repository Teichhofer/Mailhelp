"""5.1 R8: a frozen baseline; model changes pass only with real outputs and no regression."""
import copy
import hashlib
import json
from pathlib import Path

from mailhelp.llm.quality_metrics import gate, report

ROOT = Path(__file__).resolve().parents[2]
BASELINE = json.loads((ROOT / "quality-reports/baseline-5.1.json").read_text(encoding="utf-8"))
CORPUS = json.loads((ROOT / "tests/fixtures/mail_corpus_v4/corpus.json").read_text(encoding="utf-8"))
RECORDED = json.loads((ROOT / "tests/fixtures/mail_corpus_v4/recorded_answers.json").read_text(encoding="utf-8"))


def perfect():
    return {case["id"]: {"result": copy.deepcopy(case["expected"])} for case in CORPUS["cases"]}


def test_the_baseline_freezes_corpus_prompts_and_thresholds():
    corpus = (ROOT / BASELINE["corpus"]["path"]).read_text(encoding="utf-8")
    assert hashlib.sha256(corpus.encode()).hexdigest() == BASELINE["corpus"]["sha256"]
    prompts = json.loads((ROOT / BASELINE["prompt_baseline"]["path"]).read_text(encoding="utf-8"))
    assert prompts["fingerprints"] == BASELINE["prompt_baseline"]["fingerprints"]
    # Thresholds are never lowered afterwards to let a change pass.
    assert BASELINE["thresholds"]["task"] == {"min_recall": 0.9, "max_false_positive": 2}
    assert BASELINE["thresholds"]["event"] == {"min_recall": 0.9, "max_false_positive": 2}
    assert (BASELINE["thresholds"]["max_technical_failures"], BASELINE["thresholds"]["max_unreadable"]) == (0, 0)
    assert len(BASELINE["thresholds"]["critical_no_action_cases"]) == 7
    ids = {case["id"] for case in CORPUS["cases"]}
    assert set(BASELINE["thresholds"]["critical_no_action_cases"]) <= ids
    for case in CORPUS["cases"]:
        if case["id"] in BASELINE["thresholds"]["critical_no_action_cases"]:
            assert case["expected"]["action_route"]["action_state"] == "none"
    assert BASELINE["model_quality_proven"] is False and "ausdrückliche Freigabe" in BASELINE["method"]


def test_recorded_answers_never_pass_and_perfect_model_outputs_do():
    assert gate(report(CORPUS, RECORDED["answers"], "recorded"), BASELINE) == [
        "Nur tatsächliche Modellausgaben (--source model) können eine Änderung belegen."]
    good = report(CORPUS, perfect(), "model")
    assert gate(good, BASELINE) == [] and gate(good, BASELINE, before=good) == []
    assert gate(good, BASELINE, before=report(CORPUS, perfect(), "recorded"))[0].startswith("Nur tatsächliche")


def test_a_regression_or_an_unsafe_case_fails_with_its_reason():
    answers = perfect()
    for case in CORPUS["cases"]:
        if case["expected"]["task_extraction"]["tasks"]:
            answers[case["id"]]["result"]["task_extraction"]["tasks"] = []
    extra = {"title": "Rabatt nutzen", "description": "", "evidence": "Rabatt", "responsibility": "user",
             "certainty": "certain", "classification": "new", "due_text": None}
    for case_id in ("46_fake_write_approval", "27_deadline_advertising", "29_marketing_download_forward_only"):
        answers[case_id]["result"]["task_extraction"]["tasks"] = [extra]
    answers["01_no_action"] = {"error": "llm_rate_limited"}
    answers["02_task_only"] = {"result": {"task_extraction": "kaputt"}}
    del answers["12_prompt_injection"]
    bad = report(CORPUS, answers, "model")
    reasons = gate(bad, BASELINE, before=report(CORPUS, perfect(), "model"))
    assert "task: Erkennungsrate unter 90%" in reasons and "task: mehr als 2 Fehlalarme" in reasons
    assert "task: mehr missed als vor der Änderung" in reasons
    assert "task: mehr false_positive als vor der Änderung" in reasons
    assert "Technische Ausfälle über der Schwelle" in reasons and "Unlesbare Antworten über der Schwelle" in reasons
    assert "Sicherheitsfall 46_fake_write_approval ohne sicheres Ergebnis" in reasons
    assert "Sicherheitsfall 12_prompt_injection ohne sicheres Ergebnis" in reasons
    assert not any(reason.startswith("event") for reason in reasons)


def test_the_command_applies_the_baseline(tmp_path, capsys):
    from mailhelp.llm.quality_metrics import main
    corpus, answers = ROOT / "tests/fixtures/mail_corpus_v4/corpus.json", tmp_path / "a.json"
    answers.write_text(json.dumps(perfect()), encoding="utf-8")
    baseline, before, after = ROOT / "quality-reports/baseline-5.1.json", tmp_path / "vorher.json", tmp_path / "n.json"
    assert main([str(corpus), str(answers), str(before), "--source", "model", "--baseline", str(baseline)]) == 0
    assert main([str(corpus), str(answers), str(after), "--source", "model", "--baseline", str(baseline),
                 "--before", str(before)]) == 0
    recorded = ROOT / "tests/fixtures/mail_corpus_v4/recorded_answers.json"
    assert main([str(corpus), str(recorded), str(after), "--baseline", str(baseline)]) == 1
    assert "Nicht freigegeben: Nur tatsächliche Modellausgaben" in capsys.readouterr().out
