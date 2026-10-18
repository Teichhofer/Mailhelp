# Mailhelp 3.5 – Einstellungsbereiche und Postfächer aktivieren

Stand: 17. Oktober 2026. Anwendungsversion: 3.5.0.

Die [Planung 3.5](Planung-3.5.md) und die
[Projektspezifikation](../Mailhelp-Projektspezifikation.md) beschreiben den technischen Vertrag.

## Einstellungen finden

**Einstellungen** öffnet die Übersicht mit Kacheln für Konten, allgemeine Regeln, Inhalte
und Systemaktionen. Jeder Bereich hat eine eigene Seite und eine aktive Navigation.
Die Suche berücksichtigt alle Wörter in Bezeichnung, Feldname, Gruppe und Bereich.
Kacheln zeigen gespeicherte, noch nicht aktive Änderungen. KI-Modelle stehen unter
**KI und Auswertung**, Push-Steuerung unter **Benachrichtigungen**, Passwörter und
API-Schlüssel unter **Zugangsdaten**. Die Bestätigung vor dem Speichern bleibt erhalten.
Alle Bereiche: [Web-Einstellungen](Web-Einstellungen.md).

## Neues Postfach verbinden

1. **Einstellungen → Postfächer** öffnen. Anzeigename, Server und Port sowie SSL/TLS
   (meist 993), STARTTLS (meist 143) oder unverschlüsselte Verbindung wählen.
2. Benutzername und Passwort/App-Passwort eintragen. Leere Zugangsfelder verwenden
   hinterlegte `IMAP_<id>_USERNAME` und `IMAP_<id>_PASSWORD`, wenn vorhanden.
3. Quellordner kommagetrennt eingeben; der erste ist der Posteingang. Den Ordner für
   Antwortentwürfe angeben. Die Startgrenze ist heute 00:00 Uhr in der konfigurierten
   Zeitzone. Ein leeres Datum erlaubt die Verarbeitung des gesamten Altbestands.
4. **Verbindung prüfen und Postfach aktivieren** wählen. Mailhelp meldet sich an,
   prüft Ordnerliste und Lesezugriff und speichert erst bei Erfolg. Fehlende Ordner
   werden mit einer begrenzten Liste vorhandener Ordner genannt. Bei Fehlern bleiben
   die übrigen Eingaben stehen; das Passwort muss erneut eingegeben werden.

Der Abruf beginnt im nächsten sicheren Mailzyklus ohne manuellen Neustart. Offene
Relevanzrückfragen gegebenenfalls zuerst beantworten. Bestehende Verbindungen werden
weiterverwendet. Schlägt der neue Verbindungsaufbau fehl, wird er im nächsten Zyklus
wiederholt; die laufenden Postfächer bleiben erhalten. Karten zeigen den Zustand
einschließlich Entwurf und ausstehender Aktivierung. Auch deaktivierte Konten werden
bei der Doppelkontoprüfung berücksichtigt. Höchstens zehn Postfächer sind unterstützt.

Die eingeklappte Alternative **Stattdessen nur als Entwurf hinzufügen** verwendet
weiterhin separate Zugangsdaten, Diagnose, Übernahme und Neustart. Bestehende Postfächer
ändern oder entfernen benötigt diesen Entwurfsablauf. Browser-OAuth und Erststart
ohne Konfiguration gehören nicht zu dieser Version.

## Betrieb und Fehlerbehebung

`config.yaml` und `.env` müssen beschreibbar sein. Unter Docker ein beschreibbares
Konfigurationsverzeichnis verwenden, damit atomarer Dateiaustausch möglich ist.
Prozessvariablen haben Vorrang vor `.env`; widersprüchliche neue Zugangswerte werden
abgewiesen. Andere Entwürfe werden durch die Aktivierung nicht übernommen.

Veraltete Seiten liefern HTTP 409: Seite neu laden und Änderungen erneut prüfen.
Nach unterbrochenem Speichern zunächst `config.yaml` und den gespeicherten Kontenstatus
prüfen; derselbe Idempotenzschlüssel führt keine zweite Aktivierung aus. Ein bereits
gespeichertes Postfach kann durch einen kontrollierten Dienstneustart geladen werden.
Fehlermeldungen zeigen keine Serverantworten oder Zugangswerte. Die Aktivierung liest
nur vom Mailserver und autorisiert keine Anlage in Kalender oder Aufgabenliste.

## Aktualisieren und zurückkehren

Dienst stoppen und Konfiguration, `.env`, Token-Dateien und vollständigen Zustandsordner
sichern. Paket oder Docker-Image aktualisieren, `mailhelp --check` ausführen und starten.
Es werden keine neuen Pflichtfelder benötigt. Beim ersten Hinzufügen wird das frühere
Einzelpostfachformat automatisch in `imap.mailboxes` überführt; Nummer und Einstellungen
des alten Postfachs bleiben erhalten. Die Oberfläche funktioniert auch ohne JavaScript.
Für eine Rückkehr Paket/Image und die zusammengehörige Sicherung wiederherstellen.

## Prüfung

Unter Linux/WSL bestehen 2.694 Python-Tests mit 100 % Zeilen- und 100 % Branch-Abdeckung.
202 Browser-Tests prüfen Desktop, Mobil und schmale Ansichten; `app.js` und `sw.js`
erreichen 100 % Blockabdeckung. Ruff und mypy sind ohne Befunde. Das isoliert installierte
Wheel besteht die Paket- und Ressourcenprüfungen. Externe Dienste sind in den Tests simuliert.
