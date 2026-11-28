"""8.9.4: the quality report reads mailhelp-evaluate reports and compares places without possessives.

Regression of the before run of 28.11.2026: case 08 says "in meinem Büro" (from Jonas Weber); the verbatim answer
"meinem Büro" counted as a wrong place against "Büro von Jonas Weber". Until 8.9.3 an evaluation report also had to
be converted by hand before mailhelp-quality-report could score it. Synthetic data only.
"""
import copy
import json
from pathlib import Path

from mailhelp.llm.quality_metrics import answers_from_run, main, score_case

ROOT = Path(__file__).resolve().parents[2]
CORPUS_PATH = ROOT / "tests/fixtures/mail_corpus_v5/corpus.json"
CORPUS = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
CASES = {case["id"]: case for case in CORPUS["cases"]}


def answer(case, **events):
    result = {stage: copy.deepcopy(case["expected"][stage])
              for stage in ("relevance", "task_extraction", "event_extraction")}
    for event in result["event_extraction"]["events"]:
        event.update(events)
    return {"result": result}


def test_regression_a_possessive_does_not_make_another_place():
    case = CASES["08_invalid_date"]
    assert score_case(case, answer(case, location="meinem Büro"))["event"]["fields"][0]["location"] is True
    assert score_case(case, answer(case, location="Raum 14"))["event"]["fields"][0]["location"] is False
    room = CASES["K15_recurring_weekday"]
    assert score_case(room, answer(room, location="online"))["event"]["fields"][0]["location"] is False


def test_an_evaluation_report_is_scored_directly(tmp_path, capsys):
    cases = []
    for case in CORPUS["cases"]:
        outputs = {stage: copy.deepcopy(case["expected"][key]) for stage, key in (
            ("relevance", "relevance"), ("task_extraction", "task_extraction"), ("event_extraction", "event_extraction"))}
        cases.append({"id": case["id"], "error": None, "review_outputs": outputs})
    cases[0] = {"id": cases[0]["id"], "error": "LlmTimeout", "review_outputs": {}}
    run = {"schema_version": 3, "prompt_fingerprint": "f" * 64, "cases": cases}
    assert answers_from_run(run)[cases[0]["id"]] == {"error": "LlmTimeout"}
    path, output = tmp_path / "run.json", tmp_path / "metrics.json"
    path.write_text(json.dumps(run), encoding="utf-8")
    assert main([str(CORPUS_PATH), str(path), str(output), "--source", "model"]) == 0
    metrics = json.loads(output.read_text(encoding="utf-8"))
    assert metrics["technical_failures"] == 1 and metrics["totals"]["event"]["field_errors"] == 0
    assert "Tatsächliche Modellausgaben" in capsys.readouterr().out
