"""Expected review failures.

They derive from ``ValueError`` so that existing Telegram handling, which
treats every ``ValueError`` of a decision as a rejected action, is unchanged.
"""

from __future__ import annotations


class ReviewError(ValueError):
    """A command was understood but cannot be applied."""


class StaleCommand(ReviewError):
    """The command refers to a version or state that is no longer current."""


class AnswerRequired(ReviewError):
    """A confirmation needs the open questions to be answered first."""


class ReviewBusy(ReviewError):
    """Another answer is being processed; the command may be repeated later."""


__all__ = ["AnswerRequired", "ReviewBusy", "ReviewError", "StaleCommand"]
