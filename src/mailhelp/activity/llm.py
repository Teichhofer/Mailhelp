"""The two language-model steps of an activity report and their local checks."""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Literal

from pydantic import Field

from ..analysis import Analyzer, ClassifiedRun
from ..domain._base import StrictModel
from .models import ActivityReport, ReportEvent, ReportMail

MAX_EVENTS = 20


class ActivityRelevance(StrictModel):
    relevant: bool
    confidence: Literal["high", "medium", "low"]
    reason: str = Field(min_length=1, max_length=500)


class ActivityEventCandidate(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    day: date = Field(alias="date")
    start_time: str | None = Field(default=None, pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
    end_time: str | None = Field(default=None, pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
    location: str | None = Field(default=None, max_length=300)
    evidence: str = Field(min_length=1, max_length=500)
    cancelled: bool = False


class ActivityEvents(StrictModel):
    events: list[ActivityEventCandidate] = Field(max_length=MAX_EVENTS)


def _compact(text: str) -> str:
    return " ".join(text.split()).casefold()


def _clean(text: str | None, limit: int) -> str | None:
    """Untrusted text without control characters, bounded for storage."""
    if text is None:
        return None
    return re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", text).strip()[:limit] or None


class ActivityAnalyzer:
    """Relevance and date extraction for one report mail; nothing is written anywhere."""

    def __init__(self, analyzer: Analyzer, personal_info: Any = lambda: ""):
        self.analyzer = analyzer
        # Read on every call, so a changed setting applies without a restart.
        self.personal_info = personal_info

    def _mail(self, mail: ReportMail, received: date) -> dict[str, Any]:
        return {"from_or_to": mail.sender, "subject": mail.subject, "received": received.isoformat(),
                "text": mail.text}

    def suspicious(self, mail: ReportMail) -> bool:
        return self.analyzer.suspicious_link_bait({"text": mail.text})

    def relevance(self, report: ActivityReport, mail: ReportMail, received: date) -> tuple[str, ActivityRelevance]:
        payload = {"report": {"title": report.definition.title, "topic": report.definition.topic},
                   "personal_info": self.personal_info(), "mail": self._mail(mail, received)}
        return ClassifiedRun(self.analyzer, "activity_relevance", payload, ActivityRelevance.model_validate,
                             ActivityRelevance, None, None).run()

    def events(self, report: ActivityReport, mail: ReportMail, received: date,
               log: Any) -> tuple[str, list[ReportEvent]]:
        """Dated activities of a relevant mail, each proven by a verbatim quote."""
        payload = {"report": {"title": report.definition.title, "topic": report.definition.topic},
                   "period": {"since": report.definition.since.isoformat(),
                              "until": report.definition.until.isoformat()},
                   "mail": self._mail(mail, received)}
        call, result = ClassifiedRun(self.analyzer, "activity_events", payload, ActivityEvents.model_validate,
                                     ActivityEvents, None, None).run()
        source = _compact(f"{mail.subject}\n{mail.text}")
        events: list[ReportEvent] = []
        for candidate in result.events:
            if _compact(candidate.evidence) not in source:
                # An invented quote invents the date as well; the user can add it manually.
                log.event("WARNING", "activity", "event_evidence_missing", report_id=report.id, call_id=call)
                continue
            events.append(ReportEvent(
                id=f"e{len(events) + 1}", title=_clean(candidate.title, 200) or "Termin", day=candidate.day,
                start_time=candidate.start_time, end_time=candidate.end_time,
                location=_clean(candidate.location, 300), evidence=_clean(candidate.evidence, 500) or "",
                cancelled=candidate.cancelled, out_of_range=not report.in_range(candidate.day)))
        return call, events


__all__ = ["MAX_EVENTS", "ActivityAnalyzer", "ActivityEventCandidate", "ActivityEvents", "ActivityRelevance"]
