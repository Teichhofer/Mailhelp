"""Proposal answer interpretation, revision retries, and recovery."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

import httpx
from pydantic import ValidationError

from ..adapter import RetryableError
from ..analysis import ContradictoryRevision, TechnicalRevisionError
from ..models import AnswerStatus, MailState, Proposal, ProposalClarificationState, ProposalClassification, ProposalRevisionStatus, ProposalStatus, QuestionStatus, TelegramDialogState
from ..storage import JsonStore

from .client import TelegramTransport
from .persistence import clarification_name, proposal_name, proposal_version_name
from .formatting import clarification_prompt
from .writes import ProposalPersistence
from .revision_contracts import ProposalRevisionService, EventLogger
from .answer_interpretation import AuthorizedAnswerInterpreter
from .revision_recovery import RevisionRecovery
from .revision_successor import build_revision_successor
from .. import state_names


class ProposalRevisions(Protocol):
    def answer(self, answer: str) -> None: ...
    def resume(self) -> None: ...


class ProposalRevisionProcessor:
    """Own authorized answers, revision retries, and restart recovery."""

    def __init__(
        self,
        store: JsonStore,
        revision_service: ProposalRevisionService | None,
        persistence: ProposalPersistence,
        telegram: TelegramTransport,
        chat_id: int,
        logger: EventLogger,
        configured_timezone: str,
        *,
        interpretation_attempts: int,
        interpretation_backoff_seconds: int,
        revision_attempts: int,
        revision_backoff_seconds: int,
    ):
        self.store, self.revision_service = store, revision_service
        self.persistence, self.telegram, self.chat_id = persistence, telegram, chat_id
        self.logger, self.configured_timezone = logger, configured_timezone
        self.interpretation_attempts = interpretation_attempts
        self.interpretation_backoff_seconds = interpretation_backoff_seconds
        self.revision_attempts = revision_attempts
        self.revision_backoff_seconds = revision_backoff_seconds

    def resume(self) -> None:
        recovery = RevisionRecovery(
            self.store, self.revision_service, self.persistence, self.logger,
            self.interpretation_attempts, self._interpret_pending, self._revise_answered,
        )
        recovery.resume_durable()
        recovery.resume_legacy()

    def answer(self, answer: str) -> None:
        dialog = self.store.load_model("telegram-dialog", TelegramDialogState)
        if dialog is None or dialog.proposal_id is None:
            self.logger.event(
                "INFO", "telegram.dialog", "answer_rejected", reason="no_open_dialog"
            )
            self.telegram.send(
                self.chat_id, "Keine offene Rückfrage. Bitte /offen öffnen und beim gewünschten Vorschlag „Klären“, „Ändern“ oder „Manuell prüfen“ wählen."
            )
            return
        assert dialog.mail_id is not None
        proposal = self._dialog_proposal(dialog)
        if proposal is None:
            return
        question = (
            proposal.open_questions[0]
            if proposal.open_questions
            else "Welche Änderung soll übernommen werden?"
        )
        clarification_record_name = clarification_name(
            dialog.mail_id, dialog.proposal_id, dialog.version
        )
        if self._already_answered(clarification_record_name):
            return
        normalized_answer = " ".join(answer.casefold().strip().rstrip(".!?").split())
        if (
            proposal.classification == ProposalClassification.NON_BINDING
            and normalized_answer == "nein"
        ):
            self._reject_non_binding(dialog, proposal, question, answer, clarification_record_name)
            return
        if self.revision_service is None:
            self.logger.event(
                "ERROR",
                "telegram.dialog",
                "answer_revision_unavailable",
                mail_id=dialog.mail_id,
                proposal_id=dialog.proposal_id,
                version=dialog.version,
            )
            self.telegram.send(
                self.chat_id,
                "Die Überarbeitung ist derzeit nicht verfügbar; der Vorschlag blieb unverändert.",
            )
            return
        # This is the acknowledgement boundary: persist the authorized input
        # atomically before the first fallible interpretation call.  The raw
        # answer exists only in this state file and is never added to logs.
        pending = ProposalClarificationState(
            mail_id=dialog.mail_id,
            proposal_id=dialog.proposal_id,
            version=dialog.version,
            question=question,
            authorized_answer=answer,
        )
        self.store.save(clarification_record_name, pending.model_dump(mode="json"))
        self._interpret_pending(pending)

    def _dialog_proposal(self, dialog: TelegramDialogState) -> Proposal | None:
        """The proposal the open question belongs to; ``None`` ends a missing or stale dialog."""
        proposal = self.store.load_model(
            proposal_name(dialog.mail_id, dialog.proposal_id), Proposal
        )
        if proposal is None:
            self.logger.event(
                "WARNING",
                "telegram.dialog",
                "answer_rejected",
                reason="proposal_missing",
                mail_id=dialog.mail_id,
                proposal_id=dialog.proposal_id,
                version=dialog.version,
            )
            self.store.save("telegram-dialog", TelegramDialogState().model_dump())
            self.telegram.send(
                self.chat_id, "Der zugehörige Vorschlag wurde nicht gefunden."
            )
            return None
        assert isinstance(proposal, Proposal)
        if (
            proposal.version != dialog.version
            or proposal.status != ProposalStatus.NEEDS_CLARIFICATION
        ):
            self.logger.event(
                "WARNING",
                "telegram.dialog",
                "answer_rejected",
                reason="stale_dialog",
                mail_id=dialog.mail_id,
                proposal_id=dialog.proposal_id,
                dialog_version=dialog.version,
                proposal_version=proposal.version,
                proposal_status=proposal.status.value,
            )
            self.store.save("telegram-dialog", TelegramDialogState().model_dump())
            self.telegram.send(
                self.chat_id, "Die Rückfrage ist veraltet; es wurde nichts geändert."
            )
            return None
        return proposal

    def _already_answered(self, clarification_record_name: str) -> bool:
        """An answer for this version is already stored; tell the user instead of storing a second one."""
        existing = self.store.load_model(
            clarification_record_name, ProposalClarificationState
        )
        if isinstance(existing, ProposalClarificationState):
            if existing.question_status == QuestionStatus.ANSWERED:
                self.store.save(
                    "telegram-dialog", TelegramDialogState().model_dump(mode="json")
                )
                self.telegram.send(
                    self.chat_id,
                    "Keine offene Rückfrage. Die vorherige Antwort ist bereits gespeichert.",
                )
                return True
            if (
                existing.authorized_answer is not None
                and existing.answer_status == AnswerStatus.PENDING
            ):
                self.telegram.send(
                    self.chat_id,
                    "Die autorisierte Antwort ist bereits sicher gespeichert und wird verarbeitet.",
                )
                return True
        return False

    def _reject_non_binding(self, dialog: TelegramDialogState, proposal: Proposal, question: str,
                            answer: str, clarification_record_name: str) -> None:
        """"Nein" to a non-binding hint rejects it without any language model."""
        rejected = proposal.model_copy(update={"status": ProposalStatus.REJECTED})
        self.persistence.persist(rejected)
        answered = ProposalClarificationState(
            mail_id=dialog.mail_id,
            proposal_id=dialog.proposal_id,
            version=dialog.version,
            question=question,
            authorized_answer=answer,
            interpretation_status=ProposalRevisionStatus.COMPLETED,
            question_status=QuestionStatus.ANSWERED,
            answer_status=AnswerStatus.VALID,
            normalized_answer="Nein",
            proposal_revision_status=ProposalRevisionStatus.COMPLETED,
        )
        self.store.save(
            clarification_record_name, answered.model_dump(mode="json")
        )
        self.store.save(
            "telegram-dialog", TelegramDialogState().model_dump(mode="json")
        )
        self.logger.event(
            "INFO",
            "telegram.dialog",
            "proposal_rejected_by_clarification",
            mail_id=dialog.mail_id,
            proposal_id=dialog.proposal_id,
            version=dialog.version,
        )
        self.telegram.send(self.chat_id, "✅ Vorschlag wurde verworfen.")

    def _interpret_pending(self, state: ProposalClarificationState) -> None:
        interpreter = AuthorizedAnswerInterpreter(
            self.store, self.revision_service, self.telegram, self.chat_id,
            self.logger, self.configured_timezone, self.interpretation_attempts,
            self.interpretation_backoff_seconds, self._revise_answered,
            self._log_revision_failure,
        )
        interpreter.interpret_pending(state)


    def _revise_answered(self, state: ProposalClarificationState) -> None:
        """Retry a revision solely from its already validated durable answer."""
        name = clarification_name(state.mail_id, state.proposal_id, state.version)
        current = self.store.load_model(
            proposal_name(state.mail_id, state.proposal_id), Proposal
        )
        if isinstance(current, Proposal) and current.version > state.version:
            self._finish_superseded(name, state, current)
            return
        original = self.store.load_model(
            proposal_version_name(state.mail_id, state.proposal_id, state.version),
            Proposal,
        )
        if not isinstance(original, Proposal) or self.revision_service is None:
            return
        try:
            revised, deterministic = build_revision_successor(
                original, state.question, state.normalized_answer,
                self.configured_timezone, self.revision_service,
            )
        except Exception as exc:
            self._revision_failed(name, state, exc)
            return
        if deterministic:
            self.logger.event(
                "INFO",
                "analysis",
                "proposal_revision_delta_applied",
                proposal_id=original.id,
                previous_version=original.version,
                new_version=revised.version,
            )
        self.persistence.send_proposal(revised)
        self.store.save(
            name,
            state.model_copy(
                update={
                    "proposal_revision_status": ProposalRevisionStatus.COMPLETED,
                    "next_revision_at": None,
                }
            ).model_dump(mode="json"),
        )
        self._continue_clarification(revised)
        self.logger.event(
            "INFO",
            "telegram.dialog",
            "answer_revision_completed",
            mail_id=state.mail_id,
            proposal_id=state.proposal_id,
            previous_version=state.version,
            new_version=revised.version,
        )

    def _finish_superseded(self, name: str, state: ProposalClarificationState, current: Proposal) -> None:
        """The successor already exists (crash after writing it): only deliver and complete."""
        mail = self.store.load_model(state_names.mail(state.mail_id), MailState)
        notification = (
            next(
                (
                    item
                    for item in mail.proposal_notifications
                    if (item.proposal_id, item.proposal_version)
                    == (current.id, current.version)
                ),
                None,
            )
            if isinstance(mail, MailState)
            else None
        )
        if notification is None or notification.status == "pending":
            self.persistence.send_proposal(current)
        elif notification.status != "completed":
            return
        self.store.save(
            name,
            state.model_copy(
                update={
                    "proposal_revision_status": ProposalRevisionStatus.COMPLETED,
                }
            ).model_dump(mode="json"),
        )

    def _revision_failed(self, name: str, state: ProposalClarificationState, exc: Exception) -> None:
        """Keep question and answer; retry later or pause after the configured attempts."""
        classified = (
            exc
            if isinstance(
                exc,
                (
                    ContradictoryRevision,
                    TechnicalRevisionError,
                    RetryableError,
                    ValidationError,
                    httpx.TransportError,
                ),
            )
            else TechnicalRevisionError(type(exc).__name__)
        )
        attempts = state.revision_attempts + 1
        exhausted = attempts >= self.revision_attempts
        status = (
            ProposalRevisionStatus.PAUSED
            if exhausted
            else ProposalRevisionStatus.RETRY_REQUIRED
        )
        self._log_revision_failure(
            state.mail_id, state.proposal_id, state.version, classified, status
        )
        # The question and validated answer deliberately remain untouched.
        updated = state.model_copy(
            update={
                "proposal_revision_status": status,
                "revision_attempts": attempts,
                "next_revision_at": (
                    None
                    if exhausted
                    else datetime.now(timezone.utc)
                    + timedelta(seconds=self.revision_backoff_seconds)
                ),
            }
        )
        self.store.save(name, updated.model_dump(mode="json"))
        self.telegram.send(
            self.chat_id,
            (
                "Die Überarbeitung der gespeicherten Antwort wurde nach mehreren Versuchen pausiert. "
                "Die Antwort bleibt erhalten. Zur Wiederaufnahme muss ein Betreiber den "
                "Revisionsstatus auf retry_required setzen und Mailhelp neu starten."
                if exhausted
                else "Die interne Verarbeitung der gespeicherten Antwort ist verzögert."
            ),
        )

    def _continue_clarification(self, proposal: Proposal) -> None:
        """Ask the next open question at once instead of waiting for another press.

        Only for a version the user has actually been shown; a version still held
        back in the outbox gets its question when it is delivered and selected.
        """
        delivered = getattr(self.persistence, "delivered", None)
        if (
            proposal.status != ProposalStatus.NEEDS_CLARIFICATION
            or not proposal.open_questions
            or delivered is None
            or not delivered(proposal)
        ):
            return
        self.store.save(
            "telegram-dialog",
            TelegramDialogState(
                mail_id=proposal.source_mail_id,
                proposal_id=proposal.id,
                version=proposal.version,
            ).model_dump(mode="json"),
        )
        self.telegram.send(
            self.chat_id, clarification_prompt(proposal, self.configured_timezone)
        )

    def _log_revision_failure(
        self,
        mail_id: str,
        proposal_id: str,
        version: int,
        exc: Exception,
        status: ProposalRevisionStatus,
    ) -> None:
        """Log a revision failure without untrusted answer or question content."""
        fields: dict[str, Any] = {}
        if isinstance(exc, ValidationError):
            fields["validation_errors"] = [
                {
                    "location": [str(part) for part in error["loc"]],
                    "type": error["type"],
                    "message": error["msg"],
                }
                for error in exc.errors(
                    include_url=False, include_context=False, include_input=False
                )
            ]
        self.logger.event(
            "WARNING",
            "telegram.dialog",
            "answer_revision_failed",
            mail_id=mail_id,
            proposal_id=proposal_id,
            version=version,
            error_class=type(exc).__name__,
            proposal_reference=f"{mail_id}:{proposal_id}:v{version}",
            revision_status=status.value,
            **fields,
        )
