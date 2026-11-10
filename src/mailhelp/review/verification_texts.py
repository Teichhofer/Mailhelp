"""5.2: fixed texts for the check state of a written entry, shared by Telegram and the web."""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from ..domain.verification import VerificationState, WriteVerification

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
                "kind": "Art"}

ERROR_TEXTS = {
    "not_visible": "der Eintrag ist beim Anbieter nicht auffindbar",
    "access_denied": "der Anbieter verweigert den Lesezugriff",
    "rate_limited": "der Anbieter hat zu viele Anfragen gemeldet",
    "provider_unavailable": "der Anbieter war nicht erreichbar",
    "provider_refused": "der Anbieter hat den Abruf abgelehnt",
    "invalid_response": "der Anbieter hat eine ungültige Antwort geliefert",
    "target_changed": "das konfigurierte Ziel wurde inzwischen geändert",
    "account_changed": "inzwischen ist ein anderes Konto angemeldet",
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
