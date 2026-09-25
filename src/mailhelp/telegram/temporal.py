"""Conservative deterministic interpretation of temporal answers."""

from __future__ import annotations

from datetime import (
    date,
    date as calendar_date,
    datetime,
    time as clock_time,
    timedelta,
    timezone,
)
import re
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict

from ..analysis import ContradictoryRevision
from ..models import (
    Proposal,
    ProposalKind,
    ProposalRevisionDelta,
    TemporalFact,
    apply_proposal_revision,
)

__all__ = [
    "DeterministicTemporalAnswer",
    "deterministic_classification_revision",
    "deterministic_temporal_revision",
    "normalize_deterministic_temporal_answer",
    "parse_deterministic_temporal_answer",
]


class DeterministicTemporalAnswer(BaseModel):
    """Facts explicitly present in one narrowly supported Telegram answer."""

    model_config = ConfigDict(extra="forbid", strict=True)
    date: calendar_date | None = None
    start: clock_time | None = None
    end: clock_time | None = None


_DATE = r"(?:(?P<day>\d{1,2})\.(?P<month>\d{1,2})\.(?P<year>\d{4})|(?P<iso_year>\d{4})-(?P<iso_month>\d{2})-(?P<iso_day>\d{2}))"
_TIME = r"(?P<{name}_hour>\d{{1,2}})(?::(?P<{name}_minute>\d{{2}}))?\s*(?:Uhr)?"
_TEMPORAL_ANSWERS = (
    re.compile(
        rf"\s*{_DATE}\s*(?:(?:T|,|um)?\s*{_TIME.format(name='start')}(?:\s*(?:bis|[-–])\s*{_TIME.format(name='end')})?)?\s*",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\s*{_TIME.format(name='start')}\s*(?:bis|[-–])\s*{_TIME.format(name='end')}\s*",
        re.IGNORECASE,
    ),
    re.compile(rf"\s*{_TIME.format(name='start')}\s*", re.IGNORECASE),
)
_RELATIVE_TODAY = re.compile(
    rf"\s*heute\s*(?:(?:,|um)?\s*{_TIME.format(name='start')}(?:\s*(?:bis|[-–])\s*{_TIME.format(name='end')})?)?\s*",
    re.IGNORECASE,
)


def parse_deterministic_temporal_answer(
    answer: str, reference_date: calendar_date | None = None
) -> DeterministicTemporalAnswer | None:
    """Parse narrow date/time forms, resolving ``heute`` only with an explicit day."""
    relative = _RELATIVE_TODAY.fullmatch(answer)
    if relative is not None:
        if reference_date is None:
            return None
        values = relative.groupdict()

        def relative_time(name: str) -> clock_time | None:
            hour = values.get(f"{name}_hour")
            return (
                clock_time(int(hour), int(values.get(f"{name}_minute") or 0))
                if hour is not None
                else None
            )

        return DeterministicTemporalAnswer(
            date=reference_date, start=relative_time("start"), end=relative_time("end")
        )
    match = next(
        (
            pattern.fullmatch(answer)
            for pattern in _TEMPORAL_ANSWERS
            if pattern.fullmatch(answer) is not None
        ),
        None,
    )
    if match is None:
        return None
    values = match.groupdict()
    parsed_date = None
    if values.get("year"):
        parsed_date = date(
            int(values["year"]), int(values["month"]), int(values["day"])
        )
    elif values.get("iso_year"):
        parsed_date = date(
            int(values["iso_year"]), int(values["iso_month"]), int(values["iso_day"])
        )

    def parsed_time(name: str) -> clock_time | None:
        hour = values.get(f"{name}_hour")
        return (
            clock_time(int(hour), int(values.get(f"{name}_minute") or 0))
            if hour is not None
            else None
        )

    return DeterministicTemporalAnswer(
        date=parsed_date, start=parsed_time("start"), end=parsed_time("end")
    )


def normalize_deterministic_temporal_answer(parsed: DeterministicTemporalAnswer) -> str:
    """Serialize facts so restart recovery no longer depends on relative time."""
    parts = [parsed.date.isoformat()] if parsed.date is not None else []
    if parsed.start is not None:
        parts.append(parsed.start.strftime("%H:%M"))
    if parsed.end is not None:
        parts.extend(("bis", parsed.end.strftime("%H:%M")))
    return " ".join(parts)


def deterministic_temporal_revision(
    proposal: Proposal,
    question: str,
    normalized_answer: str,
    configured_timezone: str,
    reference_date: calendar_date | None = None,
) -> Proposal | None:
    """Build an unambiguous clock-time revision without another LLM call."""
    if proposal.kind != ProposalKind.EVENT or not any(
        word in question.casefold()
        for word in ("datum", "beginn", "ende", "uhrzeit", "wann")
    ):
        return None
    parsed = parse_deterministic_temporal_answer(normalized_answer, reference_date)
    if parsed is None:
        return None
    expected = (
        proposal.known_temporal_facts.date
        if proposal.known_temporal_facts is not None
        else proposal.temporal_fact.normalized_date
        if proposal.temporal_fact is not None
        else None
    )
    allowed_dates = {expected}
    if "ende" in question.casefold() and expected is not None:
        allowed_dates.add(expected + timedelta(days=1))
    if (
        parsed.date is not None
        and expected is not None
        and parsed.date not in allowed_dates
    ):
        raise ContradictoryRevision(
            "Die Antwort widerspricht dem validierten Termindatum"
        )
    day = parsed.date or expected
    question_lower = question.casefold()
    wants_end = "ende" in question_lower
    wants_start = (
        "beginn" in question_lower
        or "uhrzeit" in question_lower
        or "wann" in question_lower
    )
    # A lone clock value answers only the requested endpoint. A range explicitly
    # proves both endpoints, irrespective of which temporal question was open.
    start_time = (
        parsed.start
        if parsed.end is not None or wants_start and not wants_end
        else None
    )
    end_time = (
        parsed.end if parsed.end is not None else parsed.start if wants_end else None
    )
    if day is None and (start_time is not None or end_time is not None):
        return None
    zone = ZoneInfo(configured_timezone)

    def localize(value: clock_time | None, value_day: date | None) -> datetime | None:
        if value is None or value_day is None:
            return None
        naive = datetime.combine(value_day, value)
        candidates = []
        for fold in (0, 1):
            candidate = naive.replace(tzinfo=zone, fold=fold)
            if (
                candidate.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None)
                == naive
            ):
                if not candidates or candidate.utcoffset() != candidates[0].utcoffset():
                    candidates.append(candidate)
        if len(candidates) != 1:
            raise ContradictoryRevision(
                "Die Ortszeit ist wegen der Zeitumstellung nicht eindeutig"
            )
        return candidates[0]

    start = localize(start_time, day)
    if (
        start is None
        and day is not None
        and proposal.known_temporal_facts is not None
        and proposal.known_temporal_facts.start_time is not None
    ):
        start = localize(proposal.known_temporal_facts.start_time, day)
    end_day = parsed.date or day
    known_start = (
        proposal.known_temporal_facts.start
        if proposal.known_temporal_facts is not None
        else proposal.start
    )
    reference_start = start or known_start
    end = localize(end_time, end_day)
    if (
        end is not None
        and reference_start is not None
        and end <= reference_start
        and parsed.end is not None
    ):
        # ``day`` is guaranteed above whenever a clock value exists.  A range
        # whose end clock is not later therefore explicitly crosses midnight.
        end = localize(end_time, day + timedelta(days=1))
    elif end is not None and reference_start is not None and end <= reference_start:
        raise ContradictoryRevision("Das Terminende muss nach dem Beginn liegen")
    changes: dict[str, Any] = {}
    if parsed.date is not None and expected is None:
        changes["temporal_date"] = parsed.date
    if start is not None:
        changes["start"] = start
        if (
            end is None
            and proposal.duration_minutes is not None
            and not proposal.duration_is_upper_bound
        ):
            end = start + timedelta(minutes=proposal.duration_minutes)
    if end is not None:
        changes["end"] = end
    revised = apply_proposal_revision(
        proposal, ProposalRevisionDelta(answered_question=question, changes=changes)
    )
    if parsed.date is not None and (
        proposal.temporal_fact is None or proposal.temporal_fact.normalized_date is None
    ):
        revised = Proposal.model_validate(
            revised.model_copy(
                update={
                    "temporal_fact": TemporalFact(
                        raw_text=normalized_answer,
                        normalized_date=parsed.date,
                        year_source="telegram",
                        status="resolved",
                    )
                }
            ).model_dump()
        )
    return revised


_EXPLICIT_CREATE_FALLBACK_ANSWERS = (
    re.compile(r"neu anlegen"),
    re.compile(r"(?:als )?neuen (?:kalender)?(?:eintrag|termin) anlegen"),
    re.compile(
        r"(?:ja,? )?(?:bitte )?(?:stattdessen |ersatzweise )?(?:einen )?neuen (?:kalender)?(?:eintrag|termin) (?:erstellen|anlegen)"
    ),
)


def deterministic_classification_revision(
    proposal: Proposal, question: str, answer: str
) -> Proposal | None:
    """Turn an explicit refusal to update an existing event into a new item.

    The intentionally closed vocabulary avoids guessing from ambiguous replies.
    It also keeps this security-relevant state transition independent of an LLM.
    """
    normalized_question = " ".join(question.casefold().split())
    if (
        proposal.classification.value != "change"
        or "bestehende" not in normalized_question
        or "geändert" not in normalized_question
    ):
        return None
    normalized_answer = " ".join(answer.casefold().strip().rstrip(".!?").split())
    if not any(
        pattern.fullmatch(normalized_answer)
        for pattern in _EXPLICIT_CREATE_FALLBACK_ANSWERS
    ):
        return None
    return apply_proposal_revision(
        proposal,
        ProposalRevisionDelta(
            answered_question=question,
            changes={"explicit_create_fallback_confirmed": True},
        ),
        allow_create_fallback=True,
    )
