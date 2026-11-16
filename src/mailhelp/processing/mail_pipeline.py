"""Stage sequence of one mail (prepare → relevance → summary → actions → notification)."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, cast

from ..config import TargetSettings
from ..domain.deep_links import resolve_client
from ..domain.extraction import ActionRoute, Summary
from ..domain.mail import DisplayHeaders, MailState
from ..domain.prepared import PreparedMail
from ..domain.processing import ProcessingStage, ProposalNotification
from ..domain.proposal import Proposal
from ..domain.relevance import Relevance, RelevanceDialog
from ..mailbox.imap import FetchedMail
from ..mailbox.mime import extract_display_headers, prepare
from ..mailbox.sender_filter import is_irrelevant_sender
from ..notifications.briefing_identity import is_own_briefing
from . import pipeline_failures, pipeline_proposals
from .perspective import Perspective, read_perspective
from .stage_timing import StageClock, part

if TYPE_CHECKING:
    from .orchestrator import Orchestrator


def _content(state: MailState) -> dict[str, Any]:
    """The mail being processed; retention removes content only from finished mails."""
    assert state.mail is not None
    return state.mail


def _perspective(state: MailState) -> Perspective:
    return Perspective(state.self_mail, state.user_note, state.is_forwarding, state.forwarded_headers)


def _with_perspective(state: MailState) -> dict[str, Any]:
    """The mail for routing and extraction, plus who wrote it (4.5); never stored."""
    return _perspective(state).model_input(_content(state))


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
    # 6.1.6: measures each step; every assignment to ``stage`` starts the next one.
    timer: StageClock | None = None

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "stage" and self.__dict__.get("timer") is not None:
            self.__dict__["timer"].enter(value.value)
        object.__setattr__(self, name, value)


class AnalysisDataUnavailable(ValueError):
    """A completed prerequisite has lost its result and cannot be replayed."""


class MailPipeline:
    """Owned by the Orchestrator; reads its services through ``o``."""

    def __init__(self, owner: Orchestrator) -> None:
        self.o = owner

    def advance(self, run: ProcessingRun, fetched: FetchedMail) -> ProcessingResult | None:
        """Run every pending step; a result ends processing early (duplicate, open question)."""
        if run.state.missing_analysis_steps:
            run.stage = ProcessingStage(run.state.missing_analysis_steps[0])
            raise AnalysisDataUnavailable("Analyse-Daten fehlen für einen abgeschlossenen Verarbeitungsschritt.")
        self._prepare(run, fetched)
        state = run.state
        assert state.mail is not None
        if any(item["extraction_status"] == "skipped_oversized"
               for item in state.mail.get("extracted_attachments", [])):
            self._manual_attachment_review(run)
            self._notify_proposals(run)
            return None
        if self.o.duplicates.check(run.name, state):
            duplicate = state.duplicate
            assert duplicate is not None  # check() recorded the decision
            self.o.logger.event("INFO", "orchestrator", "duplicate_skipped", mail_id=state.id,
                              previous_mail_id=duplicate.previous_mail_id)
            return ProcessingResult(ProcessingOutcome.COMPLETED, state.model_dump(mode="json"))
        if self.o.vision is not None and state.steps.relevance == "pending":
            with part(run.timer, "bilderkennung"):
                self.o.read_images(run.name, state, fetched.raw)
        self._relevance(run)
        if state.relevance is None:
            raise AnalysisDataUnavailable("Analyse-Daten fehlen für die Relevanzprüfung.")
        if state.relevance.decision == "irrelevant":
            self._skip_after_irrelevant(state)
        elif state.relevance.decision == "unclear":
            self._ask_relevance(run)
            return ProcessingResult(ProcessingOutcome.WAITING, state.model_dump(mode="json"))
        else:
            self._summarize(run)
            self._detect_actions(run)
            self._notify_proposals(run)
            self._auto_draft(run)
        return None

    def _auto_draft(self, run: ProcessingRun) -> None:
        """4.8: a reply draft without a click; a failure is logged and never stops the mail."""
        state = run.state
        if state.steps.auto_draft != "pending":
            return
        route, drafts = state.action_route, self.o.drafts
        if route is None or not route.reply_needed or drafts is None:
            state.steps.auto_draft = "skipped"
            self.o.save(run.name, state)
            return
        try:
            outcome = drafts.auto_draft(state.id, route.reply_reason)
        except Exception as exc:
            state.steps.auto_draft = "failed"
            self.o.save(run.name, state)
            self.o.logger.event("WARNING", "orchestrator", "auto_draft_failed", mail_id=state.id,
                                error=type(exc).__name__)
            return
        state.steps.auto_draft = "skipped" if outcome == "skipped" else "completed"
        self.o.save(run.name, state)
        self.o.logger.event("INFO", "orchestrator", "auto_draft_completed", mail_id=state.id, outcome=outcome)

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
                    event_defaults=cfg.event_defaults.model_dump(), mailbox_id=mailbox.id,
                    mail_link_kind=resolve_client(mailbox.mail_client, mailbox.host))
            else:
                # 4.7: without mailbox settings the link opens the mail in Apple Mail.
                state.proposal_policy["mail_link_kind"] = "apple_mail"
            if state.display_headers is None:
                display = extract_display_headers(fetched.raw, self.o.max_bytes)
                state.display_headers = DisplayHeaders(sender=display["from"], subject=display["subject"])
                self.o.save(name, state)
            with part(run.timer, "zerlegen"):
                state.mail = prepare(fetched.raw, self.o.max_bytes, fetched.received_at, self.o.user_timezone)
            if is_own_briefing(self.o.store, state.imap.account_id, fetched.raw):
                cast(dict[str, Any], state.mail["metadata"])["mailhelp_briefing"] = True
            cast(list[dict[str, Any]], state.mail["extracted_attachments"]).extend(
                {"filename": filename[:500], "content_type": content_type[:200], "size_bytes": size,
                 "text": "", "extraction_status": "skipped_oversized", "character_count": 0}
                for filename, content_type, size in fetched.oversized_attachments)
            state.mail["internal_id"] = state.id
            perspective = read_perspective(state.mail, self.o.own_addresses(state.imap.account_id))
            state.self_mail, state.user_note = perspective.self_mail, perspective.user_note
            state.is_forwarding, state.forwarded_headers = perspective.is_forwarding, perspective.forwarded_headers
            with part(run.timer, "anhaenge"):
                self.o.cache_previews(state, fetched.raw)
            state.steps.preparation = "completed"
            self.o.save(name, state)
            self.o.logger.event("INFO", "orchestrator", "preparation_completed", mail_id=state.id,
                              preparation_metadata=state.mail["metadata"])

    def _manual_attachment_review(self, run: ProcessingRun) -> None:
        """A deterministic review task survives relevance filtering, LLM failures and restarts."""
        state = run.state
        if state.proposals:
            return
        attachments = _prepared(state).extracted_attachments
        filenames = ", ".join(item.filename for item in attachments if item.extraction_status == "skipped_oversized")
        description = ("Mindestens ein Anhang überschreitet die Grenze für die automatische Texterkennung. "
                       "Bitte die Originalnachricht und ihre Anhänge manuell auf Termine und Aufgaben prüfen. "
                       f"Betroffene Anhänge: {filenames}")[:4000]
        state.relevance = Relevance(decision="relevant", topic_ids=[], reason="Großer Anhang: manuelle Prüfung nötig")
        state.summary = Summary(sentences=["Die Nachricht muss wegen eines zu großen Anhangs manuell geprüft werden."])
        policy = state.proposal_policy or {}
        targets = (TargetSettings.model_validate(policy["targets"]) if "targets" in policy else self.o.targets)
        profile = policy.get("target_profile", 1)
        proposal = Proposal(
            id=f"manual_attachment_{state.id}", version=1, kind="task", responsibility="user", certainty="certain",
            classification="new", title=("Nachricht manuell prüfen: " + _prepared(state).headers.subject)[:500],
            description=description, evidence="Anhang überschreitet die konfigurierte Texterkennungsgrenze.",
            source_mail_id=state.id, target=targets.task_target,
            target_profile=profile, target_provider=targets.task_provider)
        proposal = self.o.reconciliation.save(proposal)
        state.proposals = [proposal]
        state.proposal_notifications = [ProposalNotification(
            proposal_id=proposal.id, proposal_version=proposal.version)]
        state.steps.relevance = state.steps.summary = state.steps.action_detection = "completed"
        state.steps.normalization = state.steps.proposal_building = "completed"
        state.steps.action_router = state.steps.task_extraction = state.steps.event_extraction = "skipped"
        state.steps.duplicate_precheck = state.steps.summary_notification = "skipped"
        self.o.save(run.name, state)
        self.o.logger.event("WARNING", "orchestrator", "attachment_manual_review", mail_id=state.id,
                          proposal_id=proposal.id)

    def _relevance(self, run: ProcessingRun) -> None:
        run.stage = ProcessingStage.RELEVANCE
        state = run.state
        if state.steps.relevance == "pending":
            if _prepared(state).metadata.get("mailhelp_briefing") is True:
                state.relevance = Relevance(decision="irrelevant", topic_ids=[], reason="Eigenes Postfach-Briefing")
                call = None
                self.o.analyzer.last_relevance_source = "prefilter"
            elif state.imap.account_id in self.o.always_relevant:
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
                own = _perspective(state).own_relevance()
                if self.o.mailbox_settings is not None and not any(topic.enabled for topic in topics):
                    call = None
                    state.relevance = Relevance(
                        decision="irrelevant", topic_ids=[], reason="Kein relevantes Thema für dieses Postfach"
                    )
                    self.o.analyzer.last_relevance_source = "prefilter"
                elif own is not None:
                    # 4.5.6: own notes and forwardings skip the topic decision.
                    call, state.relevance = None, own
                    self.o.analyzer.last_relevance_source = "self_mail"
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
        state.steps.auto_draft = "skipped"

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
            # 4.5.9: the summary also learns who wrote the mail (own registration, own note).
            call, summary = self.o.analyzer.summary(_with_perspective(state))
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
        return pipeline_proposals._detect_actions(self, run)

    def _extract(self, run: ProcessingRun, route: ActionRoute, wants_tasks: bool, wants_llm_events: bool) -> None:
        return pipeline_proposals._extract(self, run, route, wants_tasks, wants_llm_events)

    def _build(self, run: ProcessingRun, wanted: bool) -> None:
        return pipeline_proposals._build(self, run, wanted)

    def _notify_proposals(self, run: ProcessingRun) -> None:
        return pipeline_proposals._notify_proposals(self, run)

    def handle_failure(self, run: ProcessingRun, exc: Exception) -> ProcessingOutcome:
        return pipeline_failures.handle_failure(self, run, exc)
