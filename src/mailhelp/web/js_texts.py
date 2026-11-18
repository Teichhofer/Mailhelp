"""7.8: owned JavaScript UI message ids handed to scripts by the page renderer."""

import json
from functools import cache

from ..i18n import Locale, tr, use_locale


@cache
def messages(locale: Locale) -> str:
    if locale == Locale.DE:
        return "{}"
    with use_locale(locale):
        return json.dumps({text: tr(text) for text in JS_TEXTS}, ensure_ascii=False, separators=(",", ":"))


JS_TEXTS = (
    " zum Verwerfen markiert.",
    " zur Übernahme ausgewählt · ",
    " – vergrößert",
    " – wird verarbeitet …",
    '<span aria-hidden="true">?</span><span class="nav-label">Tastenkürzel</span>',
    "Aktionen werden sofort angenommen. Weitere Vorgänge bleiben bedienbar.",
    "Am Server deaktiviert; das Browser-Abonnement konnte nicht entfernt werden. Websitedaten löschen.",
    "An den Anbieter übergeben. Warte auf dieses Gerät.",
    "Anfrage fehlgeschlagen. Bitte erneut versuchen.",
    "Anfrage wird gesendet …",
    "Antwort unterbrochen. Der Annahmestatus wird geprüft; es wird nichts erneut gesendet.",
    "Auf dem iPhone zuerst zum Home-Bildschirm hinzufügen und von dort öffnen.",
    "Auf diesem Gerät zuerst Push aktivieren.",
    "Ausgewählter Vorgang",
    "Benachrichtigungen sind für diese Seite blockiert. In den Browsereinstellungen erlauben.",
    "Bestätigen",
    "Bildanhang vergrößert",
    "Bitte den Antworttext markieren und manuell kopieren.",
    "Bitte den Bericht markieren und manuell kopieren.",
    "Das Browser-Abonnement ist ungültig. Websitedaten löschen und neu aktivieren.",
    "Das Browser-Abonnement konnte nicht angelegt werden. Benachrichtigungseinstellungen prüfen.",
    "Das alte Abonnement konnte nicht abgemeldet werden. Websitedaten löschen und neu aktivieren.",
    (
        "Der Anbieter hat angenommen, das Gerät hat nichts angezeigt. "
        "Fokus-Modus, Systemeinstellungen und Energiesparen prüfen."
    ),
    "Der Hintergrunddienst startet nicht innerhalb von zehn Sekunden. Seite neu laden.",
    "Der Hintergrunddienst startet nicht. Seite neu laden; hilft das nicht, Websitedaten für Mailhelp löschen.",
    "Der Prüfstand wurde geändert. Seite neu laden und erneut testen.",
    "Der Push-Anbieter ist vorübergehend nicht erreichbar. Später erneut testen.",
    "Der Serverschlüssel wurde geändert. Seite neu laden und Push neu aktivieren.",
    "Der Test hat das Zeitlimit erreicht. Prüfstand neu laden und später erneut testen.",
    "Der Test konnte nicht ausgeführt werden. Verbindungen prüfen und erneut testen.",
    "Details nicht geladen. Bitte Verbindung und Anmeldung prüfen.",
    "Die Aktion wurde nicht angenommen.",
    "Die Sicherheitsprüfung ist abgelaufen. Seite neu laden und erneut versuchen.",
    "Die Sofortsuche ist gerade nicht verfügbar – „Suchen“ funktioniert weiterhin.",
    "Die Testanfrage ist unvollständig. Seite neu laden.",
    "Diese Adresse ist nicht per HTTPS erreichbar. Mailhelp über die HTTPS-Adresse öffnen.",
    "Diese Aktion ist für den ausgewählten Vorgang nicht möglich.",
    "Diese Aktion ist für diesen Vorgang nicht möglich.",
    "Dieser Browser unterstützt kein Web-Push.",
    "Dieser Push-Anbieter ist nicht erlaubt. Einen unterstützten Browser verwenden.",
    "Dieses Gerät muss neu aktiviert werden.",
    "Dokumentation nicht verfügbar. Bitte Anmeldung prüfen.",
    "Entwurf wird erstellt …",
    "Ergebnis noch nicht sichtbar",
    "Erst die Antwort senden oder das Feld leeren.",
    "Filter nicht geladen. Bitte Verbindung prüfen.",
    "Gespräch aktualisiert.",
    "Keine Einstellung gefunden.",
    "Klicken zum Vergrößern",
    "Kopieren nicht erlaubt. Bitte den Antworttext manuell kopieren.",
    "Kopieren nicht erlaubt. Bitte den Bericht manuell kopieren.",
    "Mailhelp ist nicht erreichbar. Verbindung prüfen und erneut versuchen.",
    "Nach rechts wischen: anlegen · nach links: verwerfen",
    "Neue Daten – bitte neu laden",
    "Neue Vorschläge werden nicht per Push gemeldet.",
    "Nicht gespeichert: Anmeldung abgelaufen. Bitte neu anmelden.",
    "Nächster Vorgang",
    "Offene Vorgänge",
    "PC nicht erreichbar",
    "Push ist auf diesem Gerät aktiviert.",
    "Push ist auf diesem Gerät deaktiviert.",
    "Schließen",
    "Sitzung abgelaufen. Bitte erneut anmelden.",
    "Status gerade nicht verfügbar.",
    "Status nicht verfügbar",
    "Tastenkürzel",
    "Test-Push wird an den Anbieter übergeben.",
    "Test-Push: auf diesem Gerät angekommen. Systemmeldung bitte prüfen.",
    "Ungespeicherte Änderungen zuerst speichern oder die Seite neu laden.",
    "Verbindung unterbrochen. Die Aktion wird nicht erneut gesendet; der Status wird weiter geprüft.",
    "Verwerfen",
    "Vom Anbieter abgelehnt. Gerät neu aktivieren und Kontaktadresse des Servers prüfen.",
    "Web-Push ist auf dem Server nicht eingeschaltet. Unter Einrichtung einschalten und neu starten.",
    "Wird geprüft … das kann bis zu 15 Sekunden je Dienst dauern.",
    "Zuerst die laufende Aktion oder Eingabe abschließen.",
    "Zuletzt an den Anbieter übergeben: ",
    "noch nicht geprüft",
    "wird geprüft",
    "Übersicht nicht verfügbar",
    "● Verbunden",
)
