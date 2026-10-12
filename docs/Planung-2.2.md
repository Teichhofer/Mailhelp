# Mailhelp 2.2 – Planung: Tätigkeitsbericht

**Zielversion:** 2.2.0
**Stand:** 12. Oktober 2026
**Status:** Geplant, Entscheidungen getroffen (folgt auf 2.1.0)
**Grundlage:** [Entwicklungsregeln](../AGENTS.md), [Projektspezifikation](../Mailhelp-Projektspezifikation.md),
[Release-2.0.md](Release-2.0.md), [Planung-2.1.md](Planung-2.1.md)

---

## 1. Ziel

Ein neuer Modus **Tätigkeitsbericht** beantwortet die Frage: *„An welchen Terminen
war ich im Zeitraum X für das Thema Y tätig?“* – etwa für den Jahresbericht eines
Ehrenamts, eine Abrechnung oder einen Nachweis gegenüber dem Arbeitgeber.

Ablauf aus Sicht des Nutzers:

1. In der Weboberfläche einen Bericht anlegen: Thema mit Beschreibung,
   Zeitraum und Ordner.
2. Mailhelp liest alle Mails des Zeitraums schreibfrei aus dem Postfach,
   überspringt ignorierte Absender und lässt jede übrige Mail per LLM prüfen, ob
   sie zum Berichtsthema gehört.
3. Aus jeder relevanten Mail extrahiert ein zweiter LLM-Schritt alle genannten
   Termine – ausdrücklich **auch vergangene**.
4. Die Weboberfläche zeigt die Termine chronologisch mit ihrer Quellmail. Der
   Nutzer kann Fehltreffer ausschließen und Termine korrigieren.
5. Ein Klick erzeugt eine **xlsx-Liste** mit Termin, Datum, Mailbetreff,
   Absender und Volltext.

**Nicht Teil von 2.2:** Anlage der Termine in Google Kalender oder Todoist,
Versand des Berichts, Bewertung von Arbeitszeit oder Kosten, Mehrbenutzerbetrieb,
eine Telegram-Bedienung des Berichts.

---

## 2. Verbindliche Grundsätze

- **Lesend:** Der Bericht schreibt nichts in Postfach, Kalender oder Todoist.
  IMAP wird nur mit `select(readonly=True)` und `BODY.PEEK` gelesen; `\Seen`
  bleibt unverändert.
- **Getrennt vom Normalbetrieb:** Berichte erzeugen keine Vorschläge, keine
  Telegram-Nachrichten, keine Pushes und keine Einträge in `mail-*.json`,
  `duplicate-index` oder den UID-Checkpoints der Mailverarbeitung. Ein Bericht
  verändert keinen Analyse-Fingerprint.
- **Nicht vertrauenswürdig:** Mailinhalte und LLM-Ausgaben sind Daten. Jedes
  LLM-Ergebnis wird per Pydantic-Schema geprüft; Termine brauchen einen Beleg,
  der wörtlich in der Mail steht.
- **Kostenkontrolle:** Jede Mail wird höchstens einmal je Schritt bewertet,
  auch nach Neustarts. Vor dem Start nennt die Oberfläche Mailzahl und
  geschätzte Kosten; ein Höchstwert je Bericht ist konfigurierbar.
- **Weboberfläche:** Jede Aktion braucht eine gültige, bei Ausführung erneut
  geprüfte Sitzung, CSRF-Schutz, Versionsprüfung und einen Idempotenzschlüssel.
  Alle Funktionen gehen auch ohne JavaScript.
- **Datenschutz:** Berichte enthalten Volltexte. Sie unterliegen einer eigenen
  Aufbewahrungsfrist, werden von `mailhelp --clear` gelöscht und erscheinen nicht
  in normalen Anwendungslogs (vollständige LLM-Inhalte nur bei eingeschaltetem
  LLM-Logging).
- **Konfiguration:** Einstellungen in `config.yaml`, Prompts in `prompts.yaml`,
  Zustand als lesbares, schema-versioniertes JSON, Ereignisse als JSONL.
- **Qualität:** 100 % Zeilen- und Branch-Abdeckung, Browsertests mit 100 %
  JavaScript-Blockabdeckung, simulierte Dienste und synthetische Daten.

---

## 3. Warum ein eigener Lauf und nicht die gespeicherten Mails?

| Gegebenheit | Folge |
| :--- | :--- |
| `retention.full_mail_days: 30` entfernt Mailtexte nach 30 Tagen | Für einen Jahresbericht fehlen die Texte im Zustand. |
| `imap.historical_start` begrenzt den Normalbetrieb (aktuell 01.10.2026) | Ältere Mails wurden nie analysiert. |
| Die Relevanzprüfung des Normalbetriebs prüft gegen `topics.yaml` | Das Berichtsthema ist meist enger oder anders geschnitten. |
| `event_extraction` stuft vergangene Termine als `already_completed` ein und erwartet eine Anzahl aus `action_router` | Für einen Rückblick ungeeignet. |

Der Bericht liest deshalb selbst aus IMAP. Dafür genügt der vorhandene,
schreibfreie `ImapReader` (`discover_since` mit `SINCE`, `fetch_uid` mit
`BODY.PEEK[]`), dazu `mime.prepare` samt Anhangextraktion. Für Absender und
Anhänge werden vorhandene Bausteine wiederverwendet:
`sender_filter.is_irrelevant_sender`, `attachment_extractor` und das
LLM-Ratenbudget des Adapters.

---

## 4. Fachliches Modell

### 4.1 Berichtsdefinition

| Feld | Beschreibung | Prüfung |
| :--- | :--- | :--- |
| `title` | Name des Berichts, z. B. „Elternbeirat 2025/26“ | 1–120 Zeichen |
| `topic` | Thema in eigenen Worten: worum es geht, was dazugehört, was nicht | 10–2.000 Zeichen |
| `since`, `until` | Berichtszeitraum (Mail-Eingangsdatum, lokale Zeitzone) | `since ≤ until`, höchstens 3 Jahre |
| `folders` | Ordner, Standard: `imap.folders` ohne Papierkorb, Spam und Entwürfe | nur per `LIST` bekannte Ordner |
| `include_sent` | Gesendete Mails einbeziehen (eigene Zusagen belegen Tätigkeit) | Standard: ja, falls ein `\Sent`-Ordner existiert |

Nach dem Start ist die Definition unveränderlich. „Mit geändertem Thema neu
bewerten“ legt einen neuen Bericht an und übernimmt dabei bereits geladene
Mails, aber keine LLM-Ergebnisse.

### 4.2 Zustände eines Berichts

```
entwurf → zählt → bereit → läuft ⇄ pausiert → fertig
                                  ↘ abgebrochen
                          läuft → fehlgeschlagen (nach begrenzten Wiederholungen)
```

- **zählt:** nur `UID SEARCH SINCE/BEFORE` je Ordner, kein Mailinhalt; liefert
  die Mailzahl und die Kostenschätzung.
- **bereit:** wartet auf die ausdrückliche Startbestätigung (kostenpflichtig).
- **läuft:** ein Hintergrundthread arbeitet die Mails ab; Fortschritt wird nach
  jeder Mail gespeichert.
- **pausiert:** durch Nutzer, durch Erreichen des Kostenlimits oder beim
  Beenden von Mailhelp; nach einem Neustart steht der Bericht auf „pausiert“
  und wird nicht automatisch fortgesetzt.

### 4.3 Verarbeitung je Mail

1. **Identität:** Ordner, UIDVALIDITY, UID und normalisierte Message-ID. Eine
   Mail, die in mehreren Ordnern liegt (z. B. INBOX und Archiv), wird über die
   Message-ID nur einmal bewertet.
2. **Datumsfilter:** IMAP `SINCE` ist tagesgenau und serverabhängig; maßgeblich
   ist das geparste Eingangsdatum in der konfigurierten Zeitzone.
3. **Ignorierte Absender:** `is_irrelevant_sender` mit der beim Start gesicherten
   Liste. Diese Mails werden ohne LLM-Aufruf als „übersprungen: ignorierter
   Absender“ gezählt. Bei gesendeten Mails wird stattdessen der Empfänger
   geprüft.
4. **Weitere lokale Vorfilter, ohne LLM:** zu große Mails (`limits.max_mail_bytes`),
   der bestehende Kurzlink-Köder-Schutz und automatische Benachrichtigungen mit
   `Auto-Submitted`/`List-Unsubscribe` *nur*, wenn der Nutzer dies in der
   Definition wählt (Standard: aus, da Vereinsnewsletter oft relevant sind).
5. **Relevanz (`activity_relevance`):** LLM-Aufruf mit Thema, Absender, Betreff,
   Datum, Mailtext und Anhangtexten. Antwort
   `{"relevant": bool, "confidence": "high"|"medium"|"low", "reason": str}`.
   `low` wird in der Oberfläche als „unsicher“ markiert.
6. **Terminextraktion (`activity_events`):** nur bei `relevant: true`. Antwort:
   eine Liste mit höchstens 20 Einträgen
   `{"title", "date", "start_time"?, "end_time"?, "all_day", "location"?, "evidence"}`.
   - Relative Angaben („nächsten Dienstag“) bezieht das Modell auf das
     Mail-Datum; die lokale Normalisierung aus `action_normalization`
     (Wochentag-/Datumsabgleich) prüft das Ergebnis.
   - `evidence` muss nach Whitespace-Normalisierung wörtlich im Mailtext oder
     einem Anhangtext stehen. Sonst wird der Termin verworfen und protokolliert
     (`event_evidence_missing`).
   - Termine außerhalb von `since − 30 Tage … until + 365 Tage` werden markiert,
     nicht verworfen (Ankündigungen künftiger Termine sind zulässig).
   - Gleiche Termine aus mehreren Mails (Einladung, Erinnerung, Absage) werden
     über Datum, Uhrzeit und normalisierten Titel zusammengeführt; die Quellmails
     bleiben alle sichtbar. Eine erkannte Absage (`"status": "cancelled"`) wird
     angezeigt und standardmäßig nicht exportiert.
7. **Relevant ohne Termin:** Die Mail erscheint im Bericht unter
   „Relevante Mails ohne Termin“ und im Export mit leerem Datum (abschaltbar).

### 4.4 Kosten und Ratenbudget

- Die Schätzung vor dem Start nutzt die Durchschnittswerte aus `metrics`
  (Token und Kosten je Schritt). Ohne Messwerte nennt sie nur die Zahl der
  LLM-Aufrufe. Für lokales Ollama gilt die bestehende Stromkostenannahme.
- Der Lauf teilt sich `limits.llm_calls_per_minute` mit dem Normalbetrieb und
  belegt höchstens `activity_report.max_share_of_llm_budget` (Standard 50 %),
  damit eingehende Mails nicht warten müssen.
- `activity_report.max_mails` (Standard 2.000) und `max_llm_calls` je Bericht
  begrenzen die Kosten; bei Erreichen pausiert der Bericht mit Hinweis.
- Die Relevanzprüfung darf in `prompts.yaml` auf ein günstigeres Modell zeigen
  als die Extraktion.

---

## 5. Zustand und Dateien

| Datei | Inhalt |
| :--- | :--- |
| `activity-reports.json` | Index: ID, Titel, Status, Zeitraum, Zähler, Version |
| `activity-report-<id>.json` | Definition, Status, Version, gesicherte Absenderliste, Fortschritt je Ordner (UIDVALIDITY, letzte UID), Zähler, Kosten, Operationen (Idempotenzschlüssel) |
| `activity-report-<id>-mails.json` | je Mail: Identität, Datum, Absender, Betreff, Volltext (gekürzt auf `max_fulltext_chars`), Anhangnamen, Relevanzergebnis mit Call-ID, Termine, Nutzerkorrekturen |
| `logs/application.jsonl` | Ereignisse `activity_report_*` ohne Inhalte (IDs, Zähler, Fehlerklassen) |

- Jede Datei hat `schema_version: 1`. Geschrieben wird atomar über `JsonStore`.
- Bei mehr als 2.000 Mails wird `…-mails.json` in Blöcke zu 500 Mails geteilt
  (`…-mails-<n>.json`), damit kein Speichervorgang unnötig groß wird.
- **Neustart:** Ein Lauf setzt an der letzten gespeicherten UID je Ordner fort.
  Ergebnisse sind je Mail und Schritt gespeichert; ein vor dem Speichern
  abgebrochener LLM-Aufruf wird einmal wiederholt (lesender Schritt, kein
  externer Schreibzugriff). Ändert sich die UIDVALIDITY eines Ordners, wird
  dieser Ordner neu aufgezählt. Bereits bewertete Message-IDs werden dabei
  übernommen.
- **Aufbewahrung:** `retention.activity_report_days` (Standard 365). Danach
  werden Volltexte entfernt; Termine, Betreff und Absender bleiben, bis der
  Bericht gelöscht wird. „Bericht löschen“ entfernt alle Dateien sofort.
- `mailhelp --clear` löscht Berichte mit dem übrigen Zustand.

---

## 6. Weboberfläche

Neuer Navigationspunkt **Berichte** (`/berichte`). Alle Seiten funktionieren
ohne JavaScript; JavaScript ergänzt nur Fortschrittsaktualisierung und Filter.

| Route | Zweck |
| :--- | :--- |
| `GET /berichte` | Liste der Berichte mit Status, Zeitraum, Fortschritt, Kosten |
| `GET /berichte/neu`, `POST /berichte` | Definition anlegen; danach Zählung |
| `GET /berichte/<id>` | Status, Fortschritt (Mails gelesen/übersprungen/bewertet/relevant), Kosten, Ergebnisliste |
| `POST /berichte/<id>/aktion` | `start` (nach Schätzung, mit ausdrücklicher Bestätigung), `pause`, `fortsetzen`, `abbrechen`, `loeschen` |
| `POST /berichte/<id>/eintrag` | Korrektur: Mail ein-/ausschließen, Termin bearbeiten, ausschließen oder manuell hinzufügen |
| `GET /berichte/<id>/export.xlsx` | Download der aktuellen Liste |

**Ergebnisansicht:**

- Chronologische Tabelle: Datum, Uhrzeit, Termin, Ort, Quelle (Absender ·
  Betreff, Link zur Mail-Detailansicht des Berichts), Sicherheit.
- Filter: Monat, Absender, „nur unsichere“, „ausgeschlossene anzeigen“.
- Detailansicht je Mail: Volltext, Anhänge, Begründung des Modells,
  hervorgehobener Beleg je Termin.
- Abschnitt „Relevante Mails ohne Termin“ und – einklappbar – „Als nicht
  relevant bewertet“ zum Gegenprüfen mit Schaltfläche „Doch relevant“. Diese
  Schaltfläche löst eine Terminextraktion für genau diese Mail aus.
- Korrekturen erhöhen die Version des Berichts; ein veraltetes Formular wird
  mit 409 abgelehnt. Korrekturen gehen nie verloren, auch nicht durch einen
  fortgesetzten Lauf.
- Während eines Laufs aktualisiert sich die Seite über den vorhandenen
  `/api/state`-Fingerprint-Mechanismus, ohne Eingaben zu überschreiben.
- Bei Abschluss optional ein neutraler Web-Push („Tätigkeitsbericht fertig“).

---

## 7. xlsx-Export

- Neue Abhängigkeit **openpyxl** (Version fest pinnen, in `requirements.lock`
  und im Docker-Image). Erzeugt wird im Speicher bei jedem Download; es bleibt
  keine Datei liegen.
- Antwort mit `Content-Type:
  application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`,
  `Content-Disposition: attachment; filename="Taetigkeitsbericht-<slug>-<datum>.xlsx"`,
  `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`.

**Blatt „Termine“** (eine Zeile je Termin, nach Datum sortiert):

| Spalte | Inhalt | Format |
| :--- | :--- | :--- |
| Termin | Titel (ggf. korrigiert) | Text |
| Datum | Termindatum | echtes Excel-Datum `TT.MM.JJJJ` |
| Uhrzeit | `HH:MM–HH:MM`, leer bei ganztägig | Text |
| Ort | falls erkannt | Text |
| Mail-Betreff | Betreff der Quellmail | Text |
| Absender | Name und Adresse | Text |
| Mail-Datum | Eingangsdatum | Excel-Datum mit Uhrzeit |
| Volltext | Mailtext und Anhangtexte | Text, Zeilenumbruch, gekürzt |

Mehrere Quellmails eines Termins ergeben je eine Zeile, damit jeder Volltext
zugeordnet bleibt; eine Spalte „Termin-Nr.“ verbindet sie.

**Blatt „Ohne Termin“:** relevante Mails ohne erkannten Termin (abschaltbar).
**Blatt „Bericht“:** Titel, Thema, Zeitraum, Ordner, Erstellungszeit, Zähler,
Mailhelp-Version, Hinweis „KI-gestützt erstellt, vom Nutzer geprüft: ja/nein“.

**Sicherheit und Grenzen:**

- **Formel-Injektion:** openpyxl speichert Texte, die mit `=` beginnen, als
  Formel. Jede Textzelle wird ausdrücklich als Zeichenkette gesetzt
  (`data_type = "s"`). Werte, die mit `=`, `+`, `-`, `@`, Tab oder CR beginnen,
  erhalten zusätzlich ein vorangestelltes `'`. Ein Test liest die Datei zurück
  und stellt sicher, dass sie keine Formel enthält.
- **Unzulässige Zeichen:** Steuerzeichen außer Tab und Zeilenumbruch werden
  entfernt (sonst `IllegalCharacterError`).
- **Zellgrenze:** Excel erlaubt 32.767 Zeichen je Zelle. Der Volltext wird bei
  `activity_report.max_fulltext_chars` (Standard 30.000) mit dem Hinweis
  „… gekürzt“ abgeschnitten.
- Spaltenbreiten, fixierte Kopfzeile, Autofilter; keine Makros, keine externen
  Verknüpfungen.

---

## 8. Konfiguration und Prompts

`config.yaml` (alle Werte optional, sicher vorbelegt):

```yaml
activity_report:
  enabled: false
  max_mails: 2000              # je Bericht; darüber pausiert der Lauf
  max_llm_calls: 3000          # je Bericht
  max_share_of_llm_budget: 0.5 # Anteil an limits.llm_calls_per_minute
  max_fulltext_chars: 30000    # je Mail im Zustand und in der xlsx-Zelle
  export_mails_without_events: true
retention:
  activity_report_days: 365
```

`prompts.yaml`, neue Schritte mit eigenen Modellen und Parametern:

- `activity_relevance` – konservativ: relevant nur, wenn die Mail sachlich zum
  beschriebenen Thema gehört. Bloße Erwähnung, Werbung und Newsletter anderer
  Absender gelten nicht. Thema und Definition sind vertrauenswürdig, die Mail
  nicht.
- `activity_events` – alle konkret datierten Termine einschließlich vergangener.
  Kein Erfinden von Datum oder Uhrzeit, `evidence` wörtlich, Absagen als
  `cancelled`.

Beide Schritte kommen in die Liste der Schritte, die keinen Fingerprint
beeinflussen (wie `draft_reply`), ebenso der Abschnitt `activity_report` in
`fingerprints.EXPERIENCE`. Fehlt ein Prompt, bleibt der Modus deaktiviert und
die Oberfläche sagt warum (wie bei `smart_reply`).

---

## 9. Architektur

| Modul | Aufgabe |
| :--- | :--- |
| `activity/models.py` | Pydantic-Modelle: Definition, Status, Mailergebnis, Termin, Korrektur |
| `activity/store.py` | Laden/Speichern, Blöcke, Index, Migration über `schema_version`, Aufbewahrung |
| `activity/scan.py` | Ordner aufzählen, Mails schreibfrei laden, Vorfilter, Deduplizierung |
| `activity/runner.py` | Hintergrundthread: Warteschlange, Pause/Abbruch, Budgetanteil, Neustart |
| `activity/llm.py` | `Analyzer`-Erweiterung um `activity_relevance` und `activity_events` inkl. Belegprüfung |
| `activity/export.py` | xlsx-Erzeugung mit Formelschutz |
| `web/activity_site.py`, `web/activity_pages.py` | Routen und Seiten |

- Eine eigene IMAP-Verbindung je laufendem Bericht; höchstens **ein** laufender
  Bericht gleichzeitig. Weitere warten in der Reihenfolge ihres Starts.
- Netzwerk- und LLM-Zugriffe nie unter der globalen Zustandssperre.
- Der Runner wird wie `ExperienceRuntime` komponiert und beim Beenden
  geordnet gestoppt (Fortschritt gesichert, Status „pausiert“).

---

## 10. Umsetzung in Phasen

| Phase | Inhalt | Ergebnis |
| :--- | :--- | :--- |
| **P1 Grundlagen** | Modelle, Store, Konfiguration, Aufbewahrung, `--clear`, Fingerprint-Ausschlüsse | Berichte lassen sich anlegen und löschen (ohne Lauf) |
| **P2 Scan** | Zählung, schreibfreies Laden, Datum-/Absender-/Größenfilter, Deduplizierung, Neustart, UIDVALIDITY | Lauf ohne LLM mit Zählern „gelesen/übersprungen“ |
| **P3 LLM-Schritte** | Prompts, Schemas, Belegprüfung, Datumsnormalisierung, Zusammenführung, Budgetanteil, Kostenschätzung | vollständiger Lauf mit Ergebnissen im Zustand |
| **P4 Weboberfläche** | Seiten, Aktionen, Korrekturen, Fortschritt, Push | bedienbar ohne und mit JavaScript |
| **P5 Export** | openpyxl, drei Blätter, Formelschutz, Grenzen | xlsx-Download |
| **P6 Qualität und Freigabe** | Qualitätsprüfung mit echten eigenen Mails (manuell, lokal), Spezifikation, README, `Release-2.2.md`, Changelog | Release 2.2.0 |

Jede Phase ist für sich grün und einzeln commitbar.

---

## 11. Tests

Alle mit simuliertem IMAP, simuliertem LLM und synthetischen Mails.

- **Scan:** Zeitraumgrenzen inkl. Zeitzone und Sommerzeit; `SINCE`-Unschärfe;
  ignorierte Absender (Adresse und Domain, auch gesendete Mails über den
  Empfänger); Duplikate über Ordner; UIDVALIDITY-Wechsel; nicht lesbarer Ordner
  wird übersprungen und gemeldet; `\Seen` wird nie gesetzt (Prüfung der
  IMAP-Befehle).
- **LLM:** Schema-Verstöße, Prompt-Injection in Mailtext und Anhang, erfundener
  Beleg wird verworfen, relative Datumsangaben, vergangene Termine bleiben
  erhalten, Absagen, mehr als 20 Termine, leere Liste.
- **Neustart und Wiederholung:** Abbruch nach jedem Schritt (vor/nach
  LLM-Aufruf, vor/nach Speichern) setzt korrekt fort, ohne doppelte bezahlte
  Aufrufe; doppelte Startklicks; Kostenlimit pausiert.
- **Autorisierung:** jede Route ohne Sitzung, mit abgelaufener Sitzung,
  falschem CSRF-Token, veralteter Version, wiederverwendetem
  Idempotenzschlüssel; Sitzung läuft zwischen Bestätigung und Ausführung ab.
- **Export:** Rücklesen mit openpyxl; Datumszellen sind Datumswerte; keine
  Formeln trotz `=HYPERLINK(...)`, `+cmd`, `@SUM` in Betreff und Text;
  Steuerzeichen; Kürzung bei 32.767; Umlaute; leerer Bericht.
- **Aufbewahrung und Löschen:** Volltexte verschwinden nach Frist, Termine
  bleiben; Löschen entfernt alle Blöcke; `--clear`.
- **Normalbetrieb unberührt:** ein laufender Bericht verändert weder
  `mail-*.json` noch Checkpoints, Vorschläge oder Telegram-Ausgaben;
  Fingerprints bleiben gleich.
- **Browser (Playwright):** Bericht anlegen → Schätzung → Start → Fortschritt
  → Korrektur → Download, auf Desktop und Smartphone; ohne JavaScript;
  Barrierefreiheitsprüfung (`audit`).

---

## 12. Entscheidungen

Am 12. Oktober 2026 wie empfohlen getroffen; sie sind für die Umsetzung verbindlich.

| Frage | Entscheidung |
| :--- | :--- |
| Gesendete Mails einbeziehen? | **Ja, Standard an.** Eigene Zusagen sind oft der beste Tätigkeitsbeleg. |
| Relevante Mails ohne Termin exportieren? | **Ja, eigenes Blatt.** Sonst fehlen z. B. Protokolle oder Aufgaben ohne Datum. |
| Mehrere Quellmails eines Termins: eine Zeile oder mehrere? | **Mehrere Zeilen mit Termin-Nr.**, weil die Liste den Volltext je Mail enthalten soll. |
| Bedienung auch per CLI (`--activity-report`)? | **Nein in 2.2.** Ergebnisse sollen in der Weboberfläche geprüft und korrigiert werden. |
| Erkannte Termine optional in den Kalender übernehmen? | **Nein in 2.2.** Später möglich über den bestehenden Bestätigungsweg je Vorschlagsversion. |
| Ist `personal_info` Kontext für die Relevanzprüfung? | **Ja.** Name und Rolle helfen zu erkennen, ob der Nutzer selbst beteiligt ist; die Angaben sind bereits als vertrauenswürdig eingestuft. |

---

## 13. Risiken

| Risiko | Gegenmaßnahme |
| :--- | :--- |
| Hohe LLM-Kosten bei großen Postfächern | Zählung und Schätzung vor dem Start, Limits, günstiges Relevanzmodell, keine Doppelbewertung |
| Normalbetrieb wird langsamer | Budgetanteil, nur ein Lauf gleichzeitig, eigene IMAP-Verbindung |
| Erfundene oder falsch datierte Termine | wörtlicher Beleg, lokale Datumsprüfung, Kennzeichnung „unsicher“, Korrektur vor Export |
| Übersehene relevante Mails | Ansicht „als nicht relevant bewertet“ mit „Doch relevant“, konservativ formuliertes Thema mit Beispielen |
| Volltexte in Zustand und xlsx | eigene Aufbewahrung, Löschen-Aktion, `--clear`, `no-store` beim Download |
| Formel-Injektion über Mailinhalte | erzwungene Textzellen, Präfix, Rücklesetest |
