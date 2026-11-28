"""8.9.1 (Planung 8.9 AP1): evaluation contract v5 and its frozen reference corpus.

The corpus is frozen before any model run: its checksum is part of the baseline, every changed expectation
of a v4 case names its rule and reason, and the new control cases are new mails. Synthetic data only.
"""
import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path

import pytest

from mailhelp.domain.extraction import ActionRoute, EventExtraction, Summary, TaskExtraction
from mailhelp.domain.relevance import Relevance
from mailhelp.mailbox.mime import prepare

ROOT = Path(__file__).resolve().parents[2]
V5_PATH = ROOT / "tests/fixtures/mail_corpus_v5/corpus.json"
V5 = json.loads(V5_PATH.read_text(encoding="utf-8"))
V4 = json.loads((ROOT / "tests/fixtures/mail_corpus_v4/corpus.json").read_text(encoding="utf-8"))
BASELINE = json.loads((ROOT / "quality-reports/baseline-8.9.json").read_text(encoding="utf-8"))
CASES = {case["id"]: case for case in V5["cases"]}
STAGES = {"relevance": Relevance, "summary": Summary, "action_route": ActionRoute,
          "task_extraction": TaskExtraction, "event_extraction": EventExtraction}
WEEKDAYS = ("montag", "dienstag", "mittwoch", "donnerstag", "freitag", "samstag", "sonntag")


def source(case):
    received = case.get("received_at")
    mail = prepare(case["raw_email"].encode("utf-8"), 100_000,
                   received_at=datetime.fromisoformat(received) if received else None, user_timezone="Europe/Berlin")
    parts = [mail["headers"].get("subject") or "", mail["text"],
             *(item.get("text") or "" for item in mail.get("extracted_attachments", [])), *case.get("vision", {}).values()]
    return " ".join(" ".join(parts).casefold().split())


def test_the_baseline_freezes_the_corpus_and_keeps_the_limits():
    assert hashlib.sha256(V5_PATH.read_text(encoding="utf-8").encode()).hexdigest() == BASELINE["corpus"]["sha256"]
    assert (BASELINE["contract_version"], V5["contract_version"], V5["schema_version"]) == (5, 5, 5)
    assert (BASELINE["corpus"]["cases"], BASELINE["corpus"]["control_cases"]) == (68, 22)
    # Never lowered compared with the 5.1 baseline; only new no-action cases are added.
    old = json.loads((ROOT / BASELINE["predecessor"]).read_text(encoding="utf-8"))["thresholds"]
    for name in ("task", "event", "max_technical_failures", "max_unreadable"):
        assert BASELINE["thresholds"][name] == old[name]
    assert set(old["critical_no_action_cases"]) < set(BASELINE["thresholds"]["critical_no_action_cases"])
    for case_id in BASELINE["thresholds"]["critical_no_action_cases"]:
        route = CASES[case_id]["expected"]["action_route"]
        assert (route["action_state"], route["task_count"], route["event_count"]) == ("none", 0, 0)
    assert BASELINE["model_quality_proven"] is False and BASELINE["prompt_baseline"] is None
    assert "ausdrückliche Freigabe" in BASELINE["method"]
    contract = (ROOT / BASELINE["contract"]).read_text(encoding="utf-8")
    for rule in ("Kalenderbehandlung", "Teilnahme", "Mehrere Themen", "Zusammenfassung", "Antwortbedarf",
                 "Ankunft und Belegung", "Ende-zu-Ende", "Review"):
        assert rule in contract


def test_every_expectation_is_valid_and_the_router_counts_match():
    assert len(CASES) == len(V5["cases"]) == 68
    for case in V5["cases"]:
        assert case["purpose"].strip() and "@example.test" in case["raw_email"]
        for stage, model in STAGES.items():
            for value in [case["expected"][stage], *case.get("accept", {}).get(stage, [])]:
                model.model_validate(value)
        route = case["expected"]["action_route"]
        assert (route["task_count"], route["event_count"]) == (len(case["expected"]["task_extraction"]["tasks"]),
                                                              len(case["expected"]["event_extraction"]["events"]))


def test_v4_cases_keep_their_mails_and_every_change_names_its_rule():
    for old in V4["cases"]:
        case = CASES[old["id"]]
        assert case["raw_email"] == old["raw_email"] and case["migration"]["from"] == "mail_corpus_v4"
        plain_topics = {"required": old["expected"]["relevance"]["topic_ids"], "any_of": [], "allowed": []}
        changed = (case["expected"] != old["expected"] or case.get("accept") != old.get("accept")
                   or case["topics"] != plain_topics or "aliases" in case)
        changes = case["migration"]["changes"]
        if changed:
            assert changes and all(item["change"] and item["reason"] for item in changes), old["id"]
            assert case["migration"]["rules"], old["id"]
        else:
            assert changes == [] and case["migration"]["reason"].startswith("Unverändert"), old["id"]
    # Rule 1: the calendar adjustment of a moved appointment is no second task (until 8.8 it was one).
    moved = CASES["20_quoted_old_task_after_reschedule"]["expected"]
    assert moved["task_extraction"]["tasks"] == [] and moved["action_route"]["action_state"] == "event"
    assert "Regel 1 Kalenderbehandlung" in CASES["20_quoted_old_task_after_reschedule"]["migration"]["rules"]


def test_control_cases_are_new_mails_with_other_names_and_dates():
    controls = [case for case in V5["cases"] if case.get("control")]
    assert len(controls) == 22 and all(case["id"].startswith("K") for case in controls)
    old_mails = {case["raw_email"] for case in V4["cases"]}
    old_subjects = {re.search(r"^Subject: (.*)$", mail, re.M)[1] for mail in old_mails}
    for case in controls:
        assert case["raw_email"] not in old_mails and case["migration"]["from"] is None
        assert re.search(r"^Subject: (.*)$", case["raw_email"], re.M)[1] not in old_subjects
        assert "2027" in case["raw_email"] and "2026" not in case["raw_email"]


def test_topic_contracts_name_known_topics_and_hold_for_the_expectation():
    known = {topic["id"] for topic in V5["topics"]}
    for case in V5["cases"]:
        contract, topics = case["topics"], set(case["expected"]["relevance"]["topic_ids"])
        named = {*contract["required"], *contract["any_of"], *contract["allowed"]}
        assert named <= known, case["id"]
        assert set(contract["required"]) <= topics <= named, case["id"]
        assert not contract["any_of"] or topics & set(contract["any_of"]), case["id"]
        if case["expected"]["relevance"]["decision"] == "irrelevant":
            assert topics == set() == set(contract["required"]), case["id"]


def test_aliases_name_expected_titles_and_every_evidence_stands_in_the_source():
    for case in V5["cases"]:
        titles = {kind: {item["title"] for item in case["expected"][stage][key]}
                  for kind, stage, key in (("task", "task_extraction", "tasks"), ("event", "event_extraction", "events"))}
        for kind, aliases in case.get("aliases", {}).items():
            assert set(aliases) <= titles[kind] and all(aliases.values()), case["id"]
        text = source(case)
        for stage, key in (("task_extraction", "tasks"), ("event_extraction", "events")):
            for value in [case["expected"][stage], *case.get("accept", {}).get(stage, [])]:
                for item in value[key]:
                    assert " ".join(item["evidence"].casefold().split()) in text, (case["id"], item["evidence"])
    assert sum(bool(case.get("diagnostic")) for case in V5["cases"]) == 9


@pytest.mark.parametrize(("case_id", "named", "day", "contradicts"), [
    ("K13_weekday_contradiction", "Montag", date(2027, 3, 3), True),
    ("K14_weekday_with_den_consistent", "Freitag", date(2027, 3, 5), False),
    ("K04_cancellation_own", "Donnerstag", date(2027, 3, 18), False),
    ("K20_quoted_old_weekday", "Donnerstag", date(2027, 2, 18), False)])
def test_the_weekdays_of_the_control_mails_are_as_their_purpose_says(case_id, named, day, contradicts):
    assert (WEEKDAYS[day.weekday()] != named.casefold()) is contradicts
    assert f"{named}, " in CASES[case_id]["raw_email"]
    if case_id == "K20_quoted_old_weekday":  # only the quoted older mail names the wrong weekday
        quoted = CASES[case_id]["raw_email"].split("--- Ursprüngliche Nachricht ---")[1]
        assert "Dienstag, 18.02.2027" in quoted and WEEKDAYS[day.weekday()] == "donnerstag"

