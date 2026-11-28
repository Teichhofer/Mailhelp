"""Reviewed prompt examples retain arrival, programme start and optionality without guessing travel."""
import json
from pathlib import Path

import pytest
import yaml

from mailhelp.config import TargetSettings
from mailhelp.domain.extraction import EventExtraction
from mailhelp.llm.evaluation import evaluate
from mailhelp.proposals.action_normalization import MailDateContext
from mailhelp.proposals.proposal_builder import ProposalBuilder
from tests.fakes.prompt_gate_fakes import repository_prompts
from tests.fakes.shared_quality_corpus import ExpectedAnswers

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("relative", ["prompts.yaml", "src/mailhelp/defaults/prompts.yaml"])
@pytest.mark.parametrize("label,start", [
    ("Ankommen vor Programmbeginn", "12:30:00"),
    ("Freiwilliges Vorprogramm", "13:00:00"),
    ("Vorbereitung nur fuer andere Personen", "13:00:00"),
])
def test_arrival_examples_keep_the_participant_start_and_programme_end(relative, label, start):
    prompt = yaml.safe_load((ROOT / relative).read_text(encoding="utf-8"))["prompts"]["event_extraction"]["system_prompt"]
    example = prompt.split("Beispiel: " + label + "\n", 1)[1]
    mail, answer = example.split("Ausgabe: ", 1)
    extraction = EventExtraction.model_validate(json.loads(answer.splitlines()[0]))
    assert len(extraction.events) == 1
    event = extraction.events[0]
    assert event.time_text in mail and event.end_time_text in mail
    assert event.evidence in mail
    items = ProposalBuilder("a" * 24, TargetSettings(todoist_project="tasks", google_calendar="calendar"),
        MailDateContext(date_context_status="valid", date_header_parsed="2027-03-01T09:00:00+01:00",
                        imap_received_at="2027-03-01T09:01:00+01:00",
                        user_timezone="Europe/Berlin")).build([], extraction.events)
    assert len(items) == 1
    assert items[0].start.isoformat() == "2027-03-18T" + start + "+01:00"
    assert items[0].end.isoformat() == "2027-03-18T17:00:00+01:00"
    assert items[0].status == "pending_confirmation"
    assert "13:00" in items[0].description


def test_bundled_and_checkout_arrival_rules_are_identical():
    def event_prompt(relative):
        return yaml.safe_load((ROOT / relative).read_text(encoding="utf-8"))["prompts"]["event_extraction"]["system_prompt"]

    prompt = event_prompt("prompts.yaml")
    assert prompt == event_prompt("src/mailhelp/defaults/prompts.yaml")
    for label in ("Ankommen", "Einlass", "Registrierung", "Check-in"):
        assert label in prompt
    assert "Erfinde keine Anreisezeiten, Fahrtzeiten oder Zeitpuffer" in prompt


def test_independent_arrival_cases_pass_the_offline_processing_contract():
    corpus = json.loads((ROOT / "tests/fixtures/event_arrival_corpus.json").read_text(encoding="utf-8"))
    assert len(corpus["cases"]) == 4
    report = evaluate(corpus, repository_prompts(), ExpectedAnswers(corpus), 20)
    assert report["passed"] and report["complete"]
    starts = {case["id"]: case["stages"]["event_extraction"]["actual"]["events"][0]["when"]["start"]
              for case in report["cases"]}
    assert starts == {
        "arrival_arrival_before_opening": "2027-03-18T13:40:00+01:00",
        "arrival_checkin_before_conference": "2027-03-18T09:10:00+01:00",
        "arrival_optional_coffee": "2027-03-18T10:00:00+01:00",
        "arrival_crew_only_preparation": "2027-03-18T11:00:00+01:00",
    }
