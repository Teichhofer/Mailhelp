"""Estimates from previous measured report steps; no invented model prices."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from ..metrics import electricity
from .models import ActivityReport


def estimate(report: ActivityReport, records: list[dict[str, Any]]) -> str:
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
            return "Noch keine ausreichenden Kostenmesswerte für beide Schritte; nur Aufrufzahlen verfügbar."
        samples.append(len(measured))
        for currency, amount in measured:
            totals[currency] += amount * report.total / len(measured)
    amounts = ", ".join(f"{value:.4f} {currency}" for currency, value in totals.items() if value)
    return (f"Geschätzt bis etwa {amounts or '0.0000 USD'} bei vollständig relevanten Mails. "
            f"Basis: {samples[0]} Relevanz- und {samples[1]} Terminmessungen; "
            "andere Textlängen, Modelle und Wiederholungen verändern die Kosten.")
