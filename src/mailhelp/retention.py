"""Inhaltsminimierung abgeschlossener, sicher wiederaufnehmbarer Vorgänge."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from . import state_names
from .config import RetentionSettings
from .models import MailState, ProposalStatus
from .storage import JsonStore, mail_state_names

Period = int | Literal["disabled", "unlimited"]
_OPEN_PROPOSALS = {
    ProposalStatus.NEEDS_CLARIFICATION,
    ProposalStatus.PENDING_CONFIRMATION,
    ProposalStatus.CONFIRMED,
    ProposalStatus.WRITING,
    ProposalStatus.UNCERTAIN,
}


@dataclass(frozen=True)
class CleanupResult:
    scanned: int = 0
    protected: int = 0
    mail_scrubbed: int = 0
    debug_scrubbed: int = 0


class RetentionService:
    """Scrub content without deleting restart and duplicate-protection records."""

    def __init__(self, store: JsonStore, settings: RetentionSettings,
                 logger: object, clock: Callable[[], datetime] | None = None):
        self.store = store
        self.settings = settings
        self.logger = logger
        self.clock = clock or (lambda: datetime.now(UTC))

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
        return any(proposal.status in _OPEN_PROPOSALS for proposal in state.proposals)

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
                if record is not None and self._expired(period, state.updated_at, now):
                    self.store.save(f"{prefix}-{state.id}", {"schema_version": 1, "removed": True})
                    if prefix == "history":
                        for snapshot in self.store.names(state_names.proposals_of(state.id)):
                            if snapshot.rsplit("-", 1)[-1].startswith("v") and snapshot.rsplit("-", 1)[-1][1:].isdigit():
                                old = self.store.load(snapshot)
                                old.update(title="Historischer Vorschlag", description="", evidence="Nach Aufbewahrung entfernt", location=None, video_link=None)
                                self.store.save(snapshot, old)
            mail_changed = self._expired(self.settings.full_mail_days, state.updated_at, now) and state.mail is not None
            debug_changed = self._expired(self.settings.debug_llm_days, state.updated_at, now) and any(
                (state.relevance is not None, state.summary is not None, bool(state.llm_call_ids), bool(state.validation_errors))
            )
            if not mail_changed and not debug_changed:
                continue
            if mail_changed:
                from .attachments import AttachmentCache
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
        result = CleanupResult(scanned, protected, mail_scrubbed, debug_scrubbed)
        self.logger.event("INFO", "retention", "cleanup_completed", processed_at=now.isoformat(),
                          scanned_count=scanned, protected_count=protected,
                          mail_count=mail_scrubbed, debug_count=debug_scrubbed)
        return result
