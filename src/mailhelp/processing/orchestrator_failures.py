"""Failures of the mail processing: record, classify and resolve them (7.0, R5)."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal, cast

from .. import state_names
from ..domain.mail import MailState
from ..domain.processing import ProcessingError, ProcessingErrorCode, ProcessingStage
from ..domain.relevance import Relevance, RelevanceDialogStatus
from ..telegram.formatting import mail_line
from .mail_pipeline import ProcessingOutcome
from .retry import failed

if TYPE_CHECKING:
    from .orchestrator import Orchestrator


def failure(orchestrator: Orchestrator, name: str, state: MailState, code: ProcessingErrorCode,
             stage: ProcessingStage, text: str, retryable: bool | None = None) -> None:
    """Mark before sending, and retain a matching generation across restarts."""
    now = datetime.now(UTC)
    error = state.error
    if error is None or error.code != code or error.stage != stage:
        error = state.error = ProcessingError(code=code, stage=stage, occurred_at=now, retryable=retryable)
    failed(state, orchestrator.fingerprint_for(state.imap.account_id), now)
    retry = state.processing_retry
    if retry is not None and not retry.abandoned:
        orchestrator.save(name, state)
        return
    if retry is not None:
        if retry.notification_marked_at is not None:
            orchestrator.save(name, state)
            return
        retry.notification_marked_at = now
        text = "Mail wird nicht weiter versucht. " + text
        settings = getattr(orchestrator, "mailbox_settings", None)
        if settings is not None and settings.web.enabled:
            # Late: against the layer direction, named in tests/unit/test_layers.py.
            from ..web.factory import base_url
            text += "\n" + base_url(settings) + "/mail/" + state.id
        error.notification_marked_at = None
    if error.notification_marked_at is not None:
        orchestrator.save(name, state)
        return
    error.notification_marked_at = now
    orchestrator.save(name, state)
    if state.prepared is not None:
        sender, subject = state.prepared.headers.sender, state.prepared.headers.subject
    else:
        display = state.display_headers
        sender, subject = (display.sender, display.subject) if display else ("—", "—")
    orchestrator.notifier.send(
        orchestrator.chat_id,
        "\n".join([
            mail_line(sender or "—", subject or "—"),
            f"⚠️ Schritt {stage.value}: {text}",
        ]),
    )


def failure_outcome(orchestrator: Orchestrator, name: str, state: MailState,
                     stage: ProcessingStage) -> ProcessingOutcome:
    """Complete the mail while retaining a retryable action-only failure."""
    action_stages = {ProcessingStage.ACTION_ROUTER, ProcessingStage.TASK_EXTRACTION,
                     ProcessingStage.EVENT_EXTRACTION, ProcessingStage.NORMALIZATION,
                     ProcessingStage.PROPOSAL_BUILDING, ProcessingStage.DUPLICATE_PRECHECK}
    if stage not in action_stages:
        return ProcessingOutcome.FAILED
    step_name = {
        ProcessingStage.ACTION_ROUTER: "action_router",
        ProcessingStage.TASK_EXTRACTION: "task_extraction",
        ProcessingStage.EVENT_EXTRACTION: "event_extraction",
        ProcessingStage.NORMALIZATION: "normalization",
        ProcessingStage.PROPOSAL_BUILDING: "proposal_building",
        ProcessingStage.DUPLICATE_PRECHECK: "duplicate_precheck",
    }[stage]
    setattr(state.steps, step_name, "failed")
    state.steps.action_detection = "failed"
    state.steps.proposal_notification = "pending"
    state.steps.completion = "completed"
    orchestrator.save(name, state)
    return ProcessingOutcome.COMPLETED_WITH_ACTION_ERROR


def resolve_relevance(orchestrator: Orchestrator, mail_id: str, version: int, decision: str,
                      telegram_offset: int) -> MailState:
    name = state_names.mail(mail_id)
    state = orchestrator.store.load_model(name, MailState)
    if not isinstance(state, MailState) or state.relevance_dialog is None:
        raise ValueError("Relevanzfrage wurde nicht gefunden")
    dialog = state.relevance_dialog
    if dialog.mail_id != mail_id or dialog.version != version or dialog.status != RelevanceDialogStatus.OPEN:
        raise ValueError("Die Relevanzfrage ist veraltet oder bereits beantwortet")
    if decision not in {"relevant", "irrelevant"}:
        raise ValueError("Ungültige Relevanzentscheidung")
    state.relevance = Relevance(
        decision=cast(Literal["relevant", "irrelevant"], decision), topic_ids=[], reason="Telegram-Entscheidung"
    )
    state.awaiting_relevance = False
    state.relevance_dialog = dialog.model_copy(update={
        "status": RelevanceDialogStatus.DECIDED, "decision": decision, "telegram_offset": telegram_offset})
    if decision == "irrelevant":
        state.steps.summary = state.steps.action_detection = "skipped"
        state.steps.action_router = state.steps.task_extraction = state.steps.event_extraction = "skipped"
        state.steps.normalization = state.steps.proposal_building = "skipped"
        state.steps.duplicate_precheck = "skipped"
        state.steps.summary_notification = state.steps.proposal_notification = "skipped"
        state.steps.auto_draft = "skipped"
        state.steps.completion = "completed"
    else:
        state.steps.summary_notification = "pending"
    orchestrator.save(name, state)
    return state
