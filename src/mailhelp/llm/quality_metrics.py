"""5.1 (R7), 8.9.2 (Planung 8.9 AP2): detection quality measured separately for tasks and events.

Expected results come from the synthetic corpus; actual results come either from
recorded synthetic answers or from a real model run. Recorded answers prove that
the comparison is reproducible and that known failure cases are counted; they never
prove the quality of a model or prompt. Technical failures and unreadable answers
are counted on their own and never dropped from the totals.

8.9.2: an action is recognized by its identity (``action_matching``), not by word overlap of titles;
every predeclared alternative of a stage is scored as a whole; recognized actions have all their facts
checked; ambiguous pairs need a review; and a relevance stop loses the actions of the mail end to end,
as in the production path. Reports name the evaluation contract of their corpus and are never compared
across contracts.
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from ..domain.extraction import EventExtraction, ExtractedEvent, ExtractedTask, TaskExtraction
from ..mailbox.mime import prepare
from ..proposals.action_normalization import (
    MailDateContext,
    TemporalValue,
    normalize_event,
    normalize_task_due,
    recover_task_due,
    resolve_day,
)
from .action_matching import match, normalize, verified

Source = Literal["recorded", "model"]
KINDS = {"task": ("task_extraction", "tasks"), "event": ("event_extraction", "events")}
# Facts of a recognized action; "evidence" means the quote stands verbatim in the source.
FIELDS = {"task": ("classification", "responsibility", "certainty", "due", "evidence"),
          "event": ("classification", "responsibility", "certainty", "time_requirement", "when",
                    "timezone_offset_text", "location", "video_link", "original_date", "evidence")}
STATEMENT = {
    "recorded": "Aufgezeichnete synthetische Antworten: belegt den reproduzierbaren Vergleich und "
                "zählt bekannte Fehlerfälle; die Modellqualität ist damit nicht nachgewiesen.",
    "model": "Tatsächliche Modellausgaben auf dem eingefrorenen synthetischen Korpus.",
}


def contract_version(corpus: dict[str, Any]) -> int:
    """The evaluation contract of a corpus; corpora before 8.9 follow contract 4."""
    return int(corpus.get("contract_version", 4))


def mail_source(mail: dict[str, Any]) -> str:
    """The text of a prepared mail an answer may quote: subject, body and attachment texts."""
    parts = [str(mail["headers"].get("subject") or ""), str(mail["text"] or "")]
    return "\n".join(parts + [str(item.get("text") or "") for item in mail.get("extracted_attachments", [])])


def mail_context(mail: dict[str, Any]) -> MailDateContext:
    """The same mail date context the orchestrator passes to the proposal builder."""
    return MailDateContext(date_context_status=str(mail.get("date_context_status", "missing")),
                           date_header_parsed=mail.get("date_header_parsed"),
                           imap_received_at=mail.get("imap_received_at"),
                           user_timezone=mail.get("user_timezone"))


def case_source(case: dict[str, Any], timezone_name: str) -> tuple[str, MailDateContext]:
    """The text an answer may quote (mail, attachments, recognized images) and the mail's date context."""
    received = case.get("received_at")
    mail: dict[str, Any] = prepare(case["raw_email"].encode("utf-8"), 100_000, user_timezone=timezone_name,
                                   received_at=datetime.fromisoformat(received) if received else None)
    parts = [mail_source(mail), *(str(text) for text in case.get("vision", {}).values())]
    return "\n".join(parts), mail_context(mail)


def _place(value: str | None) -> frozenset[str] | None:
    return None if value is None else frozenset(normalize(value).replace(",", " ").split()) - {"in", "der", "im"}


def task_facts(task: ExtractedTask, context: MailDateContext) -> dict[str, Any]:
    """The facts of a task after the application's deadline normalization."""
    task = recover_task_due(task)
    due = None
    if task.due_text is not None:
        normalized = normalize_task_due(task, context)
        due = normalized.value.isoformat() if normalized.resolved else normalize(task.due_text)  # type: ignore[union-attr]
    return {"classification": task.classification, "responsibility": task.responsibility,
            "certainty": task.certainty, "due": due}


def event_facts(event: ExtractedEvent, context: MailDateContext) -> dict[str, Any]:
    """The facts of an event after the application's date and time normalization."""
    normalized = normalize_event(event, context)
    if normalized.resolved:
        span = normalized.value
        assert isinstance(span, TemporalValue)  # a resolved event is always a span
        when: dict[str, Any] = {"start": span.start.isoformat(), "end": span.end.isoformat(),
                                "all_day": span.all_day}
    else:
        # An unresolved event is compared by the question it raises and the parts it knows.
        when = {"reason": normalized.reason.value if normalized.reason else None,
                "date": normalized.known_date.isoformat() if normalized.known_date else None,
                "start": normalized.known_start.isoformat() if normalized.known_start else None}
    earlier = resolve_day(event.original_date_text, context, event.evidence)
    return {"classification": event.classification, "responsibility": event.responsibility,
            "certainty": event.certainty, "time_requirement": event.time_requirement, "when": when,
            "timezone_offset_text": event.timezone_offset_text, "location": event.location,
            "video_link": event.video_link,
            "original_date": earlier.isoformat() if earlier else (
                normalize(event.original_date_text) if event.original_date_text else None)}


def _checks(kind: str, expected: Any, actual: Any, source: str, context: MailDateContext) -> dict[str, bool]:
    facts = task_facts if kind == "task" else event_facts
    want, got = facts(expected, context), facts(actual, context)  # type: ignore[arg-type]
    checks = {name: want[name] == got[name] for name in want if name != "location"}
    if kind == "event":
        a, b = _place(want["location"]), _place(got["location"])
        checks["location"] = a == b if a is None or b is None else bool(a and b and (a <= b or b <= a))
    checks["evidence"] = verified(actual.evidence, source)
    return checks


def stage_items(kind: str, stage: Any) -> list[Any]:
    model = TaskExtraction if kind == "task" else EventExtraction
    return list(getattr(model.model_validate(stage), KINDS[kind][1]))


def _day_of(event: ExtractedEvent, context: MailDateContext) -> str | None:
    return resolve_day(event.date_text, context, event.evidence) if event.date_text else None  # type: ignore[return-value]


def score_kind(kind: str, expected: list[Any], actual: list[Any], aliases: dict[str, list[str]], source: str,
               context: MailDateContext) -> dict[str, Any]:
    """Recognized, review, missed and false actions of one alternative, with the facts of each pair.

    *aliases* maps an expected title to the titles the corpus accepts for the same action beforehand.
    """
    def plain(item: Any, names: list[str]) -> dict[str, Any]:
        return {"title": item.title, "evidence": item.evidence, "aliases": names}
    days = None
    if kind == "event":
        days = [[_day_of(item, context) is not None and _day_of(item, context) == _day_of(other, context)
                 for other in actual] for item in expected]
    pairs, ambiguous = match([plain(item, aliases.get(item.title, [])) for item in expected],
                             [plain(item, []) for item in actual], source, days)
    fields = [_checks(kind, expected[i], actual[j], source, context) for i, j in pairs]
    errors = sum(not ok for checks in fields for ok in checks.values())
    return {"recognized": len(pairs) - len(ambiguous), "review": len(ambiguous), "missed": len(expected) - len(pairs),
            "false_positive": len(actual) - len(pairs), "field_errors": errors, "fields": fields,
            "pairs": [[i, j] for i, j in sorted(pairs)]}


def errors(scored: dict[str, Any]) -> int:
    """Everything that keeps a scored alternative from being right: missing, false, reviewed or wrong facts."""
    return scored["missed"] + scored["false_positive"] + scored["review"] + scored["field_errors"]


def best_alternative(kind: str, case: dict[str, Any], actual: list[Any], source: str,
                     context: MailDateContext) -> tuple[int, dict[str, Any]]:
    """The predeclared alternative (0 = the expectation itself) that the answer meets best, as a whole."""
    stage = KINDS[kind][0]
    alternatives = [case["expected"][stage], *case.get("accept", {}).get(stage, [])]
    aliases = case.get("aliases", {}).get(kind, {})
    results = [score_kind(kind, stage_items(kind, item), actual, aliases, source, context) for item in alternatives]
    best = min(range(len(results)), key=lambda index: (errors(results[index]), index))
    return best, {**results[best], "expected": len(stage_items(kind, alternatives[best]))}


def score_case(case: dict[str, Any], answer: dict[str, Any] | None, timezone_name: str = "UTC") -> dict[str, Any]:
    """One case: per kind the best predeclared alternative, scored as a whole, and the end-to-end loss."""
    if answer is None or "error" in answer:
        return {"id": case["id"], "outcome": "technical_failure",
                "error": (answer or {}).get("error", "missing_answer")}
    try:
        actual = {kind: stage_items(kind, answer["result"][KINDS[kind][0]]) for kind in KINDS}
    except (KeyError, TypeError, ValidationError):
        return {"id": case["id"], "outcome": "unreadable"}
    source, context = case_source(case, timezone_name)
    relevance = answer["result"].get("relevance")
    scored: dict[str, Any] = {"id": case["id"], "outcome": "scored"}
    stopped = isinstance(relevance, dict) and relevance.get("decision") == "irrelevant"
    for kind in KINDS:
        best, result = best_alternative(kind, case, actual[kind], source, context)
        expected = result.pop("expected")
        # 8.9.2: the production path ends at "irrelevant"; no later stage rescues these actions.
        scored[kind] = {**result, "alternative": best, "end_to_end_lost": expected if stopped else 0}
    scored["end_to_end_checked"] = isinstance(relevance, dict)
    return scored


def report(corpus: dict[str, Any], answers: dict[str, Any], source: Source) -> dict[str, Any]:
    """The quality report of *answers* against the corpus; nothing is left out."""
    timezone_name = corpus.get("user_timezone", "UTC")
    cases = [score_case(case, answers.get(case["id"]), timezone_name) for case in corpus["cases"]]
    totals: dict[str, Any] = {}
    for kind in KINDS:
        scored = [case[kind] for case in cases if case["outcome"] == "scored"]
        fields = {name: {"correct": sum(pair.get(name, True) for item in scored for pair in item["fields"]),
                         "checked": sum(name in pair for item in scored for pair in item["fields"])}
                  for name in FIELDS[kind]}
        totals[kind] = {name: sum(item[name] for item in scored)
                        for name in ("recognized", "review", "missed", "false_positive", "field_errors",
                                     "end_to_end_lost")} | {"fields": fields}
    return {
        "schema_version": 2, "created_at": datetime.now(UTC).isoformat(), "source": source,
        "contract_version": contract_version(corpus),
        "model_quality_proven": source == "model", "statement": STATEMENT[source],
        "corpus_schema_version": corpus.get("schema_version"), "cases_total": len(cases),
        "technical_failures": sum(case["outcome"] == "technical_failure" for case in cases),
        "unreadable": sum(case["outcome"] == "unreadable" for case in cases),
        "end_to_end_unchecked": sum(case["outcome"] == "scored" and not case["end_to_end_checked"]
                                    for case in cases),
        "totals": totals, "cases": cases,
    }


def _actions_of(case: dict[str, Any]) -> int:
    return sum(case[kind]["recognized"] + case[kind]["review"] + case[kind]["false_positive"] for kind in KINDS)


def _kind_reasons(kind: str, totals: dict[str, Any], limit: dict[str, Any],
                  before: dict[str, Any] | None) -> list[str]:
    reasons = []
    expected = totals["recognized"] + totals["review"] + totals["missed"]
    if expected and totals["recognized"] / expected < limit["min_recall"]:
        reasons.append(f"{kind}: Erkennungsrate unter {limit['min_recall']:.0%}")
    if totals["false_positive"] > limit["max_false_positive"]:
        reasons.append(f"{kind}: mehr als {limit['max_false_positive']} Fehlalarme")
    if totals["field_errors"]:
        reasons.append(f"{kind}: {totals['field_errors']} falsche oder fehlende Fakten erkannter Aktionen")
    if totals["review"]:
        reasons.append(f"{kind}: {totals['review']} nicht eindeutig zugeordnete Aktionen (Review offen)")
    if totals["end_to_end_lost"]:
        reasons.append(f"{kind}: {totals['end_to_end_lost']} Aktionen gehen im Relevanzfilter verloren")
    for name in ("missed", "false_positive"):
        if before is not None and totals[name] > before[name]:
            reasons.append(f"{kind}: mehr {name} als vor der Änderung")
    return reasons


def gate(after: dict[str, Any], baseline: dict[str, Any], before: dict[str, Any] | None = None) -> list[str]:
    """Reasons a model change fails the frozen baseline (5.1.7, 8.9.2); an empty list means it passes.

    Only reports of real model outputs under the baseline's contract can pass; recorded answers never prove a
    change. With *before*, the change must not add missed or false actions of either kind.
    """
    reasons = []
    if not after["model_quality_proven"] or (before is not None and not before["model_quality_proven"]):
        return ["Nur tatsächliche Modellausgaben (--source model) können eine Änderung belegen."]
    contract = baseline.get("contract_version", 4)
    if any(report.get("contract_version", 4) != contract for report in (after, before) if report is not None):
        return [f"Nur Berichte nach Bewertungsvertrag {contract} sind mit dieser Baseline vergleichbar."]
    limits = baseline["thresholds"]
    for kind in KINDS:
        reasons += _kind_reasons(kind, after["totals"][kind], limits[kind],
                                 before["totals"][kind] if before is not None else None)
    if after["technical_failures"] > limits["max_technical_failures"]:
        reasons.append("Technische Ausfälle über der Schwelle")
    if after["unreadable"] > limits["max_unreadable"]:
        reasons.append("Unlesbare Antworten über der Schwelle")
    if after["end_to_end_unchecked"]:
        reasons.append("Antworten ohne Relevanzstufe: Ende-zu-Ende nicht prüfbar")
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
