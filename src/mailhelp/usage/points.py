"""8.7: system consumption in points – 1 point is 0.1 euro cent, 1,000 points are 1 euro.

Money is calculated with :class:`~decimal.Decimal` in a fixed 34-digit context, never with binary
floating point. Points stay high-precision per attempt; only the display rounds (ROUND_HALF_UP).
"""

from __future__ import annotations

import math
from datetime import datetime
from decimal import ROUND_HALF_UP, Context, Decimal, InvalidOperation
from enum import StrEnum
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

POINTS_PER_EUR = Decimal(1000)
# Plan 8.7 §5.2: at least 28 significant digits; no rounding of a single attempt.
CONTEXT = Context(prec=34)
SMALLEST = Decimal("0.01")


# Pydantic refuses NaN and infinity for Decimal fields unless explicitly allowed.
Finite = Annotated[Decimal, Field(allow_inf_nan=False)]


class Valuation(BaseModel):
    """One immutable valuation revision of an instance: exchange rate and markup from ``valid_from``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    revision: int = Field(ge=1)
    usd_per_eur: Finite = Field(gt=0)
    markup_percent: Finite = Field(ge=0)
    valid_from: AwareDatetime
    actor: str = Field(min_length=1, max_length=80)


class CostStatus(StrEnum):
    REPORTED = "reported"  # the provider reported a cost (zero stays zero)
    MISSING = "missing"  # no cost reported: not determinable yet, never free
    INVALID = "invalid"  # negative, not finite or not a number: a case to clarify
    NOT_SENT = "not_sent"  # the connection was refused: the request provably never reached the provider


def reported_cost(raw: object) -> tuple[CostStatus, Decimal | None]:
    """Classify a provider cost value without ever turning a doubtful value into zero."""
    if raw is None:
        return CostStatus.MISSING, None
    if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
        return CostStatus.INVALID, None
    if isinstance(raw, float) and not math.isfinite(raw):
        return CostStatus.INVALID, None
    try:
        # repr keeps the shortest decimal that names the float, not its binary expansion.
        value = Decimal(repr(raw) if isinstance(raw, float) else str(raw).strip())
    except InvalidOperation:
        return CostStatus.INVALID, None
    if not value.is_finite() or value < 0:
        return CostStatus.INVALID, None
    return CostStatus.REPORTED, value


def points(cost_usd: Decimal, valuation: Valuation) -> Decimal:
    """EUR = USD / rate; rated EUR = EUR × (1 + markup / 100); points = rated EUR × 1,000."""
    euro = CONTEXT.divide(cost_usd, valuation.usd_per_eur)
    factor = CONTEXT.add(Decimal(1), CONTEXT.divide(valuation.markup_percent, Decimal(100)))
    return CONTEXT.multiply(CONTEXT.multiply(euro, factor), POINTS_PER_EUR)


def total(values: list[Decimal]) -> Decimal:
    """Sum of the stored high-precision values; nothing is rounded before the sum."""
    result = Decimal(0)
    for value in values:
        result = CONTEXT.add(result, value)
    return result


def display(value: Decimal, *, english: bool = False) -> str:
    """Two decimals, half up; a positive amount below 0.01 is never shown as free."""
    unit = "points" if english else "Punkte"
    if Decimal(0) < value < SMALLEST:
        return f"< {'0.01' if english else '0,01'} {unit}"
    rounded = value.quantize(SMALLEST, rounding=ROUND_HALF_UP, context=CONTEXT)
    whole, fraction = f"{rounded:,.2f}".split(".")
    if not english:
        whole = whole.replace(",", ".")
    return f"{whole}{'.' if english else ','}{fraction} {unit}"


def current(valuations: list[Valuation], at: datetime) -> Valuation | None:
    """The revision valid at ``at``: the newest that already began."""
    started = [item for item in valuations if item.valid_from <= at]
    return max(started, key=lambda item: (item.valid_from, item.revision)) if started else None


__all__ = ["CONTEXT", "POINTS_PER_EUR", "CostStatus", "Valuation", "current", "display", "points",
           "reported_cost", "total"]
