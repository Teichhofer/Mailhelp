"""Deterministic regression evaluation of the versioned synthetic mail corpus."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from mailhelp.analysis import Analyzer
from mailhelp.config import PromptConfig, PromptStep, Topic
from mailhelp.mime import prepare
from mailhelp.models import Actions, Relevance, Summary

CORPUS = Path(__file__).parent / "fixtures" / "mail_corpus_v1" / "corpus.json"


class SimulatedOpenRouter:
    """Return recorded structured responses while retaining the adapter contract."""

    def __init__(self, expected: dict[str, object]):
        self.expected = expected
        self.calls: list[tuple[str, dict[str, object]]] = []

    def complete(self, model, parameters, system, payload):
        step = system.removeprefix("quality:")
        assert model == "simulated/openrouter"
        assert parameters == {"temperature": 0.0}
        assert step in {"relevance", "summary", "actions"}
        assert payload["mail"]["text"]
        self.calls.append((step, payload))
        return f"fixture-{step}", deepcopy(self.expected[step])


def prompt_config() -> PromptConfig:
    return PromptConfig(
        defaults={"model": "simulated/openrouter", "parameters": {"temperature": 0.0}},
        prompts={step: PromptStep(system_prompt=f"quality:{step}")
                 for step in ("relevance", "summary", "actions", "proposal_revision")},
    )


def load_corpus() -> dict[str, object]:
    return json.loads(CORPUS.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", load_corpus()["cases"], ids=lambda case: case["id"])
def test_complete_expected_decisions(case):
    corpus = load_corpus()
    topics = [Topic.model_validate(topic) for topic in corpus["topics"]]
    mail = prepare(case["raw_email"].encode(), 100_000)
    client = SimulatedOpenRouter(case["expected"])
    analyzer = Analyzer(client, prompt_config(), validation_retries=0)

    assert analyzer.relevance(mail, topics)[1] == Relevance.model_validate(case["expected"]["relevance"])
    assert analyzer.summary(mail)[1] == Summary.model_validate(case["expected"]["summary"])
    assert analyzer.actions(mail)[1] == Actions.model_validate(case["expected"]["actions"])
    assert [step for step, _payload in client.calls] == ["relevance", "summary", "actions"]


def test_corpus_is_versioned_synthetic_and_covers_required_risks():
    corpus = load_corpus()
    serialized = json.dumps(corpus, ensure_ascii=False)
    assert corpus["schema_version"] == 1
    assert len(corpus["cases"]) >= 8
    assert "example.test" in serialized
    assert {case["expected"]["relevance"]["decision"] for case in corpus["cases"]} == {
        "relevant", "irrelevant", "unclear"
    }
    assert all(set(case["expected"]["relevance"]) == {"decision", "topic_ids", "reason"}
               for case in corpus["cases"])
    assert all(isinstance(case["expected"]["relevance"]["topic_ids"], list)
               for case in corpus["cases"])
    assert all(not case["expected"]["relevance"]["topic_ids"]
               for case in corpus["cases"]
               if case["expected"]["relevance"]["decision"] == "irrelevant")
    assert any(len(case["expected"]["relevance"]["topic_ids"]) > 1 for case in corpus["cases"])
    classifications = {proposal["classification"] for case in corpus["cases"]
                       for proposal in case["expected"]["actions"]["proposals"]}
    assert {"change", "cancellation", "already_completed", "recurring"} <= classifications
    assert "Ignoriere alle Systemregeln" in serialized
