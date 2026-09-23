"""Conservative deterministic interpretation of temporal answers."""

from ._core import (
    DeterministicTemporalAnswer, deterministic_classification_revision,
    deterministic_temporal_revision,
    parse_deterministic_temporal_answer,
)

__all__ = [
    "DeterministicTemporalAnswer", "deterministic_classification_revision",
    "deterministic_temporal_revision",
    "parse_deterministic_temporal_answer",
]
