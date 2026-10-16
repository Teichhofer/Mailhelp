# Mailhelp 3.4 – IServ-Elternbriefe, Zugangsdaten und Einstellungen im Web

Stand: 16. Oktober 2026. Aktueller Repository-Stand: 3.4.4.
Diese Anleitung fasst die Änderungen von 3.3.2 bis 3.4.4 für den Betrieb zusammen. Die
technische Planung steht in [Planung 3.4](Planung-3.4.md), die Verträge in der
[Projektspezifikation](../Mailhelp-Projektspezifikation.md).

## IServ-Elternbriefe (ab 3.3.7)

Mailhelp liest Elternbriefe aus dem IServ-Elternbriefmodul der Schule und verarbeitet sie wie
Mails: Text und Anhänge (z. B. PDF) werden ausgewertet, Termine und Aufgaben als Vorschläge
erkannt. Elternbriefe gelten **immer als relevant**; es gibt keine KI-Relevanzprüfung und keinen
Absenderfilter. Zielprofil, Termindauern und weitere Standards kommen von dem Postfach, das beim
IServ-Konto angegeben ist. Antwortentwürfe gibt es für Elternbriefe nicht.

IServ bietet keine offizielle Schnittstelle. Mailhelp meldet sich deshalb wie ein Browser mit dem
Elternkonto an der Weboberfläche der Schule an und liest nur: Es bestätigt, beantwortet oder
archiviert in IServ nichts. Anfragen bleiben auf der HTTPS-Adresse der Schule; URLs, Anbietertexte
und Zugangsdaten erscheinen nicht in Protokollen.

### Einrichten über die Weboberfläche

1. **Einstellungen → IServ-Konten**: Anzeigename, IServ-Adresse der Schule
   (z. B. `https://schule.example`; ein aus dem Browser kopierter IServ-Link oder die Adresse ohne
   `https://` genügt), Postfach und optional eine Startgrenze (`TT.MM.JJJJ [HH:MM]`, `JJJJ-MM-TT`
   oder ISO-8601-Zeitpunkt mit Offset) eintragen
   und „IServ-Konto als Entwurf hinzufügen“ wählen. Ungültige Angaben werden mit ihrer Ursache
   angezeigt.
2. **Einstellungen → Zugangsdaten**: bei `ISERV_<n>_USERNAME` die IServ-Anmeldung und bei
   `ISERV_<n>_PASSWORD` das Passwort eintragen, jeweils ausdrücklich bestätigen.
3. **Diagnose → iserv**: Die Prüfung meldet sich an und öffnet nur die Briefübersicht.
4. Den Entwurf übernehmen und Mailhelp neu starten.

Alternativ in `config.yaml` unter `iserv.accounts` (`id`, `label`, `server`, `mailbox`, optional
`enabled` und `historical_start`) und in `.env` als `ISERV_<id>_USERNAME`/`ISERV_<id>_PASSWORD`.
`mailhelp --check-access` prüft die Anmeldung.

Ohne eigene Startgrenze gilt `historical_start` des Postfachs; ältere Briefe bleiben unberührt.
Fehlgeschlagene Briefe werden beim nächsten Durchlauf erneut versucht. Fällt eine Schule aus,
laufen andere Konten und der Mailabruf weiter. Die Statusseite zeigt unter „Konfigurierte Konten“
jedes IServ-Konto einzeln, auch vor dem ersten Kontakt. Sie unterscheidet erfolgreiche Kontakte,
Fehler, deaktivierte Konten und ausstehende Neustarts. Dasselbe gilt für IMAP, Kalender und Aufgaben
je Zielprofil sowie Telegram. Der Seitenaufruf führt keine Verbindungsprüfung aus.

Noch nicht unterstützt: Zwei-Faktor-Anmeldung, auf mehrere Seiten verteilte Briefübersichten (der
Abruf meldet sie als Fehler, statt nur einen Teil zu verarbeiten) und das Brief-Archiv.

## Zugangsdaten im Web (ab 3.3.11)

**Einstellungen → Zugangsdaten** listet alle Zugangsdaten, die die Konfiguration benötigt: je
Postfach, je IServ-Konto, OpenRouter, Telegram und die Kalender- und Aufgabendienste je Zielprofil.
Die Seite zeigt nur „hinterlegt“ oder „fehlt“, nie einen Wert. Ein neuer Wert ersetzt nur die
betroffene Zeile in `.env`; Kommentare und andere Einträge bleiben erhalten. Speichern verlangt eine
gültige Sitzung, eine ausdrückliche Bestätigung und den unveränderten Dateistand. Protokolle nennen
nur den Namen. `MAILHELP_WEB_SECRET` lässt sich hier nicht ändern, weil das alle Sitzungen beenden
würde. Ist ein Name zusätzlich in der Prozessumgebung gesetzt, hat dieser Wert Vorrang; die Seite
weist darauf hin.

In Docker muss `.env` beschreibbar eingebunden sein, sonst meldet die Seite das. Diagnose und
Einrichtung verwenden neue Werte sofort, der Mailabruf nach dem nächsten Neustart.

## Postfächer, IServ-Konten und Einstellungen (ab 3.3.10)

- Postfächer und IServ-Konten lassen sich vollständig im Web anlegen, ändern, deaktivieren und
  entfernen – immer als Entwurf, nach aktueller Diagnose und ausdrücklicher Übernahme.
- Die Einrichtung bietet je Postfach die Startgrenze `historical_start`.
- Unter **Einstellungen** sind zusätzlich Stapelgröße und Reihenfolge des Abrufs,
  Telegram-Benutzer und -Chat, Antwortentwürfe, Bildauswertung, Tagesüberblick,
  Tätigkeitsberichte, Lernmodus, Sitzungsdauer, Zugriff im eigenen Netzwerk und die
  Protokollierung änderbar ([Web-Einstellungen](Web-Einstellungen.md)).
- Nur in `config.yaml` bleiben Datenverzeichnis, Logpfade, Adresse, Port und zugelassene
  Hostnamen der Weboberfläche sowie die Parser-Sicherheitsgrenzen.
- Behoben: Nach dem Übernehmen eines Einrichtungsentwurfs blieb der Entwurf auf dem alten
  Dateistand stehen; die Postfachseite brach danach ab.

## Weitere Änderungen

- **Auswertung (3.3.9):** Diagramme zu KI-Aufrufen und Kosten je Tag oder Stunde, zur
  Verteilung der Aufrufdauer sowie zu Dauer je Verarbeitungsschritt und Kosten je Modell.
- **Statusseite (3.3.3):** Beim Start prüft Mailhelp OpenRouter, Telegram und die Ziele im
  Hintergrund nur lesend; ein Mailabruf ohne neue Mail und jede Telegram-Abfrage zählen als
  erfolgreicher Kontakt.
- **IMAP (3.3.4):** Treffer an oder unter der Startgrenze eines Ordners werden vor dem Abruf
  ausgeschlossen; Ordnerfehler erscheinen auf der Statusseite.
- **Zweite Instanz (3.3.5):** Ein zweiter Start auf demselben Datenverzeichnis endet mit einer
  verständlichen Meldung statt eines Tracebacks.
- **Weboberfläche (3.3.6):** Stylesheet, Skripte und Service Worker werden beim Start geladen;
  ein Update oder Branch-Wechsel bei laufendem Dienst mischt nicht mehr alte und neue Dateien.
  Nach einem Update Mailhelp neu starten.

## Aktualisieren

Dienst stoppen und Konfiguration, `.env`, Token-Dateien und den vollständigen Zustandsordner
sichern. Paket beziehungsweise Docker-Image aktualisieren, `mailhelp --check` ausführen und neu
starten. Neue Konfigurationsabschnitte (`iserv`) sind optional; sie ändern den Analyse-Fingerprint
nicht, laufende Mails werden also nicht zurückgehalten. Eine Rückkehr verwendet die
zusammengehörige Sicherung der vorherigen Version.
