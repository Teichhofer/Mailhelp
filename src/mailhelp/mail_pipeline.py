"""Stage sequence of one mail (prepare → relevance → summary → actions → notification)."""
from __future__ import annotations

import re
import time
import traceback
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from .adapter import PermanentError
from .analysis import (
    LlmInvalidJson,
    LlmProviderResponseInvalid,
    LlmSchemaValidationExceeded,
)
from .domain.prepared import PreparedMail
from .domain.proposal import ProposalStatus
from .imap import FetchedMail
from .mime import MimeLimitExceeded, extract_display_headers, prepare
from .models import (
    ActionRoute,
    DisplayHeaders,
    MailState,
    ProcessingErrorCode,
    ProcessingStage,
    Proposal,
    ProposalNotification,
    Relevance,
    RelevanceDialog,
    ValidationIssue,
)
from .openrouter import RateLimitExceeded
from .sender_filter import is_irrelevant_sender

if TYPE_CHECKING:
    from .orchestrator import Orchestrator


def _content(state: MailState) -> dict[str, Any]:
    """The mail being processed; retention removes content only from finished mails."""
    assert state.mail is not None
    return state.mail


def _prepared(state: MailState) -> PreparedMail:
    assert state.prepared is not None  # prepared together with the content
    return state.prepared


class ProcessingOutcome(StrEnum):
    """Extern sichtbares Ergebnis eines Verarbeitungsversuchs."""

    COMPLETED = "completed"
    COMPLETED_WITH_ACTION_ERROR = "completed_with_action_error"
    WAITING = "waiting"
    FAILED = "failed"


@dataclass(frozen=True)
class ProcessingResult:
    outcome: ProcessingOutcome
    state: dict[str, Any]

    @property
    def user_action_open(self) -> bool:
        return self.outcome is ProcessingOutcome.WAITING or any(
            item["status"] in {"pending_confirmation", "needs_clarification"}
            for item in self.state.get("proposals", [])
        )

    def __getitem__(self, key: str) -> Any:
        """Keep state inspection concise while making the outcome explicit."""
        return self.state[key]

    def __contains__(self, key: object) -> bool:
        return key in self.state


@dataclass
class ProcessingRun:
    """One processing pass: the stage is read by the failure handling."""

    name: str
    state: MailState
    stage: ProcessingStage
    started: float


class MailPipeline:
    """Owned by the Orchestrator; reads its services through ``o``."""

    def __init__(self, owner: Orchestrator):
        self.o = owner

    def advance(self, run: ProcessingRun, fetched: FetchedMail) -> ProcessingResult | None:
        """Run every pending step; a result ends processing early (duplicate, open question)."""
        self._prepare(run, fetched)
        state = run.state
        assert state.mail is not None
        if self.o.duplicates.check(run.name, state):
            duplicate = state.duplicate
            assert duplicate is not None  # check() recorded the decision
            self.o.logger.event("INFO", "orchestrator", "duplicate_skipped", mail_id=state.id,
                              previous_mail_id=duplicate.previous_mail_id)
            return ProcessingResult(ProcessingOutcome.COMPLETED, state.model_dump(mode="json"))
        if self.o.vision is not None and state.steps.relevance == "pending":
            self.o.read_images(run.name, state, fetched.raw)
        self._relevance(run)
        assert state.relevance is not None
        if state.relevance.decision == "irrelevant":
            self._skip_after_irrelevant(state)
        elif state.relevance.decision == "unclear":
            self._ask_relevance(run)
            return ProcessingResult(ProcessingOutcome.WAITING, state.model_dump(mode="json"))
        else:
            self._summarize(run)
            self._detect_actions(run)
            self._notify_proposals(run)
        return None

    def _prepare(self, run: ProcessingRun, fetched: FetchedMail) -> None:
        state, name = run.state, run.name
        if state.steps.preparation == "pending":
            cfg = self.o.effective_settings(state.imap.account_id) if self.o.mailbox_settings is not None else None
            state.proposal_policy = {
                "schema_version": 1, "normalization_version": "2.4-v1",
                "matching_policy": self.o.reconciliation.policy, "event_defaults": self.o.event_defaults.model_dump(),
                "max_semantic_candidates": self.o.reconciliation_settings.max_semantic_candidates}
            if cfg is not None:
                assert self.o.mailbox_settings is not None
                mailbox = self.o.mailbox_settings.imap.mailbox(self.o.mailbox_number(state.imap.account_id))
                assert mailbox is not None
                state.proposal_policy.update(targets=cfg.targets.model_dump(), target_profile=mailbox.target_profile,
                    event_defaults=cfg.event_defaults.model_dump(), mailbox_id=mailbox.id)
            if state.display_headers is None:
                display = extract_display_headers(fetched.raw, self.o.max_bytes)
                state.display_headers = DisplayHeaders(sender=display["from"], subject=display["subject"])
                self.o.save(name, state)
            state.mail = prepare(fetched.raw, self.o.max_bytes, fetched.received_at, self.o.user_timezone)
            state.mail["internal_id"] = state.id
            self.o.cache_previews(state, fetched.raw)
            state.steps.preparation = "completed"
            self.o.save(name, state)
            self.o.logger.event("INFO", "orchestrator", "preparation_completed", mail_id=state.id,
                              preparation_metadata=state.mail["metadata"])

    def _relevance(self, run: ProcessingRun) -> None:
        run.stage = ProcessingStage.RELEVANCE
        state = run.state
        if state.steps.relevance == "pending":
            if state.imap.account_id in self.o.always_relevant:
                state.relevance = Relevance(
                    decision="relevant", topic_ids=[], reason="IServ-Elternbrief: immer relevant"
                )
                call = None
                self.o.analyzer.last_relevance_source = "iserv"
            elif is_irrelevant_sender(_prepared(state).headers.sender, self.o.blocked_senders(),
                                    self.o.mailbox_number(state.imap.account_id)):
                state.relevance = Relevance(
                    decision="irrelevant", topic_ids=[], reason="Absender-Vorfilter"
                )
                call = None
                self.o.analyzer.last_relevance_source = "prefilter"
            else:
                topics = self.o.topics_for(state.config_fingerprint, state.imap.account_id)
                if self.o.mailbox_settings is not None and not any(topic.enabled for topic in topics):
                    call = None
                    state.relevance = Relevance(
                        decision="irrelevant", topic_ids=[], reason="Kein relevantes Thema für dieses Postfach"
                    )
                    self.o.analyzer.last_relevance_source = "prefilter"
                else:
                    call, state.relevance = self.o.analyzer.relevance(_content(state), topics)
                    state.llm_call_ids.append(call)
            state.steps.relevance = "completed"
            self.o.save(run.name, state)
            self.o.logger.event("INFO", "orchestrator", "relevance_completed", mail_id=state.id,
                              call_id=call, sender_prefilter=call is None)

    @staticmethod
    def _skip_after_irrelevant(state: MailState) -> None:
        state.steps.summary = "skipped"
        state.steps.action_detection = "skipped"
        state.steps.action_router = state.steps.task_extraction = state.steps.event_extraction = "skipped"
        state.steps.normalization = state.steps.proposal_building = "skipped"
        state.steps.duplicate_precheck = "skipped"
        state.steps.summary_notification = state.steps.proposal_notification = "skipped"

    def _ask_relevance(self, run: ProcessingRun) -> None:
        state, name = run.state, run.name
        if state.steps.summary_notification == "pending":
            state.relevance_dialog = RelevanceDialog(mail_id=state.id)
            state.awaiting_relevance = True
            self.o.save(name, state)
            headers = _prepared(state).headers
            self.o.notifier.send_relevance(
                state.relevance_dialog,
                headers.sender or "—",
                headers.subject or "—",
            )
            state.steps.summary_notification = "completed"
            state.steps.proposal_notification = "skipped"
            self.o.save(name, state)
            self.o.logger.event("INFO", "orchestrator", "notification_completed", mail_id=state.id)

    def _summarize(self, run: ProcessingRun) -> None:
        state, name = run.state, run.name
        run.stage = ProcessingStage.SUMMARY
        if state.steps.summary == "pending":
            call, summary = self.o.analyzer.summary(_content(state))
            state.summary = summary
            state.llm_call_ids.append(call)
            state.steps.summary = "completed"
            self.o.save(name, state)
            self.o.logger.event("INFO", "orchestrator", "summary_completed", mail_id=state.id, call_id=call)
        run.stage = ProcessingStage.SUMMARY_NOTIFICATION
        if state.steps.summary_notification == "pending":
            # ``sending`` is a durable uncertainty marker.  A crash after
            # Telegram accepted the call must not cause an automatic duplicate.
            state.steps.summary_notification = "sending"
            self.o.save(name, state)
            self.o.notifier.send(self.o.chat_id, self.o.notification_text(state))
            state.steps.summary_notification = "completed"
            self.o.save(name, state)

    def _detect_actions(self, run: ProcessingRun) -> None:
        state, name = run.state, run.name
        run.stage = ProcessingStage.ACTION_DETECTION
        if state.steps.action_detection not in {"pending", "failed"}:
            return
        if state.steps.action_router in {"pending", "failed"}:
            run.stage = ProcessingStage.ACTION_ROUTER
            call, route = self.o.analyzer.action_route(_content(state))
            state.action_route = route
            state.action_router_call_id = call
            state.llm_call_ids.append(call)
            state.steps.action_router = "completed"
            self.o.save(name, state)
        else:
            assert state.action_route is not None
            route = state.action_route
        assert state.action_router_call_id is not None
        # Extraction is read-only. A candidate counted by an unclear
        # route should therefore become a reviewable proposal too.
        wants_tasks = (route.action_state in {"task", "task_and_event"}
                       or route.task_count > 0)
        # An event candidate must not disappear merely because the
        # router is unsure whether the message is an invitation.  The
        # extractor and proposal boundary preserve that uncertainty,
        # while Telegram still receives the detected appointment.
        has_cal_events = bool(_prepared(state).calendar_events)
        wants_llm_events = (route.action_state in {"event", "task_and_event"}
                            or route.event_count > 0)
        wants_events = wants_llm_events or has_cal_events
        self._extract(run, route, wants_tasks, wants_llm_events)
        self._build(run, wants_tasks or wants_events)
        state.proposal_notifications = [
            ProposalNotification(
                proposal_id=item.id,
                proposal_version=item.version,
                status="completed" if item.status == ProposalStatus.ALREADY_EXISTS else "pending",
            )
            for item in state.proposals
        ]
        state.steps.action_detection = "completed"
        self.o.save(name, state)
        self.o.logger.event("INFO", "orchestrator", "actions_completed", mail_id=state.id,
                          action_state=route.action_state,
                          proposal_ids=[item.id for item in state.proposals])

    def _extract(self, run: ProcessingRun, route: ActionRoute, wants_tasks: bool, wants_llm_events: bool) -> None:
        state, name = run.state, run.name
        if wants_tasks and state.steps.task_extraction in {"pending", "failed"}:
            run.stage = ProcessingStage.TASK_EXTRACTION
            call, extraction = self.o.analyzer.extract_tasks(
                _content(state), expected_count=route.task_count)
            state.task_extraction = extraction
            state.llm_call_ids.append(call)
            state.steps.task_extraction = "completed"
            self.o.save(name, state)
            self.o.record_count_conflict(name, state, "task", route.task_count,
                                        len(extraction.tasks),
                                        state.action_router_call_id, call)
        if not wants_tasks:
            state.steps.task_extraction = "skipped"
            self.o.save(name, state)
        if wants_llm_events and state.steps.event_extraction in {"pending", "failed"}:
            run.stage = ProcessingStage.EVENT_EXTRACTION
            call, events = self.o.analyzer.extract_events(
                _content(state), expected_count=route.event_count)
            state.event_extraction = events
            state.llm_call_ids.append(call)
            state.steps.event_extraction = "completed"
            self.o.save(name, state)
            self.o.record_count_conflict(name, state, "event", route.event_count,
                                        len(events.events),
                                        state.action_router_call_id, call)
        elif not wants_llm_events:
            state.steps.event_extraction = "skipped"
            self.o.save(name, state)

    def _build(self, run: ProcessingRun, wanted: bool) -> None:
        state, name = run.state, run.name
        run.stage = ProcessingStage.NORMALIZATION
        if state.steps.normalization in {"pending", "failed"}:
            state.normalized_proposals = self.o.build_proposals(state) if wanted else []
            state.steps.normalization = "completed"
            self.o.save(name, state)
        run.stage = ProcessingStage.PROPOSAL_BUILDING
        if state.steps.proposal_building in {"pending", "failed"}:
            state.proposals = [Proposal.model_validate(item.model_dump(mode="json"))
                               for item in state.normalized_proposals]
            state.steps.proposal_building = "completed"
            self.o.save(name, state)
        self.o.questions.resolve(name, state)
        run.stage = ProcessingStage.DUPLICATE_PRECHECK
        if state.steps.duplicate_precheck in {"pending", "failed"}:
            state.proposals = [
                self.o.precheck.check_proposal(p, mail_context=state.mail)
                for p in state.proposals
            ]
            state.steps.duplicate_precheck = "completed"
            self.o.save(name, state)
        limit = (state.proposal_policy["max_semantic_candidates"] if state.proposal_policy is not None else None)
        state.proposals = [self.o.reconciliation.reconcile(p, limit) for p in state.proposals]
        state.proposals = [self.o.reconciliation.required(p.source_mail_id, p.id)
                           for p in state.proposals]
        self.o.save(name, state)
        events = [p for p in state.proposals if p.kind == "event"]
        for task in (p for p in state.proposals if p.kind == "task"):
            if len(events) == 1 and re.search(r"teilnahme|zurückmeld|anmeld|zusag|absag", task.title.casefold()):
                self.o.reconciliation.relate(task, events[0])

    def _notify_proposals(self, run: ProcessingRun) -> None:
        name = run.name
        run.stage = ProcessingStage.PROPOSAL_NOTIFICATION
        if run.state.steps.proposal_notification not in {"pending", "sending"}:
            return
        state = run.state
        first_attempt = state.steps.proposal_notification == "pending"
        if first_attempt:
            state.steps.proposal_notification = "sending"
            self.o.save(name, state)
        if (first_attempt and state.action_route is not None
                and state.action_route.action_state == "unclear"):
            self.o.notifier.send(
                self.o.chat_id,
                "Mögliche Aufgabe oder möglicher Termin benötigt fachliche Klärung: "
                + state.action_route.reason,
            )
        for conflict in state.extraction_count_conflicts:
            if conflict.notification_marked_at is not None:
                continue
            # Mark before delivery: an uncertain Telegram result must
            # never lead to an automatic duplicate after restart.
            conflict.notification_marked_at = datetime.now(UTC)
            self.o.save(name, state)
            self.o.notifier.send(
                self.o.chat_id,
                f"Zählerabweichung für {conflict.category}: Router "
                f"{conflict.expected_count}, Extraktion {conflict.actual_count}. "
                "Bitte die tatsächliche Anzahl klären.",
            )
        for proposal, notification in zip(state.proposals, state.proposal_notifications, strict=True):
            if notification.status != "pending":
                continue
            if proposal.status == ProposalStatus.MERGED:
                # The alias belongs to this mail; delivery belongs to the canonical
                # revision. Mark first so an uncertain delivery is never repeated.
                notification.status = "sending"
                self.o.save(name, state)
                assert proposal.canonical_ref is not None
                canonical = self.o.reconciliation.resolve(proposal.canonical_ref)
                if canonical is None:
                    raise ValueError("Zusammengeführter Vorschlag fehlt")
                self.o.notifier.send_proposal(canonical)
                notification.status = "completed"
                self.o.save(name, state)
                continue
            dedicated_delivery = bool(getattr(
                self.o.notifier, "manages_proposal_delivery", False))
            if not dedicated_delivery:
                notification.status = "sending"
                self.o.save(name, state)
            self.o.notifier.send_proposal(proposal)
            # ProposalDeliveryService owns the sending/completed
            # transition.  Reload its authoritative projection so a
            # later orchestrator save cannot overwrite that state.
            state = run.state = MailState.model_validate(self.o.store.load(name))
            current = next(item for item in state.proposal_notifications
                           if (item.proposal_id, item.proposal_version) ==
                           (proposal.id, proposal.version))
            # Compatibility for simple notifier ports: the
            # dedicated delivery service has already completed its
            # own transition, while a synchronous legacy notifier
            # reports success by returning normally.
            if current.status == "pending" or (
                    not dedicated_delivery and current.status == "sending"):
                current.status = "completed"
                self.o.save(name, state)
        state.steps.proposal_notification = "completed"
        self.o.save(name, state)

    def handle_failure(self, run: ProcessingRun, exc: Exception) -> ProcessingOutcome:
        """Record a failed step; called inside ``except`` so the traceback is current."""
        name, state, stage, started = run.name, run.state, run.stage, run.started
        if isinstance(exc, RateLimitExceeded):
            state.deferred_until = datetime.fromtimestamp(exc.next_allowed_at, UTC)
            retry_at = state.deferred_until.isoformat()
            self.o.failure(name, state, ProcessingErrorCode.LLM_RATE_LIMITED, stage,
                          f"LLM-Limit erreicht. Automatischer neuer Versuch nach {retry_at}.", True)
            self.o.logger.event("WARNING", "orchestrator", "llm_rate_limited", mail_id=state.id,
                              next_allowed_at=retry_at, duration_ms=round((time.perf_counter() - started) * 1000, 3),
                              error=exc, stacktrace=traceback.format_exc())
            return ProcessingOutcome.WAITING
        if isinstance(exc, MimeLimitExceeded):
            self.o.failure(name, state, ProcessingErrorCode.MIME_LIMIT_EXCEEDED, stage,
                          "Die Nachricht überschreitet ein Sicherheitslimit. "
                          "Bitte Anhänge oder Nachrichtengröße reduzieren.", False)
            self.o.logger.event("WARNING", "orchestrator", "mime_limit_exceeded", mail_id=state.id, stage=stage.value,
                              limit=exc.limit, error=exc, stacktrace=traceback.format_exc())
            return ProcessingOutcome.FAILED
        if isinstance(exc, LlmProviderResponseInvalid):
            self.o.failure(name, state, ProcessingErrorCode.PROVIDER_RESPONSE_INVALID, stage,
                          "Der LLM-Anbieter hat keine verwendbare Antwort geliefert.", True)
            self.o.logger.event("ERROR", "orchestrator", "provider_response_invalid", mail_id=state.id,
                              stage=stage.value, reason=exc.reason, error=exc, stacktrace=traceback.format_exc())
        elif isinstance(exc, LlmInvalidJson):
            self.o.failure(name, state, ProcessingErrorCode.INVALID_JSON, stage,
                          "Die LLM-Antwort enthielt kein gültiges JSON.", True)
            self.o.logger.event("ERROR", "orchestrator", "invalid_json", mail_id=state.id, stage=stage.value,
                              error=exc, stacktrace=traceback.format_exc())
        elif isinstance(exc, LlmSchemaValidationExceeded):
            state.validation_errors.append(ValidationIssue(
                stage=stage, code="schema_validation_failed", occurred_at=datetime.now(UTC)
            ))
            self.o.failure(name, state, ProcessingErrorCode.SCHEMA_VALIDATION_FAILED, stage,
                          "Die automatische Auswertung war nicht zuverlässig. "
                          "Bitte die Nachricht manuell prüfen.", True)
            self.o.logger.event("ERROR", "orchestrator", "schema_validation_failed", mail_id=state.id,
                              stage=stage.value, error=exc, stacktrace=traceback.format_exc())
        elif isinstance(exc, PermanentError):
            detail = getattr(exc, "safe_detail", None)
            suffix = f" {detail}" if detail else ""
            self.o.failure(name, state, ProcessingErrorCode.PERMANENT_ADAPTER_ERROR, stage,
                          ("Ein externer Dienst hat die Anfrage dauerhaft abgelehnt. "
                           f"Bitte dessen Konfiguration prüfen.{suffix}"), False)
            self.o.logger.event("ERROR", "orchestrator", "permanent_adapter_error", mail_id=state.id, stage=stage.value,
                              error=exc, stacktrace=traceback.format_exc())
        else:
            self.o.failure(name, state, ProcessingErrorCode.INTERNAL_ERROR, stage,
                          "Ein interner Fehler ist aufgetreten. Bitte Protokoll und Konfiguration prüfen.")
            self.o.logger.event("ERROR", "orchestrator", "processing_failed", mail_id=state.id, stage=stage.value,
                              error=exc, duration_ms=round((time.perf_counter() - started) * 1000, 3),
                              stacktrace=traceback.format_exc())
        return self.o.failure_outcome(name, state, stage)
