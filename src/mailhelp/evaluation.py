"""Explicitly opted-in, bounded model evaluation; never connected to write adapters."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import yaml

from .action_normalization import (DEADLINE_DATE_PATTERN, MailDateContext, deadline_core,
                                   normalize_event,
                                   normalize_task_due, recover_task_due)
from .analysis import Analyzer
from .config import PromptConfig, Topic
from .mime import prepare
from .models import EventExtraction, TaskExtraction
from .openrouter import OpenRouterClient

_STAGES = ("relevance", "summary", "action_router", "task_extraction", "event_extraction")
_EXPECTED_KEY = {"action_router": "action_route"}


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


class UsageRecorder:
    """Collect provider-reported token usage and cost; no content is retained."""

    def __init__(self) -> None:
        self.prompt_tokens = self.completion_tokens = self.total_tokens = 0
        self.cost = 0.0
        self.responses_without_usage = 0

    def event(self, level: str, module: str, event: str, **context: Any) -> None:
        return None

    def llm_event(self, event: str, request: Any = None, response: Any = None,
                  **context: Any) -> None:
        if event == "token_usage_recorded":
            usage = context.get("token_usage")
            if not isinstance(usage, dict):
                self.responses_without_usage += 1
                return
            for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
                value = usage.get(field)
                if type(value) is int:
                    setattr(self, field, getattr(self, field) + value)
        elif event == "response_received":
            cost = context.get("reported_cost")
            if type(cost) in (int, float):
                self.cost += cost

    def report(self) -> dict[str, Any]:
        return {"prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "total_tokens": self.total_tokens,
                "reported_cost": round(self.cost, 6),
                "responses_without_usage": self.responses_without_usage}


def _text(value: str | None) -> str | None:
    """Compare free text independent of case and whitespace."""
    return " ".join(value.split()).casefold() if value is not None else None


_DATE_TOKEN = re.compile(rf"(?i)(?<![\d.])({DEADLINE_DATE_PATTERN})(?![\d.-]?\d)")
WITHOUT_DATE = "<ohne Datum>"


def _deadline_keys(value: str, context: MailDateContext) -> set[str]:
    """Reduce a summary deadline or appointment to the calendar dates it names.

    Free wording ("24.09.2026, 09:00–10:00 Uhr", "bis 24.09.2026") is not
    compared; an entry without a supported date only counts as such.
    """
    keys = set()
    for token in _DATE_TOKEN.findall(value):
        task = TaskExtraction.model_validate({"tasks": [{
            "title": "Frist", "description": "", "evidence": token, "responsibility": "user",
            "certainty": "certain", "classification": "new", "due_text": token}]}).tasks[0]
        result = normalize_task_due(task, context)
        keys.add(result.value.isoformat() if result.resolved else _text(token))
    return keys or {WITHOUT_DATE}


def _sorted(items: list[dict]) -> list[dict]:
    return sorted(items, key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=False))


def semantic_result(stage: str, value: dict, context: MailDateContext) -> dict:
    """Compare independent factual expectations, not incidental wording.

    Dates are compared after the same deterministic normalization the
    application uses, so "bis 01.10.2026" and "01.10.2026" are equal.
    """
    if stage == "relevance":
        return {"decision": value["decision"], "topic_ids": sorted(value["topic_ids"])}
    if stage == "summary":
        return {"deadlines": sorted(set().union(*(_deadline_keys(item, context)
                                                for item in value["deadlines"]))),
                "valid_sentence_count": 1 <= len(value["sentences"]) <= 2}
    if stage == "action_router":
        return {key: value[key] for key in ("action_state", "task_count", "event_count")}
    if stage == "task_extraction":
        result = []
        for task in TaskExtraction.model_validate(value).tasks:
            task = recover_task_due(task)
            due = None
            if task.due_text is not None:
                normalized = normalize_task_due(task, context)
                due = (normalized.value.isoformat() if normalized.resolved
                       else _text(deadline_core(task.due_text)))
            result.append({"classification": task.classification,
                           "responsibility": task.responsibility,
                           "certainty": task.certainty, "due": due})
        return {"tasks": _sorted(result)}
    result = []
    for event in EventExtraction.model_validate(value).events:
        normalized = normalize_event(event, context)
        if normalized.resolved:
            when = {"start": normalized.value.start.isoformat(),
                    "end": normalized.value.end.isoformat(),
                    "all_day": normalized.value.all_day}
        else:
            when = {"date": _text(event.date_text), "time": _text(event.time_text),
                    "end_time": _text(event.end_time_text)}
        result.append({"classification": event.classification,
                       "responsibility": event.responsibility, "certainty": event.certainty,
                       "time_requirement": event.time_requirement, "when": when,
                       "timezone_offset_text": event.timezone_offset_text,
                       "has_location": event.location is not None,
                       "video_link": event.video_link})
    return {"events": _sorted(result)}


def _received_at(case: dict) -> datetime | None:
    value = case.get("received_at")
    return datetime.fromisoformat(value) if value else None


def _context(mail: dict) -> MailDateContext:
    """The same mail date context the orchestrator passes to the builder."""
    return MailDateContext(
        date_context_status=str(mail.get("date_context_status", "missing")),
        date_header_parsed=mail.get("date_header_parsed"),
        imap_received_at=mail.get("imap_received_at"),
        user_timezone=mail.get("user_timezone"),
    )


def evaluate(corpus: dict, prompts: PromptConfig, client: object, max_calls: int,
             progress: Callable[[dict], None] | None = None) -> dict:
    bounded = BoundedCompleter(client, max_calls)
    analyzer = Analyzer(bounded, prompts, validation_retries=0, provider_retries=0)
    topics = [Topic.model_validate(item) for item in corpus["topics"]]
    timezone_name = corpus.get("user_timezone", "UTC")
    results = []
    report = {
        "schema_version": 2, "created_at": datetime.now(timezone.utc).isoformat(),
        "prompt_fingerprint": hashlib.sha256(prompts.model_dump_json().encode()).hexdigest(),
        "corpus_fingerprint": hashlib.sha256(json.dumps(corpus, sort_keys=True).encode()).hexdigest(),
        "corpus_schema_version": corpus.get("schema_version"),
        "routes": {stage: [route.model_dump(mode="json") for route in prompts.resolved_routes(stage)[0]]
                   for stage in _STAGES},
        "max_calls": max_calls, "calls": 0, "cases_total": len(corpus["cases"]),
        "complete": False, "passed": False, "cases": results,
        "manual_review": "Zusammenfassung, Titel, Beschreibung und Evidenz benötigen zusätzlich fachliche Prüfung.",
    }
    # Stage-separated evaluation also checks action extraction for irrelevant cases.
    # No expected answer is ever supplied to the provider.
    for case in corpus["cases"]:
        mail = prepare(case["raw_email"].encode("utf-8"), 100_000,
                       received_at=_received_at(case), user_timezone=timezone_name)
        context = _context(mail)
        observed = {}
        error = None
        try:
            observed["relevance"] = analyzer.relevance(mail, topics)[1].model_dump(mode="json")
            observed["summary"] = analyzer.summary(mail)[1].model_dump(mode="json")
            route = analyzer.action_route(mail)[1]
            observed["action_router"] = route.model_dump(mode="json")
            observed["task_extraction"] = {"tasks": []}
            observed["event_extraction"] = {"events": []}
            # The route model guarantees task/event states carry a positive
            # count, so this is the orchestrator's extraction rule.
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
            key = _EXPECTED_KEY.get(stage, stage)
            accepted = [semantic_result(stage, item, context)
                        for item in [case["expected"][key], *case.get("accept", {}).get(key, [])]]
            actual = semantic_result(stage, actual, context)
            comparisons[stage] = {"passed": actual in accepted, "expected": accepted[0],
                                  "accepted_alternatives": accepted[1:], "actual": actual}
        result = {"id": case["id"], "error": error, "stages": comparisons,
                  "review_outputs": observed,
                  "passed": error is None and all(item["passed"] for item in comparisons.values())}
        results.append(result)
        report["calls"] = bounded.calls
        if progress is not None:
            progress(report)
        if bounded.calls >= max_calls:
            break
    report["complete"] = len(results) == len(corpus["cases"])
    report["passed"] = report["complete"] and all(item["passed"] for item in results)
    report["stage_pass_counts"] = {
        stage: sum(item["stages"].get(stage, {}).get("passed", False) for item in results)
        for stage in _STAGES}
    return report


def write_report(path: Path, report: dict) -> None:
    """Replace the report atomically so an interrupted run leaves valid JSON."""
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        os.replace(temporary, path)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise


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
    # Fail before the first paid call if the report cannot be written.
    write_report(args.output, {"schema_version": 2, "complete": False, "cases": []})
    usage = UsageRecorder()
    client = OpenRouterClient(os.environ["OPENROUTER_API_KEY"], 60, 0, 600, logger=usage)
    total = len(corpus["cases"])

    def progress(report: dict) -> None:
        latest = report["cases"][-1]
        report["usage"] = usage.report()
        write_report(args.output, report)
        state = "bestanden" if latest["passed"] else "abweichend"
        print(f"[{len(report['cases'])}/{total}] {latest['id']}: {state} "
              f"(Aufrufe {report['calls']}/{report['max_calls']})", file=sys.stderr, flush=True)

    try:
        report = evaluate(corpus, prompts, client, args.max_calls, progress)
        report["usage"] = usage.report()
        write_report(args.output, report)
        return 0 if report["passed"] else 1
    finally:
        client.close()
