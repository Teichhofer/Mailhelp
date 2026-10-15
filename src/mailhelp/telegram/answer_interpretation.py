"""Interpretation of durably authorized answers, with its own retry policy."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from pydantic import ValidationError

from ..adapter import RetryableError
from ..analysis import LlmInvalidJson, LlmProviderResponseInvalid, LlmSchemaValidationFailed, LlmTokenLimitExceeded
from ..domain.revision_errors import ContradictoryRevision, IncompleteUserAnswer, TechnicalRevisionError
from ..models import (
    AnswerStatus,
    Proposal,
    ProposalClarificationState,
    ProposalKind,
    ProposalRevisionStatus,
    QuestionStatus,
    TelegramDialogState,
)
from ..persistence.proposals import clarification_name, proposal_name
from ..storage import JsonStore
from ..temporal_answers import (
    deterministic_classification_revision,
    deterministic_temporal_revision,
    expected_event_date,
    normalize_deterministic_temporal_answer,
    parse_deterministic_temporal_answer,
    relative_end_answer,
)
from .client import TelegramTransport
from .revision_contracts import EventLogger, ProposalRevisionService


@dataclass
class AuthorizedAnswerInterpreter:
    store: JsonStore
    revision_service: ProposalRevisionService | None
    telegram: TelegramTransport
    chat_id: int
    logger: EventLogger
    configured_timezone: str
    interpretation_attempts: int
    interpretation_backoff_seconds: int
    revise: Callable[[ProposalClarificationState], None]
    log_failure: Callable[[str, str, int, Exception, ProposalRevisionStatus], None]

    def interpret_pending(self, state: ProposalClarificationState) -> None:
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
        # "nach 3h" for the end question is resolved against the known start.
        temporal_answer = relative_end_answer(
            proposal, state.question, state.authorized_answer, self.configured_timezone
        ) or state.authorized_answer
        local_temporal = (
            proposal.kind == ProposalKind.EVENT
            and parse_deterministic_temporal_answer(temporal_answer, current_date)
            is not None
        )
        try:
            normalized = self._deterministic_answer(proposal, state, temporal_answer, current_date)
            if normalized is not None:
                self._answered(name, state, normalized)
                return
            _, interpretation = self.revision_service.interpret_telegram_answer(
                proposal, state.question, state.authorized_answer
            )
            if not interpretation.usable:
                self._ask_again(name, state, proposal, interpretation.reason, current_date)
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
            self._mark_invalid(name, state)
            message = self._contradiction_message(state, proposal, temporal_answer, current_date)
            self._log_clarification(state, type(exc).__name__)
            self.telegram.send(self.chat_id, message)
            return
        # The validated value is the recovery record.  It must reach disk before
        # removing the active user question or making another fallible LLM call.
        assert interpretation.normalized_answer is not None  # a usable interpretation carries it
        self._answered(name, state, interpretation.normalized_answer)

    def _deterministic_answer(self, proposal: Proposal, state: ProposalClarificationState,
                              temporal_answer: str, current_date: date) -> str | None:
        """The normalized answer when no language model is needed, else ``None``."""
        assert state.authorized_answer is not None  # checked by interpret_pending
        deterministic = deterministic_classification_revision(
            proposal, state.question, state.authorized_answer
        )
        if deterministic is None:
            deterministic = deterministic_temporal_revision(
                proposal,
                state.question,
                temporal_answer,
                self.configured_timezone,
                current_date,
            )
        if deterministic is None:
            return None
        parsed_answer = parse_deterministic_temporal_answer(
            temporal_answer, current_date
        )
        normalized_answer = temporal_answer
        if parsed_answer is not None:
            normalized_answer = normalize_deterministic_temporal_answer(
                parsed_answer
            )
        return normalized_answer

    def _answered(self, name: str, state: ProposalClarificationState, normalized_answer: str) -> None:
        """Persist the valid answer, end the active question, then revise."""
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
        self.revise(answered)

    def _mark_invalid(self, name: str, state: ProposalClarificationState) -> None:
        invalid = state.model_copy(
            update={
                "answer_status": AnswerStatus.INVALID,
                "interpretation_status": ProposalRevisionStatus.COMPLETED,
                "next_interpretation_at": None,
            }
        )
        self.store.save(name, invalid.model_dump(mode="json"))

    def _log_clarification(self, state: ProposalClarificationState, error_class: str) -> None:
        self.logger.event(
            "INFO",
            "telegram.dialog",
            "answer_clarification_requested",
            mail_id=state.mail_id,
            proposal_id=state.proposal_id,
            version=state.version,
            error_class=error_class,
            proposal_reference=f"{state.mail_id}:{state.proposal_id}:v{state.version}",
            revision_status=ProposalRevisionStatus.PENDING.value,
        )

    def _ask_again(self, name: str, state: ProposalClarificationState, proposal: Proposal,
                   reason: str, current_date: date) -> None:
        """An unusable answer: keep the question open and ask more concretely."""
        incomplete = IncompleteUserAnswer(reason)
        self._mark_invalid(name, state)
        assert self.revision_service is not None and state.authorized_answer is not None  # see interpret_pending
        _, clarification = self.revision_service.clarify_telegram_answer(
            state.question,
            state.authorized_answer,
            reason,
            current_date=current_date,
        )
        self._log_clarification(state, type(incomplete).__name__)
        self.telegram.send(self.chat_id,
                           f"❓ {clarification.message}\n"
                           f"„{proposal.title}“ · /abbrechen beendet die Bearbeitung")

    @staticmethod
    def _contradiction_message(state: ProposalClarificationState, proposal: Proposal,
                               temporal_answer: str, current_date: date) -> str:
        """Explain which validated fact a deterministic time answer contradicts."""
        expected = expected_event_date(proposal)
        parsed = parse_deterministic_temporal_answer(temporal_answer, current_date)
        # Without a validated date there is nothing the answer could contradict.
        allowed_dates = (
            set() if expected is None
            else {expected, expected + timedelta(days=1)} if "ende" in state.question.casefold()
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
            assert expected is not None  # part of wrong_date
            return (
                "Das genannte Datum widerspricht dem bereits validierten "
                f"Termindatum. Erwartet wird {expected.isoformat()}. "
                "Bitte bestätige das richtige Datum konkret."
            )
        if "ende" in state.question.casefold() and known_start is not None:
            return (
                f"{known_start.strftime('%H:%M')} Uhr ist bereits als Beginn "
                "belegt und kann nicht zugleich das Ende sein. Bitte nenne "
                "die Endzeit nach dem Beginn konkret."
            )
        return (
            "Die Zeitangabe widerspricht den bereits belegten Terminfakten. "
            "Bitte bestätige Datum und Uhrzeit konkret."
        )

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
                    else datetime.now(UTC)
                    + timedelta(seconds=self.interpretation_backoff_seconds)
                ),
            }
        )
        self.store.save(name, updated.model_dump(mode="json"))
        self.log_failure(
            state.mail_id, state.proposal_id, state.version, exc, status
        )
        if exhausted:
            message = ("Die Interpretation wurde nach mehreren Versuchen pausiert. "
                       "Die gespeicherte Antwort bleibt erhalten.")
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

