"""Synthetic prompt contracts: distinguish occupancy, uncertain work and calendar notes."""
import json
from pathlib import Path

import pytest
import yaml

from mailhelp.domain.extraction import EventExtraction, TaskExtraction
from mailhelp.llm.evaluation import evaluate
from tests.fakes.prompt_gate_fakes import repository_prompts
from tests.fakes.shared_quality_corpus import ExpectedAnswers

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("relative", ["prompts.yaml", "src/mailhelp/defaults/prompts.yaml"])
@pytest.mark.parametrize("stage,label,kind,responsibility,certainty,time_requirement", [
    ("event_extraction", "Bestaetigte Belegung", "events", "user", "certain", "all_day"),
    ("event_extraction", "Stornierte Belegung", "events", "user", "certain", "all_day"),
    ("event_extraction", "Besprechung ohne Uhrzeit", "events", "user", "certain", "required_unknown"),
    ("task_extraction", "Unverbindliche Besprechungsidee", "tasks", "unclear", "uncertain", None),
    ("task_extraction", "Auftrag an eine andere Person", "tasks", "other", "certain", None),
])
def test_refinement_examples_preserve_evidence_and_roles(relative, stage, label, kind,
                                                        responsibility, certainty, time_requirement):
    prompt = yaml.safe_load((ROOT / relative).read_text(encoding="utf-8"))["prompts"][stage]["system_prompt"]
    example = prompt.split("Beispiel: " + label + "\n", 1)[1]
    mail, output = example.split("Ausgabe: ", 1)
    schema = EventExtraction if kind == "events" else TaskExtraction
    result = schema.model_validate(json.loads(output.splitlines()[0]))
    items = getattr(result, kind)
    assert len(items) == 1
    item = items[0]
    assert item.evidence in mail
    assert (item.responsibility, item.certainty) == (responsibility, certainty)
    if kind == "events":
        assert item.time_requirement == time_requirement
        assert item.time_text is None and item.end_time_text is None
        assert item.date_text in mail
        assert item.classification == ("cancellation" if label == "Stornierte Belegung" else "new")
    else:
        assert item.due_text is None
        assert item.classification == ("non_binding" if responsibility == "unclear" else "new")


def test_calendar_note_is_not_duplicated_as_work():
    prompts = yaml.safe_load((ROOT / "prompts.yaml").read_text(encoding="utf-8"))["prompts"]
    for stage in ("action_router", "task_extraction"):
        example = prompts[stage]["system_prompt"].split("Beispiel: Reine Kalendervormerkung\n", 1)[1]
        output = json.loads(example.split("Ausgabe: ", 1)[1].splitlines()[0])
        if stage == "action_router":
            assert output["action_state"] == "event"
            assert (output["task_count"], output["event_count"]) == (0, 1)
        else:
            assert TaskExtraction.model_validate(output).tasks == []


def test_independent_refinement_corpus_preserves_the_processing_contract():
    corpus = json.loads((ROOT / "tests/fixtures/prompt_refinement_corpus.json").read_text(encoding="utf-8"))
    assert len(corpus["cases"]) == 10
    measured = evaluate(corpus, repository_prompts(), ExpectedAnswers(corpus), 50)
    assert measured["complete"] and measured["passed"]
    by_id = {item["id"]: item for item in measured["cases"]}
    for ident in ("occupancy", "cancel_occupancy", "calendar_note"):
        actual = by_id["refinement_" + ident]["stages"]
        assert actual["task_extraction"]["actual"] == {"tasks": []}
        assert actual["event_extraction"]["actual"]["events"][0]["time_requirement"] == "all_day"
    missing = by_id["refinement_meeting_time_missing"]["stages"]["event_extraction"]["actual"]
    assert missing["events"][0]["time_requirement"] == "required_unknown"


@pytest.mark.parametrize("relative", ["prompts.yaml", "src/mailhelp/defaults/prompts.yaml"])
def test_named_resource_is_retained_in_location(relative):
    prompt = yaml.safe_load((ROOT / relative).read_text(encoding="utf-8"))["prompts"]["event_extraction"]["system_prompt"]
    example = prompt.split("Beispiel: Benannte Ressource\n", 1)[1]
    mail, output = example.split("Ausgabe: ", 1)
    item = EventExtraction.model_validate(json.loads(output.splitlines()[0])).events[0]
    assert item.location == "Hütte Waldlicht" and item.location in mail
    assert "Sommer" in item.title and item.evidence in mail
    assert (item.responsibility, item.time_requirement) == ("user", "all_day")


@pytest.mark.parametrize("stage", ["action_router", "task_extraction"])
@pytest.mark.parametrize("label", ["Fremdbericht ohne Eigenauftrag", "Versandte Bitte ohne Selbstauftrag"])
def test_exclusion_examples_do_not_create_foreign_work(stage, label):
    prompt = yaml.safe_load((ROOT / "prompts.yaml").read_text(encoding="utf-8"))["prompts"][stage]["system_prompt"]
    example = prompt.split("Beispiel: " + label + "\n", 1)[1]
    output = json.loads(example.split("Ausgabe: ", 1)[1].splitlines()[0])
    if stage == "action_router":
        assert output["action_state"] == "none"
        assert output["task_count"] == output["event_count"] == 0
    else:
        assert TaskExtraction.model_validate(output).tasks == []


def test_final_controls_keep_safety_cases_and_booking_evidence_unchanged():
    corpus = json.loads((ROOT / "tests/fixtures/prompt_refinement_final_corpus.json").read_text(encoding="utf-8"))
    frozen = json.loads((ROOT / "tests/fixtures/mail_corpus_v4/corpus.json").read_text(encoding="utf-8"))
    originals = {case["id"]: case for case in frozen["cases"]}
    assert len(corpus["cases"]) == 9
    for case in corpus["cases"]:
        if case["id"] in originals:
            assert case == originals[case["id"]]
    measured = evaluate(corpus, repository_prompts(), ExpectedAnswers(corpus), 50)
    assert measured["complete"] and measured["passed"]
    by_id = {case["id"]: case for case in measured["cases"]}
    for ident in ("42_foreign_responsibility", "43_sent_request_to_others"):
        actual = by_id[ident]["stages"]
        assert actual["task_extraction"]["actual"] == {"tasks": []}
        assert actual["event_extraction"]["actual"] == {"events": []}
