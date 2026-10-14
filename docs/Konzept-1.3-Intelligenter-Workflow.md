# Mailhelp 1.3 – Konzept und detaillierter Umsetzungsplan: Smart Engine, Kalenderabgleich und Anhangsauswertung

> Historischer Versionsstand: Dieses Dokument beschreibt die genannte Version oder
> deren damaligen Plan. Ursprüngliche Ziele und Prüfergebnisse sind kein Nachweis
> des heutigen Umfangs. Aktueller Betrieb: [README](../README.md),
> [Release 3.3](Release-3.3.md) und [Projektspezifikation](../Mailhelp-Projektspezifikation.md).

**Stand:** 11. Oktober 2026  
**Zielversion:** 1.3.0  
**Status:** Historischer Entwurf; Kernfunktionen seit 1.3 implementiert. Maßgeblich für das aktuelle Verhalten ist die Projektspezifikation.
**Grundlage:** [Mailhelp-Projektspezifikation](../Mailhelp-Projektspezifikation.md), [Entwicklungsregeln](../AGENTS.md), [Konzept-1.2-Web-Ausbau.md](Konzept-1.2-Web-Ausbau.md), [Planung-1.3.md](Planung-1.3.md)  
**Nachfolge-Konzept:** [Konzept-2.0-Redesign-und-Web-Push.md](Konzept-2.0-Redesign-und-Web-Push.md)

---

## 1. Ziel und vollständiger Umfang

Version 1.3 optimiert die Effizienz der E-Mail-Verarbeitung grundlegend. Statt wie bisher jeden extrahierten Termin und jede Aufgabe blind zur Entscheidung vorzulegen, gleicht Mailhelp den Datenbestand vorausschauend ab und wertet Kalendereinladungen sowie Dokumentenanhänge (PDF, Word, Text) ganzheitlich aus.

Das Release stützt sich auf **vier tragende Pfeiler**:

| Pfeiler | Funktion | Kernnutzen |
| :--- | :--- | :--- |
| **A. Dubletten-Vorabprüfung** | Vorab-Leseabgleich gegen lokales Ledger, Google Kalender und Todoist vor jeder Entscheidungsvorlage. | Bereits vorhandene Einträge belasten weder Telegram noch Web `/offen`. Sie bleiben im Web mit Direktlink einsehbar. |
| **B. Terminaktualisierung & Absagen** | Erkennung von Verschiebungen und Stornierungen bestehender Google-Kalender-Termine (`PATCH`). | Verhindert Kalender-Leichen und doppelte Termine; bietet präzise Änderungs-Bestätigungen an. |
| **C. ICS-Anhangsauswertung** | Deterministisches Parsen von MIME-Parts `text/calendar` und `.ics`-Anhängen nach RFC 5545. | 100 % Präzision bei Zeiten und Konferenzlinks, massive Ersparnis teurer LLM-Extraktions-Tokens. |
| **D. Dokumenten-Text-Extraktion** | Extraktion von Fließtext aus Dokumenten-Anhängen (PDF, Word `.docx`, Text, Markdown). | Ermöglicht die Extraktion von Aufgaben, Fristen und Terminen aus Protokollen, Verträgen und Tagesordnungen. |

---

## 2. Ausgangslage und technische Ansatzpunkte im Code

- **Pipeline-Orchestrierung (`orchestrator.py`):** Bisher werden Vorschläge in `_build_proposals()` generiert und erhalten sofort `PENDING_CONFIRMATION`. Sie wandern ohne Prüfung in `ProposalDeliveryService.enqueue()`. Zwischen Normalisierung und Benachrichtigung wird ein neuer Pipeline-Schritt `ProcessingStage.DUPLICATE_PRECHECK` eingezogen.
- **Externer Schreibadapter (`integrations.py`):** `HttpWriter` besitzt bereits Lese- und Reconcile-Funktionen sowie `_matching_calendar_event()` und `_time_changes()`. Diese Logik wird aus dem Schreibpfad herausgelöst und für die Vorabprüfung (`GET`) sowie für gezielte `PATCH`-Updates wiederverwendet.
- **MIME- und Anhangsverarbeitung (`mime.py`):** Verarbeitet derzeit Plaintext und HTML. Anhänge (`text/calendar`, `application/pdf`, `application/vnd.openxmlformats-officedocument.wordprocessingml.document`) werden bisher nicht strukturiert analysiert. Neue Parser für Kalenderdateien (`calendar_parser.py`) und Dokumente (`attachment_extractor.py`) ergänzen diesen Pfad.
- **Analyse-Prompts (`analysis.py`):** `action_route`, `extract_tasks` und `extract_events` erhalten aktuell nur den E-Mail-Körper. Die Eingabe wird um strukturierte, größenbegrenzte Textauszüge aus Anhängen erweitert.
- **Weboberfläche (`review/views.py`, `web/review_pages.py`):** Die offene Entscheidungsmenge `_OPEN` enthält bisher `{ProposalStatus.PENDING_CONFIRMATION, ProposalStatus.NEEDS_CLARIFICATION}`. Der neue Status `ALREADY_EXISTS` wird davon isoliert, bleibt aber in `/mails`, `/mail/<id>` und `/verlauf` sichtbar.

---

## 3. Verbindliche Invarianten und Sicherheitsregeln

Gemäß den [Entwicklungsregeln](../AGENTS.md) gelten für Version 1.3 folgende unverrückbare Grundsätze:

1. **Strenge Trennung von Lese- und Schreibzugriffen:**
   - Vorabprüfung (Pfeiler A), ICS-Parsing (Pfeiler C) und Dokumentenextraktion (Pfeiler D) sind **streng lesend**. Sie erzeugen niemals eigenmächtige Änderungen an externen Systemen.
2. **Bestätigungsregel für Änderungen und Neuanlagen:**
   - Sowohl Neuanlagen als auch Terminaktualisierungen (`PATCH`) oder Stornierungen (`DELETE`/Statusupdate) erfordern vor dem externen Schreibzugriff eine **ausdrückliche, versionsbezogene Bestätigung** über Telegram oder die authentifizierte Weboberfläche mit CSRF-Schutz und Idempotenzschlüssel.
3. **Resilienz und konservativer Fallback:**
   - Ist ein externes Zielsystem (Google Kalender oder Todoist) während der Vorabprüfung nicht erreichbar:
     - Der Lauf bricht nicht ab, Daten gehen nicht verloren.
     - Der Vorschlag verbleibt sicher im Status `PENDING_CONFIRMATION` und wird dem Nutzer wie bisher zur manuellen Prüfung vorgelegt.
4. **Schutz vor DoS und bösartigen Anhängen:**
   - Keine Ausführung von Skripten oder Makros aus Anhängen.
   - Feste Dateigrößen- und Speicherlimits (max. 10 MB pro Anhang, max. 20.000 Zeichen extrahierter Text pro Anhang).
   - Timeouts gegen Decompression-Bombs oder rekursive PDF-Strukturen.
5. **Verbindliche 100 % Zeilen- und Branch-Abdeckung:**
   - Für alle neuen Module (`calendar_parser.py`, `attachment_extractor.py`, `precheck.py`) und Modifikationen sind vollständige Unit- und Integrationstests mit synthetischen Daten und Mock-Transports Pflicht.

---

## 4. Pfeiler A im Detail: Dubletten-Vorabprüfung

```mermaid
sequenceDiagram
    autonumber
    participant Orch as Orchestrator
    participant Builder as ProposalBuilder
    participant PreCheck as DuplicatePreCheckService
    participant Ledger as ActionLedger (Lokal)
    participant Ext as Externe APIs (Google/Todoist)
    participant Store as JsonStore
    participant Notifier as Notifier (Telegram)
    participant Web as Web-UI (/offen & /mails)

    Orch->>Builder: Extraktion normalisieren & Proposals bauen
    Builder-->>Orch: Liste[Proposal] (Status: pending_confirmation)
    
    Orch->>PreCheck: check_proposals(proposals, mail_context)
    
    rect rgb(245, 248, 255)
        Note over PreCheck,Ext: Stufe 1: Lokales ActionLedger (Zero-Latency)
        PreCheck->>Ledger: prior_actions(proposal)
        alt Treffer im Ledger
            Ledger-->>PreCheck: ActionLedgerEntry
        else Kein Ledger-Treffer
            Note over PreCheck,Ext: Stufe 2: Read-Only API-Prüfung
            alt ProposalKind.EVENT
                PreCheck->>Ext: GET /calendars/{target}/events (timeMin, timeMax)
                Ext-->>PreCheck: Liste existierender Events
                PreCheck->>PreCheck: calendar_matcher / UID-Vergleich
            else ProposalKind.TASK
                PreCheck->>Ext: GET /tasks?project_id={target}
                Ext-->>PreCheck: Aktive Todoist-Tasks
                PreCheck->>PreCheck: Titel- & Fristen-Vergleich
            end
        end
    end

    alt Exaktes Duplikat erkannt
        PreCheck-->>Orch: Duplikat-Treffer (ALREADY_EXISTS, Referenzdaten)
        Orch->>Store: Proposal sichern (status="already_exists", duplicate_match=...)
        Note over Orch,Notifier: KEINE Benachrichtigung (stille Erledigung)
        Note over Orch,Web: Nicht in /offen; sichtbar in /mails & /mail/{id}
    else Kein Duplikat
        PreCheck-->>Orch: Kein Treffer (PENDING_CONFIRMATION)
        Orch->>Store: Proposal sichern
        Orch->>Notifier: Benachrichtigung senden (Telegram)
        Note over Orch,Web: Sichtbar in /offen zur Bestätigung
    end
```

### Datenmodell-Erweiterung
In `src/mailhelp/domain/proposal.py`:
```python
class ProposalStatus(StrEnum):
    NEEDS_CLARIFICATION = "needs_clarification"
    PENDING_CONFIRMATION = "pending_confirmation"
    ALREADY_EXISTS = "already_exists"         # <-- NEU: Duplikat vorab erkannt
    CONFIRMED = "confirmed"
    WRITING = "writing"
    CREATED = "created"
    SIMULATED = "simulated"
    REJECTED = "rejected"
    FAILED = "failed"
    UNCERTAIN = "uncertain"

class DuplicateSource(StrEnum):
    ACTION_LEDGER = "action_ledger"
    GOOGLE_CALENDAR = "google_calendar"
    TODOIST = "todoist"

class DuplicateMatchInfo(StrictModel):
    source: DuplicateSource
    external_id: str | None = Field(default=None, max_length=500)
    external_link: str | None = Field(default=None, max_length=2000)
    matched_title: str = Field(min_length=1, max_length=500)
    matched_time: datetime | date | None = None
    similarity_score: float | None = Field(default=None, ge=0.0, le=1.0)
    details: str = Field(default="", max_length=1000)
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

---

## 5. Pfeiler B im Detail: Intelligente Terminaktualisierung & Absagen

### Das Problem bisher
Wenn ein E-Mail-Absender mitteilt: *„Achtung, das Team-Meeting am Freitag verschiebt sich von 10:00 auf 14:00 Uhr“*, stuft das LLM die Aktion korrekt als `classification == CHANGE` ein. Da Mailhelp jedoch keinen bestehenden Kalendereintrag zuordnen konnte, forderte das System vom Nutzer bisher die Anlage als *neuen* Ersatztermin. Die Folge: Der alte Termin verblieb als Leiche im Kalender, und der neue Termin stand doppelt im Planer.

### Der neue Ablauf in 1.3
1. **Erkennung von Abweichungen:**
   Die Vorabprüfung findet bei einem Event-Vorschlag mit `classification in {CHANGE, CANCELLATION}` (oder bei starker Titelähnlichkeit) das bestehende Kalendereintragsobjekt über `_matching_calendar_event()`.
2. **Diff-Bildung:**
   Mailhelp stellt die Unterschiede fest:
   - Beginn/Ende: `10:00 Uhr → 14:00 Uhr`
   - Ort: `Konferenzraum 1 → Zoom-Link`
   - Status: `CONFIRMED → CANCELLED`
3. **Strukturierter Änderungsvorschlag:**
   - Das Proposal erhält den Status `PENDING_CONFIRMATION` mit speziellem Aktionstyp:
     - `target_event_id`: ID des existierenden Google-Kalender-Events.
     - `time_changes`: Liste der Differenzen.
     - `is_cancellation`: Boolesches Flag bei Terminabsagen.
4. **Vorlage zur Bestätigung:**
   - **Telegram:**  
     *„Terminänderung für ‚Projekt-Jour-Fixe‘ erkannt:\nBeginn: 10:00 → 14:00 Uhr.\nBestehenden Google-Kalender-Termin aktualisieren?“*  
     `[Termin aktualisieren]` `[Als neuen Termin anlegen]` `[Verwerfen]`
   - **Web `/offen`:**  
     Klare Diff-Box mit grünen/roten Markierungen und Button *„Bestehenden Termin aktualisieren“*.
5. **Ausführung:**
   Nach der Bestätigung führt `HttpWriter` ein gezieltes `PATCH /calendars/{target}/events/{event_id}` aus. Bei einer Absage wird der Termin im Kalender als abgesagt markiert (`status: cancelled`) oder optional aus dem Kalender gelöscht.

---

## 6. Pfeiler C im Detail: Deterministische ICS-Anhangsauswertung (RFC 5545)

### MIME-Extraktion und Größenbegrenzung
In `src/mailhelp/mime.py` wird der Parser erweitert:
- Prüft `Content-Type: text/calendar` (auch mit Parametern wie `method=REQUEST`) sowie Dateianhänge mit Endung `.ics`.
- **DoS-Schutz:** Maximale Größe pro Kalenderdatei beträgt 1 MB; überschüssige Bytes werden verworfen.

### Kalender-Parser (`src/mailhelp/calendar_parser.py`)
Ein schlanker, robuster, standardkonformer Parser ohne schwere Drittabhängigkeiten:
- **`VEVENT`-Extraktion:**
  - `UID`: Weltweit eindeutiger Bezeichner des Termins.
  - `SEQUENCE`: Revisionszähler (ermöglicht die automatische Erkennung von Terminaktualisierungen!).
  - `DTSTART` & `DTEND`: Beginn und Ende, inklusive nativer `TZID`-Auswertung über `zoneinfo.ZoneInfo`.
  - `SUMMARY`: Titel des Termins.
  - `DESCRIPTION`: Beschreibungstext.
  - `LOCATION`: Veranstaltungsort.
  - `STATUS`: `CONFIRMED`, `TENTATIVE` oder `CANCELLED`.
  - Konferenzlinks: Automatische Erkennung von Google Meet, Zoom, MS Teams aus `LOCATION`, `DESCRIPTION` oder `X-GOOGLE-CONFERENCE`.
- **Vorteile für den Gesamtablauf:**
  1. **Kein LLM-Aufruf erforderlich:** Die Extraktion erfolgt deterministisch in 1 ms statt 2–5 s LLM-Laufzeit. Keine Tokenkosten, keine Provider-Timeouts.
  2. **100 % Präzision:** Zeitzonen, Sekunden und Links werden bitgenau übernommen.
  3. **Direkte Kopplung mit Pfeiler A & B:**  
     - `UID` bereits im Kalender vorhanden und `SEQUENCE` gleich $\rightarrow$ sofortiges `ALREADY_EXISTS`.
     - `UID` vorhanden, aber `SEQUENCE` höher $\rightarrow$ sofortige `Terminaktualisierung` (Pfeiler B).
     - `UID` neu $\rightarrow$ sofortiger Neuanlage-Vorschlag.

---

## 7. Pfeiler D im Detail: Text-Extraktion aus Dokumenten-Anhängen (PDF, Word, Text)

### Unterstützte Dateiformate & Parsing-Architektur
In `src/mailhelp/attachment_extractor.py`:
1. **PDF (`application/pdf`, `.pdf`):**
   - Nutzung der etablierten, reinen Python-Bibliothek `pypdf` (keine C-Compiler-Abhängigkeiten, plattformunabhängig unter Windows 11 und Docker-Linux).
   - Extraktion des sichtbaren Textlayers (`extract_text()`) je Seite.
2. **Word (`.docx`):**
   - Standardkonforme OpenXML-Verarbeitung ohne schwere externe Office-Abhängigkeiten:
   - Ein `.docx` ist eine ZIP-Datei; der Text wird direkt aus `word/document.xml` mittels `zipfile` und `xml.etree.ElementTree` über alle `<w:t>`-Tags strukturiert und extrem performant ausgelesen.
3. **Textdokumente (`.txt`, `.md`, `.csv`, `.rtf`):**
   - Sichere Dekodierung mit Erkennung gängiger Zeichensätze (UTF-8, Latin-1, CP1252 Fallback).

### Sicherheitsgrenzen & Token-Budgetierung (DoS-Schutz)
- **Größenbegrenzung:** Anhänge über `limits.max_attachment_bytes` (Standard: 10 MB) werden von der Text-Extraktion ausgeschlossen.
- **Extraktions-Timeout:** Jede Extraktion wird auf max. 2 Sekunden begrenzt (Schutz gegen Decompression-Bombs oder rekursive PDF-Strukturen).
- **Text-Truncation für das LLM:**
  - Pro Anhang werden maximal 20.000 Zeichen Fließtext extrahiert.
  - Überschreitet der Text das Limit, wird er sauber trunkiert und mit folgendem Vermerk versehen:  
    `\n[... Text nach 20.000 Zeichen gekürzt ...]\n`
- **Fehlerbehandlung:** Passwortgeschützte PDFs, beschädigte Archive oder reine Bilderscans (ohne Textlayer) erzeugen keinen Programmabbruch, sondern den Status `extraction_status: "no_text_found"` oder `"encrypted"`. Der Mailtext wird normal weiterverarbeitet.

### Prompt-Integration und Provenienz
In `src/mailhelp/analysis.py` wird der analysierte Text strukturiert zusammengesetzt:
```text
E-Mail-Inhalt:
Absender: vorstand@verein.de
Betreff: Protokoll & Beschlüsse
Text: Anbei die Zusammenfassung der heutigen Sitzung.

--- Anhang: Protokoll_2026-10-10.pdf (142 KB) ---
TOP 1: Begrüßung ...
TOP 2: Finanzbericht ...
Beschluss: Herr Müller muss die Steuererklärung bis zum 30.11.2026 einreichen.
Nächster Sitzungstermin: 15.12.2026 19:00 Uhr im Vereinsheim.
--- Ende Anhang ---
```
- **Belegführung (`evidence`):** Extrahierte Aufgaben und Termine enthalten im `evidence`-Feld den Namen des Dokuments:  
  *„Gefunden in Anhang ‚Protokoll_2026-10-10.pdf‘: 'Herr Müller muss die Steuererklärung bis zum 30.11.2026 einreichen.'“*

---

## 8. Verhalten in den Benutzerschnittstellen (Version 1.3)

| Ansicht | Darstellung und Verhalten in Version 1.3 |
| :--- | :--- |
| **Telegram** | • Vorschläge mit `status == ALREADY_EXISTS` erzeugen keine Fragekarten und blockieren das Fragen-Gate nicht.<br>• Terminaktualisierungen bieten Buttons `[Aktualisieren]`, `[Als neu anlegen]`, `[Verwerfen]`. |
| **Web `/offen`** | • Reine Entscheidungs-Warteschlange: `ALREADY_EXISTS` ist ausgefiltert.<br>• Terminaktualisierungen zeigen ein klares Differenz-Panel (vorher/nachher) mit primärem Button *„Bestehenden Termin aktualisieren“*. |
| **Web `/mails` & `/mail/<id>`** | • Vollständige Transparenz: Alle extrahierten Termine/Tasks werden angezeigt.<br>• Duplikate tragen den Badge `[Bereits im Kalender vorhanden]` mit klickbarem Direktlink zu Google Calendar/Todoist.<br>• Liste der Anhänge mit Extraktionsstatus (`PDF extrahiert: 12.400 Zeichen`).<br>• Primäre Anlege-Buttons entfallen bei Duplikaten; optionales Sekundärmenü *„Trotzdem anlegen“*. |
| **Web `/verlauf`** | • Lückenlose Historie mit neuem Filter: `Nur vorab abgeglichene Duplikate`. |

*(Hinweis: Das umfassende Web-Redesign nach modernen Design-Patterns mit Master-Detail-View, Keyboard-Shortcuts, Quick-Filter-Chips, Daumenzonen-UI und Web-Push folgt im anschließenden Großrelease **Version 2.0**, siehe [Konzept-2.0-Redesign-und-Web-Push.md](Konzept-2.0-Redesign-und-Web-Push.md)).*

---

## 9. Phasenweiser Umsetzungsplan für Version 1.3

### Phase 1: Domänenmodelle, Invarianten & Status
1. `ProposalStatus.ALREADY_EXISTS` und `DuplicateMatchInfo` in `domain/proposal.py` anlegen.
2. `ExtractedAttachmentText`-Modelle definieren.
3. Aktionsmodelle für Terminaktualisierung (`UPDATE_EVENT`, `CANCEL_EVENT`) definieren.
4. Invarianten: `is_creatable` anpassen, Validierung für Ziel-Event-IDs und Diff-Felder.
5. Unit-Tests für alle neuen Datenmodelle und Statusübergänge schreiben (100 % Coverage).

### Phase 2: ICS- & Dokumenten-Text-Extraktoren
1. Modul `src/mailhelp/calendar_parser.py` implementieren (`VEVENT`, Zeitzonen, UID, SEQUENCE).
2. Modul `src/mailhelp/attachment_extractor.py` implementieren:
   - PDF-Extraktion via `pypdf`.
   - DOCX-Extraktion via `zipfile` & `xml.etree.ElementTree`.
   - Textdateien mit Encoding-Fallback.
3. `src/mailhelp/mime.py` um Aufrufe beider Extraktoren und DoS-Größenlimits erweitern.
4. Unit-Tests für synthetische Kalender- und Dokumentdateien (Normalfälle, Truncation, defekte Dateien, Passwörter).

### Phase 3: Read-Only Query-Adapter & Caching
1. `HttpWriter` um isolierte Leseabfragen erweitern: `fetch_events_in_window()` und `fetch_active_tasks()`.
2. In-Memory-Laufzeitcache für externe Leseanfragen implementieren.
3. Fehlerbehandlung mit Graceful Fallback bei Timeouts oder 5xx-Fehlern absichern.
4. Unit-Tests mit simulierten HTTP-Transports für Normal- und Fehlerfälle.

### Phase 4: Pipeline-Integration im Orchestrator
1. `DuplicatePreCheckService` implementieren (Ledger-Check + externer Leseabgleich + ICS-UID-Abgleich).
2. Anhangstexte in die Analyse-Prompts für `action_route`, `task_extraction` und `event_extraction` einspeisen.
3. Neuen Pipeline-Schritt `DUPLICATE_PRECHECK` in `orchestrator.py` nach der Normalisierung einbinden.
4. Reschedule-Erkennung implementieren: Identifikation bestehender Events und Überführung in Update-Proposals.
5. Event-Logging für Vorabtreffer, Anhangsextraktion und Terminverschiebungen.

### Phase 5: Weboberfläche & Interaktionsanpassung (Version 1.3 Scope)
1. `review/views.py`: `_OPEN` hält `ALREADY_EXISTS` fern; Bereitstellung von `DuplicateMatchInfo` und Anhangs-Metadaten für Detailansichten.
2. Webseiten aktualisieren:
   - `/offen`: Diff-Darstellung für Terminaktualisierungen.
   - `/mails` und `/mail/<id>`: Badges, Trefferdetails, Anhangsliste und Direktlinks zum Kalender/Todoist.
3. Telegram-Presenter und Dialoge anpassen (keine Benachrichtigung bei Duplikaten, gezielte Rückfrage bei Verschiebungen).

### Phase 6: End-to-End-Tests, Regressionstests & Release 1.3
1. E2E-Tests für alle vier Pfeiler mit simulierten externen Diensten ausführen.
2. Spezifische Regressionstests für behobene Ineffizienzen und Anhangs-Aufgaben nachweisen.
3. Vollständige Testsuite prüfen (100 % Zeilen- und Branch-Coverage verbindlich).
4. Dokumentation aktualisieren (`CHANGELOG.md`, `Mailhelp-Projektspezifikation.md`, `README.md`).
5. Version auf `1.3.0` anheben.

---

## 10. Test- und Qualitätssicherungsstrategie

- **Simulierte externe Dienste:** Alle Netzwerkaufrufe (Google Calendar API, Todoist API) werden über `httpx.MockTransport` vollständig offline und deterministisch simuliert.
- **Synthetische Dokumenten-Testsuite:**
  - PDF mit sichtbarem Textlayer, PDF ohne Textlayer (Scan), verschlüsseltes PDF, beschädigtes PDF.
  - Valides Word `.docx` mit Aufgabenabsatz, Word-Dokument mit Formatierungs-XML, beschädigtes ZIP-Archiv.
  - ICS-Dateien mit verschiedenen Zeitzonen (UTC, `Europe/Berlin`, `America/New_York`) und ganztägigen Events.
- **Regressionstest-Suite:**
  - *Regression 1:* Ein Termin, der bereits im Kalender steht, darf niemals eine Telegram-Fragekarte oder einen `/offen`-Eintrag erzeugen.
  - *Regression 2:* Eine Terminverschiebung in einer Mail darf keinen zweiten Termin anlegen, sondern muss nach Bestätigung das bestehende Event via `PATCH` aktualisieren.
  - *Regression 3:* Eine E-Mail mit reinem Verweistext (*„Aufgaben siehe Anhang“*) muss zuverlässig die Fristen und Aufgaben aus dem Anhang extrahieren.
- **Coverage-Gate:** 100 % Zeilen- und 100 % Branch-Abdeckung für sämtlichen eigenen Anwendungscode ohne Ausnahmen.
