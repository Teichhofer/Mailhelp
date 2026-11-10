"""Inhaltsminimierung abgeschlossener, sicher wiederaufnehmbarer Vorgänge."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from .. import state_names
from ..config import RetentionSettings
from ..logging import EventLogger
from ..models import MailState, ProposalStatus
from ..storage import JsonStore, mail_state_names

Period = int | Literal["disabled", "unlimited"]
_OPEN_PROPOSALS = {
    ProposalStatus.NEEDS_CLARIFICATION,
    ProposalStatus.PENDING_CONFIRMATION,
    ProposalStatus.CONFIRMED,
    ProposalStatus.WRITING,
    ProposalStatus.UNCERTAIN,
    # 5.2: written but not yet verified; its mail keeps the content verification may show.
    ProposalStatus.VERIFYING,
}

_REMOVED = {"schema_version": 1, "removed": True}

@dataclass(frozen=True)
class CleanupResult:
    scanned: int = 0
    protected: int = 0
    mail_scrubbed: int = 0
    debug_scrubbed: int = 0
    activity_scrubbed: int = 0
    reanalysis_removed: int = 0


class RetentionService:
    """Scrub content without deleting restart and duplicate-protection records."""

    def __init__(self, store: JsonStore, settings: RetentionSettings,
                 logger: EventLogger, clock: Callable[[], datetime] | None = None, full_mail_period=None):
        self.store = store
        self.settings = settings
        self.logger = logger
        self.clock = clock or (lambda: datetime.now(UTC))
        self.full_mail_period = full_mail_period

    @staticmethod
    def _expired(period: Period, updated_at: datetime, now: datetime) -> bool:
        if period == "unlimited":
            return False
        if period == "disabled":
            return True
        return updated_at <= now - timedelta(days=period)

    @staticmethod
    def _protected(state: MailState) -> bool:
        if state.steps.completion != "completed" or state.awaiting_relevance:
            return True
        return any(proposal.status in _OPEN_PROPOSALS or proposal.merge_review_required for proposal in state.proposals)

    def run(self) -> CleanupResult:
        now = self.clock()
        if now.tzinfo is None:
            raise ValueError("Bereinigungszeitpunkt benötigt eine Zeitzone")
        scanned = protected = mail_scrubbed = debug_scrubbed = 0
        for name in mail_state_names(self.store):
            scanned += 1
            state = self.store.load_model(name, MailState)
            if state is None:
                continue
            if self._protected(state):
                protected += 1
                continue
            analysis_period = self.settings.analysis_days
            if analysis_period is None:
                analysis_period = self.settings.debug_llm_days
            for prefix, period in (("analysis", analysis_period), ("history", self.settings.history_days)):
                record = self.store.load(f"{prefix}-{state.id}")
                # An already removed record is not rewritten: every save costs an fsync and a store revision.
                if record not in (None, _REMOVED) and self._expired(period, state.updated_at, now):
                    self.store.save(f"{prefix}-{state.id}", _REMOVED)
                    if prefix == "history":
                        for snapshot in self.store.names(state_names.proposals_of(state.id)):
                            suffix = snapshot.rsplit("-", 1)[-1]
                            if suffix.startswith("v") and suffix[1:].isdigit():
                                old = self.store.load(snapshot)
                                old.update(title="Historischer Vorschlag", description="",
                                           evidence="Nach Aufbewahrung entfernt", location=None,
                                           video_link=None)
                                self.store.save(snapshot, old)
            period = self.settings.full_mail_days if self.full_mail_period is None else self.full_mail_period(state)
            mail_changed = self._expired(period, state.updated_at, now) and state.mail is not None
            debug_changed = self._expired(self.settings.debug_llm_days, state.updated_at, now) and any(
                (state.relevance is not None, state.summary is not None, bool(state.llm_call_ids),
                 bool(state.validation_errors))
            )
            if not mail_changed and not debug_changed:
                continue
            if mail_changed:
                from ..processing.attachments import AttachmentCache
                AttachmentCache(self.store).remove(state.id)
                draft = self.store.load(state_names.draft(state.id))
                if draft is not None:
                    draft["text"] = ""
                    self.store.save(state_names.draft(state.id), draft)
                state.mail = None
                mail_scrubbed += 1
            if debug_changed:
                state.relevance = None
                state.summary = None
                state.llm_call_ids = []
                state.validation_errors = []
                debug_scrubbed += 1
            # Identity, duplicate decision, the separate duplicate index, proposal
            # versions/results and write/idempotency references deliberately remain.
            self.store.save(name, state.model_dump(mode="json"))
            self.logger.event("INFO", "retention", "state_scrubbed", mail_id=state.id,
                              processed_at=now.isoformat(), mail_count=int(mail_changed),
                              debug_count=int(debug_changed))
        from ..review.learning_log import prune
        learning_removed = prune(self.store.directory, self.settings.decision_learning_days, now)
        from ..activity.store import ActivityReportStore
        activity_scrubbed = ActivityReportStore(self.store).remove_expired_texts(
            self.settings.activity_report_days, now)
        from ..config import ReanalysisSettings
        from ..processing.reanalysis import ReanalysisJobs
        analysis = self.settings.debug_llm_days if self.settings.analysis_days is None else self.settings.analysis_days
        reanalysis_removed = ReanalysisJobs(self.store, ReanalysisSettings(), self.logger).remove_expired(
            analysis, self.settings.full_mail_days, now, self._expired)
        result = CleanupResult(scanned, protected, mail_scrubbed, debug_scrubbed, activity_scrubbed,
                               reanalysis_removed)
        self.logger.event("INFO", "retention", "cleanup_completed", processed_at=now.isoformat(),
                          scanned_count=scanned, protected_count=protected,
                          mail_count=mail_scrubbed, debug_count=debug_scrubbed,
                          activity_count=activity_scrubbed, learning_count=learning_removed,
                          reanalysis_count=reanalysis_removed)
        return result
