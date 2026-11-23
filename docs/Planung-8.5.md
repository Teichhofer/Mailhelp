# Mailhelp 8.5 – Übersichtliche Einstellungen

**Stand:** 23. November 2026. **Status:** Geplant. Erste Auslieferung 8.5.1; weitere Commits mit
fortlaufenden Patchversionen gemäß [Entwicklungsregeln](../AGENTS.md).

**Grundlagen:** [Entwicklungsregeln](../AGENTS.md),
[Spezifikation](../Mailhelp-Projektspezifikation.md),
[Einstellungen der Weboberfläche](Web-Einstellungen.md),
[Bedienung](Bedienung.md),
[Planung 8.2](Planung-8.2.md) (Onboarding und Kontoverbindungen).

Dieser Plan ändert Darstellung und Bedienung der Einstellungen. Er ändert keine
Bedeutung einer Einstellung, keinen Standardwert und keine Schutzregel: Jede Änderung
bleibt ein Entwurf, wird auf einer Prüfseite mit allen Abweichungen gezeigt und erst
nach ausdrücklicher Bestätigung mit Sitzung, CSRF, Version und Idempotenzschlüssel
übernommen. Externe Schreibaktionen werden durch diesen Plan nicht berührt.

## 1. Ausgangslage (Bestandsaufnahme vom 23. November 2026)

Alle 19 Einstellungsseiten wurden mit synthetischen Daten auf Desktop (1440 px) und
Smartphone (390 px) erfasst.

| Befund | Beleg |
| --- | --- |
| Ein Formular je Einstellung | „Mailabruf“: 55 Einzelformulare, 110 Schaltflächen, 6 200 px Höhe; jede Änderung verlangt Aufklappen, „Prüfen“ und eine eigene Bestätigung |
| Gliederung nach Konfigurationsdatei | 44 Zeitlimits/Wiederholungen von neun Diensten stehen zwischen „Sprache der Oberfläche“ und „Zeitzone“ |
| Verstreute Themen | Benachrichtigungen auf drei Seiten (Bereich, Benachrichtigungsprofil, Zustellhistorie), Briefings als vierter Bereich |
| Doppelte Einstiege | Zugangsdaten, Neustart/Beenden und Verbindungsprüfung sind über zwei bis drei Wege erreichbar; die Übersicht hat 17 Kacheln |
| Vier Navigationsarten | Bereichsliste links, zwei verschiedene Knopfleisten, eine Linkzeile mit neun Links (Zielprofile) |
| Technische Rohwerte | `notifications.categories.decisions`, `["telegram"]`, `true`/`false`, `telegram_bot_token: fehlt`, „Stabile Nummer“, `google`/`todoist`, „h:993 · INBOX“ |
| Fehlende Orientierung | Jede Bereichsseite heißt „Einstellungen“; auf dem Smartphone füllen neun Bereichsknöpfe den ersten Bildschirm |
| Unklare Fehlermeldung | „Einstellungen nicht übernommen; Bestätigung und Sitzung prüfen“ auch dann, wenn eine Verbindungsprüfung fehlt |

## 2. Ziel und Abnahme aus Nutzersicht

1. Die Übersicht zeigt zuerst, was Aufmerksamkeit braucht (Verbindungsprobleme, fehlende
   Zugangsdaten, ausstehende Änderungen), danach höchstens sechs Bereiche.
2. Jede Bereichsseite trägt ihren Namen als Überschrift und eine Brotkrume
   „Einstellungen › Bereich“.
3. Mehrere Werte eines Abschnitts lassen sich auf einmal ändern; eine feste Leiste zeigt
   „n Änderungen“ mit „Verwerfen“ und „Prüfen“. Die Prüfseite listet alle Änderungen mit
   Wirkung („sofort“/„nach Neustart“) und übernimmt sie in einem Schritt.
4. Werte erscheinen mit verständlichen Namen und passenden Eingabeelementen: Ja/Nein,
   Auswahllisten mit Anzeigenamen, Zahlen mit Einheit, Uhrzeiten. Konfigurationsschlüssel
   und Variablennamen stehen nur unter „Technische Details“.
5. Selten benötigte Werte (Zeitlimits, Wiederholungen, Mailgrenzen, Protokollierung)
   liegen unter „Erweitert“; die Zeitlimits als Tabelle Dienst × Wert.
6. Jedes Feld zeigt, ob es vom Standard abweicht, und bietet „Auf Standard zurücksetzen“.
7. Hilfe: ein (i) je Feld; „Dazu fragen“ steht im geöffneten Hilfetext statt als eigener
   Link unter jeder Zeile.
8. Auf dem Smartphone wählt eine kompakte Auswahl den Bereich; der Inhalt beginnt im
   ersten Bildschirm.
9. Eine abgelehnte Übernahme nennt den Grund und den nächsten Schritt, etwa „Erst
   Verbindungen prüfen“ mit direktem Knopf.

## 3. Neue Bereiche

| Bereich (Schlüssel) | Inhalt | Bisher |
| --- | --- | --- |
| Übersicht | Handlungsbedarf, Konten mit Status, Bereiche, Suche | Übersicht mit 17 Kacheln |
| Allgemein (`allgemein`) | Sprache, Zeitzone, Abrufintervall, Mails je Durchlauf, neueste zuerst, Trockenlauf | Teile von „Mailabruf“ |
| Benachrichtigungen (`benachrichtigungen`) | Telegram, Tagesüberblick, Postfach-Briefings, Verweis auf Benachrichtigungsprofil und Zustellhistorie | „Benachrichtigungen“, „Postfach-Briefings“ |
| Antworten und Termine (`antworten`) | unverändert | „Antworten und Termine“ |
| KI und Auswertung (`ki`) | unverändert | „KI und Auswertung“ |
| Daten und Datenschutz (`daten`) | Aufbewahrung, Originalanhänge, Protokolle | „Daten und Protokolle“ |
| Erweitert (`erweitert`) | Aufrufbudget und Mailgrenzen, Zeitlimits und Wiederholungen (Tabelle), Weboberfläche und System | Teile von „Mailabruf“, „Weboberfläche und System“ |

Alte Adressen `?bereich=abruf`, `?bereich=briefing` und `?bereich=system` leiten dauerhaft
auf den neuen Bereich mit dem passenden Abschnitt um; Suchtreffer und Hilfe-Anker bleiben
gültig. Kontenseiten (Postfächer, IServ, Zielprofile, Zugangsdaten) und Inhalte (Themen,
Absender-Regeln) behalten ihre Adressen und erhalten die gemeinsame Kopfzeile.

## 4. Bedienmodell

### 4.1 Abschnittsformulare

- Ein `<form>` je Abschnitt mit allen Feldern; unveränderte Felder werden nicht gesendet.
- `POST /einstellungen/speichern` nimmt einen oder mehrere Werte an (`name`/`value` je
  Feld, höchstens 60 Felder); alle Werte bilden einen gemeinsamen Patch.
- Die vorhandene Prüfseite zeigt alle Änderungen; die Bestätigung erzeugt genau einen
  Konfigurationsbefehl. Ein Fehler in einem Feld lehnt den ganzen Patch ab und nennt das
  Feld; nichts wird teilweise übernommen.
- Ohne JavaScript funktioniert das Formular vollständig; mit JavaScript zählt die Leiste die
  geänderten Felder und warnt beim Verlassen der Seite mit ungesicherten Änderungen.

### 4.2 Felder

- Bezeichnung, darunter ein Satz Hinweis, rechts ein Kennzeichen „sofort“ oder „nach Neustart“.
- Ja/Nein als Auswahl mit „Ja“/„Nein“ (kein `true`/`false`), Listen mit Anzeigenamen.
- „Standard“ als Kennzeichen; ein Abweichen zeigt „Auf Standard zurücksetzen“ (setzt das Feld
  im Formular, gespeichert wird erst über die Prüfseite).
- „Technische Details“ (eingeklappt) nennt Schlüssel, gespeicherten und aktiven Wert.

### 4.3 Erweitert: Zeitlimits als Tabelle

Zeilen: Dienste (IMAP, OpenRouter, Ollama, Telegram, Todoist, Google Kalender, Google Tasks,
CalDAV, Microsoft 365, Notion). Spalten: Zeitlimit, Wiederholungen, erste Wartezeit, längste
Wartezeit. Jede Zelle ist ein Feld desselben Abschnittsformulars.

### 4.4 Benachrichtigungsprofil

Kategorien (Entscheidungen, Aktionsergebnisse, Tagesüberblick, Systemfehler) × Kanäle
(Telegram, Web-Push) als Tabelle mit Häkchen; Ruhezeiten, Bündelung und Zustellung als
beschriftete Felder in Abschnittsformularen statt je Wert eines Formulars.

### 4.5 Einrichtung und Fehlermeldungen

- Ja/Nein und Anbieter mit Anzeigenamen; fehlende Zugangsdaten mit verständlichem Namen.
- Abgelehnte Übernahmen nennen den Grund. Fehlt eine aktuelle Verbindungsprüfung, zeigt die
  Prüfseite das vor der Bestätigung und bietet „Verbindungen prüfen“ an.

## 5. Gemeinsame Kopfzeile und Navigation

- Brotkrume, Bereichsname als `h1`, kurze Beschreibung.
- Desktop: eine Bereichsliste links für alle Einstellungsseiten (Bereiche, Konten, Inhalte,
  System). Smartphone: eine Auswahlliste „Bereich“ mit Sprung ohne JavaScript über ein
  GET-Formular.
- Übersicht: Handlungsbedarf, Konten (Postfächer, IServ, Kalender und Aufgaben,
  Zugangsdaten) mit Status, Bereiche, Inhalte, System. Doppelte Kacheln entfallen; Neustart
  und Beenden stehen nur noch unter „Erweitert“ und im System-Abschnitt der Übersicht.

## 6. Abgrenzung

- Keine neue Einstellung, kein geänderter Standardwert, keine Migration von `config.yaml`.
- Postfach-, IServ- und Zielprofilformulare behalten ihre Abläufe aus 8.1/8.2; sie erhalten
  nur Kopfzeile, Navigation und verständliche Werte.
- Die Telegram-Bedienung bleibt unverändert.

## 7. Arbeitspakete

1. **8.5.1 – Struktur und Lesbarkeit:** neue Bereiche mit Umleitungen, Kopfzeile und
   Navigation, verständliche Werte (Benachrichtigungsprofil, Einrichtung), Hilfe im (i),
   Zeitlimits-Tabelle, Fehlermeldung mit Grund bei abgelehnter Übernahme.
2. **8.5.2 – Abschnittsformulare:** Mehrfach-Patch, gemeinsame Prüfseite, Änderungsleiste,
   Standard-Kennzeichen und Zurücksetzen.
3. **8.5.3 – Übersicht und Smartphone:** Handlungsbedarf, Kontenstatus, Bereichsauswahl
   auf dem Smartphone, Feinschliff und Dokumentation.

## 8. Verbindliche Prüfung

- Tests für jeden Bereich (Felder vollständig, keine Einstellung verloren: die Vereinigung
  aller Bereiche entspricht `SETTINGS_FIELDS`), Umleitungen alter Adressen, Mehrfach-Patch
  (Erfolg, Teilfehler, Wiederholung mit gleichem Schlüssel, veraltete Version, abgelaufene
  Sitzung, fehlende CSRF), Anzeigenamen und Ja/Nein-Werte, Standard-Kennzeichen.
- Golden-Ausgaben und Browserfälle für Desktop und Smartphone, einschließlich Bedienung ohne
  JavaScript und Tastaturbedienung.
- 100 % Zeilen- und Branch-Abdeckung, `python -m devtools.check full --workers 12` und die
  Browsersuite nacheinander; Ruff und mypy ohne Befund.
- Dokumentation: Web-Einstellungen und Bedienung (DE/EN), Hilfeindex, Konfigurationsreferenz
  ohne inhaltliche Änderung, CHANGELOG und README.

## 9. Abnahmeszenarien

1. Sprache und Zeitzone in „Allgemein“ ändern, gemeinsam prüfen, in einem Schritt übernehmen.
2. Drei Zeitlimits in der Tabelle unter „Erweitert“ ändern; die Prüfseite nennt genau drei
   Änderungen mit „nach Neustart“.
3. Einen Wert mit ungültiger Eingabe senden: nichts wird gespeichert, das Feld wird genannt.
4. Benachrichtigungskanäle als Häkchen setzen; keine Rohwerte sichtbar.
5. Alte Adresse `?bereich=abruf` öffnet „Allgemein“ bzw. den passenden Abschnitt.
6. Smartphone (390 px): Bereichsauswahl und erstes Feld im ersten Bildschirm.
7. Übernahme ohne aktuelle Verbindungsprüfung: Grund und Knopf „Verbindungen prüfen“.
