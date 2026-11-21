"""Preflight one paused answer, then explicitly requeue that exact version (8.1).

No external services, messages, calendar writes or LLM calls. Default: dry run.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from mailhelp.domain.processing import ProposalClarificationState, ProposalRevisionStatus
from mailhelp.domain.proposal import Proposal
from mailhelp.persistence.proposals import clarification_name, proposal_name
from mailhelp.persistence.storage import JsonStore
from mailhelp.processing.analysis import validate_revision_successor
from mailhelp.text.temporal_answers import deterministic_temporal_revision


def recover(store: JsonStore, mail: str, proposal: str, version: int,
            timezone: str, *, apply: bool = False) -> bool:
    """Return whether requeueing is needed; an already requeued answer is idempotent."""
    with store.locked():
        original = store.peek_model(proposal_name(mail, proposal), Proposal)
        name = clarification_name(mail, proposal, version)
        answer = store.peek_model(name, ProposalClarificationState)
        if (original is None or answer is None or original.version != version
                or (original.source_mail_id, original.id) != (mail, proposal)
                or (answer.mail_id, answer.proposal_id, answer.version) != (mail, proposal, version)
                or original.status != "needs_clarification"
                or answer.question not in original.open_questions
                or answer.answer_status != "valid" or answer.question_status != "answered"
                or answer.interpretation_status != "completed"
                or answer.proposal_revision_status not in {"paused", "retry_required"}):
            raise ValueError("not_recoverable")
        candidate = deterministic_temporal_revision(original, answer.question, answer.normalized_answer or "", timezone)
        if candidate is None:
            raise ValueError("not_deterministic")
        validate_revision_successor(original, candidate, configured_timezone=timezone)
        if answer.proposal_revision_status == "retry_required":
            return False
        if apply:
            updated = answer.model_copy(update={"proposal_revision_status": ProposalRevisionStatus.RETRY_REQUIRED,
                                                "revision_attempts": 0, "next_revision_at": None})
            store.save(name, updated.model_dump(mode="json"))
        return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, type=Path)
    parser.add_argument("--mail", required=True)
    parser.add_argument("--proposal", required=True)
    parser.add_argument("--version", required=True, type=int)
    parser.add_argument("--timezone", default="Europe/Berlin")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    with JsonStore(args.data) as store:
        recover(store, args.mail, args.proposal, args.version, args.timezone, apply=args.apply)
    print("requeued" if args.apply else "preflight_ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
