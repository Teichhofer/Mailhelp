"""Fixed rejection reasons for proposals (Planung 6.5, E1, 3.2)."""
from __future__ import annotations

REJECT_REASONS: dict[str, str] = {
    "not_for_me": "Betrifft mich nicht",
    "info_only": "Nur zur Information",
    "advertising": "Werbung oder Rundschreiben",
    "misrecognized": "Falsch erkannt (Datum, Inhalt)",
    "other": "Anderer Grund",
    "already_done": "Schon erledigt",
}

# The five reasons offered to the user in the UI / Telegram
USER_REJECT_REASONS: tuple[tuple[str, str], ...] = (
    ("not_for_me", "Betrifft mich nicht"),
    ("info_only", "Nur zur Information"),
    ("advertising", "Werbung oder Rundschreiben"),
    ("misrecognized", "Falsch erkannt (Datum, Inhalt)"),
    ("other", "Anderer Grund"),
)
