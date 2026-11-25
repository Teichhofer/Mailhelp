"""8.7.4: a points limit for a learning run, converted on the server into the run's USD limit.

The customer chooses a whole number of points; the operator sets the price assumption in
``operator.yaml``. The USD limit is rounded *down* (10⁻¹² USD), so a run never may spend more than the
chosen points are worth. Points of an amount always come from :func:`~mailhelp.usage.points.points`
– there is no second formula.
"""

from __future__ import annotations

import math
from decimal import ROUND_CEILING, ROUND_DOWN, Decimal

from .points import CONTEXT, POINTS_PER_EUR, Valuation, points

MIN_POINTS = 1
MAX_POINTS = 10_000_000
USD_STEP = Decimal("1e-12")
MILLION = Decimal(1_000_000)


def parse_points(raw: str) -> int:
    """A whole number of points between 1 and 10,000,000; anything else is refused."""
    text = raw.strip()
    if not text.isdecimal() or not text.isascii():
        raise ValueError("Punktegrenze muss eine ganze Zahl sein")
    value = int(text)
    if not MIN_POINTS <= value <= MAX_POINTS:
        raise ValueError("Punktegrenze außerhalb des erlaubten Bereichs")
    return value


def points_to_usd(value: Decimal | int, valuation: Valuation) -> Decimal:
    """USD = points / 1,000 × rate / (1 + markup / 100), rounded down to 10⁻¹² USD."""
    factor = CONTEXT.add(Decimal(1), CONTEXT.divide(valuation.markup_percent, Decimal(100)))
    euro = CONTEXT.divide(Decimal(value), POINTS_PER_EUR)
    usd = CONTEXT.divide(CONTEXT.multiply(euro, valuation.usd_per_eur), factor)
    return usd.quantize(USD_STEP, rounding=ROUND_DOWN, context=CONTEXT)


def usd_to_points(usd: Decimal, valuation: Valuation) -> Decimal:
    return points(usd, valuation)


def tokens_to_usd(tokens: int, usd_per_million: Decimal) -> Decimal:
    return CONTEXT.divide(CONTEXT.multiply(Decimal(tokens), usd_per_million), MILLION)


def tokens_to_points(tokens: int, usd_per_million: Decimal, valuation: Valuation) -> Decimal:
    """Points of an estimate: the tokens at the operator's price assumption."""
    return usd_to_points(tokens_to_usd(tokens, usd_per_million), valuation)


def decimal_of(value: float) -> Decimal:
    """The shortest decimal naming a stored float (the run's limits are kept as floats)."""
    return Decimal(repr(value))


def limit_float(usd: Decimal) -> float:
    """The run's USD limit as the float the worker compares with; never above ``usd``."""
    result = float(usd)
    if Decimal(result) > usd:
        result = math.nextafter(result, 0.0)
    if not result > 0:
        raise ValueError("Punktegrenze zu klein")
    return result


def fits(limit: int, tokens: int, usd_per_million: Decimal, valuation: Valuation) -> bool:
    """Whether the run's start check (floats, as in ``LearningJobs``) accepts this points limit."""
    try:
        usd = limit_float(points_to_usd(limit, valuation))
    except ValueError:
        return False
    return tokens * float(usd_per_million) / 1_000_000 <= usd


def minimum_points(tokens: int, usd_per_million: Decimal, valuation: Valuation) -> int:
    """The smallest whole points limit the start accepts for an estimate of ``tokens``.

    Rounding the limit down may cost the last fraction of a point; then one more point is needed.
    """
    needed = max(MIN_POINTS, int(tokens_to_points(tokens, usd_per_million, valuation)
                                 .to_integral_value(rounding=ROUND_CEILING, context=CONTEXT)))
    return needed if fits(needed, tokens, usd_per_million, valuation) else needed + 1


__all__ = ["MAX_POINTS", "MIN_POINTS", "decimal_of", "fits", "limit_float", "minimum_points", "parse_points",
           "points_to_usd", "tokens_to_points", "tokens_to_usd", "usd_to_points"]
