"""Explicitly opted-in, bounded model evaluation; never connected to write adapters."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from datetime import datetime, timezone

import yaml

from .analysis import Analyzer
from .config import PromptConfig, Topic
from .mime import prepare
from .openrouter import OpenRouterClient


class EvaluationBudgetExceeded(RuntimeError):
    """No further paid call is authorized by this evaluation run."""


class BoundedCompleter:
    def __init__(self, client: object, max_calls: int):
        if max_calls < 1:
            raise ValueError("max_calls muss positiv sein")
        self.client, self.max_calls, self.calls = client, max_calls, 0

    def complete(self, model, parameters, system, payload, **metadata):
        if self.calls >= self.max_calls:
            raise EvaluationBudgetExceeded("Aufrufbudget ausgeschöpft")
        # Limits remain in prompts.yaml. Refuse an unbounded configuration.
        tokens = parameters.get("max_tokens")
        if type(tokens) is not int or not 1 <= tokens <= 16000:
            raise ValueError("Jede Evaluationsroute benötigt max_tokens zwischen 1 und 16000")
        self.calls += 1
        return self.client.complete(model, parameters, system, payload, **metadata)


def semantic_result(stage: str, value: dict) -> dict:
    """Compare independent factual expectations, not incidental wording."""
    if stage == "relevance":
        return {"decision": value["decision"], "topic_ids": sorted(value["topic_ids"])}
    if stage == "summary":
        return {"deadlines": value["deadlines"], "valid_sentence_count": 1 <= len(value["sentences"]) <= 2}
    if stage == "action_router":
        return {key: value[key] for key in ("action_state", "task_count", "event_count")}
    key = "tasks" if stage == "task_extraction" else "events"
    fields = ("classification", "responsibility", "certainty", "due_text") if key == "tasks" else (
        "classification", "responsibility", "certainty", "date_text", "time_text",
        "end_time_text", "time_requirement", "timezone_offset_text", "location", "video_link")
    return {key: [{field: item.get(field) for field in fields} for item in value[key]]}


def evaluate(corpus: dict, prompts: PromptConfig, client: object, max_calls: int) -> dict:
    bounded = BoundedCompleter(client, max_calls)
    analyzer = Analyzer(bounded, prompts, validation_retries=0, provider_retries=0)
    topics = [Topic.model_validate(item) for item in corpus["topics"]]
    results = []
    # Stage-separated evaluation also checks action extraction for irrelevant cases.
    # No expected answer is ever supplied to the provider.
    for case in corpus["cases"]:
        mail = prepare(case["raw_email"].encode("utf-8"), 100_000)
        observed = {}
        error = None
        try:
            observed["relevance"] = analyzer.relevance(mail, topics)[1].model_dump(mode="json")
            observed["summary"] = analyzer.summary(mail)[1].model_dump(mode="json")
            route = analyzer.action_route(mail)[1]
            observed["action_router"] = route.model_dump(mode="json")
            observed["task_extraction"] = {"tasks": []}
            observed["event_extraction"] = {"events": []}
            if route.task_count > 0:
                observed["task_extraction"] = analyzer.extract_tasks(
                    mail, expected_count=route.task_count)[1].model_dump(mode="json")
            if route.event_count > 0:
                observed["event_extraction"] = analyzer.extract_events(
                    mail, expected_count=route.event_count)[1].model_dump(mode="json")
        except Exception as exc:
            error = type(exc).__name__  # Provider messages may contain credentials.
        comparisons = {}
        for stage, actual in observed.items():
            expected_key = "action_route" if stage == "action_router" else stage
            expected = semantic_result(stage, case["expected"][expected_key])
            actual = semantic_result(stage, actual)
            comparisons[stage] = {"passed": actual == expected, "expected": expected, "actual": actual}
        results.append({"id": case["id"], "error": error, "stages": comparisons,
                        "review_outputs": observed,
                        "passed": error is None and all(item["passed"] for item in comparisons.values())})
        if bounded.calls >= max_calls:
            break
    complete = len(results) == len(corpus["cases"])
    return {
        "schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
        "prompt_fingerprint": hashlib.sha256(prompts.model_dump_json().encode()).hexdigest(),
        "corpus_fingerprint": hashlib.sha256(json.dumps(corpus, sort_keys=True).encode()).hexdigest(),
        "routes": {stage: [route.model_dump(mode="json") for route in prompts.resolved_routes(stage)[0]]
                   for stage in ("relevance", "summary", "action_router", "task_extraction", "event_extraction")},
        "max_calls": max_calls, "calls": bounded.calls, "complete": complete,
        "passed": complete and all(item["passed"] for item in results), "cases": results,
        "manual_review": "Zusammenfassung, Titel, Beschreibung und Evidenz benötigen zusätzlich fachliche Prüfung.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Explizite OpenRouter-Qualitätsprüfung mit synthetischem Korpus")
    parser.add_argument("--allow-network", action="store_true", required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--prompts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-calls", type=int, required=True)
    args = parser.parse_args(argv)
    if args.max_calls < 1 or not os.environ.get("OPENROUTER_API_KEY"):
        parser.error("Positives Aufrufbudget und OPENROUTER_API_KEY sind erforderlich")
    prompts = PromptConfig.model_validate(yaml.safe_load(args.prompts.read_text(encoding="utf-8")))
    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    client = OpenRouterClient(os.environ["OPENROUTER_API_KEY"], 60, 0, 600)
    try:
        report = evaluate(corpus, prompts, client, args.max_calls)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return 0 if report["passed"] else 1
    finally:
        client.close()
