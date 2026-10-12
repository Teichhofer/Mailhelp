"""Durable answer/revision recovery and compatibility with legacy dialogs."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from .. import state_names
from ..analysis import validate_revision_successor
from ..models import (
    AnswerStatus,
    Proposal,
    ProposalClarificationState,
    ProposalRevisionStatus,
    QuestionStatus,
    TelegramDialogState,
)
from ..storage import JsonStore
from .persistence import proposal_name
from .revision_contracts import EventLogger, ProposalRevisionService
from .writes import ProposalPersistence


@dataclass
class RevisionRecovery:
    store: JsonStore
    revision_service: ProposalRevisionService | None
    persistence: ProposalPersistence
    logger: EventLogger
    interpretation_attempts: int
    interpret: Callable[[ProposalClarificationState], None]
    revise: Callable[[ProposalClarificationState], None]

    def resume_durable(self) -> None:
        if self.revision_service is None:
            return
        for name in self.store.names(state_names.CLARIFICATION_PREFIX):
            state = self.store.load_model(name, ProposalClarificationState)
            assert isinstance(state, ProposalClarificationState)
            now = datetime.now(UTC)
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
                self.interpret(state)
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
                self.revise(state)


    def resume_legacy(self) -> None:
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

