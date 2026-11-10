"""5.2: fixed texts for the check state of a written entry, shared by Telegram and the web."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from ..domain.verification import RECHECKABLE, VerificationState, WriteVerification

# The answer to a confirmation whose entry is written but not yet verified.
VERIFYING_MESSAGE = "Gespeichert – der Eintrag wird beim Anbieter geprüft."

STATE_TEXTS = {
    VerificationState.PENDING: "Gespeichert – Eintrag wird geprüft",
    VerificationState.VERIFIED: "Angelegt und geprüft",
    VerificationState.NOT_FOUND: "Eintragung noch nicht bestätigt",
    VerificationState.UNAVAILABLE: "Eintragung noch nicht bestätigt",
    VerificationState.MISMATCH: "Eintrag vorhanden, Angaben weichen ab",
    VerificationState.UNSUPPORTED: "Kalenderdatei bereitgestellt – Übernahme in den Kalender nicht prüfbar",
    VerificationState.LEGACY_UNVERIFIED: "Angelegt (vor 5.2, nicht nachgeprüft)",
    VerificationState.SIMULATED: "Simuliert – nichts eingetragen",
}

FIELD_LABELS = {"title": "Titel", "description": "Beschreibung", "due": "Fälligkeit", "start": "Beginn",
                "end": "Ende", "all_day": "Ganztägig", "location": "Ort", "container": "Projekt/Kalender",
                "kind": "Art", "status": "Status", "uid": "Kennung"}

ERROR_TEXTS = {
    "not_visible": "der Eintrag ist beim Anbieter nicht auffindbar",
    "access_denied": "der Anbieter verweigert den Lesezugriff",
    "rate_limited": "der Anbieter hat zu viele Anfragen gemeldet",
    "provider_unavailable": "der Anbieter war nicht erreichbar",
    "provider_refused": "der Anbieter hat den Abruf abgelehnt",
    "invalid_response": "der Anbieter hat eine ungültige Antwort geliefert",
    "target_changed": "das konfigurierte Ziel wurde inzwischen geändert",
    "account_changed": "inzwischen ist ein anderes Konto angemeldet",
    "still_active": "der Termin ist beim Anbieter weiterhin aktiv",
}


def shown(value: str | None, zone: ZoneInfo) -> str:
    """A compared value for display: dates and times in German form, a missing value as a dash."""
    if value is None or value == "":
        return "–"
    try:
        if "T" in value:
            moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
            local = moment.astimezone(zone) if moment.tzinfo is not None else moment
            return f"{local:%d.%m.%Y %H:%M} Uhr"
        return f"{date.fromisoformat(value):%d.%m.%Y}"
    except ValueError:
        return {"True": "ja", "False": "nein"}.get(value, value)


def differences_text(record: WriteVerification, zone: ZoneInfo) -> str:
    return "; ".join(f"{FIELD_LABELS.get(name, name)}: erwartet {shown(item.expected, zone)}, "
                     f"gefunden {shown(item.actual, zone)}"
                     for name, item in sorted(record.differences.items()))


def reason_text(record: WriteVerification) -> str:
    return ERROR_TEXTS.get(record.last_error or "", "die Nachprüfung war nicht möglich")


@dataclass(frozen=True)
class VerificationSummary:
    """What the web shows about the check of a written entry; every value is display text."""

    state: VerificationState
    title: str
    detail: str | None
    differences: tuple[tuple[str, str, str], ...]
    recheckable: bool


def _when(value: datetime | None, zone: ZoneInfo) -> str:
    return "–" if value is None else f"{value.astimezone(zone):%d.%m.%Y, %H:%M} Uhr"


def summary(record: WriteVerification, zone: ZoneInfo) -> VerificationSummary:
    detail: str | None = None
    if record.state == VerificationState.PENDING and record.attempts:
        detail = (f"Nachprüfung ausstehend – nächster Versuch {_when(record.next_check_at, zone)} "
                  f"({reason_text(record)}).")
    elif record.state == VerificationState.VERIFIED:
        detail = f"Frisch beim Anbieter geprüft am {_when(record.checked_at, zone)}."
    elif record.state in {VerificationState.NOT_FOUND, VerificationState.UNAVAILABLE}:
        reason = reason_text(record)
        detail = f"{reason[0].upper()}{reason[1:]}. Letzte Prüfung: {_when(record.checked_at, zone)}."
    elif record.state == VerificationState.MISMATCH:
        detail = f"Letzte Prüfung: {_when(record.checked_at, zone)}. Mailhelp ändert den Eintrag nicht automatisch."
    rows = tuple((FIELD_LABELS.get(name, name), shown(item.expected, zone), shown(item.actual, zone))
                 for name, item in sorted(record.differences.items()))
    return VerificationSummary(record.state, STATE_TEXTS[record.state], detail, rows, record.state in RECHECKABLE)
