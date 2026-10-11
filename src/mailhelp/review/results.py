"""Typed results of review commands, independent of the channel."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ResultStatus(StrEnum):
    # Applied: rejected, clarification started, answer handed over, relevance decided.
    DONE = "done"
    WRITTEN = "written"
    WRITE_UNCERTAIN = "write_uncertain"
    WRITE_FAILED = "write_failed"
    # Confirmed, but no external write took place (e.g. not writable).
    NOT_WRITTEN = "not_written"
    NEEDS_DUPLICATE_CONFIRMATION = "needs_duplicate_confirmation"
    NEEDS_ANSWER = "needs_answer"
    STALE = "stale"
    BUSY = "busy"
    INVALID = "invalid"
    UNAUTHORIZED = "unauthorized"
    # Unexpected failure while executing; details are only in the log.
    FAILED = "failed"


# Results after which nothing changed and the user has to act differently.
REJECTED_STATUSES = frozenset({
    ResultStatus.NEEDS_ANSWER, ResultStatus.STALE, ResultStatus.BUSY,
    ResultStatus.INVALID, ResultStatus.UNAUTHORIZED,
})


class ReviewResult(BaseModel):
    """Outcome shown to the user; it contains no mail content."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    status: ResultStatus
    message: str = Field(max_length=500)


__all__ = ["REJECTED_STATUSES", "ResultStatus", "ReviewResult"]
