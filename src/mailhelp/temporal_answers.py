"""Conservative deterministic interpretation of temporal answers."""

from __future__ import annotations

import re
from datetime import (
    UTC,
    date,
    datetime,
    timedelta,
)
from datetime import (
    date as calendar_date,
)
from datetime import (
    time as clock_time,
)
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict

from .domain.proposal import ProposalRevisionChanges
from .domain.revision_errors import ContradictoryRevision
from .domain.temporal import TemporalResolutionStatus, YearSource
from .models import (
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
    "relative_end_answer",
]


class DeterministicTemporalAnswer(BaseModel):
    """Facts explicitly present in one narrowly supported Telegram answer."""

    model_config = ConfigDict(extra="forbid", strict=True)
    date: calendar_date | None = None
    start: clock_time | None = None
    end: clock_time | None = None


_DATE = (r"(?:(?P<day>\d{1,2})\.(?P<month>\d{1,2})\.(?P<year>\d{4}|\d{2})"
         r"|(?P<iso_year>\d{4})-(?P<iso_month>\d{2})-(?P<iso_day>\d{2}))")
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


_DURATION = re.compile(
    r"\s*(?:nach|plus|\+|in)?\s*(?P<amount>\d+(?:[.,]\d+)?)\s*"
    r"(?P<unit>h|std\.?|stunden?|min\.?|minuten?)\s*"
    r"(?:später|danach|nach\s+(?:dem\s+)?beginn)?\s*",
    re.IGNORECASE,
)
# A duration longer than a week is not a plausible event length.
_MAX_DURATION_MINUTES = 7 * 24 * 60


def relative_end_answer(
    proposal: Proposal, question: str, answer: str, configured_timezone: str
) -> str | None:
    """Turn a duration answer to the end question into an absolute end.

    "nach 3h", "2 Stunden", "+90 min" or "1,5 h nach Beginn" are resolved only
    when the start is already known; the result is an ordinary date and clock
    answer for the deterministic revision.
    """
    if proposal.kind != ProposalKind.EVENT or not (
        {"ende", "endet"} & set(re.findall(r"\w+", question.casefold()))
    ):
        return None
    match = _DURATION.fullmatch(answer)
    known = proposal.known_temporal_facts.start if proposal.known_temporal_facts else None
    start = proposal.start if isinstance(proposal.start, datetime) else known
    if match is None or not isinstance(start, datetime):
        return None
    amount = float(match["amount"].replace(",", "."))
    minutes = amount if match["unit"].casefold().startswith("min") else amount * 60
    if not 0 < minutes <= _MAX_DURATION_MINUTES:
        return None
    end = start.astimezone(ZoneInfo(configured_timezone)) + timedelta(minutes=round(minutes))
    return f"{end:%d.%m.%Y %H:%M}"


def parse_deterministic_temporal_answer(
    answer: str, reference_date: calendar_date | None = None
) -> DeterministicTemporalAnswer | None:
    """Parse narrow date/time forms, resolving ``heute`` only with an explicit day.

    An impossible day or time ("31.02.2026", "30 Uhr") is no deterministic answer;
    like any other free answer it is left to the interpretation step.
    """
    try:
        return _parse_temporal_answer(answer, reference_date)
    except ValueError:
        return None


def _parse_temporal_answer(
    answer: str, reference_date: calendar_date | None
) -> DeterministicTemporalAnswer | None:
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
        year = int(values["year"])
        if year < 100:
            # Never guess a century from untrusted input. A short year is safe
            # only when it confirms the already validated proposal date.
            if reference_date is None or year != reference_date.year % 100:
                return None
            year = reference_date.year
        parsed_date = date(
            year, int(values["month"]), int(values["day"])
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


def expected_event_date(proposal: Proposal) -> date | None:
    """The validated event date an answer must not contradict."""
    return (
        proposal.known_temporal_facts.date
        if proposal.known_temporal_facts is not None
        else proposal.temporal_fact.normalized_date
        if proposal.temporal_fact is not None
        else None
    )


def _requested_times(parsed: DeterministicTemporalAnswer,
                     question: str) -> tuple[clock_time | None, clock_time | None]:
    """Which endpoint each parsed clock value answers."""
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
    return start_time, end_time


def _localize(value: clock_time | None, value_day: date | None, zone: ZoneInfo) -> datetime | None:
    """A local wall-clock time; ambiguous or missing times at a DST change are refused."""
    if value is None or value_day is None:
        return None
    naive = datetime.combine(value_day, value)
    candidates: list[datetime] = []
    for fold in (0, 1):
        candidate = naive.replace(tzinfo=zone, fold=fold)
        if (
            candidate.astimezone(UTC).astimezone(zone).replace(tzinfo=None)
            == naive
        ):
            if not candidates or candidate.utcoffset() != candidates[0].utcoffset():
                candidates.append(candidate)
    if len(candidates) != 1:
        raise ContradictoryRevision(
            "Die Ortszeit ist wegen der Zeitumstellung nicht eindeutig"
        )
    return candidates[0]


def _interval(proposal: Proposal, parsed: DeterministicTemporalAnswer, day: date | None,
              start_time: clock_time | None, end_time: clock_time | None,
              zone: ZoneInfo) -> tuple[datetime | None, datetime | None]:
    """Start and end of the answer, checked against the already known start."""
    start = _localize(start_time, day, zone)
    if (
        start is None
        and day is not None
        and proposal.known_temporal_facts is not None
        and proposal.known_temporal_facts.start_time is not None
    ):
        start = _localize(proposal.known_temporal_facts.start_time, day, zone)
    end_day = parsed.date or day
    known_start = (
        proposal.known_temporal_facts.start
        if proposal.known_temporal_facts is not None
        else proposal.start
    )
    reference_start = start or (
        known_start if isinstance(known_start, datetime) else None
    )
    end = _localize(end_time, end_day, zone)
    if (
        end is not None
        and reference_start is not None
        and end <= reference_start
        and parsed.end is not None
    ):
        # ``day`` is guaranteed above whenever a clock value exists.  A range
        # whose end clock is not later therefore explicitly crosses midnight.
        assert day is not None
        end = _localize(end_time, day + timedelta(days=1), zone)
    elif end is not None and reference_start is not None and end <= reference_start:
        raise ContradictoryRevision("Das Terminende muss nach dem Beginn liegen")
    return start, end


def _temporal_changes(proposal: Proposal, parsed: DeterministicTemporalAnswer, expected: date | None,
                      start: datetime | None, end: datetime | None) -> dict[str, Any]:
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
        if proposal.all_day and isinstance(proposal.start, date) and not isinstance(
            proposal.start, datetime
        ):
            # An end clock does not prove a beginning clock. Keep the timed
            # event incomplete rather than persisting a mixed interval.
            changes.update(start=None, all_day=False)
    return changes


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
    expected = expected_event_date(proposal)
    parsed = parse_deterministic_temporal_answer(
        normalized_answer, reference_date or expected
    )
    if parsed is None:
        return None
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
    start_time, end_time = _requested_times(parsed, question)
    if day is None and (start_time is not None or end_time is not None):
        return None
    start, end = _interval(proposal, parsed, day, start_time, end_time, ZoneInfo(configured_timezone))
    changes = _temporal_changes(proposal, parsed, expected, start, end)
    revised = apply_proposal_revision(
        proposal, ProposalRevisionDelta(answered_question=question,
                                        changes=ProposalRevisionChanges.model_validate(changes))
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
                        year_source=YearSource.TELEGRAM,
                        status=TemporalResolutionStatus.RESOLVED,
                    )
                }
            ).model_dump()
        )
    return revised


_EXPLICIT_CREATE_FALLBACK_ANSWERS = (
    re.compile(r"neu anlegen"),
    re.compile(r"(?:als )?neuen (?:kalender)?(?:eintrag|termin) anlegen"),
    re.compile(
        r"(?:ja,? )?(?:bitte )?(?:stattdessen |ersatzweise )?(?:einen )?"
        r"neuen (?:kalender)?(?:eintrag|termin) (?:erstellen|anlegen)"
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
    normalized_answer = " ".join(answer.casefold().strip().rstrip(".!?").split())
    if (
        proposal.classification.value == "non_binding"
        and "nicht bindende hinweis" in normalized_question
        and "angelegt werden" in normalized_question
        and normalized_answer == "ja"
    ):
        return apply_proposal_revision(
            proposal,
            ProposalRevisionDelta(
                answered_question=question,
                changes=ProposalRevisionChanges(explicit_non_binding_create_confirmed=True),
            ),
            allow_create_fallback=True,
        )
    if (
        proposal.classification.value != "change"
        or "bestehende" not in normalized_question
        or "geändert" not in normalized_question
    ):
        return None
    if not any(
        pattern.fullmatch(normalized_answer)
        for pattern in _EXPLICIT_CREATE_FALLBACK_ANSWERS
    ):
        return None
    return apply_proposal_revision(
        proposal,
        ProposalRevisionDelta(
            answered_question=question,
            changes=ProposalRevisionChanges(explicit_create_fallback_confirmed=True),
        ),
        allow_create_fallback=True,
    )
