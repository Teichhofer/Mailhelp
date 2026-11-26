"""Estimates from previous measured report steps; no invented model prices."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from ..support.metrics import electricity
from .models import ActivityReport

NOT_MEASURED = "Noch keine ausreichenden Kostenmesswerte für beide Schritte; nur Aufrufzahlen verfügbar."


@dataclass(frozen=True)
class Measured:
    """Extrapolated totals per currency and the number of measurements of both steps."""

    totals: dict[str, Decimal]
    relevance: int
    events: int


def measure(report: ActivityReport, records: list[dict[str, Any]]) -> Measured | None:
    """None until both report steps have at least one measured successful call."""
    totals = {"USD": Decimal(0), "EUR Strom": Decimal(0)}
    samples = []
    for stage in ("activity_relevance", "activity_events"):
        rows = [row for row in records if row["stage"] == stage and row["status"] == "success"]
        measured = []
        for row in rows:
            if row["mode"] == "local":
                measured.append(("EUR Strom", electricity([(row["start"], row["end"])],
                                                          row["power_watts"], row["electricity_price"])))
            elif row["cost_usd"] is not None:
                measured.append(("USD", Decimal(str(row["cost_usd"]))))
        if not measured:
            return None
        samples.append(len(measured))
        for currency, amount in measured:
            totals[currency] += amount * report.total / len(measured)
    return Measured(totals, samples[0], samples[1])


def estimate(report: ActivityReport, records: list[dict[str, Any]]) -> str:
    measured = measure(report, records)
    if measured is None:
        return NOT_MEASURED
    amounts = ", ".join(f"{value:.4f} {currency}" for currency, value in measured.totals.items() if value)
    return (f"Geschätzt bis etwa {amounts or '0.0000 USD'} bei vollständig relevanten Mails. "
            f"Basis: {measured.relevance} Relevanz- und {measured.events} Terminmessungen; "
            "andere Textlängen, Modelle und Wiederholungen verändern die Kosten.")
