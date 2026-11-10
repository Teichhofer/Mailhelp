"""5.1 (R7): detection quality measured separately for tasks and events.

Expected results come from the synthetic corpus; actual results come either from
recorded synthetic answers or from a real model run. Recorded answers prove that
the comparison is reproducible and that known failure cases are counted; they never
prove the quality of a model or prompt. Technical failures and unreadable answers
are counted on their own and never dropped from the totals.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from ..domain.extraction import EventExtraction, TaskExtraction

Source = Literal["recorded", "model"]
KINDS = {"task": ("task_extraction", "tasks"), "event": ("event_extraction", "events")}
# Field checks of a recognized action; "assignment" is the classification (new, change, …).
FIELDS = {"task": ("due", "responsibility", "evidence", "assignment"),
          "event": ("date", "time", "responsibility", "evidence", "assignment")}
STATEMENT = {
    "recorded": "Aufgezeichnete synthetische Antworten: belegt den reproduzierbaren Vergleich und "
                "zählt bekannte Fehlerfälle; die Modellqualität ist damit nicht nachgewiesen.",
    "model": "Tatsächliche Modellausgaben auf dem eingefrorenen synthetischen Korpus.",
}


def _day(text: str | None) -> str | None:
    """A date written as 17.11.2026 or 2026-11-17, as ISO day; anything else stays as it is."""
    if text is None:
        return None
    if found := re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", text):
        return f"{found[3]}-{int(found[2]):02d}-{int(found[1]):02d}"
    if found := re.search(r"(\d{4})-(\d{2})-(\d{2})", text):
        return found[0]
    return text.strip().casefold()


def _clock(text: str | None) -> str | None:
    if text is None:
        return None
    found = re.search(r"(\d{1,2})[:.](\d{2})", text)
    return f"{int(found[1]):02d}:{found[2]}" if found else text.strip().casefold()


def _words(title: str) -> set[str]:
    return set(re.findall(r"\w{3,}", title.casefold()))


def _similar(left: dict[str, Any], right: dict[str, Any]) -> bool:
    a, b = _words(left["title"]), _words(right["title"])
    return bool(a & b) and len(a & b) / len(a | b) >= 0.5


def _fields(kind: str, expected: dict[str, Any], actual: dict[str, Any]) -> dict[str, bool]:
    checks = {"responsibility": expected["responsibility"] == actual["responsibility"],
              "evidence": bool(actual["evidence"].strip()),
              "assignment": expected["classification"] == actual["classification"]}
    if kind == "task":
        checks["due"] = _day(expected.get("due_text")) == _day(actual.get("due_text"))
    else:
        checks["date"] = _day(expected.get("date_text")) == _day(actual.get("date_text"))
        checks["time"] = _clock(expected.get("time_text")) == _clock(actual.get("time_text"))
    return checks


def _actions(kind: str, result: dict[str, Any]) -> list[dict[str, Any]]:
    stage, key = KINDS[kind]
    model = TaskExtraction if kind == "task" else EventExtraction
    return [item.model_dump(mode="json") for item in getattr(model.model_validate(result[stage]), key)]


def score_case(case: dict[str, Any], answer: dict[str, Any] | None) -> dict[str, Any]:
    """One case: recognized, missed and false actions per kind with field checks."""
    if answer is None or "error" in answer:
        return {"id": case["id"], "outcome": "technical_failure",
                "error": (answer or {}).get("error", "missing_answer")}
    try:
        actual = {kind: _actions(kind, answer["result"]) for kind in KINDS}
    except (KeyError, TypeError, ValidationError):
        return {"id": case["id"], "outcome": "unreadable"}
    scored: dict[str, Any] = {"id": case["id"], "outcome": "scored"}
    for kind in KINDS:
        expected, remaining = _actions(kind, case["expected"]), list(actual[kind])
        pairs = []
        for item in expected:
            match = next((other for other in remaining if _similar(item, other)), None)
            if match is not None:
                remaining.remove(match)
                pairs.append(_fields(kind, item, match))
        scored[kind] = {"recognized": len(pairs), "missed": len(expected) - len(pairs),
                        "false_positive": len(remaining), "fields": pairs}
    return scored


def report(corpus: dict[str, Any], answers: dict[str, Any], source: Source) -> dict[str, Any]:
    """The quality report of *answers* against the corpus; nothing is left out."""
    cases = [score_case(case, answers.get(case["id"])) for case in corpus["cases"]]
    totals: dict[str, Any] = {}
    for kind in KINDS:
        scored = [case[kind] for case in cases if case["outcome"] == "scored"]
        fields = {name: {"correct": sum(pair[name] for item in scored for pair in item["fields"]),
                         "checked": sum(len(item["fields"]) for item in scored)} for name in FIELDS[kind]}
        totals[kind] = {name: sum(item[name] for item in scored)
                        for name in ("recognized", "missed", "false_positive")} | {"fields": fields}
    return {
        "schema_version": 1, "created_at": datetime.now(UTC).isoformat(), "source": source,
        "model_quality_proven": source == "model", "statement": STATEMENT[source],
        "corpus_schema_version": corpus.get("schema_version"), "cases_total": len(cases),
        "technical_failures": sum(case["outcome"] == "technical_failure" for case in cases),
        "unreadable": sum(case["outcome"] == "unreadable" for case in cases),
        "totals": totals, "cases": cases,
    }


def _actions_of(case: dict[str, Any]) -> int:
    return sum(case[kind]["recognized"] + case[kind]["false_positive"] for kind in KINDS)


def gate(after: dict[str, Any], baseline: dict[str, Any], before: dict[str, Any] | None = None) -> list[str]:
    """Reasons a model change fails the frozen baseline (5.1.7); an empty list means it passes.

    Only reports of real model outputs can pass; recorded answers never prove a change.
    With *before*, the change must not add missed or false actions of either kind.
    """
    reasons = []
    if not after["model_quality_proven"] or (before is not None and not before["model_quality_proven"]):
        return ["Nur tatsächliche Modellausgaben (--source model) können eine Änderung belegen."]
    limits = baseline["thresholds"]
    for kind in KINDS:
        totals, limit = after["totals"][kind], limits[kind]
        expected = totals["recognized"] + totals["missed"]
        if expected and totals["recognized"] / expected < limit["min_recall"]:
            reasons.append(f"{kind}: Erkennungsrate unter {limit['min_recall']:.0%}")
        if totals["false_positive"] > limit["max_false_positive"]:
            reasons.append(f"{kind}: mehr als {limit['max_false_positive']} Fehlalarme")
        if before is not None:
            for name in ("missed", "false_positive"):
                if totals[name] > before["totals"][kind][name]:
                    reasons.append(f"{kind}: mehr {name} als vor der Änderung")
    if after["technical_failures"] > limits["max_technical_failures"]:
        reasons.append("Technische Ausfälle über der Schwelle")
    if after["unreadable"] > limits["max_unreadable"]:
        reasons.append("Unlesbare Antworten über der Schwelle")
    cases = {case["id"]: case for case in after["cases"]}
    for case_id in limits["critical_no_action_cases"]:
        case = cases.get(case_id)
        if case is None or case["outcome"] != "scored" or _actions_of(case):
            reasons.append(f"Sicherheitsfall {case_id} ohne sicheres Ergebnis")
    return reasons


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Erkennungsqualität getrennt nach Aufgaben und Terminen.")
    parser.add_argument("corpus", type=Path)
    parser.add_argument("answers", type=Path,
                        help="JSON: Fall-ID → {result: …} oder {error: …}, auch unter dem Schlüssel answers")
    parser.add_argument("output", type=Path)
    parser.add_argument("--source", choices=["recorded", "model"], default="recorded")
    parser.add_argument("--baseline", type=Path, help="eingefrorene Baseline; Abbruch mit 1 bei Verstoß")
    parser.add_argument("--before", type=Path, help="Bericht des unveränderten Stands für den Vergleich")
    arguments = parser.parse_args(argv)
    corpus = json.loads(arguments.corpus.read_text(encoding="utf-8"))
    answers = json.loads(arguments.answers.read_text(encoding="utf-8"))
    # A recorded file documents its answers next to a description.
    answers = answers.get("answers", answers)
    result = report(corpus, answers, arguments.source)
    arguments.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(result["statement"])
    if arguments.baseline is None:
        return 0
    baseline = json.loads(arguments.baseline.read_text(encoding="utf-8"))
    before = json.loads(arguments.before.read_text(encoding="utf-8")) if arguments.before else None
    reasons = gate(result, baseline, before)
    for reason in reasons:
        print("Nicht freigegeben:", reason)
    return 1 if reasons else 0

