# Mailhelp 8.5 – Umsetzung und Freigabestand

Stand: 23. November 2026. Version 8.5.1. Grundlage: [Planung 8.5](Planung-8.5.md).

## Umgesetzt in 8.5.1

| Planpunkt | Umsetzung |
| --- | --- |
| Bereiche nach Aufgaben | Allgemein, Benachrichtigungen, Antworten und Termine, KI und Auswertung, Daten und Datenschutz, Erweitert; frühere Adressen `abruf`, `briefing`, `system` leiten mit HTTP 308 um |
| Kopfzeile | Bereichsname als Überschrift, „Einstellungen“ als Zuordnung, Rückweg „Alle Einstellungen“ |
| Abschnittsformulare | Ein Formular je Abschnitt; nur geänderte Werte bilden den Patch; gemeinsame Prüfseite; ein Befehl; ungültige Werte werden benannt, nichts teilweise übernommen |
| Felder | Beschriftete Eingaben, Ja/Nein statt `true`/`false`, Wirkung, „Standard“/„angepasst“, „Auf Standard zurücksetzen“, „Technische Details“ |
| Erweitert | Zeitlimits als Tabelle Dienst × Wert mit unsichtbarer Beschreibung je Zelle und Hinweis auf gespeicherte, noch nicht aktive Werte |
| Übersicht | Handlungsbedarf (ausstehende Änderungen, fehlende Zugangsdaten) zuerst; Konten, Bereiche, Inhalte, System |
| Smartphone | Auswahl „Bereich“ mit „Öffnen“ statt neun Knöpfen; Speicherleiste über der Tab-Leiste |
| Einrichtung und Benachrichtigungsprofil | Anzeigenamen für Kategorien, Kanäle, Anbieter, Verbindungsarten und Zugangsdaten |
| Fehlermeldung bei fehlender Prüfung | vorgezogen in 8.4.3 |

## Abweichungen vom Plan

- „Dazu fragen“ steht in der Hinweiszeile unter dem Feld statt im Hilfetext: Der Hilfetext ist ein
  Tooltip, ein Link darin wäre mit Tastatur nicht sicher erreichbar.
- Das Benachrichtigungsprofil zeigt die Kanäle je Kategorie als beschriftete Auswahl (keine, Telegram,
  Push im Browser, beide) statt als Häkchentabelle; Speichern bleibt dort ein Entwurf der Einrichtung.
- Für Einstellungen ohne Standardwert (etwa Zeitzone, Abrufintervall, Zeitlimits) entfällt das
  Kennzeichen „Standard“.
- Treffer der Suche behalten das einzelne Formular je Einstellung.

## Prüfung

- `python -m devtools.check full --workers 12`: 6 408 bestanden, 2 Lasttests bestanden, 100 % Zeilen-
  und Branch-Abdeckung. Neue Tests: `tests/web/test_settings_sections.py` (gemeinsame Übernahme,
  Teilfehler, Konflikte, Zurücksetzen, typisierte Werte, Umleitungen, Sprachcookie, Standardwerte).
- Browsersuite: 1 000 bestanden, 234 übersprungen, 100 % JavaScript-Abdeckung; vier Zeit- und
  Lastausreißer des 15-Minuten-Laufs (Live-Suche, Wischgeste, Postfach-OAuth, Zugangsdaten schmal)
  bestanden einzeln. Neue Browserfälle zählen geänderte Werte, prüfen die Warnung vor dem Verlassen
  und die gemeinsame Übernahme; Smartphone-Prüfungen verlangen 44 px Tippfläche und erreichbare
  Scrollbereiche.
- Ruff und mypy ohne Befund.
