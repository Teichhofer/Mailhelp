"""8.9.2 (Planung 8.9 AP2): the scorer recognizes actions by identity and checks every fact.

Regressions of the audit of 26.11.2026: until 8.9.1 a differently worded but verified title counted as a missed
action plus a false alarm, a predeclared empty alternative counted as missed, "prüfen" passed as "bezahlen", the
result depended on the output order, and the gate ignored wrong facts and a relevance stop. Synthetic data only.
"""
import copy
import json
from pathlib import Path

import pytest

from mailhelp.llm.quality_metrics import gate, report, score_case

ROOT = Path(__file__).resolve().parents[2]
CORPUS = json.loads((ROOT / "tests/fixtures/mail_corpus_v5/corpus.json").read_text(encoding="utf-8"))
BASELINE = json.loads((ROOT / "quality-reports/baseline-8.9.json").read_text(encoding="utf-8"))
CASES = {case["id"]: case for case in CORPUS["cases"]}
AUDIT_TITLES = {  # case: (kind, title the model wrote), verified in the audit of 26.11.2026
    "02_task_only": ("task", "Belege für Reisekostenabrechnung einreichen"),
    "04_task_and_event": ("task", "Protokoll der letzten Sitzung senden"),
    "14_invitation_registration": ("task", "Für Fachtag Digitalisierung anmelden"),
    "28_registration_optional_forward_download": ("task", "Für Fachtag Digitalisierung anmelden"),
    "15_invitation_optional_greeting": ("task", "Rückmeldung zu Grußwort geben"),
    "21_jimdo_inquiry": ("task", "Jimdo-Anfrage zu Hofführung beantworten"),
    "20_quoted_old_task_after_reschedule": ("event", "Projektgespräch verschoben"),
    "23_booking_confirmation": ("event", "Stellplatz 3 Buchung Familie Weber"),
    "32_self_note_photo_invitation": ("event", "Landesversammlung des Landesverbands"),
}


def answer(case, **changes):
    result = {stage: copy.deepcopy(case["expected"][stage])
              for stage in ("relevance", "task_extraction", "event_extraction")}
    for stage, value in changes.items():
        result[stage] = value
    return {"result": result}


def perfect():
    return {case_id: answer(case) for case_id, case in CASES.items()}


def without_aliases(case):
    case = copy.deepcopy(case)
    case.pop("aliases", None)
    return case


@pytest.mark.parametrize("case_id", sorted(AUDIT_TITLES))
def test_regression_a_verified_other_title_of_the_same_action_is_recognized(case_id):
    case = without_aliases(CASES[case_id])  # the identity holds without the predeclared alias, too
    kind, title = AUDIT_TITLES[case_id]
    stage, key = ("task_extraction", "tasks") if kind == "task" else ("event_extraction", "events")
    renamed = copy.deepcopy(case["expected"][stage])
    renamed[key][0]["title"] = title
    scored = score_case(case, answer(case, **{stage: renamed}))[kind]
    assert (scored["recognized"], scored["missed"], scored["false_positive"], scored["field_errors"]) == (
        len(renamed[key]), 0, 0, 0)


@pytest.mark.parametrize("case_id", ["05_unclear_action", "16_invitation_feedback_other"])
def test_regression_a_predeclared_empty_alternative_is_no_missed_task(case_id):
    case = CASES[case_id]
    empty = case["accept"]["task_extraction"][0]
    assert empty["tasks"] == []
    scored = score_case(case, answer(case, task_extraction=empty))["task"]
    assert (scored["missed"], scored["false_positive"], scored["alternative"]) == (0, 0, 1)


def test_regression_checking_an_invoice_is_not_paying_it():
    case = CASES["K18_check_not_pay"]
    paid = copy.deepcopy(case["expected"]["task_extraction"])
    paid["tasks"][0]["title"] = "Rechnung der Druckerei Seidel bezahlen"
    scored = score_case(case, answer(case, task_extraction=paid))["task"]
    assert (scored["recognized"], scored["missed"], scored["false_positive"]) == (0, 1, 1)


def test_the_same_deadline_does_not_make_another_action_the_same():
    case = CASES["K07_documents_by_house_post"]
    other = copy.deepcopy(case["expected"]["task_extraction"])
    other["tasks"][0].update(title="Zum Kurs anmelden", evidence="bitte senden Sie die unterschriebene")
    scored = score_case(case, answer(case, task_extraction=other))["task"]
    assert (scored["recognized"], scored["missed"], scored["false_positive"]) == (0, 1, 1)


def test_regression_the_output_order_does_not_change_the_result():
    case = CASES["K19_two_tasks_sign_return"]
    tasks = copy.deepcopy(case["expected"]["task_extraction"])
    reverse = copy.deepcopy(tasks)
    reverse["tasks"].reverse()
    first = score_case(case, answer(case, task_extraction=tasks))["task"]
    second = score_case(case, answer(case, task_extraction=reverse))["task"]
    assert first["recognized"] == second["recognized"] == 2 and first["field_errors"] == second["field_errors"] == 0


def test_regression_another_person_with_the_same_title_is_a_wrong_fact():
    case = CASES["K06_roster_own_and_other"]
    other = copy.deepcopy(case["expected"]["event_extraction"])
    other["events"][0].update(evidence="15:00-16:30 Uhr: Fr. Kranz, Foyer", time_text="15:00", end_time_text="16:30")
    scored = score_case(case, answer(case, event_extraction=other))["event"]
    assert scored["recognized"] == 1 and scored["field_errors"] == 1 and scored["fields"][0]["when"] is False


@pytest.mark.parametrize(("field", "value", "check"), [
    ("end_time_text", "18:30", "when"), ("certainty", "uncertain", "certainty"),
    ("responsibility", "other", "responsibility"), ("location", "Aula", "location"),
    ("evidence", "Hr. Muster kommt nicht", "evidence")])
def test_regression_a_wrong_fact_of_a_recognized_action_blocks_the_gate(field, value, check):
    answers = perfect()
    wrong = answers["K06_roster_own_and_other"]["result"]["event_extraction"]["events"][0]
    wrong[field] = value
    result = report(CORPUS, answers, "model")
    case = next(item for item in result["cases"] if item["id"] == "K06_roster_own_and_other")
    assert case["event"]["fields"][0][check] is False
    assert "event: 1 falsche oder fehlende Fakten erkannter Aktionen" in gate(result, BASELINE)


def test_regression_duplicated_actions_of_a_series_need_a_review():
    case = CASES["30_council_series"]
    events = copy.deepcopy(case["expected"]["event_extraction"])
    events["events"][1] = copy.deepcopy(events["events"][0])  # the first meeting twice, the second one missing
    scored = score_case(case, answer(case, event_extraction=events))["event"]
    assert scored["recognized"] + scored["review"] == len(events["events"])
    assert scored["field_errors"] >= 1 or scored["review"] >= 1


def test_regression_a_relevance_stop_loses_the_actions_end_to_end():
    answers = perfect()
    answers["37_change_new_room"]["result"]["relevance"] = {"decision": "irrelevant", "topic_ids": [],
                                                           "reason": "Allgemeiner Veranstaltungshinweis."}
    result = report(CORPUS, answers, "model")
    assert result["totals"]["event"]["end_to_end_lost"] == 1
    assert "event: 1 Aktionen gehen im Relevanzfilter verloren" in gate(result, BASELINE)


def test_perfect_answers_pass_and_old_contracts_or_missing_relevance_do_not():
    good = report(CORPUS, perfect(), "model")
    assert gate(good, BASELINE) == [] and gate(good, BASELINE, before=good) == []
    assert good["contract_version"] == 5 and good["totals"]["task"]["review"] == 0
    old = {**good, "contract_version": 4}
    assert gate(old, BASELINE) == ["Nur Berichte nach Bewertungsvertrag 5 sind mit dieser Baseline vergleichbar."]
    answers = perfect()
    del answers["01_no_action"]["result"]["relevance"]
    assert "Antworten ohne Relevanzstufe: Ende-zu-Ende nicht prüfbar" in gate(report(CORPUS, answers, "model"), BASELINE)


def test_an_ambiguous_pair_is_reviewed_not_recognized():
    from mailhelp.llm.action_matching import match
    expected = [{"title": "Aufsicht", "evidence": "Aufsicht Foyer", "aliases": []},
                {"title": "Aufsicht", "evidence": "Aufsicht Foyer", "aliases": []}]
    actual = [{"title": "Aufsicht", "evidence": "Aufsicht Foyer"}, {"title": "Aufsicht", "evidence": "Aufsicht Foyer"}]
    pairs, ambiguous = match(expected, actual, "Aufsicht Foyer")
    assert len(pairs) == 2 and ambiguous == {0, 1}
