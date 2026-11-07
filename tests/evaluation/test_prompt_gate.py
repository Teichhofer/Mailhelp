"""Planung 4.1, Schritt 9.12: deterministic evaluation gate for prompts.yaml and topics.yaml.

The corpus runs through the real evaluation path (``evaluate``, the core of
``mailhelp-evaluate``) with the repository's prompts and topics; only the model answers
are simulated. A change that makes an expected answer impossible fails here at once: a
missing or renamed stage, an unresolvable route, or a corpus topic that topics.yaml no
longer offers. Whether a new prompt wording makes real models better or worse still needs
``mailhelp-evaluate`` against a real provider; this gate is free and runs on every commit.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from devtools.prompt_guard import verify_baseline
from mailhelp.config import PromptConfig, Topic
from mailhelp.llm.evaluation import _STAGES, evaluate
from tests.fakes.prompt_gate_fakes import gated_corpus, repository_prompts, repository_topic_gaps, repository_topics
from tests.fakes.shared_quality_corpus import ExpectedAnswers

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "tests" / "fixtures" / "mail_corpus_v3" / "corpus.json"










def test_the_repository_prompts_and_topics_carry_every_expected_answer():
    verify_baseline(ROOT)
    topics = repository_topics()
    corpus = gated_corpus(topics)
    assert repository_topic_gaps(corpus, topics) == []
    provider = ExpectedAnswers(corpus)
    report = evaluate(corpus, repository_prompts(), provider, 10 * len(corpus["cases"]) * len(_STAGES))
    failed = [case["id"] for case in report["cases"] if not case["passed"]]
    assert failed == [] and report["complete"], failed
    assert report["stage_pass_counts"] == {stage: len(corpus["cases"]) for stage in _STAGES}
    assert provider.models and all(models for models in report["routes"].values())


def test_the_gate_fails_when_a_corpus_topic_disappears_from_topics_yaml():
    topics = repository_topics()
    corpus = gated_corpus(topics)
    removed = {key: value for key, value in topics.items() if key != "camping-und-stellplatzbuchungen"}
    disabled = {**topics, "jimdo-anfragen-und-nachrichten":
                topics["jimdo-anfragen-und-nachrichten"].model_copy(update={"enabled": False})}
    assert repository_topic_gaps(corpus, removed) == ["camping-und-stellplatzbuchungen"]
    assert repository_topic_gaps(corpus, disabled) == ["jimdo-anfragen-und-nachrichten"]


def test_the_gate_fails_when_an_evaluated_stage_is_missing_from_prompts_yaml():
    prompts = repository_prompts()
    broken = prompts.model_copy(update={"prompts": {key: value for key, value in prompts.prompts.items()
                                                    if key != "event_extraction"}})
    corpus = gated_corpus(repository_topics())
    provider = ExpectedAnswers(corpus)
    with pytest.raises(KeyError, match="event_extraction"):
        evaluate(corpus, broken, provider, 1000)
    assert provider.models == set()  # refused before the first (paid) model call
