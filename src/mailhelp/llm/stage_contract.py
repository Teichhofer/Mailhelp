"""8.9.2 (Planung 8.9 AP2): stage comparisons of the evaluation contract v5 (docs/Bewertungsvertrag-v5.md).

Relevance follows the topic contract of a case (required, any of, allowed); a summary keeps every dated and
timed fact of the reference with its precision and adds only facts the source names; extractions are compared
by action identity and all facts through ``quality_metrics``, every predeclared alternative as a whole.
"""
from __future__ import annotations

import re
from typing import Any

from ..domain.extraction import TaskExtraction
from ..proposals.action_normalization import DEADLINE_DATE_PATTERN, MailDateContext, normalize_task_due
from .action_matching import normalize, same_word
from .quality_metrics import KINDS, best_alternative, errors, stage_items

_DATE = re.compile(rf"(?i)(?<![\d.])({DEADLINE_DATE_PATTERN})(?![\d.-]?\d)")
_DAY_MONTH = re.compile(r"(?<![\d.])(\d{1,2})\.(\d{1,2})\.(?!\d)")
_CLOCK = re.compile(r"(?i)(?<![\d.:])(\d{1,2})(?:[:.](\d{2})(?:\s*uhr)?|\s*uhr)(?![\d])")
_FILLERS = frozenset("bis und von vom um uhr ab am an zum zur im in nur noch spaetestens den der die das ca etwa "
                     "gegen jeweils sowie oder".split())


def topics_passed(contract: dict[str, Any], topic_ids: list[str]) -> bool:
    """Every required topic, at least one of *any_of*, and nothing outside the named topics (rule 3)."""
    actual, required, any_of = set(topic_ids), set(contract["required"]), set(contract["any_of"])
    return required <= actual <= required | any_of | set(contract["allowed"]) and (not any_of or bool(actual & any_of))


def _iso_day(token: str, context: MailDateContext) -> str:
    task = TaskExtraction.model_validate({"tasks": [{
        "title": "Frist", "description": "", "evidence": token, "responsibility": "user",
        "certainty": "certain", "classification": "new", "due_text": token}]}).tasks[0]
    result = normalize_task_due(task, context)
    return result.value.isoformat() if result.resolved else normalize(token)  # type: ignore[union-attr]


def deadline_parts(value: str, context: MailDateContext) -> set[str]:
    """Calendar days, clock times and the remaining wording of one summary entry (rule 4)."""
    parts = {f"day:{_iso_day(token, context)}" for token in _DATE.findall(value)}
    rest = _DATE.sub(" ", value)
    parts |= {f"day:--{int(month):02}-{int(day):02}" for day, month in _DAY_MONTH.findall(rest)}
    rest = _DAY_MONTH.sub(" ", rest)
    for hour, minute in _CLOCK.findall(rest):
        if int(hour) <= 23:
            parts.add(f"time:{int(hour):02}:{minute or '00'}")
    words = [word for word in re.findall(r"[a-z0-9]+", normalize(_CLOCK.sub(" ", rest))) if word not in _FILLERS]
    if words:
        parts.add("text:" + " ".join(words))
    return parts


def _source_parts(source: str, context: MailDateContext) -> tuple[set[str], list[str]]:
    days = {f"day:{_iso_day(token, context)}" for token in _DATE.findall(source)}
    days |= {"day:--" + day[9:] for day in days if day[4:5].isdigit()}  # a year-less entry of a dated day
    days |= {f"day:--{int(month):02}-{int(day):02}" for day, month in _DAY_MONTH.findall(source)}
    clocks = {f"time:{int(hour):02}:{minute or '00'}" for hour, minute in _CLOCK.findall(source) if int(hour) <= 23}
    return days | clocks, re.findall(r"[a-z0-9]+", normalize(source))  # every word, fillers included


def _covers(part: str, others: set[str]) -> bool:
    if not part.startswith("text:"):
        return part in others
    words = part[5:].split()
    return any(all(any(same_word(word, other) for other in candidate[5:].split()) for word in words)
               for candidate in others if candidate.startswith("text:"))


def _supported(part: str, facts: set[str], words: list[str]) -> bool:
    if part.startswith("text:"):
        return all(any(same_word(word, other) for other in words) for word in part[5:].split())
    return part in facts


def summary_passed(alternatives: list[dict[str, Any]], actual: dict[str, Any], source: str,
                   context: MailDateContext) -> tuple[bool, dict[str, Any]]:
    """Rule 4: no fact of the reference is lost or made less precise, and nothing is added without a source."""
    got = set().union(*(deadline_parts(item, context) for item in actual["deadlines"]))
    facts, words = _source_parts(source, context)
    unsupported = sorted(part for part in got if not _supported(part, facts, words))
    wanted = [set().union(*(deadline_parts(item, context) for item in alternative["deadlines"]))
              for alternative in alternatives]
    missing = [sorted(part for part in parts if not _covers(part, got)) for parts in wanted]
    sentences = 1 <= len(actual["sentences"]) <= 2
    passed = sentences and not unsupported and any(not item for item in missing)
    return passed, {"parts": sorted(got), "missing": min(missing, key=len), "unsupported": unsupported,
                    "valid_sentence_count": sentences}


def extraction_passed(kind: str, case: dict[str, Any], actual: dict[str, Any], source: str,
                      context: MailDateContext) -> tuple[bool, dict[str, Any]]:
    """Identity and facts of every action against the best predeclared alternative as a whole."""
    best, result = best_alternative(kind, case, stage_items(kind, actual), source, context)
    detail = {key: result[key] for key in ("recognized", "review", "missed", "false_positive", "field_errors")}
    return errors(result) == 0, {**detail, "alternative": best}


def compare_stages(case: dict[str, Any], observed: dict[str, Any], source: str,
                   context: MailDateContext) -> dict[str, dict[str, Any]]:
    """The v5 comparison of every observed stage except the action router (compared as before)."""
    comparisons: dict[str, dict[str, Any]] = {}
    if "relevance" in observed:
        actual = observed["relevance"]
        decisions = [item["decision"] for item in [case["expected"]["relevance"],
                                                   *case.get("accept", {}).get("relevance", [])]]
        comparisons["relevance"] = {
            "passed": actual["decision"] in decisions and topics_passed(case["topics"], actual["topic_ids"]),
            "expected": {"decisions": decisions, "topics": case["topics"]},
            "actual": {"decision": actual["decision"], "topic_ids": sorted(actual["topic_ids"])}}
    if "summary" in observed:
        alternatives = [case["expected"]["summary"], *case.get("accept", {}).get("summary", [])]
        passed, detail = summary_passed(alternatives, observed["summary"], source, context)
        comparisons["summary"] = {"passed": passed, "actual": detail}
    for kind, (stage, _key) in KINDS.items():
        if stage in observed:
            passed, detail = extraction_passed(kind, case, observed[stage], source, context)
            comparisons[stage] = {"passed": passed, "actual": detail}
    return comparisons


__all__ = ["compare_stages", "deadline_parts", "extraction_passed", "summary_passed", "topics_passed"]
