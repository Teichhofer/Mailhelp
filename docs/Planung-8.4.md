# Mailhelp 8.4 – Automatische Erinnerungen für neue Kalendereinträge

**Stand:** 22. November 2026 (überarbeitet nach Codeabgleich). **Status:** Umgesetzt
(Version 8.4.1). Keine automatischen Änderungen an produktiven Kalendereinträgen.

**Zielversion:** 8.4, erste Auslieferung 8.4.1; weitere Commits mit
fortlaufenden Patchversionen gemäß [Entwicklungsregeln](../AGENTS.md).

**Grundlagen:** [Entwicklungsregeln](../AGENTS.md),
[Spezifikation](../Mailhelp-Projektspezifikation.md),
[Planung 7.2](Planung-7.2.md),
[Planung 8.0](Planung-8.0.md),
[Planung 8.1](Planung-8.1.md),
[Ziele einrichten](Ziele-einrichten.md),
[Einstellungen der Weboberfläche](Web-Einstellungen.md).

Dieser Plan autorisiert keine Kalenderanlage und keine Änderung bestehender
Kalendereinträge. Jede geplante Schreibaktion benötigt weiterhin eine
ausdrückliche, versionsbezogene Bestätigung.

## 1. Ziel und Abnahme aus Nutzersicht

Für jedes Zielprofil kann der Nutzer festlegen, ob neu angelegte zeitgebundene
Kalendereinträge eine Benachrichtigung erhalten. Die Option heißt
„Kalendererinnerung hinzufügen“ und ist standardmäßig eingeschaltet.

Neben der Option kann der Nutzer wählen, wie viele Minuten vor dem Termin die
Erinnerung erscheinen soll:

- Standard: **5 Minuten**
- Zulässiger Bereich: **0 bis 1440 Minuten**
- `0` bedeutet eine Erinnerung zum Beginn des Termins
- Ganztägige Termine erhalten keinen zeitlichen Provider-Alarm, solange der
  Anbieter dafür keinen eindeutig zugeordneten Terminzeitpunkt unterstützt

Die Einstellung gilt je Zielprofil. Profile ohne eigene Erinnerungseinstellung
verwenden den Standard des Normalprofils beziehungsweise `true` und `5`.

Die Vorschau und die bestätigungsbedürftige Telegram-/Webkarte müssen vor der
Freigabe erkennen lassen:

```text
Erinnerung: 5 Minuten vor Beginn
```

Bei `1` Minute steht `Erinnerung: 1 Minute vor Beginn`, bei `0` Minuten steht
`Erinnerung: zum Beginn` (Englisch: `Reminder: 5 minutes before start`,
`Reminder: 1 minute before start`, `Reminder: at start`).

Bei deaktivierter Erinnerung steht stattdessen:

```text
Erinnerung: keine
```

(Englisch: `Reminder: none`). Bei ganztägigen Terminen, reinen Dubletten ohne
Schreibvorgang oder Absagen behauptet die Vorschau keine Erinnerung.

Das Speichern der Einstellung allein darf keine Terminschreibaktion auslösen.
Änderungen an bestehenden Terminen werden erst durch die bestehende ausdrückliche
Freigabe wirksam.

## 2. Abgrenzung

Die Version umfasst ausschließlich Provider-Erinnerungen neuer oder in derselben
Bestätigung ausdrücklich aktualisierter Termine.

Nicht Bestandteil sind:

- automatische nachträgliche Aktualisierung bereits angelegter Termine
- Kalenderbenachrichtigungen für Aufgaben oder Fristen
- neue Push-Benachrichtigungen von Mailhelp außerhalb der Kalenderanbieter
- mehrere Erinnerungen je Termin
- individuelle Erinnerungszeiten je Vorschlag
- Erinnerungen an der LLM-Extraktion oder in Vorschlagstexten
- Änderungen an Drittanbieter-Einstellungen, die bereits vorhandene Termine
  individuell überschrieben haben
- E-Mail-/Browser-Benachrichtigungen der Weboberfläche

Bestehende Dubletten bleiben standardmäßig unverändert, wenn die Freigabe nur
„Bereits vorhanden / keine Anlage“ bedeutet. Wird ein bestehender Termin mit
einer bestätigten Vorschlagsänderung aktualisiert, darf die neue
Erinnerungseinstellung in dieselbe bestätigte Änderung übernommen werden.
Dies darf keine zusätzliche Anlage erzeugen.

## 3. Konfigurationsmodell

In `src/mailhelp/config/target_settings.py` werden bei `TargetSettings` zwei
zueinander geprüfte Felder ergänzt:

```yaml
calendar_reminder_enabled: true
calendar_reminder_minutes: 5
```

- `calendar_reminder_enabled: bool = true`
- `calendar_reminder_minutes: int = 5`, `ge=0`, `le=1440`
- Das Feld für Minuten wird auch bei deaktivierter Erinnerung technisch gültig
  gehalten und darf beim späteren Reaktivieren erhalten bleiben
- Bei `calendar_reminder_enabled = false` darf `calendar_reminder_minutes`
  weiterhin als Vorbereitung gespeichert werden
- Ein ungültiger Wert außer dem genannten Bereich wird bereits beim Laden der
  Konfiguration abgewiesen
- Neue Zielprofile übernehmen die Felder wie alle bestehenden Zielfeldwerte
- Bestehende Konfigurationen erhalten beim Upgrade implizit `true` und `5`

Die Felder werden in `config.example.yaml`, der Einstellungsreferenz und der
Weboberfläche sichtbar benannt und zweisprachig dokumentiert:

- Deutsch: „Kalendererinnerung hinzufügen“ / „Minuten vor Beginn“
- Englisch: „Add calendar reminder“ / „Minutes before start“

Die Webeinrichtung (`/einstellungen` für Profil 1 und `/einstellungen/zielprofile`
für weitere Zielprofile) verwendet eine Ja/Nein-Auswahl (bzw. Checkbox) und ein
begrenztes Zahlenfeld (`min=0`, `max=1440`). Bei deaktivierter Erinnerung wird der
Zustand im Hinweistext klar als inaktiv gekennzeichnet, das Zahlenfeld bleibt jedoch
als Vorbereitung speicherbar, damit der vorbereitete Minutenwert beim späteren
Reaktivieren erhalten bleibt. Beide Felder werden in `SETTINGS_FIELDS`,
`docs/Web-Einstellungen.md` sowie `docs/en/Web-Einstellungen.md` geführt.
Das Speichern bleibt Session-, CSRF-, Versions- und Konfigurationsrevisions-geprüft.

## 4. Datenweg und Provider-Anbindung

Die Erinnerung wird aus dem aktiven Zielprofil (`TargetSettings`) über `build_writers`
an die gemeinsame Kalenderbasis `CalendarOperations` (`src/mailhelp/external/calendar.py`)
übergeben, die von `HttpWriter` (Google), `OutlookCalendar` (Microsoft Graph) und
`CalDavCalendar` (CalDAV/iCloud) geerbt wird. Keine einzelne Erstellungsmethode liest
die Einstellung selbst aus Konfigurationsdateien.

Eine gemeinsame, seiteneffektfreie Hilfsfunktion berechnet aus Zielprofil, Terminart
(zeitgebunden vs. ganztägig) und Vorgangsart (Neuanlage, bestätigte Aktualisierung,
Absage, reine Dublette) sowohl den effektiven Erinnerungswert (`int | None`) als auch
den lokalisierten Vorschautext. Vorschau (`CardContent` / Web / Telegram) und
Schreibpfad (`CalendarOperations`) beziehen ihren Wert aus derselben Quelle.
Da `profile_binding.policy_hash` das vollständige Zielprofil umfasst, sichern
Änderungen an den Erinnerungsfeldern automatisch auch die Profilrevision ab.

### 4.1 Google Kalender

Bei neuen zeitgebundenen Ereignissen ergänzt `GoogleCalendar`:

```json
{
  "reminders": {
    "useDefault": false,
    "overrides": [
      {"method": "popup", "minutes": 5}
    ]
  }
}
```

- Bei `enabled = false`: `useDefault: false` und `overrides: []`
- Bei `enabled = true`: genau ein Popup-Hinweis mit dem konfigurierten Wert
- Keine Vermischung mit den im Kalender gespeicherten Standarderinnerungen
- Die Erinnerung wird für neue Ereignisse explizit gesetzt
- Bei einem zeitgebundenen bestätigten Update wird das Feld mitsamt dem übrigen
  neuen Provider-Body aktualisiert
- `0` erzeugt eine Popup-Erinnerung beim Beginn
- Für Ganztagseinträge wird die Erinnerung nicht als minutengenauer Popup-Alarm
  erzeugt

### 4.2 Outlook / Microsoft 365

Der Microsoft-Calendar-Body erhält bei neuen zeitgebundenen Ereignissen:

```json
{
  "isReminderOn": true,
  "reminderMinutesBeforeStart": 5
}
```

Bei deaktivierter Erinnerung:

```json
{
  "isReminderOn": false
}
```

Graph-Felder werden in `_graph_body(...)` gemeinsam mit Start, Ende, Betreff
und übrigen Eigenschaften erzeugt. Bei Ganztagseinträgen bleibt der
Providerwert deaktiviert beziehungsweise wird kein minutengenauer Alarm gesetzt.
Bestehende Update-Pfade dürfen `isReminderOn` nur übernehmen, wenn die aktuelle
Aktualisierung ausdrücklich bestätigt wurde.

### 4.3 CalDAV und Apple Erinnerungen

Für einen neuen CalDAV-Termin wird eine Standard-`VALARM`-Komponente erzeugt:

```text
BEGIN:VALARM
TRIGGER:-PT5M
ACTION:DISPLAY
DESCRIPTION:Mailhelp-Erinnerung
END:VALARM
```

Die ICS-Erzeugung benötigt eine UTC-/Zeitzonen-angepasste, stabile Ausgabe:

- `enabled = true`: genau ein `VALARM` (`TRIGGER:-PT{minutes}M`, für `0`: `TRIGGER:PT0S`)
- `enabled = false`: kein `VALARM`
- Nur zeitgebundene Termine erhalten den Alarm
- Bestehende CalDAV-Einträge werden beim bestätigten Update unverändert
  erhalten, außer die vorhandene Alarmkomponente wird gezielt durch den
  bestätigten neuen Zustand ersetzt (bei deaktivierter Erinnerung entfernt)
- Fremde Eigenschaften, UID und vorhandene nicht verwaltete Komponenten bleiben
  erhalten

Apple iCloud-Kalender nutzt denselben CalDAV-Pfad. Apple-Erinnerungslisten
(`VTODO`) sind keine Kalendertermine und erhalten keine 5-Minuten-Erinnerung.

## 5. Vorschau, Bearbeitung und Zustandsintegration

Die gesamte Vorschau wird auf eine gemeinsame Darstellung des effektiven
Erinnerungswertes umgestellt:

- Provider-neutraler Text für Web, Vorschlagskarte und Telegram
- Keine Anbieter-Spezialisierung in der LLM-Ausgabe
- Keine Überschreibung durch freie Mailtexte
- Keine Änderung des Erinnerungssolls durch Datum-/Uhrzeitbearbeitung
- Bei Änderung des Zielprofils muss die Vorschlagsbindung die neue Profilbindung
  sichtbar machen und die Bestätigung gegen die Profilrevision sperren

Die Vorschlags-Schemaänderung ist nicht notwendig, wenn Erinnerung und Profil
erst beim bestätigten Write aus dem gebundenen Zielprofil ermittelt werden.
Die Vorschau muss trotzdem denselben gebundenen Wert anzeigen. Dafür werden:

1. effektive Zielprofile zentral ermittelt,
2. Providerneutraler Erinnerungstext aus Profil und Terminart gebildet,
3. Vorschau und tatsächlicher Write aus derselben Hilfsfunktion gespeist,
4. Ziel-/Profiländerungen weiterhin als bestehende Versionsabweichung behandelt.

Die Vorschau darf nicht behaupten, dass eine Erinnerung angelegt wird, wenn:

- der Vorschlag ganztägig ist
- der Provider keine bestimmte Erinnerung unterstützt
- der konfigurierte Kalenderdienst nicht erinnert
- eine bestehende Dublette nur übersprungen wird

## 6. Wiederholung, Neustart und Fehlerbehandlung

Das Schreiben bleibt idempotent und versionsgebunden.

- Derselbe Wiederholungsschlüssel darf keinen zweiten Termin mit einer zweiten
  Erinnerung erzeugen
- Ein unklarer Provider-Schreibresultat wird vor Wiederholung gelesen und
  abgeglichen
- Nach Neustart bleibt die Zielprofileinstellung samt Konfigurationsrevision
  erhalten
- Bereits angelegte Einträge werden nicht durch einen Neustart erneut bearbeitet
- Ist die Erinnerung beim Provider ablehnbar oder nicht lesbar:
  - der Termin darf nur gemäß bestehendem Schreibresultat angelegt werden,
  - ein Fehler in der Erinnerung allein darf nicht fälschlich die Anlage als
    fehlgeschlagen darstellen
  - Providerantwort und Nachleseprüfung müssen Alarmwunsch und tatsächlichen
    Providerstand getrennt ausweisen
- Die 5-Minuten-Standardvorgabe beeinflusst keine bereits angelegten Einträge

Die Nachleseprüfung (`verification.py`, `write_verification.py`, `verification_texts.py`)
wird auf die Providerfähigkeiten erweitert. Sie prüft bei Google (`reminders.useDefault == false`
und passender `popup`-Override), Microsoft (`isReminderOn` / `reminderMinutesBeforeStart`)
und CalDAV (`VALARM`-`TRIGGER`), ob der gewünschte Alarm an der angelegten bzw. aktualisierten
Kalenderressource als explizite, nicht standardmäßige Erinnerung existiert (oder bei
Deaktivierung explizit aus ist). Eine Provider-Antwort, die den Alarm nicht bestätigt,
führt nicht zu stiller Wiederholung, sondern zu einer nachvollziehbaren Abweichung im
Nachlesebericht (`reminder` / „Erinnerung“).

## 7. Arbeitspakete

1. **Konfigurationsmodell**
   - Felder in `TargetSettings` und gegebenenfalls Hilfstypen ergänzen
   - Default-Upgrade für bestehende Konfigurationen
   - Schema-, Grenze-, Upgrade- und Profiltests
2. **Provider-Neutraler Kalenderpayload**
   - Gemeinsame Hilfsfunktion für effektive Erinnerung
   - Vorschau-/Telegram-/Webtext ohne Abweichung zum Write
   - Keine Änderung von Dubletten ohne bestätigte Aktualisierung
3. **Provider-Payloads**
   - Google `reminders.overrides`
   - Microsoft `isReminderOn` / `reminderMinutesBeforeStart`
   - CalDAV `VALARM` und Update-Erhaltung
4. **Web-/Einstellungsoberfläche**
   - Zweisprachige Checkbox und Zahlenfeld je Zielprofil
   - Einstellungshilfe mit Standardwert, Grenzen und Schreiben bleibt ungeändert
   - `config.example.yaml` und Einstellungsreferenz aktualisieren
5. **Regressionstests**
   - Alle Grenzen, deaktivierte Erinnerung, Ganztag, Neustart und Wiederholung
   - Provider-spezifische Payloads, Updates, Dubletten und unklare Antworten
   - Vorschau-/Write-Konsistenz
6. **Dokumentation und Release**
   - Spezifikation, Bedienung, Ziele einrichten und README aktualisieren
   - CHANGELOG und Versionsstand gemäß Patch- und Commit-Regeln
   - Releasebericht und Abnahme hinzufügen

## 8. Verbindliche Prüfung

- Neue Terminvorschläge erhalten bei aktivierter Standardoption genau einen
  5-Minuten-Alarm.
- `0` ist als Beginn-Erinnerung möglich.
- Deaktivierung erzeugt keinen Provider-Alarm.
- Bestehende Konfigurationen starten mit aktiviertem 5-Minuten-Alarm.
- Ganztägige Termine bekommen keinen minutengenauen Provider-Alarm.
- Google, Microsoft und CalDAV erhalten für denselben Zielwert ihre
  provider-gerechten Payloads.
- Keine automatische Anlage oder Änderung beim bloßen Speichern der Einstellung.
- Sitzung, CSRF, Versionsprüfung, Zielbindung und Idempotenz bleiben wirksam.
- Neutrale Darstellung in Deutsch und Englisch.
- Neustart, Wiederholung, Callback-, Provider- und Nachlese-Unklarheiten werden
  getestet.
- 100 % Zeilen- und Branch-Abdeckung für eigenen Code.
- Jeder Bugfix enthält einen vor dem Fix fehlschlagenden Regressionstest.
- Vollständige Python-Prüfung:
  `python -m devtools.check full --workers 12`
- Anschließend getrennte Browserprüfung:
  `python -m pytest ui_tests -n 6 --dist worksteal --no-cov`

## 9. Abnahmeszenarien

| Nr. | Szenario | Erwartung |
| --- | --- | --- |
| 1 | Neue Konfiguration ohne Erinnerungseinstellung | Aktiviert, 5 Minuten |
| 2 | Neuer zeitgebundener Termin, Google | Expliziter Popup-Alarm, 5 Minuten |
| 3 | Neuer zeitgebundener Termin, Outlook | `isReminderOn=true`, 5 Minuten |
| 4 | Neuer zeitgebundener Termin, CalDAV | Genau ein `VALARM`, 5 Minuten |
| 5 | Einstellung deaktiviert | Kein Provider-Alarm, kein Schreibzugriff beim Speichern |
| 6 | Minutenfeld auf `0` | Erinnerung zum Beginn |
| 7 | Minutenfeld auf `1441` oder negativ | Konfigurations-/UI-Ablehnung |
| 8 | Ganztägiger Termin | Kein minutengenauer Alarm |
| 9 | Bestehende Dublette, keine bestätigte Änderung | Keine neue Erinnerung nachträglich angelegt |
| 10 | Bestehender Termin, bestätigte Aktualisierung | Erinnerungseinstellung kann in derselben bestätigten Änderung übernommen werden |
| 11 | Wiederholung derselben Bestätigung | Kein zweiter Termin und kein zweiter Alarm |
| 12 | Neustart nach geplanter Anlage | Kein erneuter Schreibzugriff ohne offenen bestätigten Vorgang |
| 13 | Provider antwortet unklar | Nachlesen; keine blinde Wiederholung |
| 14 | Zwei Zielprofile mit unterschiedlichen Werten | Jede Mailverarbeitung verwendet die Profilbindung des Vorschlags |
