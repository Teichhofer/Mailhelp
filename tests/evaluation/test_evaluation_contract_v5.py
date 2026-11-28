"""8.9.2 (Planung 8.9 AP2): the evaluation path compares stages by the contract v5.

Regressions: until 8.9.1 the extraction stages ignored the action ("Rechnung bezahlen" passed for "prüfen"),
an additional allowed topic failed the exact topic set, the summary reduced months and clock times to one
"<ohne Datum>" value, and a case passed although its relevance stage said "irrelevant" and production would
have dropped its actions. Only the model answers are simulated; synthetic data only.
"""
import copy
import json
from pathlib import Path

from mailhelp.llm.evaluation import _STAGES, evaluate
from mailhelp.llm.stage_contract import deadline_parts, topics_passed
from mailhelp.proposals.action_normalization import MailDateContext
from tests.fakes.prompt_gate_fakes import repository_prompts
from tests.fakes.shared_quality_corpus import ExpectedAnswers

ROOT = Path(__file__).resolve().parents[2]
CORPUS = json.loads((ROOT / "tests/fixtures/mail_corpus_v5/corpus.json").read_text(encoding="utf-8"))
CONTEXT = MailDateContext(date_context_status="valid", date_header_parsed="2027-02-15T09:00:00+01:00",
                          imap_received_at="2027-02-15T09:01:00+01:00", user_timezone="Europe/Berlin")


class Answers(ExpectedAnswers):
    """The expected answers, with chosen stages of chosen cases replaced."""

    def __init__(self, corpus, changes):
        super().__init__(corpus)
        self.changes = changes

    def complete(self, model, parameters, system, payload, **metadata):
        call, answer = super().complete(model, parameters, system, payload, **metadata)
        stage = metadata.get("stage") or system
        mail = payload.get("mail", payload)
        case_id = self.cases[mail["headers"]["subject"]]["id"]
        return call, copy.deepcopy(self.changes.get((case_id, stage), answer))


def run(changes=None, cases=None):
    corpus = {**CORPUS, "cases": [case for case in CORPUS["cases"] if cases is None or case["id"] in cases]}
    return evaluate(corpus, repository_prompts(), Answers(corpus, changes or {}), 10 * len(corpus["cases"]) * 5)


def stages(report, case_id):
    return next(case for case in report["cases"] if case["id"] == case_id)["stages"]


def test_expected_answers_pass_every_stage_of_the_v5_corpus():
    report = run()
    assert report["passed"] and report["complete"] and report["contract_version"] == 5
    assert report["stage_pass_counts"] == {stage: len(CORPUS["cases"]) for stage in _STAGES}
    assert report["end_to_end_lost"] == []


def test_regression_another_action_with_the_same_deadline_fails_the_extraction_stage():
    case = next(item for item in CORPUS["cases"] if item["id"] == "K18_check_not_pay")
    paid = copy.deepcopy(case["expected"]["task_extraction"])
    paid["tasks"][0]["title"] = "Rechnung der Druckerei Seidel bezahlen"
    report = run({("K18_check_not_pay", "task_extraction"): paid}, {"K18_check_not_pay"})
    assert not stages(report, "K18_check_not_pay")["task_extraction"]["passed"] and not report["passed"]


def test_regression_an_allowed_extra_topic_passes_and_an_excluded_one_fails():
    def relevance(topics):
        return {"decision": "relevant", "topic_ids": topics, "reason": "Synthetisch."}
    allowed = run({("39_meeting_with_preparation", "relevance"):
                   relevance(["arbeit", "persoenliche-termine-und-terminhinweise"])}, {"39_meeting_with_preparation"})
    assert stages(allowed, "39_meeting_with_preparation")["relevance"]["passed"]
    excluded = run({("39_meeting_with_preparation", "relevance"): relevance(["arbeit", "kommune"])},
                   {"39_meeting_with_preparation"})
    assert not stages(excluded, "39_meeting_with_preparation")["relevance"]["passed"]


def test_regression_a_month_is_not_any_other_month_and_a_computed_day_is_no_fact():
    summary = {"sentences": ["Synthetisch."], "deadlines": ["im Oktober", "25.09.2026"]}
    right = run({("21_jimdo_inquiry", "summary"): summary}, {"21_jimdo_inquiry"})
    assert stages(right, "21_jimdo_inquiry")["summary"]["passed"]
    wrong = run({("21_jimdo_inquiry", "summary"): {**summary, "deadlines": ["im September", "25.09.2026"]}},
                {"21_jimdo_inquiry"})
    detail = stages(wrong, "21_jimdo_inquiry")["summary"]["actual"]
    assert not stages(wrong, "21_jimdo_inquiry")["summary"]["passed"]
    assert detail["missing"] == ["text:oktober"] and detail["unsupported"] == ["text:september"]
    computed = run({("42_foreign_responsibility", "summary"): {"sentences": ["Synthetisch."],
                                                              "deadlines": ["bis Freitag", "20.11.2026"]}},
                   {"42_foreign_responsibility"})
    assert stages(computed, "42_foreign_responsibility")["summary"]["actual"]["unsupported"] == ["day:2026-11-20"]


def test_regression_irrelevant_ends_the_case_end_to_end():
    stop = {"decision": "irrelevant", "topic_ids": [], "reason": "Allgemeiner Veranstaltungshinweis."}
    report = run({("37_change_new_room", "relevance"): stop}, {"37_change_new_room"})
    case = stages(report, "37_change_new_room")
    assert case["event_extraction"]["passed"]  # the later stage alone would have been right
    assert case["end_to_end"] == {"passed": False, "lost_actions": 1}
    assert report["end_to_end_lost"] == ["37_change_new_room"] and not report["passed"]


def test_deadline_parts_keep_their_precision():
    assert deadline_parts("24.09.2026, 09:00 bis 10:00 Uhr", CONTEXT) == {"day:2026-09-24", "time:09:00", "time:10:00"}
    assert deadline_parts("nur bis Ende September", CONTEXT) == {"text:ende september"}
    assert deadline_parts("jeden Montag, 13:00 bis 14:00 Uhr", CONTEXT) == {"text:jeden montag", "time:13:00",
                                                                            "time:14:00"}
    assert deadline_parts("ab 9 Uhr am 25.09.", CONTEXT) == {"time:09:00", "day:--09-25"}
    assert deadline_parts("25:90", CONTEXT) == set()  # no clock and no wording left


def test_topic_contracts():
    contract = {"required": ["a"], "any_of": [], "allowed": ["b"]}
    assert topics_passed(contract, ["a"]) and topics_passed(contract, ["a", "b"])
    assert not topics_passed(contract, ["b"]) and not topics_passed(contract, ["a", "c"])
    either = {"required": [], "any_of": ["a", "b"], "allowed": ["a", "b"]}
    assert topics_passed(either, ["b"]) and not topics_passed(either, [])
