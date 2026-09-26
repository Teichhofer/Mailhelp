"""Proposal answer interpretation, revision retries, and recovery."""

from __future__ import annotations

from datetime import date as calendar_date, datetime, timedelta, timezone
from typing import Any, Protocol
from zoneinfo import ZoneInfo

import httpx
from pydantic import ValidationError

from ..adapter import RetryableError
from ..analysis import (
    ContradictoryRevision,
    IncompleteUserAnswer,
    LlmInvalidJson,
    LlmProviderResponseInvalid,
    LlmSchemaValidationFailed,
    LlmTokenLimitExceeded,
    TechnicalRevisionError,
    validate_revision_successor,
)
from ..models import (
    AnswerStatus,
    MailState,
    Proposal,
    ProposalClarificationState,
    ProposalClassification,
    ProposalKind,
    ProposalRevisionStatus,
    ProposalStatus,
    QuestionStatus,
    TelegramDialogState,
    TelegramAnswerInterpretation,
    TelegramClarification,
)
from ..storage import JsonStore

from .client import TelegramTransport
from .persistence import clarification_name, proposal_name, proposal_version_name
from .temporal import (
    deterministic_classification_revision,
    deterministic_temporal_revision,
    normalize_deterministic_temporal_answer,
    parse_deterministic_temporal_answer,
)
from .writes import ProposalPersistence


class ProposalRevisionService(Protocol):
    def interpret_telegram_answer(
        self, proposal: Proposal, question: str, authorized_answer: str
    ) -> tuple[str, TelegramAnswerInterpretation]: ...
    def clarify_telegram_answer(
        self,
        question: str,
        authorized_answer: str,
        reason: str,
        *,
        current_date: calendar_date | None = None,
    ) -> tuple[str, TelegramClarification]: ...
    def revise_proposal(
        self, proposal: Proposal, question: str, authorized_answer: str
    ) -> tuple[str, Proposal]: ...


class EventLogger(Protocol):
    def event(self, level: str, module: str, event: str, **fields: Any) -> None: ...


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
        self._resume_durable_revisions()
        self._resume_legacy_revision()

    def answer(self, answer: str) -> None:
        dialog = self.store.load_model("telegram-dialog", TelegramDialogState)
        if dialog is None or dialog.proposal_id is None:
            self.logger.event(
                "INFO", "telegram.dialog", "answer_rejected", reason="no_open_dialog"
            )
            self.telegram.send(
                self.chat_id, "Keine offene Rückfrage. Bitte zuerst „Ändern“ wählen."
            )
            return
        assert dialog.mail_id is not None
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
            return
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
            return
        question = (
            proposal.open_questions[0]
            if proposal.open_questions
            else "Welche Änderung soll übernommen werden?"
        )
        clarification_record_name = clarification_name(
            dialog.mail_id, dialog.proposal_id, dialog.version
        )
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
                return
            if (
                existing.authorized_answer is not None
                and existing.answer_status == AnswerStatus.PENDING
            ):
                self.telegram.send(
                    self.chat_id,
                    "Die autorisierte Antwort ist bereits sicher gespeichert und wird verarbeitet.",
                )
                return
        normalized_answer = " ".join(answer.casefold().strip().rstrip(".!?").split())
        if (
            proposal.classification == ProposalClassification.NON_BINDING
            and normalized_answer == "nein"
        ):
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

    def _interpret_pending(self, state: ProposalClarificationState) -> None:
        """Interpret one durably stored authorized answer without logging it."""
        assert state.authorized_answer is not None
        name = clarification_name(state.mail_id, state.proposal_id, state.version)
        proposal = self.store.load_model(
            proposal_name(state.mail_id, state.proposal_id), Proposal
        )
        if not isinstance(proposal, Proposal) or proposal.version != state.version:
            return
        assert self.revision_service is not None
        current_date = datetime.now(ZoneInfo(self.configured_timezone)).date()
        local_temporal = (
            proposal.kind == ProposalKind.EVENT
            and parse_deterministic_temporal_answer(
                state.authorized_answer, current_date
            )
            is not None
        )
        try:
            deterministic = deterministic_classification_revision(
                proposal, state.question, state.authorized_answer
            )
            if deterministic is None:
                deterministic = deterministic_temporal_revision(
                    proposal,
                    state.question,
                    state.authorized_answer,
                    self.configured_timezone,
                    current_date,
                )
            if deterministic is not None:
                parsed_answer = parse_deterministic_temporal_answer(
                    state.authorized_answer, current_date
                )
                normalized_answer = state.authorized_answer
                if parsed_answer is not None:
                    normalized_answer = normalize_deterministic_temporal_answer(
                        parsed_answer
                    )
                answered = ProposalClarificationState(
                    mail_id=state.mail_id,
                    proposal_id=state.proposal_id,
                    version=state.version,
                    question=state.question,
                    authorized_answer=state.authorized_answer,
                    interpretation_status=ProposalRevisionStatus.COMPLETED,
                    interpretation_attempts=state.interpretation_attempts,
                    question_status=QuestionStatus.ANSWERED,
                    answer_status=AnswerStatus.VALID,
                    normalized_answer=normalized_answer,
                    proposal_revision_status=ProposalRevisionStatus.RETRY_REQUIRED,
                )
                self.store.save(name, answered.model_dump(mode="json"))
                self.store.save(
                    "telegram-dialog", TelegramDialogState().model_dump(mode="json")
                )
                self._revise_answered(answered)
                return
            _, interpretation = self.revision_service.interpret_telegram_answer(
                proposal, state.question, state.authorized_answer
            )
            if not interpretation.usable:
                incomplete = IncompleteUserAnswer(interpretation.reason)
                invalid = state.model_copy(
                    update={
                        "answer_status": AnswerStatus.INVALID,
                        "interpretation_status": ProposalRevisionStatus.COMPLETED,
                        "next_interpretation_at": None,
                    }
                )
                self.store.save(name, invalid.model_dump(mode="json"))
                _, clarification = self.revision_service.clarify_telegram_answer(
                    state.question,
                    state.authorized_answer,
                    interpretation.reason,
                    current_date=current_date,
                )
                self.logger.event(
                    "INFO",
                    "telegram.dialog",
                    "answer_clarification_requested",
                    mail_id=state.mail_id,
                    proposal_id=state.proposal_id,
                    version=state.version,
                    error_class=type(incomplete).__name__,
                    proposal_reference=f"{state.mail_id}:{state.proposal_id}:v{state.version}",
                    revision_status=ProposalRevisionStatus.PENDING.value,
                )
                self.telegram.send(self.chat_id, clarification.message)
                return
        except (
            LlmProviderResponseInvalid,
            LlmInvalidJson,
            LlmSchemaValidationFailed,
            RetryableError,
            TechnicalRevisionError,
            ValidationError,
            httpx.TransportError,
        ) as exc:
            self._defer_interpretation(name, state, exc)
            return
        except ContradictoryRevision as exc:
            if not local_temporal:
                self._defer_interpretation(name, state, exc, contradictory=True)
                return
            invalid = state.model_copy(
                update={
                    "answer_status": AnswerStatus.INVALID,
                    "interpretation_status": ProposalRevisionStatus.COMPLETED,
                    "next_interpretation_at": None,
                }
            )
            self.store.save(name, invalid.model_dump(mode="json"))
            expected = (
                proposal.known_temporal_facts.date
                if proposal.known_temporal_facts is not None
                else proposal.temporal_fact.normalized_date
                if proposal.temporal_fact is not None
                else None
            )
            parsed = parse_deterministic_temporal_answer(
                state.authorized_answer, current_date
            )
            allowed_dates = (
                {expected, expected + timedelta(days=1)}
                if "ende" in state.question.casefold()
                else {expected}
            )
            wrong_date = (
                parsed is not None
                and parsed.date is not None
                and expected is not None
                and parsed.date not in allowed_dates
            )
            known_start = (
                proposal.known_temporal_facts.start
                if proposal.known_temporal_facts is not None
                else proposal.start
            )
            if wrong_date:
                message = (
                    "Das genannte Datum widerspricht dem bereits validierten "
                    f"Termindatum. Erwartet wird {expected.isoformat()}. "
                    "Bitte bestätige das richtige Datum konkret."
                )
            elif "ende" in state.question.casefold() and known_start is not None:
                message = (
                    f"{known_start.strftime('%H:%M')} Uhr ist bereits als Beginn "
                    "belegt und kann nicht zugleich das Ende sein. Bitte nenne "
                    "die Endzeit nach dem Beginn konkret."
                )
            else:
                message = (
                    "Die Zeitangabe widerspricht den bereits belegten Terminfakten. "
                    "Bitte bestätige Datum und Uhrzeit konkret."
                )
            self.logger.event(
                "INFO",
                "telegram.dialog",
                "answer_clarification_requested",
                mail_id=state.mail_id,
                proposal_id=state.proposal_id,
                version=state.version,
                error_class=type(exc).__name__,
                proposal_reference=f"{state.mail_id}:{state.proposal_id}:v{state.version}",
                revision_status=ProposalRevisionStatus.PENDING.value,
            )
            self.telegram.send(self.chat_id, message)
            return
        # The validated value is the recovery record.  It must reach disk before
        # removing the active user question or making another fallible LLM call.
        answered = ProposalClarificationState(
            mail_id=state.mail_id,
            proposal_id=state.proposal_id,
            version=state.version,
            question=state.question,
            authorized_answer=state.authorized_answer,
            interpretation_status=ProposalRevisionStatus.COMPLETED,
            interpretation_attempts=state.interpretation_attempts,
            question_status=QuestionStatus.ANSWERED,
            answer_status=AnswerStatus.VALID,
            normalized_answer=interpretation.normalized_answer,
            proposal_revision_status=ProposalRevisionStatus.RETRY_REQUIRED,
        )
        self.store.save(name, answered.model_dump(mode="json"))
        self.store.save(
            "telegram-dialog", TelegramDialogState().model_dump(mode="json")
        )
        self._revise_answered(answered)

    def _defer_interpretation(
        self,
        name: str,
        state: ProposalClarificationState,
        exc: Exception,
        *,
        contradictory: bool = False,
    ) -> None:
        attempts = state.interpretation_attempts + 1
        exhausted = attempts >= self.interpretation_attempts
        status = (
            ProposalRevisionStatus.PAUSED
            if exhausted
            else ProposalRevisionStatus.RETRY_REQUIRED
        )
        updated = state.model_copy(
            update={
                "interpretation_status": status,
                "interpretation_attempts": attempts,
                "next_interpretation_at": (
                    None
                    if exhausted
                    else datetime.now(timezone.utc)
                    + timedelta(seconds=self.interpretation_backoff_seconds)
                ),
            }
        )
        self.store.save(name, updated.model_dump(mode="json"))
        self._log_revision_failure(
            state.mail_id, state.proposal_id, state.version, exc, status
        )
        if exhausted:
            message = "Die Interpretation wurde nach mehreren Versuchen pausiert. Die gespeicherte Antwort bleibt erhalten."
        elif contradictory:
            message = "Die Antwort widerspricht möglicherweise dem bestehenden Vorschlag und wird erneut geprüft."
        else:
            message = (
                (
                    "Technischer Abbruch: Das Modell hat sein Ausgabetokenlimit erreicht. "
                    "Die sicher gespeicherte Antwort wird mit der Ausweichstrategie erneut bewertet."
                )
                if isinstance(exc, LlmTokenLimitExceeded)
                else "Die interne Verarbeitung ist verzögert. Die sicher gespeicherte Antwort wird erneut bewertet."
            )
        self.telegram.send(self.chat_id, message)

    def _revise_answered(self, state: ProposalClarificationState) -> None:
        """Retry a revision solely from its already validated durable answer."""
        name = clarification_name(state.mail_id, state.proposal_id, state.version)
        current = self.store.load_model(
            proposal_name(state.mail_id, state.proposal_id), Proposal
        )
        if isinstance(current, Proposal) and current.version > state.version:
            mail = self.store.load_model(f"mail-{state.mail_id}", MailState)
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
            return
        original = self.store.load_model(
            proposal_version_name(state.mail_id, state.proposal_id, state.version),
            Proposal,
        )
        if not isinstance(original, Proposal) or self.revision_service is None:
            return
        try:
            candidate = deterministic_classification_revision(
                original, state.question, state.normalized_answer
            )
            if candidate is None:
                candidate = deterministic_temporal_revision(
                    original,
                    state.question,
                    state.normalized_answer,
                    self.configured_timezone,
                )
            deterministic = candidate is not None
            if candidate is None:
                _, candidate = self.revision_service.revise_proposal(
                    original, state.question, state.normalized_answer
                )
            revised = validate_revision_successor(original, candidate)
        except Exception as exc:
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
        self.logger.event(
            "INFO",
            "telegram.dialog",
            "answer_revision_completed",
            mail_id=state.mail_id,
            proposal_id=state.proposal_id,
            previous_version=state.version,
            new_version=revised.version,
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

    def _resume_durable_revisions(self) -> None:
        if self.revision_service is None or not hasattr(self.store, "names"):
            return
        for name in self.store.names("clarification-"):
            state = self.store.load_model(name, ProposalClarificationState)
            assert isinstance(state, ProposalClarificationState)
            now = datetime.now(timezone.utc)
            if (
                state.answer_status == AnswerStatus.PENDING
                and state.authorized_answer is not None
                and state.interpretation_status
                in {
                    ProposalRevisionStatus.PENDING,
                    ProposalRevisionStatus.RETRY_REQUIRED,
                }
                and state.interpretation_attempts < self.interpretation_attempts
                and (
                    state.next_interpretation_at is None
                    or state.next_interpretation_at <= now
                )
            ):
                self._interpret_pending(state)
                # Interpretation can replace this record with an answered one;
                # load it again so revision can continue in the same resume.
                state = self.store.load_model(name, ProposalClarificationState)
                assert isinstance(state, ProposalClarificationState)
            if (
                state.question_status == QuestionStatus.ANSWERED
                and state.proposal_revision_status
                == ProposalRevisionStatus.RETRY_REQUIRED
                and (state.next_revision_at is None or state.next_revision_at <= now)
            ):
                self._revise_answered(state)

    def _resume_legacy_revision(self) -> None:
        """Resume a durable normalized answer without asking the person again."""
        dialog = self.store.load_model("telegram-dialog", TelegramDialogState)
        if not isinstance(dialog, TelegramDialogState) or not dialog.retry_required:
            return
        assert dialog.mail_id and dialog.proposal_id and dialog.version
        assert dialog.question and dialog.normalized_answer
        proposal = self.store.load_model(
            proposal_name(dialog.mail_id, dialog.proposal_id), Proposal
        )
        if not isinstance(proposal, Proposal) or proposal.version != dialog.version:
            self.store.save("telegram-dialog", TelegramDialogState().model_dump())
            return
        if self.revision_service is None:
            return
        try:
            _, revised = self.revision_service.revise_proposal(
                proposal, dialog.question, dialog.normalized_answer
            )
            revised = validate_revision_successor(proposal, revised)
        except Exception as exc:
            self.logger.event(
                "WARNING",
                "telegram.dialog",
                "answer_revision_resume_failed",
                mail_id=dialog.mail_id,
                proposal_id=dialog.proposal_id,
                version=dialog.version,
                error=exc,
            )
            return
        self.persistence.send_proposal(revised)
        self.store.save("telegram-dialog", TelegramDialogState().model_dump())
        self.logger.event(
            "INFO",
            "telegram.dialog",
            "answer_revision_resumed",
            mail_id=dialog.mail_id,
            proposal_id=dialog.proposal_id,
            previous_version=dialog.version,
            new_version=revised.version,
        )
