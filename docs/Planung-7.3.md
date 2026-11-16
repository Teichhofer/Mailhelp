# Mailhelp 7.3 – Verwaltung fehlgeschlagener Mails (Retry, Ignorieren und Fehlerreport)

**Zielversion:** 7.3, Umsetzung in Patchversionen ab 7.3.1  
**Stand:** 16. November 2026  
**Status:** In Umsetzung ab 7.3.1 (16. November 2026); Stand in [Release 7.3](Release-7.3.md).  
**Ausgangsstand:** 7.0 / 7.1; nach Abschluss von 7.1 und 7.2 gegen den aktuellen Stand abgleichen.  
**Grundlage:** [Entwicklungsregeln](../AGENTS.md), [Projektspezifikation](../Mailhelp-Projektspezifikation.md), [Planung 7.1](Planung-7.1.md), [Planung 7.2](Planung-7.2.md).

---

## 1. Ziel und Anwendungsfall

Wenn bei der Verarbeitung einer E-Mail ein Fehler auftritt (z. B. Modell-Timeout,
Rate-Limit des Anbieters, temporärer Verbindungsabbruch oder fehlerhaftes JSON),
erhält die Mail den internen Verarbeitungsstatus `failed` und wird in der Weboberfläche
unter `/mails?state=failed` (bzw. auf der Instanz unter `https://stefan.inboxstride.de/mails?state=failed`)
geführt.

Aktuell bietet diese Liste dem Anwender keine direkten Handlungsoptionen:
* Man kann eine fehlgeschlagene Mail **nicht direkt aus der Liste** erneut anstoßen oder verwerfen.
* Um eine Aktion auszuführen, muss man in die Mail hineinklicken, ganz nach unten scrollen und
  findet dort nur unauffällige Knöpfe ohne nähere Erläuterung.
* Es ist in der Liste und auf der Detailseite **nicht ersichtlich, woran die Verarbeitung scheiterte**;
  die Seite meldet lediglich pauschal: *„Diese Mail hat einen Verarbeitungsfehler.“*

### Vorgaben für Version 7.3:
1. **Erneute Verarbeitung anstoßen (Retry):**
   * Direkt in der Fehlerliste `/mails?state=failed` und auf der Mail-Detailseite kann per Klick
     ein neuer Verarbeitungsversuch angestoßen werden.
   * Der Zähler für automatische Fehlversuche (`processing_retry`) wird zurückgesetzt,
     die Mail wird beim nächsten Abrufzyklus wieder durch die Pipeline geschleust.
2. **Ignorieren / Ablegen (Dismiss / File):**
   * Eine fehlerhafte Mail kann per Klick dauerhaft ignoriert/abgelegt werden (`CommandKind.FILE_MAIL`).
   * Die Mail verbleibt im Archiv, verschwindet jedoch sofort aus dem Filter `state=failed`
     und löst keine Warnungen oder Zählerstände mehr aus.
3. **Detail-Button mit Detailliertem Fehlerreport:**
   * Jede fehlerhafte Mail erhält einen **„Details“**- / **„Fehlerbericht“**-Button.
   * Dieser öffnet einen strukturierten, verständlichen Fehlerreport (per Dialog/Modal in der Liste,
     vollständig barrierefrei und ohne JavaScript auf der Mail-Detailseite nutzbar).
   * Der Report nennt die genaue Verarbeitungsstufe (`stage`), den typisierten Fehlercode (`code`),
     eine verständliche deutsche Übersetzung und Handlungsempfehlung, den Zeitpunkt, die bisherigen
     Wiederholungsversuche und technische Diagnosedaten (ohne vertrauliche Inhalte oder Secrets).
   * Über einen Button **„Bericht kopieren“** lässt sich die Diagnose direkt in die Zwischenablage
     kopieren, um Support oder Fehlerbehebung zu erleichtern.
4. **Sammelaktionen (Bulk Actions):**
   * In der Filteransicht `/mails?state=failed` stehen Sammelaktionen bereit:
     * *„Alle erneut versuchen“*
     * *„Alle ignorieren“*

---

## 2. Analyse des Ist-Zustands

### 2.1 Datenmodell und Persistenz
In `src/mailhelp/domain/mail.py` und `src/mailhelp/domain/processing.py`:
* `MailState` speichert bei einem Fehler:
  * `error: ProcessingError | None` mit Feldern:
    * `code: ProcessingErrorCode` (z. B. `MIME_LIMIT_EXCEEDED`, `LLM_SCHEMA_VALIDATION_EXHAUSTED`,
      `PROVIDER_RESPONSE_INVALID`, `INVALID_JSON`, `SCHEMA_VALIDATION_FAILED`,
      `PERMANENT_ADAPTER_ERROR`, `LLM_RATE_LIMITED`, `INTERNAL_ERROR`, `ANALYSIS_DATA_REMOVED`)
    * `stage: ProcessingStage` (z. B. `preparation`, `relevance`, `summary`, `action_router`,
      `event_extraction`, `task_extraction`, `proposal_building`, `completion`)
    * `occurred_at: datetime`
    * `retryable: bool | None`
  * `processing_retry: ProcessingRetry | None` mit `attempts`, `first_failed_at`, `last_failed_at`, `abandoned`.
  * `processing_filed: bool` (true, wenn die Mail manuell abgelegt wurde).
  * `validation_errors: list[ValidationIssue]` mit `stage`, `code`, `path`.
  * `llm_call_ids: list[str]`.

### 2.2 Vorhandene Review-Kommandos
In `src/mailhelp/review/processing_actions.py` existieren die Kernbefehle bereits im Backend:
* `CommandKind.RETRY_MAIL`: Setzt `processing_retry = None`, `deferred_until = None`,
  erhöht `analysis_round += 1` und loggt `status="retrying"`. Die Mail wird im nächsten
  Abruf von `run_resume.py` wieder aufgenommen.
* `CommandKind.FILE_MAIL`: Setzt `processing_filed = True`, `steps.completion = "completed"`,
  erhöht `analysis_round += 1` und loggt `status="not_processed"`.

### 2.3 Schwachstellen in der Weboberfläche
1. **Projektion in `queries.py` unvollständig:**
   `ArchiveQuery` bzw. `queries.search()` erzeugt für die Listenansicht `/mails` nur ein Dict:
   `"failed": state.error is not None and not state.processing_filed`.
   Weder `error.code`, `error.stage` noch `analysis_round` werden an die Listenzeile übergeben.
2. **Keine Formulare in `_archive_row`:**
   In [src/mailhelp/web/archive_pages.py](file:///c:/Users/User/Documents/Projekte/mailhelp/Mailhelp/src/mailhelp/web/archive_pages.py)
   wird lediglich `<span class="badge danger">Fehler</span>` gerendert. Es gibt weder Buttons für
   Retry noch für Ablegen oder Fehlerdetails.
3. **Fehlende Diagnose auf der Mailseite:**
   In `mail_archive_site.py` (`analysis()`) steht hartcodiert nur:
   `<p>Diese Mail hat einen Verarbeitungsfehler.</p>`.
   Es gibt keine Anzeige von Fehlerursache, Wiederholungsversuchen oder Stufe.
4. **Fehlende Sammelaktionen:**
   Bei z. B. 10 Mails nach einem temporären Server- oder LLM-Ausfall muss jede Mail einzeln
   geöffnet und manuell bestätigt werden.

---

## 3. Fachliches Soll-Konzept

### 3.1 Zeilenansicht in `/mails?state=failed`
Jede Zeile einer fehlgeschlagenen E-Mail bietet drei direkte Bedienmöglichkeiten:
1. **„Erneut versuchen“ (Button, primär):**
   * Sendet per POST `/aktion` ein `CommandKind.RETRY_MAIL` mit CSRF und aktueller `analysis_round`.
   * Setzt die Mail zurück auf den Status „Wartet auf Wiederaufnahme“.
   * Aktualisiert per Standard-Aktionsablauf die Seite (bzw. via JavaScript per DOM-Update).
2. **„Ignorieren“ (Button, sekundär/dezent):**
   * Sendet per POST `/aktion` ein `CommandKind.FILE_MAIL`.
   * Markiert die Mail als dauerhaft abgelegt (`processing_filed`).
   * Entfernt die Mail sofort aus der Fehleransicht.
3. **„Details“ (Button / Dialog-Opener):**
   * Öffnet ein zugängliches Dialog-Modal (`<dialog class="modal">`, siehe `dialogs.js`).
   * Zeigt den formatierten Fehlerreport an.
   * Bietet im Modal zusätzlich die Knöpfe „Erneut versuchen“, „Ignorieren“ und „Bericht kopieren“.
   * **No-JS-Fallback:** Ist JavaScript deaktiviert, verlinkt der Button direkt auf `/mail/<id>#fehlerbericht`.

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ [Postfach] [Fehler] Mirjam Albrecht · 09.11.2026 16:15                                 │
│ WG: Programm Vlf Schulungstagung Bad Waldse am 07./08.01.2027                          │
│ Fehler: Modell-Antwort ungültig (Stufe: Aktionserkennung, 5 Fehlversuche)             │
│ [ 🔄 Erneut versuchen ]  [ ✕ Ignorieren ]  [ ℹ️ Details ]                              │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Detaillierter Fehlerreport
Der Fehlerreport fasst alle relevanten, unkritischen Fakten zusammen:

| Bereich | Angezeigter Inhalt |
| :--- | :--- |
| **Betroffener Schritt** | Deutsche Bezeichnung der Stufe (z. B. *„Aktionserkennung“*, *„Relevanzprüfung“*, *„Termin-Extraktion“*) |
| **Fehlerursache** | Typisierter Code mit lesbarer Erklärung (z. B. `LLM_SCHEMA_VALIDATION_EXHAUSTED` → *„Das Sprachmodell lieferte mehrfach unvollständige oder schemawidrige Antworten.“*) |
| **Status der Wiederholung** | z. B. *„5 von 5 automatischen Versuchen durchgeführt. Automatische Wiederholung pausiert.“* |
| **Zeitstempel** | Erster Fehler: `09.11.2026, 16:15:20 Uhr`, Letzter Versuch: `09.11.2026, 18:15:22 Uhr` |
| **Validierungsdetails** | Falls vorhanden: Spezifischer Feldpfad (z. B. `events.0.time_requirement`) ohne sensible Nutzdaten |
| **Technische IDs** | LLM-Call-IDs zur schnellen Auffindung im Prompt-Log |

#### Kopierfunktion („Bericht kopieren“):
Ein Klick erzeugt einen formatierten Markdown-Textblock in der Zwischenablage:
```text
=== Mailhelp Fehlerbericht ===
Mail-ID: 450553d4e60ffe8960b6c59f
Betreff: WG: Programm Vlf Schulungstagung Bad Waldse...
Fehlercode: llm_schema_validation_exhausted
Verarbeitungsstufe: action_detection
Zeitpunkt: 2026-11-09T16:15:20Z
Versuche: 5/5 (pausiert)
LLM-Calls: fdf5b233-55f5-4ea5-93cf-3f58b5abb0f1
==============================
```

### 3.3 Prominenter Fehlerabschnitt auf der Mailseite (`/mail/<id>`)
Auf der Mail-Detailseite wird bei `state.error is not None and not state.processing_filed`
ganz oben (direkt unter dem Kopfbereich) eine prominente Fehler-Karte eingefügt:
* Roter/orangefarbener Hinweisrahmen (`class="card error-card"`).
* Kompakter Fehlertext mit Button zum Aufklappen des vollständigen Fehlerberichts.
* Aktionsbuttons „Erneut versuchen“ und „Ignorieren“ direkt oben sichtbar, sodass kein Scrollen
  an das Seitenende nötig ist.

### 3.4 Sammelaktionen in der Toolbar von `/mails?state=failed`
Wenn die Filteransicht `state=failed` gewählt ist und Treffer existieren, zeigt die Toolbar:
* **„Alle Fehler erneut versuchen“** (mit Bestätigungsdialog: *„Möchtest du alle X fehlgeschlagenen Mails erneut zur Verarbeitung einreihen?“*)
* **„Alle Fehler ignorieren“** (mit Bestätigungsdialog: *„Möchtest du alle X fehlgeschlagenen Mails als nicht verarbeitet ablegen?“*)

---

## 4. Technische Architektur und Schnittstellen

### 4.1 Anpassung der Datenprojektion (`src/mailhelp/review/queries.py`)
In `queries.search()` wird das Dictionary jedes Listeneintrags erweitert:
```python
"failed": state.error is not None and not state.processing_filed,
"error_code": state.error.code.value if state.error else None,
"error_stage": state.error.stage.value if state.error else None,
"error_occurred_at": state.error.occurred_at.isoformat() if state.error else None,
"error_attempts": state.processing_retry.attempts if state.processing_retry else None,
"analysis_round": state.analysis_round,
```
Dadurch stehen alle für die Listendarstellung und die CSRF-Aktionen benötigten Daten ohne
zusätzliche Datei-Lookups zur Verfügung.

### 4.2 Fehler-Formatierung (`src/mailhelp/review/error_reporting.py`)
Ein neues Hilfsmodul kapselt die verständlichen deutschen Bezeichnungen:
* `STAGE_LABELS`: Übersetzung von `ProcessingStage` (z. B. `preparation` → „Mail-Aufbereitung“, `relevance` → „Relevanzprüfung“).
* `ERROR_DESCRIPTIONS`: Übersetzung und Erklärung der `ProcessingErrorCode`-Werte.
* `format_error_summary(error, retry)`: Einzeiler für die Zeilenanzeige.
* `format_error_report(state, timezone)`: Vollständiger HTML-Bericht und formatierter Text für das Clipboard.

### 4.3 Sammelaktionen-Endpunkt
* Erweiterung des Aktionshandlers in `src/mailhelp/web/actions.py` bzw. `site.py`:
  * Neuer Befehl: `CommandKind.BATCH_RETRY_FAILED_MAILS` und `CommandKind.BATCH_FILE_FAILED_MAILS`.
  * Verarbeitet atomar alle aktuell fehlgeschlagenen Mails mit Versionsprüfung.

### 4.4 JavaScript- und No-JS-Integration
* **Mit JavaScript:**
  * Klick auf „Details“ öffnet `modal(title, [content])` aus `dialogs.js`.
  * Kopier-Button nutzt die `navigator.clipboard.writeText`-API mit Feedback („Kopiert!“).
  * Aktionen nutzen die bestehende Warteschlangen-Animation (`data-card-command-status`).
* **Ohne JavaScript:**
  * Jedes Formular ist ein reguläres HTML-Formular mit `method="post"` auf `/aktion`.
  * „Details“ verlinkt auf `/mail/<id>#fehlerbericht`.
  * Seitenfunktion bleibt zu 100 % erhalten.

---

## 5. Datenschutz, Geheimnisschutz und Barrierefreiheit

1. **Datenschutz:** Der Fehlerreport und die Zwischenablage enthalten keine E-Mail-Volltexte,
   keine Passwörter, keine Tokens und keine IMAP-Geheimnisse.
2. **Barrierefreiheit:**
   * Alle Buttons besitzen semantische `<button>`-Tags und eindeutige Beschriftungen (`aria-label`).
   * Modale Dialoge nutzen native HTML5 `<dialog>`-Elemente mit `aria-modal="true"`, Fokusfalle
     und `Escape`-Schließung.
   * Kontrastverhältnisse entsprechen den definierten Design-Tokens aus 5.0.
3. **Idempotenz und CSRF:** Jede Einzel- und Sammelaktion ist durch ein gültiges Sitzungs-CSRF-Token
   und Versionsprüfung (`analysis_round`) abgesichert.

---

## 6. Umsetzungsschritte (Patch-Plan)

| Schritt | Patch | Inhalt |
| :--- | :--- | :--- |
| **F1** | 7.3.1 | **Projektionserweiterung & Fehler-Modul:** `queries.py` um Fehler-Metadaten und `analysis_round` ergänzen. Modul `error_reporting.py` mit Texten, Übersetzungen und Report-Builder erstellen. Unit-Tests. |
| **F2** | 7.3.2 | **Aktionen in der Fehlerliste:** Buttons „Erneut versuchen“ und „Ignorieren“ in `_archive_row` für fehlgeschlagene Mails integrieren. Backend-Verarbeitung testen. |
| **F3** | 7.3.3 | **Detail-Button und Dialog-Modal:** Modal in `dialogs.js` und `archive_pages.py` einbinden. Clipboard-Kopierfunktion implementieren. No-JS-Fallback auf Mail-Detailseite absichern. |
| **F4** | 7.3.4 | **Prominente Fehlerkarte auf der Mailseite:** Fehler-Header in `review_site.py` / `mail_page` ganz oben platzieren, inklusive Retry/Ignorieren-Aktionen. |
| **F5** | 7.3.5 | **Sammelaktionen:** Toolbar in `/mails?state=failed` um „Alle erneut versuchen“ und „Alle ignorieren“ erweitern. Bestätigungsdialoge und Batch-Verarbeitung absichern. |
| **F6** | 7.3.6 | **Gesamtabnahme & Dokumentation:** Vollständige Python- und Browser-Tests (100 % Zeilen- und Branch-Coverage), Dokumentation in Spezifikation, README und CHANGELOG. |

---

## 7. Tests und Abnahmekriterien

### 7.1 Automatisierte Python-Tests
* **Unit-Tests:**
  * `error_reporting.py`: Korrekte Formatierung aller Fehlercodes, Stufen und Wiederholungsversuche.
  * `queries.py`: Vollständige Projektion aller Fehlerfelder bei `state=failed`.
  * `processing_actions.py`: Erfolgreicher Retry, Zurücksetzen von `processing_retry`, erfolgreiches Ablegen via `FILE_MAIL`.
  * Batch-Aktionen: Konsistente Verarbeitung mehrerer Mails, Überspringen inzwischen geänderter Mails.
* **100 % Coverage-Pflicht:** 100 % Zeilen- und Branch-Abdeckung für alle neuen und berührten Codepfade.

### 7.2 Browser- und UI-Tests
* Aufruf von `/mails?state=failed`:
  * Fehlgeschlagene Mail zeigt die Buttons „Erneut versuchen“, „Ignorieren“ und „Details“.
  * Klick auf „Details“ öffnet den modalen Dialog mit allen Diagnosefeldern.
  * Klick auf „Bericht kopieren“ kopiert den Text.
  * Klick auf „Erneut versuchen“ entfernt die Mail aus der Fehlerliste und reiht sie in den Abruf ein.
  * Klick auf „Ignorieren“ entfernt die Mail dauerhaft aus `state=failed`.
* Aufruf ohne JavaScript: Formulare und No-JS-Links funktionieren einwandfrei.

---

## 8. Dokumentation bei Umsetzung

* Projektspezifikation ([Mailhelp-Projektspezifikation.md](../Mailhelp-Projektspezifikation.md)):
  Abschnitt über Fehlerbehandlung und Archivsuche um die neuen Aktionen erweitern.
* Bedienungsanleitung ([docs/Bedienung.md](Bedienung.md)):
  Erklärung der Fehlerbehebung über `/mails?state=failed` und der Diagnosefunktionen.
* Release-Dokumentation `docs/Release-7.3.md`, `README.md` und `CHANGELOG.md`.
