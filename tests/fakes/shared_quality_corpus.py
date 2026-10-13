"""Shared synthetic fixtures and doubles; no test-module dependencies."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from mailhelp.action_normalization import MailDateContext
from mailhelp.analysis import Analyzer
from mailhelp.config import PromptConfig, PromptStep, TargetSettings, Topic
from mailhelp.mime import prepare
from mailhelp.models import ActionRoute, EventExtraction, Relevance, Summary, TaskExtraction
from mailhelp.proposal_builder import ProposalBuilder

CORPUS = Path(__file__).parents[1] / "fixtures" / "mail_corpus_v1" / "corpus.json"

def load_corpus() -> dict[str, object]:
    return json.loads(CORPUS.read_text(encoding="utf-8"))

CASES = {case["id"]: case for case in load_corpus()["cases"]}

class SimulatedOpenRouter:
    """Return the fixture for exactly the requested pipeline stage."""

    def __init__(self, expected: dict[str, object]):
        self.expected = expected
        self.calls: list[str] = []

    def complete(self, model, parameters, system, payload, **_metadata):
        step = system.removeprefix("quality:")
        assert model == "simulated/openrouter"
        assert parameters == {"temperature": 0.0}
        assert step in {"relevance", "summary", "action_router", "task_extraction", "event_extraction"}
        assert payload["mail"]["text"]
        self.calls.append(step)
        fixture_key = {"action_router": "action_route"}.get(step, step)
        return f"fixture-{step}", deepcopy(self.expected[fixture_key])

def prompt_config() -> PromptConfig:
    names = ("relevance", "summary", "action_router", "task_extraction",
             "event_extraction", "mail_question_resolution", "telegram_answer_interpretation", "telegram_answer_clarification", "proposal_revision", "learning_classification", "learning_abstraction", "calendar_duplicate")
    return PromptConfig(
        defaults={"model": "simulated/openrouter", "parameters": {"temperature": 0.0}},
        prompts={name: PromptStep(system_prompt=f"quality:{name}") for name in names},
    )

def pipeline(case_id: str):
    corpus, case = load_corpus(), CASES[case_id]
    topics = [Topic.model_validate(topic) for topic in corpus["topics"]]
    mail = prepare(case["raw_email"].encode(), 100_000)
    client = SimulatedOpenRouter(case["expected"])
    analyzer = Analyzer(client, prompt_config(), validation_retries=0)

    assert analyzer.relevance(mail, topics)[1] == Relevance.model_validate(case["expected"]["relevance"])
    assert analyzer.summary(mail)[1] == Summary.model_validate(case["expected"]["summary"])
    route = analyzer.action_route(mail)[1]
    assert route == ActionRoute.model_validate(case["expected"]["action_route"])

    tasks, events = TaskExtraction(tasks=[]), EventExtraction(events=[])
    if route.action_state in {"task", "task_and_event"}:
        tasks = analyzer.extract_tasks(mail, expected_count=route.task_count)[1]
    if route.action_state in {"event", "task_and_event"}:
        events = analyzer.extract_events(mail, expected_count=route.event_count)[1]
    assert tasks == TaskExtraction.model_validate(case["expected"]["task_extraction"])
    assert events == EventExtraction.model_validate(case["expected"]["event_extraction"])

    context = MailDateContext(**corpus["date_context"])
    targets = TargetSettings.model_validate(corpus["targets"])
    proposals = ProposalBuilder(corpus["model_source_mail_id"], targets, context).build(
        tasks.tasks, events.events)
    serialized = [proposal.model_dump(mode="json") for proposal in proposals]
    normalization = [({"kind": item["kind"], "due": item["due"]}
                      if item["kind"] == "task" else
                      {key: item[key] for key in ("kind", "start", "end", "all_day")})
                     for item in serialized]
    builder = [{key: item[key] for key in ("kind", "classification", "responsibility",
                                           "status", "open_questions")} for item in serialized]
    assert normalization == case["expected"]["normalization"]
    assert builder == case["expected"]["builder"]
    return client.calls, tasks, events, proposals
