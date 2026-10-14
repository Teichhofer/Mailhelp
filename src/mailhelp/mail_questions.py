"""Answer open proposal questions from the source mail before asking on Telegram."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .analysis import LlmSchemaValidationExceeded
from .domain.revision_errors import TechnicalRevisionError
from .models import (
    MailState,
    Proposal,
)
from .temporal_answers import deterministic_temporal_revision

if TYPE_CHECKING:
    from .orchestrator import Orchestrator


# Lifecycle fields change on every revision; only the remaining facts show
# whether an answer actually changed the proposal.
_REVISION_LIFECYCLE_FIELDS = {"version", "status", "open_questions"}


def _revision_effective(previous: Proposal, revised: Proposal) -> bool:
    return (previous.model_dump(mode="json", exclude=_REVISION_LIFECYCLE_FIELDS)
            != revised.model_dump(mode="json", exclude=_REVISION_LIFECYCLE_FIELDS))


class MailQuestions:
    """Owned by the Orchestrator; reads its services through ``o``."""

    def __init__(self, owner: Orchestrator):
        self.o = owner

    def resolve(self, name: str, state: MailState) -> None:
        """Resolve consecutive open questions from the source mail before Telegram."""
        assert state.mail is not None
        for index, initial in enumerate(state.proposals):
            proposal = initial
            while proposal.open_questions:
                question = proposal.open_questions[0]
                if question.startswith("Wie viele "):
                    # A model must not resolve its own contradictory counts.
                    break
                call, interpretation = self.o.analyzer.answer_question_from_mail(
                    state.mail, proposal, question)
                state.llm_call_ids.append(call)
                self.o.save(name, state)
                if not interpretation.usable:
                    self._question_unanswered(state, proposal, question, call,
                                              "not_answered_by_mail", None)
                    break
                assert interpretation.normalized_answer is not None
                try:
                    revision_call, revised = self._revise_from_mail(
                        state, proposal, question, interpretation.normalized_answer)
                except ValueError as exc:
                    # Transient provider failures keep their retry semantics.
                    # A contradictory or unrepairable revision only leaves this
                    # question open for Telegram instead of failing the mail.
                    if (isinstance(exc, TechnicalRevisionError)
                            and not isinstance(exc, LlmSchemaValidationExceeded)):
                        raise
                    self._question_unanswered(state, proposal, question, call,
                                              "revision_failed", type(exc).__name__)
                    break
                if revision_call is not None:
                    state.llm_call_ids.append(revision_call)
                    self.o.save(name, state)
                if not _revision_effective(proposal, revised):
                    # Never report a question as resolved when nothing changed;
                    # the unchanged predecessor keeps the question open.
                    self._question_unanswered(state, proposal, question, call,
                                              "revision_without_effect", None)
                    break
                proposal = revised
                state.proposals[index] = proposal
                self.o.save(name, state)
                self.o.logger.event(
                    "INFO", "orchestrator", "mail_question_resolved",
                    mail_id=state.id, proposal_id=proposal.id,
                    proposal_version=proposal.version, question=question,
                    interpretation_call_id=call, revision_call_id=revision_call,
                )

    def _revise_from_mail(self, state: MailState, proposal: Proposal, question: str,
                          answer: str) -> tuple[str | None, Proposal]:
        """Apply clear date and clock answers deterministically before the LLM."""
        mail = state.prepared
        assert mail is not None
        deterministic = deterministic_temporal_revision(
            proposal, question, answer, mail.user_timezone or self.o.user_timezone)
        if deterministic is not None:
            return None, deterministic
        return self.o.analyzer.revise_proposal(proposal, question, answer)

    def _question_unanswered(self, state: MailState, proposal: Proposal, question: str,
                             call: str, reason: str, error_class: str | None) -> None:
        self.o.logger.event(
            "INFO", "orchestrator", "mail_question_unanswered",
            mail_id=state.id, proposal_id=proposal.id,
            proposal_version=proposal.version, question=question,
            call_id=call, reason=reason, error_class=error_class,
        )
