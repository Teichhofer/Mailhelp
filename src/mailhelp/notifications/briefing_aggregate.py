"""Read-only briefing snapshot: current review cards and summaries in a bounded time window."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .. import state_names
from ..models import MailState
from ..processing.mail_recheck import filed_as_irrelevant
from ..review.archive import AnalysisSnapshot
from ..review.cards import shorten
from ..review.views import ReviewViews
from ..storage import CorruptState, JsonStore


@dataclass(frozen=True)
class BriefingItem:
    mail_id: str
    proposal_id: str | None
    version: int
    title: str
    when: str
    state: str
    questions: tuple[str, ...] = ()


@dataclass(frozen=True)
class BriefingSummary:
    mail_id: str
    subject: str
    text: str
    deadlines: tuple[str, ...]


@dataclass(frozen=True)
class BriefingContent:
    start: datetime
    end: datetime
    events: tuple[BriefingItem, ...] = ()
    tasks: tuple[BriefingItem, ...] = ()
    relevance: tuple[BriefingItem, ...] = ()
    summaries: tuple[BriefingSummary, ...] = ()
    scanned: int = 0
    irrelevant: int = 0
    damaged: int = 0

    @property
    def empty(self) -> bool:
        return not (self.events or self.tasks or self.relevance or self.summaries)


class BriefingAggregator:
    def __init__(self, store: JsonStore, views: ReviewViews):
        self.store, self.views = store, views

    def collect(self, start: datetime, end: datetime) -> BriefingContent:
        if start.tzinfo is None or end.tzinfo is None or start > end:
            raise ValueError("Briefing-Zeitfenster benötigt geordnete Zeitpunkte mit Zeitzone")
        with self.store.locked():
            overview = self.views.overview()
            events: list[BriefingItem] = []
            tasks: list[BriefingItem] = []
            for row in overview.open:
                item = BriefingItem(row.mail_id, row.proposal_id, row.version, row.card.title,
                                    row.card.when or row.card.due or "Noch offen", row.state, row.card.questions)
                (events if row.card.kind == "event" else tasks).append(item)
            relevance = tuple(BriefingItem(row.mail_id, None, row.version, row.subject, "", "Relevanz klären")
                              for row in overview.relevance)
            summaries, scanned, irrelevant, damaged = self._summaries(start, end)
        key = lambda item: (item.when, item.title, item.mail_id)
        return BriefingContent(start, end, tuple(sorted(events, key=key)), tuple(sorted(tasks, key=key)),
                               relevance, tuple(summaries), scanned, irrelevant, max(overview.damaged, damaged))

    def _summaries(self, start: datetime, end: datetime) -> tuple[list[BriefingSummary], int, int, int]:
        result = []
        scanned = irrelevant = damaged = 0
        for name in state_names.mail_state_names(self.store):
            try:
                state = self.store.peek_model(name, MailState)
                analysis = self.store.peek_model("analysis-" + name[5:], AnalysisSnapshot, AnalysisSnapshot())
            except CorruptState:
                damaged += 1
                continue
            if state is None or state.steps.completion != "completed":
                continue
            stamp = analysis.recorded_at or state.created_at
            if not start < stamp <= end:
                continue
            scanned += 1
            if filed_as_irrelevant(state):
                irrelevant += 1
            elif state.steps.summary == "completed":
                summary = None if analysis.removed else analysis.summary or state.summary
                text = " ".join(summary.sentences) if summary else "Zusammenfassung nicht mehr aufbewahrt."
                subject = state.display_headers.subject if state.display_headers else "Mail ohne Betreff"
                result.append(BriefingSummary(state.id, subject, shorten(text, 600),
                                               tuple(summary.deadlines) if summary else ()))
        return result, scanned, irrelevant, damaged
