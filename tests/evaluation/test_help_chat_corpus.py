"""5.3 Planung 14: deterministic checks of the help chat corpus (context choice and source contract).

These checks use no model. They prove which documentation a question receives and that a
manipulated model answer cannot cite foreign sources; the quality of real model answers is a
separate, approved evaluation and is not claimed here.
"""
import json
from pathlib import Path

import pytest

from mailhelp.helpdocs import answer_validator, load

CORPUS = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "help_chat_corpus.json")
                    .read_text(encoding="utf-8"))["cases"]
BASE = load()


def test_the_corpus_has_the_planned_size_and_groups():
    groups = [case["group"] for case in CORPUS]
    assert len(CORPUS) >= 40 and groups.count("einstellung") >= 10 and groups.count("einrichtung") >= 10
    assert groups.count("fehler") >= 10 and groups.count("ohne_quelle") + groups.count("manipulation") >= 10
    known = {section.id for section in BASE.sections}
    assert all(set(case.get("sources", [])) <= known for case in CORPUS)


@pytest.mark.parametrize("case", [case for case in CORPUS if "sources" in case], ids=lambda case: case["question"])
def test_a_factual_question_receives_a_fitting_section(case):
    chosen = [section.id for section in BASE.select(case["question"])]  # all of them reach the model
    assert set(case["sources"]) & set(chosen), chosen


@pytest.mark.parametrize("case", [case for case in CORPUS if case.get("none")], ids=lambda case: case["question"])
def test_no_section_is_claimed_without_a_fitting_one(case):
    assert BASE.select(case["question"]) == []


@pytest.mark.parametrize("case", [case for case in CORPUS if case.get("manipulation")],
                         ids=lambda case: case["question"])
def test_a_manipulated_answer_cannot_cite_foreign_sources_or_settings(case):
    chosen = BASE.select(case["question"])
    assert len(chosen) <= 6 and all(section.source.startswith("docs/") for section in chosen)
    validate = answer_validator([section.id for section in chosen], [])
    for forged in ({"answer": "Erledigt.", "source_ids": ["../../.env"]},
                   {"answer": "Umgestellt.", "setting_ids": ["setting:poll_interval_seconds"]}):
        with pytest.raises(ValueError):
            validate(forged)
