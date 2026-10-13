# Mailhelp 2.3 – Planung: Weitere Kalender- und Aufgabenziele, Volltextsuche, Originaldokumente

**Zielversion:** 2.3.0
**Stand:** 13. Oktober 2026
**Status:** Umgesetzt in 2.3.0 (Branch `beta`)
**Grundlage:** [Entwicklungsregeln](../AGENTS.md), [Projektspezifikation](../Mailhelp-Projektspezifikation.md),
[Planung-2.2.md](Planung-2.2.md), [Architektur-2.1.md](Architektur-2.1.md)

---

## 1. Ziel

Bisher legt Mailhelp Termine ausschließlich in **Google Kalender** und Aufgaben
ausschließlich in **Todoist** an. Die Weboberfläche durchsucht nur Absender,
Betreff und Zusammenfassung, und von Anhängen sind nur Bildvorschauen abrufbar.

Version 2.3 ergänzt:

| Bereich | Bisher | Neu in 2.3 |
| --- | --- | --- |
| Kalender | Google Kalender | zusätzlich **CalDAV** (Nextcloud, iCloud, mailbox.org, Radicale, …) und **Outlook / Microsoft 365** (Microsoft Graph) |
| Aufgaben | Todoist | zusätzlich **Microsoft To Do** (Microsoft Graph), **CalDAV-VTODO** (Nextcloud Tasks, Thunderbird, …) und **Apple Erinnerungen** (iCloud-CalDAV, siehe Einschränkung 4.5) |
| Suche | Absender, Betreff, Zusammenfassung | zusätzlich **Volltext über Mailtext und erkannten Anhangtext** sowie Anhangnamen, mit Trefferausschnitt |
| Anhänge | nur Bildvorschau (JPEG) | **Download der Originaldokumente** (PDF, Word, Excel, OpenDocument, Text, Bilder …) |

Pro Installation ist je **ein** Kalenderziel und **ein** Aufgabenziel aktiv
(`targets.calendar_provider`, `targets.task_provider`). Mehrere Ziele
gleichzeitig sind nicht Teil von 2.3.

**Nicht Teil von 2.3:** Synchronisation in beide Richtungen, Bearbeiten
externer Einträge außerhalb der bestehenden Mailhelp-Abläufe (Duplikatergänzung,
Terminänderung, Absage), mehrere gleichzeitige Ziele, Exchange On-Premises/EWS,
Abruf alter Originalanhänge aus dem Postfach.

---

## 2. Verbindliche Grundsätze (unverändert gültig)

- **Bestätigung vor jedem Schreibzugriff:** Jeder neue Anbieter läuft über
  `execute_confirmed` und damit über dieselbe versionsbezogene Bestätigung per
  Telegram oder authentifizierter Weboberfläche. Bearbeiten/Speichern allein
  autorisiert keine Anlage. Der Zielabgleich (`proposal.target == writer.target`)
  gilt für alle Anbieter.
- **Keine Doppelanlage:** Jeder Anbieter muss einen *Abgleich* (`reconcile`) über
  den Idempotenzschlüssel `mailhelp:<mail>:<vorschlag>:v<version>` können. Unklare
  Schreibresultate werden vor jeder Wiederholung abgeglichen und nie blind
  wiederholt.
- **Nicht vertrauenswürdige Eingaben:** Antworten der Anbieter (JSON, XML, iCalendar)
  werden schemageprüft bzw. defensiv geparst; nur allow-gelistete Fehlergründe
  werden protokolliert. Mail- und Anhanginhalte werden beim Download nie als
  aktiver Inhalt ausgeliefert.
- **Geheimnisse:** Zugangsdaten nur in Umgebung/`.env` bzw. (rotierte
  OAuth-Refresh-Tokens) in einer eigenen Zustandsdatei; nie in Logs, Exporten
  oder Diagnoseausgaben.
- **Tests:** 100 % Zeilen- und Branch-Abdeckung, externe Dienste simuliert
  (`httpx.MockTransport`), synthetische Daten. Erfolg, Fehler, Wiederholung,
  Neustart und Autorisierung werden für jeden Anbieter geprüft.

---

## 3. Architektur der Schreibziele

### 3.1 Ausgangslage

`HttpWriter` vereint Google Kalender und Todoist in einer Klasse, unterschieden
über `service`. Mehrere Stellen prüfen `isinstance(writer, HttpWriter)` und
`writer.service == "google_calendar"` (Vorabprüfung, `execute_confirmed`,
Einrichtung). Die Writer liegen in einem Wörterbuch mit den Schlüsseln
`"google_calendar"` und `"todoist"`; diese Schlüssel sind auch in
`WriteAttemptReference.service` persistiert.

### 3.2 Entscheidung: Rollen-Slots bleiben, Anbieter werden austauschbar

- Die Wörterbuchschlüssel bleiben als **Rollen-Slots** erhalten:
  `"google_calendar"` = Kalenderrolle, `"todoist"` = Aufgabenrolle. Eine
  Umbenennung würde gespeicherte Zustände (`write_attempts`) ändern und eine
  Migration erfordern, ohne fachlichen Gewinn. Die Bedeutung wird in
  `external/roles.py` als Konstanten `CALENDAR_SLOT` / `TASK_SLOT` dokumentiert.
- Neue Basisklasse **`TargetWriter`** (`external/contracts.py`) beschreibt die
  gemeinsame Schnittstelle aller Anbieter:
  `service`, `role` (`"calendar"`/`"tasks"`), `target`, `label`,
  `check_access()`, `reconcile(key)`, `prepare(proposal, key) -> PreparedWrite`,
  `create(...)`, `close()` sowie lesend `fetch_events_in_window(...)`
  (Kalender) bzw. `fetch_active_tasks()` (Aufgaben).
- `HttpWriter` (Google/Todoist) erbt von `TargetWriter`; Verhalten und
  Request-Bodies bleiben byte-gleich.
- `execute_confirmed`, Vorabprüfung (`precheck.py`) und Einrichtung prüfen
  künftig `isinstance(writer, TargetWriter)` und `writer.role` statt
  `HttpWriter`/`service`.

### 3.3 Gemeinsame Kalenderlogik

Duplikatsuche per LLM (`calendar_matcher`), Ergänzen fehlender Felder,
deterministischer Zeitvergleich mit Änderungsnotiz sowie Änderung/Absage über
`target_event_id` sind heute Google-spezifisch in `CalendarOperations`
implementiert. `CalendarOperations` wird zum **anbieterneutralen Ablauf**:
Die Google-spezifischen Zugriffe werden in überschreibbare Methoden ausgelagert
(`_calendar_candidates`, `_insert_calendar_event`, `_update_calendar_event`,
Abgleich über `reconcile`), sodass jeder Kalenderanbieter nur noch diese vier
Primitive implementiert:

| Primitive | Google | CalDAV | Outlook (Graph) |
| --- | --- | --- | --- |
| `_find_by_key(key)` | `privateExtendedProperty` | `GET <kalender>/<uid>.ics` | `$filter` auf `singleValueExtendedProperties` |
| `_events_between(start, end)` | `events.list` mit Paging | `REPORT calendar-query` mit `time-range` | `calendarView` mit `@odata.nextLink` |
| `_insert(body, key)` | `POST events` | `PUT <uid>.ics` mit `If-None-Match: *` | `POST events` mit `transactionId` |
| `_update(event_id, patch, key)` | `PATCH events/<id>` | `GET` + `PUT` mit `If-Match: <ETag>` | `PATCH events/<id>` |

Alle Anbieter liefern vorhandene Termine als normalisiertes
`CalendarOverlapEvent` (`start`/`end` als `{"dateTime": …}` bzw. `{"date": …}`,
Ende ganztägig exklusiv). Der Änderungs-*Patch* bleibt das bisherige neutrale
Format (`summary`, `description`, `location`, `start`, `end`, `status`), das
jeder Anbieter in sein eigenes Format übersetzt. Damit funktionieren
Duplikatprüfung, Zeitänderungen und Absagen für alle Kalender gleich.

### 3.4 Anbieter-Fabrik

`external/providers.py` baut aus `Settings` und `Secrets` die beiden Writer
(`build_calendar_writer`, `build_task_writer`). `composition.py` und die
Einrichtung (`setup_runtime.py`) nutzen ausschließlich diese Fabrik.

---

## 4. Anbieter im Einzelnen

### 4.1 CalDAV-Kalender (Nextcloud, iCloud, mailbox.org, Radicale, …)

- **Ziel:** vollständige URL der Kalendersammlung, z. B.
  `https://cloud.example.org/remote.php/dav/calendars/anna/personal/`.
- **Anmeldung:** HTTP Basic mit Benutzername und *App-Passwort*
  (`CALDAV_USERNAME`, `CALDAV_PASSWORD`). Nur `https://` (Ausnahme: `localhost`
  für Tests/Radicale lokal).
- **Idempotenz:** Die UID des Termins wird deterministisch aus dem
  Idempotenzschlüssel abgeleitet (`mailhelp-<sha256[:32]>@mailhelp`), die
  Ressource heißt `<uid>.ics`. Anlage per `PUT` mit `If-None-Match: *`:
  - `201/204` → angelegt,
  - `412` → existiert bereits → per `GET` abgeglichen (kein Fehler, keine Doppelanlage),
  - Zeitüberschreitung/Transportfehler → *unklar*, späterer Abgleich per `GET`.
- **Inhalt:** iCalendar `VEVENT` mit `UID`, `DTSTAMP`, `SUMMARY`, `DESCRIPTION`,
  `LOCATION`, `DTSTART`/`DTEND` (UTC bzw. `VALUE=DATE`), `URL` (Videolink) und
  `X-MAILHELP-KEY`. Texte werden nach RFC 5545 maskiert und gefaltet.
- **Lesen:** `REPORT` (`calendar-query`, `time-range`), Antwort per
  `xml.etree` mit Größenlimit; VEVENTs über den vorhandenen ICS-Parser
  normalisiert.
- **Änderung/Absage:** `GET` (ETag) → Felder ersetzen, `SEQUENCE` erhöhen bzw.
  `STATUS:CANCELLED` → `PUT` mit `If-Match`. `412` → unklar/erneut abgleichen.
- **Zugriffsprüfung:** `PROPFIND` Tiefe 0 auf die Sammlung, prüft
  `calendar`-Ressourcentyp und `VEVENT`-Unterstützung.

### 4.2 Outlook / Microsoft 365 Kalender (Microsoft Graph)

- **Ziel:** Kalender-ID oder `default` für den Standardkalender.
- **Anmeldung:** OAuth 2.0 mit Refresh-Token (Microsoft Identity Platform,
  Scopes `offline_access Calendars.ReadWrite Tasks.ReadWrite`). Neue
  Geheimnisse `MICROSOFT_CLIENT_ID`, optional `MICROSOFT_CLIENT_SECRET`
  (öffentlicher Client ohne Secret wird unterstützt); der Mandant (Standard
  `common`) steht in `config.yaml` unter `targets.microsoft_tenant`.
- **Refresh-Token-Rotation:** Microsoft stellt bei jedem Token-Abruf einen neuen
  Refresh-Token aus. Der jeweils neueste wird atomar in
  `microsoft-token.json` neben `.env` gespeichert (lesbares JSON, Dateirechte
  0600 unter Linux; außerhalb des Zustandsverzeichnisses, damit
  `mailhelp --clear` die Anmeldung behält) und beim nächsten Start bevorzugt. Ein Startwert kommt aus
  `MICROSOFT_REFRESH_TOKEN` oder aus der neuen Anmeldung
  **`mailhelp --microsoft-login`** (Gerätecode-Verfahren: Code im Terminal,
  Bestätigung im Browser, kein Redirect-Server nötig).
- **Idempotenz:** Erweiterte Eigenschaft
  `String {6b1c9a0e-4f43-4c9a-9d55-6d61696c6865} Name mailhelpKey` mit dem
  Idempotenzschlüssel; Abgleich per `$filter`. Zusätzlich `transactionId`
  (Graph verwirft Doppelanlagen mit gleicher ID serverseitig).
- **Zeiten:** `dateTime` + `timeZone: "UTC"`; ganztägig `isAllDay: true` mit
  Mitternachtsgrenzen in der konfigurierten Zeitzone.
- **Änderung:** `PATCH`; **Absage:** `DELETE` des Termins (Graph erlaubt
  `cancel` nur dem Organisator von Besprechungen).
- **Fehlerklassen:** `401` → Token verwerfen, `AuthenticationError`;
  `403`/`404` → `CalendarAccessError`; `429`/`5xx` → wiederholbar
  (`Retry-After` wird beachtet, begrenzt durch die Backoff-Grenze).

### 4.3 Microsoft To Do (Microsoft Graph)

- **Ziel:** ID der Aufgabenliste oder `default` (Liste mit
  `wellknownListName == "defaultList"`, einmalig ermittelt).
- **Anmeldung:** wie 4.2 (gemeinsamer Token-Anbieter).
- **Inhalt:** `title`, `body` (Text, mit Marker `[mailhelp:…]`),
  `dueDateTime` (Datum bzw. Zeitpunkt in UTC), `linkedResources` mit
  `externalId = Idempotenzschlüssel` und `applicationName = "Mailhelp"`.
- **Abgleich:** Aufgaben der Liste mit `$expand=linkedResources` seitenweise
  lesen, Treffer über `externalId` oder Marker im Text (wie Todoist).
- **Vorabprüfung:** offene Aufgaben (`status ne 'completed'`) als normalisierte
  `TodoistTaskResponse`-kompatible Einträge.

### 4.4 CalDAV-Aufgaben (VTODO)

- **Ziel:** URL einer Aufgabenliste (Sammlung mit `VTODO`-Unterstützung),
  z. B. Nextcloud Tasks.
- Gleiches Verfahren wie 4.1 (`PUT` mit `If-None-Match`, deterministische UID,
  `GET`-Abgleich), Inhalt `VTODO` mit `SUMMARY`, `DESCRIPTION`, `DUE`,
  `STATUS:NEEDS-ACTION`, `X-MAILHELP-KEY`.
- Vorabprüfung über `REPORT` mit Filter auf nicht abgeschlossene VTODOs.

### 4.5 Apple Erinnerungen

Apple bietet **keine offizielle Programmierschnittstelle** für Erinnerungen.
Erreichbar ist nur der iCloud-CalDAV-Dienst (`https://caldav.icloud.com`) mit
App-spezifischem Passwort. Erinnerungslisten, die in iOS 13+ auf die „neuen“
iCloud-Erinnerungen aktualisiert wurden, sind dort **nicht mehr sichtbar**.

Umsetzung: Anbieter `apple_reminders` ist eine **CalDAV-VTODO-Voreinstellung**
mit iCloud-Basis-URL. Die Zugriffsprüfung erkennt eine fehlende bzw. nicht
VTODO-fähige Liste und meldet verständlich, dass die Liste über CalDAV nicht
erreichbar ist. Diese Einschränkung steht in Konfigurationshilfe, README und
Spezifikation. Kein Workaround über Kurzbefehle/AppleScript (nicht serverseitig
unter Docker/Windows ausführbar).

### 4.6 Konfiguration

```yaml
targets:
  calendar_provider: google          # google | caldav | outlook
  task_provider: todoist             # todoist | microsoft_todo | caldav | apple_reminders
  google_calendar: primary           # nur bei calendar_provider: google
  todoist_project: "2203306141"      # nur bei task_provider: todoist
  caldav_calendar_url: ""            # bei calendar_provider: caldav
  caldav_task_url: ""                # bei task_provider: caldav / apple_reminders
  outlook_calendar: default          # bei calendar_provider: outlook
  microsoft_todo_list: default       # bei task_provider: microsoft_todo
  microsoft_tenant: common           # outlook / microsoft_todo
timeouts:
  caldav:    {timeout_seconds: 30, retries: 2, initial_backoff_seconds: 1, max_backoff_seconds: 10}
  microsoft: {timeout_seconds: 30, retries: 2, initial_backoff_seconds: 1, max_backoff_seconds: 10}
```

- Fehlende neue Schlüssel haben Standardwerte, bestehende `config.yaml` bleiben
  gültig (Anbieter `google`/`todoist`).
- Ein Validator verlangt das jeweils benötigte Ziel (z. B. `caldav_calendar_url`
  bei `calendar_provider: caldav`, `https://`-URL).
- `TargetSettings.calendar_target` / `task_target` liefern das aktive Ziel; der
  Vorschlag speichert es weiterhin in `proposal.target`. Ein Anbieterwechsel
  ändert damit das Ziel, und bereits bestätigte Vorschläge für das alte Ziel
  werden wie bisher nicht in das neue geschrieben (`target_mismatch`).
- **Geheimnisse** werden nur für die gewählten Anbieter verlangt:
  Google (`GOOGLE_OAUTH_*`), Todoist (`TODOIST_*`), CalDAV/Apple
  (`CALDAV_USERNAME`, `CALDAV_PASSWORD`), Microsoft (`MICROSOFT_CLIENT_ID`,
  optional `MICROSOFT_CLIENT_SECRET`, `MICROSOFT_REFRESH_TOKEN` oder gespeicherte
  Anmeldung).
- Anbieterwahl und Ziele sind analyseneutral (kein Fingerprint-Wechsel) und in
  den Web-Einstellungen mit Hilfetexten änderbar.

### 4.7 Anzeige

Alle Texte „Google Kalender“/„Todoist“ in Telegram, Web, Tagesüberblick und
Metriken verwenden das Anbieter-Label (`Nextcloud/CalDAV-Kalender`,
`Outlook-Kalender`, `Microsoft To Do`, `CalDAV-Aufgaben`,
`Apple Erinnerungen`). Schaltflächen bleiben neutral („Im Kalender anlegen“,
„Als Aufgabe anlegen“). Links auf angelegte Einträge erscheinen nur, wenn der
Anbieter eine `https`-Adresse liefert (Graph `webLink`, Google `htmlLink`).

---

## 5. Volltextsuche in der Weboberfläche

### 5.1 Verhalten

- Das Suchfeld unter `/mails` durchsucht künftig **Absender, Betreff,
  Zusammenfassung, Mailtext, Anhangnamen und erkannten Anhangtext** (PDF-Text,
  OCR/Vision, Office-Text, Kalenderdateien).
- Mehrere Wörter werden **alle** verlangt (UND), unabhängig von Reihenfolge,
  Groß-/Kleinschreibung und Umlaut-Schreibweise (`ä`↔`ae`, `ß`↔`ss`, Unicode-NFKC).
  Begriffe in Anführungszeichen suchen die genaue Wortfolge.
- Auswahl „Suchen in“: *Alles* (Standard) oder *Nur Absender/Betreff*.
- Jeder Treffer zeigt, **wo** er gefunden wurde (Betreff, Mailtext,
  Anhang „rechnung.pdf“) und einen kurzen, HTML-maskierten Ausschnitt mit
  hervorgehobenem Begriff (`<mark>`).
- Funktioniert ohne JavaScript; Schnellfilter, Zeitraum, Thema und Status
  bleiben kombinierbar.

### 5.2 Umsetzung

- Der vorhandene revisionsgesteuerte Index in `review/queries.py` erhält je Mail
  ein normalisiertes Textfeld (`fulltext`), begrenzt auf 200 000 Zeichen je Mail.
  Er wird wie bisher nur bei geänderter Archivrevision neu aufgebaut.
- Nach Ablauf der Aufbewahrung (`retention.full_mail_days`) ist der Volltext
  entfernt; die Suche findet dann nur noch Metadaten. Die Oberfläche weist
  darauf hin.
- Keine Suchbegriffe in Logs (nur Trefferzahl und Dauer).

---

## 6. Download der Originaldokumente

### 6.1 Verhalten

- In der Maildetailansicht erhält jeder gespeicherte Anhang einen Link
  **„Original herunterladen“** (Dateiname, Typ, Größe).
- Erlaubte Typen (Allowlist nach Endung *und* erkannter Signatur): PDF, DOC,
  DOCX, ODT, RTF, TXT, CSV, XLS, XLSX, ODS, PPT, PPTX, ODP, ICS, JPG, PNG, GIF,
  WEBP, HEIC. Andere Dateien (z. B. `.exe`, `.html`, `.js`, `.svg`) werden nicht
  gespeichert und nicht angeboten.
- Höchstgröße je Datei `attachments.max_original_bytes` (Standard 25 MB),
  Gesamtgröße je Mail `attachments.max_total_bytes` (Standard 50 MB); Speichern
  abschaltbar (`attachments.store_originals`, Standard `true`).

### 6.2 Speicherung

- `AttachmentCache.prepare` legt zusätzlich zur Vorschau die Originaldatei als
  `<state>/attachments/<mail>/original-<index>.bin` ab (atomar), Metadaten
  (Name, Typ, Größe, SHA-256) in einem eigenen Manifest `originals.json`
  daneben. Die vorbereitete Mail, die an das LLM geht, bleibt unverändert.
- Aufbewahrung wie Vorschauen: `retention.full_mail_days` und `mailhelp --clear`
  löschen das Verzeichnis.
- Bereits verarbeitete Mails haben kein Original; die Oberfläche zeigt dann
  „Original nicht gespeichert (vor 2.3 verarbeitet)“.

### 6.3 Sicherheit

- Route `GET /mail/<id>/original/<index>` nur mit gültiger Sitzung.
- Antwort immer mit `Content-Disposition: attachment; filename*=UTF-8''…`
  (Dateiname bereinigt, ASCII-Ersatzname), `Content-Type` aus der Allowlist
  (nie aus der Mail), `X-Content-Type-Options: nosniff`,
  `Content-Security-Policy: default-src 'none'; sandbox`, `Cache-Control:
  private, no-store`.
- Pfade nur über geprüfte Mail-ID und ganzzahligen Index; Symlinks werden
  abgelehnt; SHA-256 wird vor der Auslieferung verglichen.
- Protokoll nur `attachment_downloaded` mit Mail-ID, Index und Größe – kein
  Dateiname.

---

## 7. Einrichtung, Diagnose, CLI

- Einrichtungsschritt 3 („Ziele“) zeigt Anbieterwahl und die passenden Felder;
  die Zugriffsprüfung nutzt die Anbieter-Fabrik.
- Diagnose `calendar`/`todoist` prüfen den gewählten Anbieter lesend
  (`PROPFIND`/`GET`).
- `mailhelp --microsoft-login` startet das Gerätecode-Verfahren und speichert den
  Refresh-Token; Ausgabe enthält nie Tokens.
- `secret_status` zeigt nur die für die gewählten Anbieter nötigen Geheimnisse.

---

## 8. Umsetzung in Phasen

| Phase | Inhalt | Ergebnis |
| --- | --- | --- |
| P1 | `TargetWriter`, Rollen-Slots, anbieterneutrale Primitive in `CalendarOperations`; `execute_confirmed`/Vorabprüfung auf `TargetWriter` umstellen | Google/Todoist verhalten sich unverändert, alle bestehenden Tests grün |
| P2 | Konfiguration (`TargetSettings`, Timeouts), Geheimnisse je Anbieter, Anbieter-Fabrik, Labels | bestehende Konfigurationen gültig, neue validiert |
| P3 | CalDAV-Kalender + CalDAV-VTODO + Apple-Voreinstellung (iCalendar-Erzeugung, XML-Lesen) | Anlage, Abgleich, Duplikat, Änderung, Absage |
| P4 | Microsoft-OAuth (Rotation, Gerätecode), Outlook-Kalender, Microsoft To Do | wie P3 |
| P5 | Volltextsuche (Index, Normalisierung, Ausschnitte, UI) | `/mails` mit Volltext |
| P6 | Originalanhänge (Speicherung, Route, UI, Aufbewahrung) | Download in Maildetail |
| P7 | Einrichtung/Diagnose/Web-Einstellungen/Hilfetexte, Spezifikation, `config.example.yaml`, README, CHANGELOG, Version 2.3.0 | Abnahme |

---

## 9. Tests

- **Je Anbieter** (simuliert mit `httpx.MockTransport`):
  Anlage Erfolg; Abgleich findet vorhandenen Eintrag; unklares Ergebnis
  (Timeout) → `UNCERTAIN` und kein zweiter Schreibversuch; Neustart mit
  `WRITING`/`UNCERTAIN` → nur Abgleich; `401`/`403`/`404` → dauerhafte Fehler
  mit Klassifikation; `429`/`5xx` → Wiederholung; ungültige Antworten (JSON/XML/ICS)
  → kontrollierter Fehler; Zielabweichung → kein Kontakt; Testmodus → kein Kontakt.
- **CalDAV:** `412` bei `If-None-Match` → Abgleich statt Fehler; ETag-Konflikt bei
  Änderung; Maskierung/Faltung von Sonderzeichen und Zeilenumbrüchen;
  ganztägige Termine; XML mit fremden Namensräumen und Paging-freien Antworten.
- **Microsoft:** Token-Rotation wird gespeichert und nach Neustart verwendet;
  Gerätecode-Ablauf inkl. `authorization_pending`/`slow_down`/`expired_token`;
  `Retry-After`; Standardliste/Standardkalender.
- **Fabrik/Konfiguration:** alle Kombinationen, fehlende Geheimnisse je Anbieter,
  unsichere URLs, alte Konfiguration ohne neue Schlüssel.
- **Volltextsuche:** Body-, Anhang- und Namens-Treffer, UND-Verknüpfung,
  Phrasen, Umlaut-Varianten, Ausschnitt mit Maskierung (XSS), nach Aufbewahrung
  entfernte Texte, Begrenzung.
- **Originale:** Allowlist (Endung + Signatur), Größenlimits, verbotene Typen,
  Header, Pfad-/Symlink-Schutz, Hash-Abweichung, ohne Sitzung → Anmeldung,
  Aufbewahrung löscht Originale.
- **Browser (`ui_tests`):** Suche mit Treffer im Anhang, Download-Link,
  Anbieterwahl in Einstellungen; axe ohne Befund; 100 % JS-Abdeckung bleibt.

---

## 10. Entscheidungen

1. **Rollen-Slots statt Umbenennung** der Writer-Schlüssel (Zustandskompatibilität).
2. **Ein Ziel je Rolle** – mehrere parallele Ziele erst nach Rückmeldung.
3. **CalDAV ohne Fremdbibliothek:** `httpx` + `xml.etree` + eigener
   iCalendar-Schreiber/-Leser (vorhanden: `external/ical.py`,
   `calendar_parser.py`). Keine neue Abhängigkeit.
4. **Microsoft ohne MSAL:** Token-Endpunkt und Gerätecode-Verfahren direkt über
   `httpx`; Rotation persistent.
5. **Apple Erinnerungen nur über iCloud-CalDAV** mit klar dokumentierter
   Einschränkung.
6. **Outlook-Absage per `DELETE`**, CalDAV per `STATUS:CANCELLED`, Google wie
   bisher `status: cancelled`.
7. **Originale nur für neu verarbeitete Mails**; kein nachträglicher
   Postfachabruf.
8. **Volltextindex im Speicher** (Einzelnutzer, begrenzte Mailzahl durch
   Aufbewahrung); kein externer Suchdienst.

---

## 11. Risiken

| Risiko | Gegenmaßnahme |
| --- | --- |
| CalDAV-Server unterscheiden sich (ETag-Format, REPORT-Unterstützung) | nur Kern-RFC 4791; Vorabprüfung fällt bei REPORT-Fehler weich auf „keine Duplikate gefunden“ zurück, Anlage bleibt idempotent über UID |
| Microsoft-Refresh-Token verfällt (90 Tage Inaktivität, Widerruf) | Diagnose meldet Ablauf verständlich; `--microsoft-login` erneuert |
| Apple-Erinnerungen über CalDAV nicht sichtbar | Diagnose erkennt es; Dokumentation |
| Speicherbedarf durch Originale | Größenlimits, Aufbewahrung, abschaltbar |
| Gefährliche Anhänge | Allowlist mit Signaturprüfung, nur als Download, Sandbox-CSP |
| Index-Speicher bei großem Archiv | 200 000 Zeichen je Mail, Aufbewahrung begrenzt Anzahl |
