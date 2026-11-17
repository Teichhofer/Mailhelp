# Mailhelp 7.4 – Mehrtägige Termine und Datumsbereiche

**Zielversion:** 7.4, Umsetzung in Patchversionen ab 7.4.1  
**Stand:** 17. November 2026
**Status:** Vollständig umgesetzt und automatisiert abgenommen. Der Nachtrag ergänzt Jahresauflösung ohne Jahreszahl und die Speicherung des Enddatums während der Klärung. Prüfstand in [Release 7.4](Release-7.4.md).
**Ausgangsfall:** E-Mail vom 09.11.2026, 16:15 Uhr MEZ (`mail-450553d4e60ffe8960b6c59f`),  
Betreff: *„WG: Programm Vlf Schulungstagung Bad Waldse am 07./08.01.2027 - "Mit Krisen und mentalen Belastungen gut umgehen"“*  
**Grundlage:** [Entwicklungsregeln](../AGENTS.md), [Projektspezifikation](../Mailhelp-Projektspezifikation.md), [Planung 7.1](Planung-7.1.md), [Planung 7.2](Planung-7.2.md).

---

## 1. Anlass und Problembeschreibung

In der Praxis scheitern Termine, die sich über mehrere Tage erstrecken, bei der
automatischen Verarbeitung in Mailhelp. Anhand der realen E-Mail vom 09.11.2026,
16:15 Uhr (`mail-450553d4e60ffe8960b6c59f`) zur *Vlf Schulungstagung Bad Waldsee*
am 07./08.01.2027 wurde das Verhalten analysiert:

* **Eingangsdaten aus der Mail:**
  * Betreff: `WG: Programm Vlf Schulungstagung Bad Waldse am 07./08.01.2027 - "Mit Krisen und mentalen Belastungen gut umgehen"`
  * Im Anhangsprogramm bzw. Text:
    * Termin: `Donnerstag 07. bis Freitag 08. Januar 2027`
    * Beginn: `11.30 Uhr` (Donnerstag)
    * Ende: `12.30 Uhr` (Freitag)
    * Ort: `Bauernschule Bad Waldsee, Frauenbergstraße 15, 88339 Bad Waldsee`
* **Ergebnis der LLM-Extraktion (`ExtractedEvent`):**
  * `title`: `"Vlf Schulungstagung Bad Waldsee"`
  * `date_text`: `"Donnerstag 07. bis Freitag 08. Januar 2027"`
  * `time_text`: `"11.30 Uhr"`
  * `end_time_text`: `"12.30 Uhr"`
  * `time_requirement`: `"timed"`
  * Das LLM hat die Daten gemäß Prompt (`prompts.yaml`) korrekt und wörtlich extrahiert.
* **Tatsächliches Verhalten der Anwendung (`action_normalization.py` / `proposal_builder.py`):**
  * Der erzeugte Terminvorschlag (`p_3b9481746680b70f76df754a`) erhält:
    * `start`: `null`
    * `end`: `null`
    * `status`: `"needs_clarification"`
    * `open_questions`: `["Welches konkrete Datum ist mit „Donnerstag 07. bis Freitag 08. Januar 2027“ gemeint?", "Ist die Nutzerin oder der Nutzer für diesen Eintrag zuständig?"]`
  * Mailhelp konnte das Datum nicht auflösen und fordert eine manuelle Klärung an,
    obwohl Datum, Beginn und Ende eindeutig in der Mail vorliegen.

---

## 2. Ursachenanalyse (Technischer Befund)

Die detaillierte Code-Prüfung ergab fünf ineinandergreifende Ursachen in
`src/mailhelp/proposals/action_normalization.py` und angrenzenden Modulen:

### Befund 1: Regex-Muster erkennen Wochentage und Kurzschreibweisen nicht
In `_DATE_RANGE_NAMED` und `_DATE_RANGE_NUMERIC`:
```python
_DATE_RANGE_NAMED = re.compile(
    rf"(?i)(?:vom\s+)?(\d{{1,2}})\.?\s*(?:-|\u2013|\u2014|bis|und)\s*"
    rf"(\d{{1,2}})\.?\s+({MONTH_PATTERN})\s+(\d{{4}})")
_DATE_RANGE_NUMERIC = re.compile(
    r"(?<!\d)(\d{1,2})\.(\d{1,2})\.(\d{4})\s*(?:-|\u2013|\u2014|bis)\s*"
    r"(\d{1,2})\.(\d{1,2})\.(\d{4})(?!\d)", re.IGNORECASE)
```
1. **Wochentage blockieren den Match:** `_DATE_RANGE_NAMED` erwartet unmittelbar vor
   der ersten Zahl optional `vom\s+`. Führende Wochentage wie `Donnerstag ` oder
   eingeschobene Wochentage wie `bis Freitag 08.` verhindern den Treffer vollständig.
   Während `_DATE_NAMED` bereits `WEEKDAY_PATTERN` kennt, fehlt dies bei Datumsbereichen.
2. **Kompakte Schreibweisen fehlen:** Schreibweisen wie `07./08.01.2027`, `07.-08.01.2027`
   oder `7./8. Januar 2027` (gleicher Monat und gleiches Jahr) werden von
   `_DATE_RANGE_NUMERIC` nicht erkannt, da dieses zwingend zwei vollständige
   `DD.MM.YYYY`-Angaben verlangt.

### Befund 2: Getaktete Termine (mit Uhrzeit) sind von Datumsbereichen ausgeschlossen
In `normalize_event` (`action_normalization.py`, Zeilen 505–508):
```python
date_range = _unambiguous_date_range(event)
if date_range is not None and event.time_text is None and event.end_time_text is None:
    return _normalize_date_range(event, context, date_range)
parsed_day = _parse_date(event.date_text, event.responsibility, context, event.evidence)
```
* Selbst wenn `_unambiguous_date_range` den Bereich `(..., 2027-01-07, 2027-01-08)`
  erkannt hätte, greift `_normalize_date_range` **ausschließlich dann**, wenn
  `event.time_text is None and event.end_time_text is None` gilt!
* Sobald ein Termin eine Uhrzeit besitzt (`time_text = "11.30 Uhr"`), überspringt
  die Logik den Datumsbereich und fällt auf `_parse_date(event.date_text, ...)` zurück.
* `_parse_date` unterstützt jedoch prinzipiell nur Einzeltage und quittiert den Bereich
  mit `NormalizationReason.UNSUPPORTED_DATE`:
  *„Welches konkrete Datum ist mit „Donnerstag 07. bis Freitag 08. Januar 2027“ gemeint?“*

### Befund 3: `_normalize_timed` setzt zwingend Start und Ende auf denselben Kalendertag
In `_normalize_timed` (`action_normalization.py`, Zeilen 450–499):
```python
def _normalize_timed(event: ExtractedEvent, context: MailDateContext, day: date,
                     fact: TemporalFact) -> NormalizationResult:
    ...
    start = datetime.combine(day, start_clock, zone)
    ...
    end = datetime.combine(day, end_clock, zone)
    if end <= start:
        return replace(_failure(NormalizationReason.END_NOT_AFTER_START, ...))
```
* `_normalize_timed` nimmt nur ein einzelnes `day: date` entgegen.
* Sowohl `start` als auch `end` werden mit demselben `day` kombiniert.
* Liegt das Ende am Folgetag (z. B. Start Do 11:30, Ende Fr 12:30):
  * Bei einer Endzeit, die numerisch vor dem Beginn liegt (z. B. Start 13:00, Ende Folgetag 12:00),
    löst die Prüfung `end <= start` den Fehler `END_NOT_AFTER_START` aus
    („Liegt das Ende an einem anderen Tag oder ist eine Uhrzeit falsch?“).
  * Bei Beginn 11:30 und Ende 12:30 am Folgetag würde das System den Termin fälschlich
    auf 1 Stunde am ersten Tag verkürzen, anstatt die 25-stündige Tagung über beide Tage abzubilden.

### Befund 4: Keine Repräsentation von Mehrtagesintervallen in der Klärungsebene
* Scheitert die Erkennung, speichert `known_temporal_facts` nur `date: date | None`.
  Ein zweites Datum (`end_date`) ist in `KnownTemporalFacts` nicht vorgesehen.
* Die Weboberfläche zur manuellen Klärung (`/klaeren`) bietet keine Eingabemöglichkeit
  für Datumsspannen, sondern validiert ausschließlich Einzeltage.

### Befund 5: Positiver Befund im Kalender-Adapter und UI
* **Google Calendar Adapter (`src/mailhelp/external/calendar.py`):**
  * `_timed_interval` übergibt ISO-8601-Datetimes (`start.isoformat()`, `end.isoformat()`).
    Google Calendar, CalDAV und Outlook unterstützen mehrtägige getaktete Events nativ.
  * `_all_day_interval` übergibt Start- und Exklusiv-Enddatum (`start.isoformat()`, `end.isoformat()`).
* **Karten-Formatierung (`src/mailhelp/review/cards.py`, Zeilen 105–116):**
  * `_event_time` unterstützt bereits die formatierte Ausgabe mehrtägiger Termine:
    * Ganztägig: `f"{start:%d.%m.%Y} – {last:%d.%m.%Y}, ganztägig"`
    * Getaktet: `f"{local_start:%d.%m.%Y, %H:%M} Uhr – {local_end:%d.%m.%Y, %H:%M} Uhr"`
* **Fazit:** Die Datenmodelle (`Proposal.start`, `Proposal.end`, `Proposal.all_day`),
  die Kalenderschnittstellen und die Darstellungslogik können bereits mit Mehrtagesterminen
  umgehen. Das Problem liegt rein in der **Erkennung und Normalisierung** in `action_normalization.py`.

---

## 3. Ziel und Soll-Verhalten für Version 7.4

1. **Umfassende Erkennung deutscher Datumsbereiche:**
   * Wochentage am Start- und Endtag (z. B. *„Donnerstag 07. bis Freitag 08. Januar 2027“*,
     *„Do 07. – Fr 08.01.2027“*, *„Donnerstag, 7. bis Freitag, 8. Januar 2027“*).
   * Monatsübergreifende benannte Bereiche (z. B. *„28. Januar bis 2. Februar 2027“*).
   * Numerische Kurzformen (z. B. *„07./08.01.2027“*, *„07.-08.01.2027“*, *„7./8.1.2027“*).
   * Jahreslose Datumsbereiche mit Mail-Kontextbezug (z. B. *„07. bis 08. Januar“*).
2. **Getaktete Mehrtagestermine (`_normalize_timed_range`):**
   * Verknüpfung von `start_day` mit `start_clock` und `inclusive_end` mit `end_clock`.
   * Ist eine Enduhrzeit angegeben, endet der Termin am Endtag um diese Uhrzeit:
     `start = combine(start_day, start_clock)`, `end = combine(inclusive_end, end_clock)`.
   * Ist keine Enduhrzeit angegeben, aber eine Dauer: Addition auf `start`.
   * Fehlt die Enduhrzeit ohne Dauer: Gezielte Rückfrage *„Wann endet der Termin am <Enddatum>?“*,
     während `known_start` und `known_end_date` als bekannte Fakten erhalten bleiben.
3. **Ganztägige Mehrtagestermine:**
   * Ganztägige Spannen werden mit `start = start_day` und `end = inclusive_end + 1 Tag`
     (Google-Kalender-Standard für exklusives Ende) und `all_day = True` normalisiert.
4. **Klärung und Bearbeitung in Web & Telegram:**
   * Die Bearbeitungsmasken für Terminvorschläge erlauben abweichende Enddaten.
   * Klärungsdialoge unterstützen Datumsspannen.
5. **Keine Regressionen:**
   * 100 % Zeilen- und Branch-Abdeckung für allen geänderten und neuen Code.
   * Bestehende Einzeltag-Termine, Zeitverschiebungen und Dublettenprüfungen bleiben unverändert.

---

## 4. Technische Umsetzung

### 4.1 Regex-Muster in `action_normalization.py`

```python
_DATE_RANGE_NAMED = re.compile(
    rf"(?i)(?:vom\s+)?(?:({WEEKDAY_PATTERN}),?\s+)?(\d{{1,2}})\.?\s*(?:-|\u2013|\u2014|bis|und)\s*"
    rf"(?:({WEEKDAY_PATTERN}),?\s+)?(\d{{1,2}})\.?\s+({MONTH_PATTERN})\s+(\d{{4}})")

_DATE_RANGE_MULTI_MONTH = re.compile(
    rf"(?i)(?:vom\s+)?(?:({WEEKDAY_PATTERN}),?\s+)?(\d{{1,2}})\.?\s+({MONTH_PATTERN})\s*(?:-|\u2013|\u2014|bis|und)\s*"
    rf"(?:({WEEKDAY_PATTERN}),?\s+)?(\d{{1,2}})\.?\s+({MONTH_PATTERN})\s+(\d{{4}})")

_DATE_RANGE_SLASH_NUMERIC = re.compile(
    r"(?<!\d)(\d{1,2})\.\s*[/–-]\s*(\d{1,2})\.(\d{1,2})\.(\d{4})(?!\d)")

_DATE_RANGE_FULL_NUMERIC = re.compile(
    r"(?<!\d)(?:({WEEKDAY_PATTERN}),?\s+)?(\d{1,2})\.(\d{1,2})\.(\d{4})\s*(?:-|\u2013|\u2014|bis)\s*"
    r"(?:({WEEKDAY_PATTERN}),?\s+)?(\d{1,2})\.(\d{1,2})\.(\d{4})(?!\d)", re.IGNORECASE)
```

Wochentage werden bei Nennung defensiv gegen den berechneten Kalendertag validiert;
Widersprüche führen zu `_WEEKDAY_MISMATCH`.

### 4.2 Verzweigungslogik in `normalize_event`

```python
def normalize_event(event: ExtractedEvent, context: MailDateContext) -> NormalizationResult:
    event = split_time_range(event)
    date_range = _unambiguous_date_range(event)
    if date_range is not None:
        if event.time_requirement == TimeRequirement.ALL_DAY or (event.time_text is None and event.end_time_text is None):
            return _normalize_all_day_date_range(event, context, date_range)
        return _normalize_timed_date_range(event, context, date_range)
    ...
```

### 4.3 Getaktete Mehrtages-Normalisierung (`_normalize_timed_date_range`)

```python
def _normalize_timed_date_range(event: ExtractedEvent, context: MailDateContext,
                                date_range: tuple[str, date, date]) -> NormalizationResult:
    raw_range, start_day, inclusive_end = date_range
    responsibility = event.responsibility
    zone = (_explicit_offset(event.timezone_offset_text)
            if event.timezone_offset_text is not None
            else _context_zone(context, responsibility))
    if isinstance(zone, NormalizationResult):
        return zone
    
    if event.time_text is None:
        return _failure(NormalizationReason.MISSING_TIME, raw_range, responsibility,
                        "Wann beginnt der Termin am ersten Tag?")
    
    start_clock = _parse_time(event.time_text, responsibility)
    if isinstance(start_clock, NormalizationResult):
        return start_clock
    
    start = (datetime.combine(start_day, start_clock, zone)
             if isinstance(zone, timezone) else _localize(start_day, start_clock, zone, responsibility))
    
    if event.end_time_text is not None:
        end_clock = _parse_time(event.end_time_text, responsibility)
        if isinstance(end_clock, NormalizationResult):
            return end_clock
        end = (datetime.combine(inclusive_end, end_clock, zone)
               if isinstance(zone, timezone) else _localize(inclusive_end, end_clock, zone, responsibility))
        if end <= start:
            return _failure(NormalizationReason.END_NOT_AFTER_START,
                            f"{event.time_text}–{event.end_time_text}", responsibility,
                            "Endzeitpunkt liegt vor dem Beginn.")
        fact = TemporalFact(raw_text=raw_range, normalized_date=start_day,
                            year_source=YearSource.EXPLICIT_MAIL, status=TemporalResolutionStatus.RESOLVED)
        return NormalizationResult(TemporalValue(start, end, False), None,
                                   f"{raw_range} {event.time_text}–{event.end_time_text}", None,
                                   responsibility, temporal_fact=fact)
    
    # Endzeit fehlt: Dauer prüfen oder Rückfrage
    ...
```

---

## 5. Umsetzungsschritte (Patch-Plan)

| Schritt | Patch | Inhalt |
| :--- | :--- | :--- |
| **M1** | 7.4.1 | **Datumsbereich-Muster:** Reguläre Ausdrücke um Wochentage, Monatswechsel und Schrägstrichschreibweisen (`07./08.01.2027`) erweitern. Validierung von Wochentagen. Unit-Tests für alle Syntaxvarianten. |
| **M2** | 7.4.2 | **Getaktete Mehrtages-Normalisierung:** `_normalize_timed_date_range` in `action_normalization.py` implementieren. Beginn an `start_day`, Ende an `inclusive_end`. Fehlerbehandlung für ungültige Zeitfolgen. |
| **M3** | 7.4.3 | **Regressionstest mit Original-Mail:** Testfall basierend auf `mail-450553d4e60ffe8960b6c59f` (Vlf Schulungstagung Bad Waldsee). Nachweis, dass der Vorschlag ohne manuelle Datumsrückfrage erzeugt wird und die Zeitspanne 07.01.2027 11:30 bis 08.01.2027 12:30 korrekt im Vorschlag steht. |
| **M4** | 7.4.4 | **Web- und Telegram-Interaktion:** Anzeige, Klärung und manuelles Editieren von Mehrtagesterminen in `proposal_edit_site.py` und Telegram-Presenter prüfen und absichern. |
| **M5** | 7.4.5 | **Kalender-Adapter und Gesamtabnahme:** Schreibtests für Google Calendar, CalDAV und Outlook mit getakteten Mehrtagesterminen. Vollständige Prüfsuite (100 % Line- und Branch-Coverage), Dokumentation und Versionsabschluss. |

---

## 6. Abnahmekriterien

1. **Originalfall:** Die E-Mail vom 09.11.2026 (`mail-450553d4e60ffe8960b6c59f`) erzeugt einen
   Terminvorschlag mit:
   * `start = 2027-01-07 11:30:00+01:00`
   * `end = 2027-01-08 12:30:00+01:00`
   * `all_day = False`
   * Keine Rückfrage nach dem Datum.
2. **Kompaktschreibweisen:** Termine mit `07./08.01.2027`, `7.-8. Januar 2027` oder
   `28.01. bis 02.02.2027` werden sowohl ganztägig als auch mit Uhrzeiten korrekt aufgelöst.
3. **Wochentagsprüfung:** Widersprüchliche Angaben (z. B. „Freitag 07. Januar 2027“, wenn der
   07.01.2027 ein Donnerstag ist) werden abgelehnt und erfordern Klärung.
4. **Qualitätssicherung:**
   * 100 % Zeilenabdeckung und 100 % Branch-Abdeckung für jeden neuen/geänderten Code.
   * `python -m devtools.check full --workers 12` und Browsertests bestehen fehlerfrei.
   * Dokumentation in Projektspezifikation, README und CHANGELOG aktualisiert.
