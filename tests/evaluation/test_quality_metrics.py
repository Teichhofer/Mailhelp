"""5.1 R7: corpus v4 and a quality report that separates detection, misses, false alarms and fields."""
import json
from pathlib import Path

import pytest

from mailhelp.domain.extraction import ActionRoute, EventExtraction, ExtractedTask, Summary, TaskExtraction
from mailhelp.domain.relevance import Relevance
from mailhelp.llm.quality_metrics import main, report, score_case, task_facts
from mailhelp.proposals.action_normalization import MailDateContext

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
CORPUS = json.loads((FIXTURES / "mail_corpus_v4/corpus.json").read_text(encoding="utf-8"))
RECORDED = json.loads((FIXTURES / "mail_corpus_v4/recorded_answers.json").read_text(encoding="utf-8"))
V3 = json.loads((FIXTURES / "mail_corpus_v3/corpus.json").read_text(encoding="utf-8"))


def test_corpus_v4_keeps_v3_and_adds_the_case_groups_of_5_1_with_a_purpose_each():
    cases = CORPUS["cases"]
    assert CORPUS["schema_version"] == 4 and len(cases) == 46
    assert len({case["id"] for case in cases}) == 46
    assert all(case["purpose"].strip() for case in cases)
    by_id = {case["id"]: case for case in cases}
    for old in V3["cases"]:
        assert by_id[old["id"]]["expected"] == old["expected"] and by_id[old["id"]]["raw_email"] == old["raw_email"]
    for case in cases:
        expected = case["expected"]
        Relevance.model_validate(expected["relevance"])
        Summary.model_validate(expected["summary"])
        route = ActionRoute.model_validate(expected["action_route"])
        tasks = TaskExtraction.model_validate(expected["task_extraction"]).tasks
        events = EventExtraction.model_validate(expected["event_extraction"]).events
        assert (route.task_count, route.event_count) == (len(tasks), len(events))
        assert "@example.test" in case["raw_email"] and "@example.test>" in case["raw_email"]
    groups = {"39_meeting_with_preparation": ("task_and_event", 1, 1), "40_meeting_information_only": ("event", 0, 1),
              "41_two_tasks_registration_documents": ("task", 2, 0), "42_foreign_responsibility": ("none", 0, 0),
              "43_sent_request_to_others": ("none", 0, 0), "44_all_day_without_time": ("event", 0, 1),
              "45_contradictory_date": ("event", 0, 1), "46_fake_write_approval": ("none", 0, 0)}
    for case_id, (state, task_count, event_count) in groups.items():
        route = by_id[case_id]["expected"]["action_route"]
        assert (route["action_state"], route["task_count"], route["event_count"]) == (state, task_count, event_count)


def test_recorded_answers_report_exactly_their_known_errors_and_prove_no_model_quality():
    result = report(CORPUS, RECORDED["answers"], "recorded")
    assert (result["model_quality_proven"], result["source"], result["cases_total"]) == (False, "recorded", 46)
    assert "Modellqualität ist damit nicht nachgewiesen" in result["statement"]
    assert (result["technical_failures"], result["unreadable"]) == (1, 1)
    tasks, events = result["totals"]["task"], result["totals"]["event"]
    assert (tasks["recognized"], tasks["missed"], tasks["false_positive"], tasks["field_errors"]) == (15, 1, 1, 1)
    assert tasks["fields"]["due"] == {"correct": 14, "checked": 15}  # the wrong deadline of case 39
    assert all(tasks["fields"][name] == {"correct": 15, "checked": 15}
               for name in ("classification", "responsibility", "certainty", "evidence"))
    assert (events["recognized"], events["missed"], events["false_positive"], events["field_errors"]) == (38, 0, 0, 1)
    assert events["fields"]["when"] == {"correct": 37, "checked": 38}  # the invented clock of case 44
    assert (tasks["review"], events["review"]) == (0, 0)
    # Recorded v4 answers have no relevance stage: the end-to-end effect is not checked, and the contract is 4.
    assert (result["contract_version"], result["end_to_end_unchecked"]) == (4, 44)
    outcomes = {case["id"]: case["outcome"] for case in result["cases"]}
    assert (outcomes["46_fake_write_approval"], outcomes["12_prompt_injection"]) == ("technical_failure", "unreadable")
    assert result["corpus_schema_version"] == 4


def test_perfect_model_answers_score_fully_and_a_missing_answer_is_a_failure():
    answers = {case["id"]: {"result": case["expected"]} for case in CORPUS["cases"]}
    del answers["01_no_action"]
    result = report(CORPUS, answers, "model")
    assert result["model_quality_proven"] is True and result["technical_failures"] == 1
    assert result["totals"]["task"]["missed"] == 0 and result["totals"]["event"]["false_positive"] == 0
    assert score_case(CORPUS["cases"][0], None) == {"id": "01_no_action", "outcome": "technical_failure",
                                                    "error": "missing_answer"}
    assert score_case(CORPUS["cases"][0], {"result": {}})["outcome"] == "unreadable"


@pytest.mark.parametrize(("due", "fact"), [("bis 17.11.2026", "2026-11-17"), ("17. November 2026", "2026-11-17"),
                                          ("nächsten Freitag", "naechsten freitag"), (None, None)])
def test_deadlines_are_compared_by_the_day_the_application_resolves(due, fact):
    context = MailDateContext(date_context_status="valid", date_header_parsed="2026-11-10T09:00:00+01:00",
                              imap_received_at="2026-11-10T09:01:00+01:00", user_timezone="Europe/Berlin")
    task = ExtractedTask(title="Bericht senden", description="", evidence="Bericht", responsibility="user",
                         certainty="certain", classification="new", due_text=due)
    assert task_facts(task, context)["due"] == fact


def test_the_command_writes_the_report(tmp_path, capsys):
    corpus, answers, output = tmp_path / "c.json", tmp_path / "a.json", tmp_path / "r.json"
    corpus.write_text(json.dumps(CORPUS), encoding="utf-8")
    answers.write_text(json.dumps(RECORDED["answers"]), encoding="utf-8")
    assert main([str(corpus), str(answers), str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["source"] == "recorded"
    assert "nicht nachgewiesen" in capsys.readouterr().out
    # The recorded file with its description is read directly.
    recorded = FIXTURES / "mail_corpus_v4/recorded_answers.json"
    assert main([str(FIXTURES / "mail_corpus_v4/corpus.json"), str(recorded), str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["totals"]["task"]["missed"] == 1
