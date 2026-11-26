"""8.7.4: estimate, reservation and actual usage of a learning run – in points, never in money.

Estimate and actual usage are named apart; calls that cannot be valued yet are counted and named,
never shown as free (Plan 8.7 §7.2). Customers see only these texts; operators see them in addition to
the USD form.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from ..i18n import Locale, current, tr
from ..usage.budget import usd_to_points
from ..usage.ledger import Purpose
from ..usage.points import Valuation, display, total
from ..usage.points import current as current_valuation

if TYPE_CHECKING:
    from ..activity.costs import Measured
    from ..usage.valuations import UsageMeter

LEARNING_PREFIX = "learning."


@dataclass(frozen=True)
class RunUsage:
    points: Decimal
    unclear: int


def points_text(value: Decimal) -> str:
    return display(value, english=current() is Locale.EN)


def valuation(meter: UsageMeter | None, at: datetime, revision: int | None = None) -> Valuation | None:
    """The revision a run is bound to, or the one valid now; none without recording."""
    if meter is None:
        return None
    revisions = meter.valuations.revisions()
    if revision is not None:
        return next((item for item in revisions if item.revision == revision), None)
    return current_valuation(revisions, at)


def learning_usage(meter: UsageMeter, started_at: float) -> RunUsage:
    """Customer usage of learning calls since the run began (each attempt counted once)."""
    start = datetime.fromtimestamp(started_at, UTC)
    chosen = [item for item in meter.ledger.attempts()
              if item.begun.stage.startswith(LEARNING_PREFIX) and item.begun.at >= start
              and item.begun.purpose is Purpose.CUSTOMER]
    return RunUsage(total([item.points for item in chosen if item.points is not None]),
                    sum(item.unclear for item in chosen))


def estimate_text(estimate: Decimal, worst: Decimal) -> str:
    return tr("Geschätzter Verbrauch: etwa {estimate}; ungünstigster Fall: höchstens {worst}.",
              estimate=points_text(estimate), worst=points_text(worst))


def reserved_text(reserved: Decimal, limit: int | None) -> str:
    if limit is None:
        return tr("Reserviert: {reserved}.", reserved=points_text(reserved))
    return tr("Reserviert: {reserved} der Punktegrenze von {limit}.", reserved=points_text(reserved),
              limit=points_text(Decimal(limit)))


def actual_text(usage: RunUsage) -> str:
    text = tr("Tatsächlich verbraucht: {points}.", points=points_text(usage.points))
    if usage.unclear:
        text += " " + tr("Bekannte Teilsumme; {count} Aufruf(e) noch nicht bewertbar.", count=usage.unclear)
    return text


def report_estimate_text(measured: Measured | None, rating: Valuation | None) -> str:
    """8.7.7: the measured report estimate in points; local electricity is never shown to customers."""
    if measured is None:
        return tr("Noch keine ausreichenden Messwerte für beide Schritte; nur die Zahl der Aufrufe ist bekannt.")
    if rating is None or not measured.totals["USD"]:
        return tr("Der Verbrauch in Punkten lässt sich noch nicht schätzen.")
    return tr("Geschätzter Verbrauch: bis etwa {points} bei vollständig relevanten Mails. Basis: {relevance} "
              "Relevanz- und {events} Terminmessungen; andere Textlängen und Wiederholungen verändern den "
              "Verbrauch.", points=points_text(usd_to_points(measured.totals["USD"], rating)),
              relevance=measured.relevance, events=measured.events)


__all__ = ["LEARNING_PREFIX", "RunUsage", "actual_text", "estimate_text", "learning_usage", "points_text",
           "report_estimate_text", "reserved_text", "valuation"]
