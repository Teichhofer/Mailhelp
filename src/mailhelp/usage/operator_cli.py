"""8.7: the operator sets the valuation at the host – never through the customer interface."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from ..i18n import tr
from .points import Valuation, display, points
from .valuations import USAGE_DIRECTORY, ValuationError, Valuations

CONFIRMATION = "BEWERTUNG"
EXAMPLE_USD = Decimal("0.01")


def _describe(item: Valuation | None) -> str:
    if item is None:
        return tr("kein Bewertungsstand (Verbrauch wird nicht erfasst)")
    return tr("Stand {revision}: {rate} USD je EUR, Aufschlag {markup} %, gültig ab {start}",
              revision=item.revision, rate=item.usd_per_eur, markup=item.markup_percent,
              start=item.valid_from.isoformat(timespec="seconds"))


def set_valuation(state_directory: Path, usd_per_eur: str, markup_percent: str, *,
                  ask: Callable[[str], str] | None = None, out: Callable[[str], None] = print,
                  clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> int:
    """Show old and new values with an example, then append the revision after explicit confirmation."""
    valuations = Valuations(state_directory / USAGE_DIRECTORY)
    try:
        rate, markup = Decimal(usd_per_eur.replace(",", ".")), Decimal(markup_percent.replace(",", "."))
        revisions = valuations.revisions()
        now = clock()
        preview = Valuation(revision=len(revisions) + 1, usd_per_eur=rate, markup_percent=markup,
                            valid_from=now, actor="operator-cli")
    except ValuationError as exc:
        out(tr("FEHLER: {error}", error=exc))
        return 2
    except (InvalidOperation, ValueError) as exc:
        out(tr("FEHLER: Kurs muss positiv und Aufschlag mindestens 0 sein, beide endlich ({error}).", error=exc))
        return 2
    old = revisions[-1] if revisions else None
    out(tr("Bisher: {old}", old=_describe(old)))
    out(tr("Neu: {new}", new=_describe(preview)))
    example = tr("Beispiel: {usd} USD ergeben {points}", usd=EXAMPLE_USD, points=display(points(EXAMPLE_USD, preview)))
    if old is not None:
        example += tr(" (bisher {points})", points=display(points(EXAMPLE_USD, old)))
    out(example)
    out(tr("Gilt nur für danach beginnende Aufrufe; erfasster Verbrauch wird nicht neu bewertet."))
    if (ask or input)(tr("Zum Übernehmen exakt {word} eingeben: ", word=CONFIRMATION)).strip() != CONFIRMATION:
        out(tr("Nicht geändert."))
        return 1
    try:
        saved = valuations.add(rate, markup, "operator-cli", clock())
    except ValuationError as exc:
        out(tr("FEHLER: {error}", error=exc))
        return 2
    out(tr("Gespeichert: {new}", new=_describe(saved)))
    return 0


__all__ = ["CONFIRMATION", "set_valuation"]
