"""8.7.6 (AP4a): the settings overview of a customer session – only the customer's own areas.

The operator page (``/einstellungen`` with areas, search and credentials) stays operator only; a
customer always gets this overview, whatever ``bereich`` or ``suche`` the address carries.
"""

from __future__ import annotations

from typing import Any

from ..i18n import msg, tr
from .pages import e, notice, page_head
from .settings_pages import GENERAL_AREA, GENERAL_PATH, _section

# 8.8.2 (Planung 8.8 AP2): the customer's personal values; all of them are customer fields.
GENERAL_FIELDS = (
    "language", "timezone", "personal_info",
    "event_defaults.video_duration_minutes", "event_defaults.in_person_duration_minutes",
    "targets.calendar_reminder_enabled", "targets.calendar_reminder_minutes",
    "drafts.enabled", "drafts.folder", "smart_reply", "auto_draft",
    "briefings.enabled", "briefings.times", "briefings.mailbox", "briefings.skip_empty",
    "daily_briefing.include_calendar", "daily_briefing.include_open", "daily_briefing.include_tasks",
)

AREAS = (
    (GENERAL_PATH, msg("Allgemein"),
     msg("Sprache, Zeitzone, persönliche Angaben, Termindauern, Kalendererinnerung, Entwürfe und Briefings.")),
    ("/einstellungen/postfaecher", msg("Postfächer"),
     msg("Eigene Postfächer, Abrufordner und Regeln je Postfach.")),
    ("/einstellungen/zielprofile", msg("Zielprofile"),
     msg("Kalender und Aufgabenlisten, in die bestätigte Vorschläge eingetragen werden.")),
    ("/themen", msg("Themen"), msg("Was für dich relevant ist und was ausgeblendet wird.")),
    ("/einstellungen/absender", msg("Absender-Regeln"), msg("Absender und Domains immer zulassen oder ignorieren.")),
    ("/benachrichtigungen", msg("Benachrichtigungen"), msg("Kanäle, Zeiten und Push-Mitteilungen.")),
    ("/lernen", msg("Lernen"), msg("Themen und Regeln aus Postfach und Entscheidungen vorschlagen lassen.")),
    ("/verbrauch", msg("Verbrauch"), msg("Verbrauchte Punkte nach Tag und Schritt.")),
    ("/geraete", msg("Geräte"), msg("Angemeldete Geräte ansehen und abmelden.")),
    ("/einstellungen/web-passwort", msg("Web-Passwort"), msg("Anmeldung mit Passwort festlegen oder ändern.")),
)


def customer_settings_page() -> str:
    cards = "".join(
        f'<section class="card"><h2><a href="{href}">{e(tr(title))}</a></h2><p class="meta">{e(tr(text))}</p></section>'
        for href, title, text in AREAS)
    return (page_head(tr("Einstellungen"), tr("Verwaltung"),
                      tr("Deine Bereiche. Zugangsdaten, Modelle und den Betrieb verwaltet der Betreiber."))
            + cards)


def customer_general_page(raw: dict[str, Any] | None, active: dict[str, Any] | None, revision: str, csrf: str) -> str:
    """One form with the customer's own values; it is checked and confirmed like every settings section."""
    head = page_head(tr("Allgemein"), tr("Einstellungen"),
                     tr("Deine persönlichen Werte. Sie werden nach dem Prüfen ausdrücklich gespeichert."))
    if raw is None:
        return head + notice(tr("Konfigurationsdienst nicht verfügbar."), "warn")
    return head + _section(tr("Allgemein"), raw, active, revision, csrf, GENERAL_AREA, list(GENERAL_FIELDS),
                           GENERAL_PATH)


__all__ = ["AREAS", "GENERAL_FIELDS", "customer_general_page", "customer_settings_page"]
