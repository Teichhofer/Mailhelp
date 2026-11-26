"""8.7.6 (AP4a): the settings overview of a customer session – only the customer's own areas.

The operator page (``/einstellungen`` with areas, search and credentials) stays operator only; a
customer always gets this overview, whatever ``bereich`` or ``suche`` the address carries.
"""

from __future__ import annotations

from ..i18n import msg, tr
from .pages import e, page_head

AREAS = (
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


__all__ = ["AREAS", "customer_settings_page"]
