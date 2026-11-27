"""8.7.8 (AP4c): which help sections a customer session reads – an explicit list, deny by default.

The product documentation is written for people who run Mailhelp themselves; most of it explains
servers, credentials, prompts and costs. A customer of an operated instance sees only the sections
named here, in the help index, on the section pages and as sources of the help chat. A section that
is added to the documentation later stays operator only until it is listed. The ids are the canonical
ids that the German and the English help share (``tests/unit/test_help_roles.py`` checks both texts).
"""

from __future__ import annotations

CUSTOMER_SECTIONS = frozenset({
    # Everyday use
    "bedienung/alltagsbedienung",
    "bedienung/offene-entscheidungen",
    "bedienung/wischen-auf-dem-telefon",
    "bedienung/rueckfragen-und-widersprueche",
    "bedienung/videolink-fuer-einen-bestehenden-termin",
    "bedienung/nach-dem-anlegen",
    "bedienung/angelegte-eintraege-wieder-entfernen",
    "bedienung/mails-nachlesen-und-verlauf",
    "bedienung/absender-regeln-und-vorfilter",
    "bedienung/bedienung-auf-dem-telefon",
    "bedienung/verbindungsprobleme",
    "bedienung/google-ueber-inboxstride-verbinden",
    "bedienung/fehlgeschlagene-mails",
    "bedienung/hilfe-beim-einstellen",
    "bedienung/eigene-werte-in-einer-kundeninstanz",
    # Learning (the customer instance section explains points)
    "bedienung/lernmodus-lernfunktion",
    "bedienung/lernen-in-einer-kundeninstanz",
    "bedienung/ergebnis-pruefen-und-uebernehmen",
    "bedienung/lernbestand",
    # Own mailboxes and targets
    "konten-verwalten/ein-postfach-einem-anderen-kalender-oder-einer-anderen-aufgabenliste-zuordnen",
    "konten-verwalten/regeln-je-postfach",
    "konten-verwalten/weitere-ziele-kalender-und-aufgabenlisten",
    "konten-verwalten/wenn-etwas-nicht-klappt",
    "ziele-einrichten/caldav-und-apple-erinnerungen",
    "ziele-einrichten/ziel-sicher-wechseln",
    # Settings a customer may change
    "web-einstellungen/themenuebersicht",
    "web-einstellungen/tagesueberblick",
    "web-einstellungen/postfach-briefings-49",
    "web-einstellungen/weitere-zielprofile-targetprofiles",
    "web-einstellungen/benachrichtigungen-notifications",
    # Troubleshooting without host access
    "fehlerbehebung/mail-wird-wiederholt-nicht-verarbeitet",
    "fehlerbehebung/analyse-daten-nach-aufbewahrung-entfernt",
    "fehlerbehebung/hilfschat-im-einstellungsfenster",
})


def customer_section(section_id: str) -> bool:
    return section_id in CUSTOMER_SECTIONS


__all__ = ["CUSTOMER_SECTIONS", "customer_section"]
