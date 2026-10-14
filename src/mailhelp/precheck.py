"""Vollautomatischer Vorab-Dubletten- und Aktualisierungsabgleich vor der Entscheidungsvorlage."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from .domain.proposal import (
    DuplicateMatchInfo,
    DuplicateSource,
    Proposal,
    ProposalClassification,
    ProposalKind,
    ProposalStatus,
)
from .external.calendar import CalendarOperations
from .external.contracts import ExternalWriter, TargetWriter
from .external.roles import CALENDAR_SLOT, TASK_SLOT, provider_key, slot
from .logging import EventLogger, NullLogger
from .telegram.ledger import ActionLedgerPort


class DuplicatePreCheckService:
    """Pre-check extracted proposals against local ledger, calendar, and task manager."""

    def __init__(
        self,
        writer: ExternalWriter | TargetWriter | None = None,
        ledger: ActionLedgerPort | None = None,
        logger: EventLogger | None = None,
        writers: dict[str, ExternalWriter] | None = None,
    ):
        self.writer = writer
        self.writers: dict[str, ExternalWriter] = dict(writers) if writers is not None else {}
        if isinstance(writer, TargetWriter):
            self.writers[slot(writer)] = writer
        self.ledger = ledger
        self.logger = logger or NullLogger()

    def check_proposal(
        self, proposal: Proposal, mail_context: dict[str, Any] | None = None
    ) -> Proposal:
        """Inspect proposal against local and external sources, returning updated proposal."""
        bound = self.writers.get(CALENDAR_SLOT if proposal.kind == ProposalKind.EVENT else TASK_SLOT)
        if isinstance(bound, TargetWriter) and (proposal.target != bound.target or
                proposal.target_provider and proposal.target_provider != provider_key(bound)):
            return self._failed(proposal, "target", ValueError("Zielbindung geändert"))
        # Stufe 1: Lokales ActionLedger
        if self.ledger is not None:
            try:
                priors = self.ledger.prior_actions(proposal)
                if priors:
                    entry = priors[0]
                    self.logger.event(
                        "INFO", "precheck", "duplicate_found_ledger",
                        proposal_id=proposal.id, action_key=entry.action_key,
                    )
                    return proposal.model_copy(update={
                        "status": ProposalStatus.ALREADY_EXISTS,
                        "duplicate_match": DuplicateMatchInfo(
                            source=DuplicateSource.ACTION_LEDGER,
                            external_id=entry.external_id,
                            external_link=entry.external_link,
                            matched_title=entry.title,
                            details="Bereits erfolgreich über Mailhelp angelegt "
                                    f"({entry.created_at.date().isoformat()})",
                        ),
                    })
            except Exception as exc:
                return self._failed(proposal, "ledger", exc)

        # Stufe 2: Kalender (Google, CalDAV oder Outlook)
        cal_writer = self.writers.get(CALENDAR_SLOT)
        if (
            proposal.kind == ProposalKind.EVENT
            and isinstance(cal_writer, CalendarOperations)
            and cal_writer.role == "calendar"
            and proposal.start is not None
            and proposal.end is not None
        ):
            try:
                result = self._check_calendar(proposal, cal_writer)
                if result is not None:
                    return result
            except Exception as exc:
                return self._failed(proposal, "calendar", exc)

        # Stufe 3: Aufgaben (Todoist, Microsoft To Do oder CalDAV)
        todo_writer = self.writers.get(TASK_SLOT)
        if (
            proposal.kind == ProposalKind.TASK
            and isinstance(todo_writer, TargetWriter)
            and todo_writer.role == "tasks"
        ):
            try:
                result = self._check_todoist(proposal, todo_writer)
                if result is not None:
                    return result
            except Exception as exc:
                return self._failed(proposal, "todoist", exc)

        return proposal

    def _failed(self, proposal: Proposal, service: str, exc: Exception) -> Proposal:
        self.logger.event("WARNING", "precheck", f"{service}_check_failed", error=type(exc).__name__)
        return proposal.model_copy(update={"duplicate_check_failed": True,
            "status": ProposalStatus.NEEDS_CLARIFICATION,
            "open_questions": list(dict.fromkeys([*proposal.open_questions,
                "Dublettenprüfung nicht verfügbar; vor einer Anlage erneut prüfen."]))})

    def _check_calendar(self, proposal: Proposal, writer: CalendarOperations) -> Proposal | None:
        assert proposal.start is not None and proposal.end is not None

        start_dt = (proposal.start if isinstance(proposal.start, datetime)
                    else datetime.combine(proposal.start, datetime.min.time(), UTC))
        end_dt = (proposal.end if isinstance(proposal.end, datetime)
                  else datetime.combine(proposal.end, datetime.min.time(), UTC))

        search_start = start_dt - timedelta(days=1)
        search_end = end_dt + timedelta(days=1)

        events = writer.fetch_events_in_window(search_start, search_end, strict=True)
        for item in events:
            is_match = False
            if writer.calendar_matcher is not None:
                safe = item.model_dump(mode="json", exclude={"htmlLink"})
                _call_id, decision = writer.calendar_matcher(proposal, safe)
                is_match = decision.same_event
            else:
                is_match = (
                    item.summary.strip().casefold() == proposal.title.strip().casefold()
                )

            if is_match:
                changes, _interval = writer.time_changes(proposal, item)
                is_reschedule_or_cancel = bool(changes) or proposal.classification in {
                    ProposalClassification.CHANGE,
                    ProposalClassification.CANCELLATION,
                }
                if is_reschedule_or_cancel:
                    self.logger.event(
                        "INFO", "precheck", "reschedule_detected",
                        proposal_id=proposal.id, existing_event_id=item.id,
                    )
                    return proposal.model_copy(update={
                        "target_event_id": item.id,
                        "time_changes": changes,
                        "is_cancellation": proposal.classification == ProposalClassification.CANCELLATION,
                    })
                else:
                    self.logger.event(
                        "INFO", "precheck", "duplicate_found_calendar",
                        proposal_id=proposal.id, existing_event_id=item.id,
                    )
                    return proposal.model_copy(update={
                        "status": ProposalStatus.ALREADY_EXISTS,
                        "duplicate_match": DuplicateMatchInfo(
                            source=DuplicateSource.GOOGLE_CALENDAR,
                            external_id=item.id,
                            external_link=item.htmlLink,
                            matched_title=item.summary or proposal.title,
                            details=f"Bereits im Kalender eingetragen ({writer.label})",
                        ),
                    })
        return None

    def _check_todoist(self, proposal: Proposal, writer: TargetWriter) -> Proposal | None:
        tasks = writer.fetch_active_tasks(strict=True)
        norm_title = proposal.title.strip().casefold()
        for task in tasks:
            if task.content.strip().casefold() == norm_title:
                self.logger.event(
                    "INFO", "precheck", "duplicate_found_todoist",
                    proposal_id=proposal.id, task_id=str(task.id),
                )
                return proposal.model_copy(update={
                    "status": ProposalStatus.ALREADY_EXISTS,
                    "duplicate_match": DuplicateMatchInfo(
                        source=DuplicateSource.TODOIST,
                        external_id=str(task.id),
                        external_link=task.url,
                        matched_title=task.content or proposal.title,
                        details=f"Bereits als Aufgabe vorhanden ({writer.label})",
                    ),
                })
        return None
