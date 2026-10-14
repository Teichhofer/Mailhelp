"""Content-free classification of failed proposal revisions.

The classes live in the domain because both the LLM analysis and the
deterministic answer parsing raise them; neither depends on the other.
"""
from __future__ import annotations


class RevisionError(ValueError):
    """Base class for content-free revision error classification."""


class IncompleteUserAnswer(RevisionError):
    """The validated user answer does not contain the requested information."""


class ContradictoryRevision(RevisionError):
    """A revision is semantically inconsistent with its predecessor."""


class TechnicalRevisionError(RevisionError):
    """A provider, transport, parsing, schema, or token-limit failure."""


__all__ = ["ContradictoryRevision", "IncompleteUserAnswer", "RevisionError", "TechnicalRevisionError"]
