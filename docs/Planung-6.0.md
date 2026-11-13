# Mailhelp 6.0 – Breitbild-Ergonomie, parallele Browsertests, Regelablehnung und kompakte Offen-Ansicht

**Zielversion:** 6.0.0, Umsetzung in Patchversionen 6.0.1 bis 6.0.8

**Stand:** 13. November 2026 (überarbeitet nach Abgleich mit dem Quellstand 5.9.10)

**Status:** In Umsetzung

**Ausgangsstand:** 5.9.11 (Abnahme der Planung 5.9)

**Vorgänger:** [Planung 5.9](Planung-5.9.md)

**Grundlage:** [Entwicklungsregeln](../AGENTS.md), [Projektspezifikation](../Mailhelp-Projektspezifikation.md)

---

## 0. Ergebnis der Überprüfung dieser Planung

Die erste Fassung vom 12.11.2026 wurde gegen den Code geprüft. Die drei bisherigen Ziele bleiben;
ergänzt werden eine kompakte Werkzeugleiste für die Offen-Ansicht und die Beschleunigung der
Browsertests durch Parallelisierung. Einige
Annahmen waren nicht tragfähig und wurden korrigiert:

| Thema | Ursprüngliche Annahme | Befund im Code | Korrektur in dieser Fassung |
| :--- | :--- | :--- | :--- |
| Breite von `/lernen/entscheidungen` | `main` ist „auf ca. 960–1080 px verengt“; Lösung `max-width: min(96vw, 1600px)` | `main { max-width: 1080px }` gilt neben einer Seitenleiste (ab 900 px). Bei 1366 px bleiben für `main` rund 1100 px, bei 1024 px nur rund 780 px. Eine feste Breite allein hilft dort nicht. | Breite bis 1600 px nur für die Lernseite, **und** der Zweispalter richtet sich nach der Breite der Karte (Container-Abfrage), nicht nach dem Fenster. |
| Umbruch-Breakpoint | Stapeln unter 900 px Fensterbreite | Zwischen 900 und etwa 1300 px ist das Fenster breit, die Karte neben der Seitenleiste aber schmal. Genau dort quetscht die Tabelle. | `.rule-review` wird Container (`container-type: inline-size`); unter 1000 px **Kartenbreite** stehen Vergleich und Formular untereinander. |
| `overflow-wrap: anywhere` | nur in `.rule-diff section` | Auch `.compare-table th, td` hat `overflow-wrap: anywhere`; die Tabelle wird außerdem im Themeneditor genutzt. | Beide Stellen auf `break-word`; Kopfzeilen `nowrap`; kurze Werte und Abzeichen bleiben ganz. Regression für Lernseite **und** Themeneditor. |
| Testmatrix | `widescreen` als viertes Gerät in `DEVICES`, damit jeder UI-Test viermal läuft | 165 Stellen in `ui_tests` verzweigen nach `page.device == "desktop"` bzw. `page.mobile = device != "desktop"`. Ein viertes Gerät liefe dort über den Mobilpfad; die Suite (heute gut 20 Minuten) würde um ein Drittel länger. | Eigene Breitbild-Prüfung `ui_tests/test_ui_widescreen60.py` für **alle** Kernseiten bei 2560 × 1440 und 1920 × 1080, hell und dunkel. Ein Wächtertest stellt sicher, dass jede Seite der Navigation in der Liste steht, so dass neue Seiten automatisch geprüft werden. |
| Höhe von Zellen „exakt 1–2 Zeilen“ | Messung über Elementhöhe | Polster und Schaltflächenränder verfälschen die Höhe (in 5.9.6 beobachtet). | Zeilen werden über `Range.getClientRects()` des Textes gezählt (wie in 5.9.6). |
| Ablehnung: Bedienung | Drei-Wege-Auswahl, Sammelleiste „X übernehmen · Y verwerfen“ | Der Ablauf ist heute: Auswahl → **Vorschau** (`rule_preview`) → ausdrückliche Bestätigung. Nach der Übernahme werden alle Vorschläge des Prüfstands verworfen (`state.proposals = []`). | Auswahl je Karte als Optionsgruppe *Übernehmen / Verwerfen / Offen lassen* (Standard: offen). Die Vorschau nennt auch die zu verwerfenden Vorschläge. Gespeichert wird erst mit der Bestätigung. „Offen lassen“ entspricht dem heutigen Nicht-Ankreuzen: nichts wird gespeichert, ein späterer Lauf darf den Vorschlag wieder bringen. |
| Nur ablehnen | nicht betrachtet | `RuleValidationService.prepare` verlangt mindestens einen übernommenen Vorschlag. | Werden nur Vorschläge verworfen, entfällt der Dateischreibvorgang; nur die Sperrliste wird gespeichert, der Prüfstand endet mit „Ablehnungen gespeichert“. |
| „Mathematisch garantiert“ | Ein abgelehnter Vorschlag erscheint nie wieder | Ein Fingerabdruck erkennt nur gleiche Änderungen. Eine sinngemäß gleiche, aber anders formulierte Regel erkennt kein deterministischer Vergleich. | Zusage präzisiert: **dieselbe** Änderung (gleiches Thema, gleiche Art, gleiche normalisierte Einträge) wird garantiert unterdrückt, ebenso eine Änderung, die nur bereits abgelehnte Einträge enthält. Für Umformulierungen bleibt die Prompt-Anweisung. |
| Sicherheit der Webaktionen | nicht genannt | AGENTS.md verlangt Sitzung (bei Ausführung erneut geprüft), CSRF, Versionsprüfung und Idempotenzschlüssel. | Verwerfen läuft über den bestehenden, so geschützten Bestätigungsweg; „Wieder zulassen“ erhält eine eigene, ebenso geschützte Aktion mit Versionszähler der Sperrliste. |
| Inhalt der Sperrliste | `rationale` und vollständige `rejected_changes` | Die Begründung stammt aus der KI-Antwort und kann Mailinhalte wiedergeben; die Liste ist dauerhaft (`RuleHistory` überlebt die Bereinigung privater Prüfinhalte). | Gespeichert werden Thema (ID, Name, Kategorie), Art, die normalisierten geänderten Einträge (das, was abgelehnt wurde) und der Zeitpunkt, **keine** Begründung und keine Belege. Höchstens 500 Einträge, älteste fallen heraus. |
| Prompt | Ergänzung in `prompts.yaml` | `decision_rule_learning` steht in `devtools/prompt_guard.py` unter `NOT_EVALUATED`; eine Änderung verändert keine bewerteten Fingerabdrücke. | Payload-Feld `rejected` nur mit den abgelehnten Änderungen der übertragenen Themen; die Anweisung steht in beiden Prompts (`system_prompt` und `output_token_retry`). |

---

## 1. Übersicht und Ziel

1. **`/lernen/entscheidungen` auf breiten Bildschirmen reparieren.** Die Vergleichstabelle zerlegt
   Wörter buchstabenweise („Bi/sh/er“, „K/ei/n/e“), während links und rechts Platz frei bleibt.
2. **Breitbild-Prüfung für alle Kernseiten.** Sehr große Bildschirme (2560 × 1440, 1920 × 1080)
   werden automatisch auf Wortzerstückelung, Überlauf und ausgewogene Breiten geprüft.
3. **Regelvorschläge ablehnen.** Ein abgelehnter Vorschlag wird gespeichert, dem Modell beim
   nächsten Lauf als unerwünscht genannt und, falls es ihn trotzdem wieder liefert, herausgefiltert.
4. **Filter und Kopfbereich der Offen-Ansicht zusammenziehen.** Eine kompakte Werkzeugleiste
   bündelt Anzahl, bestehende Schnellfilter, Suche und Sortierung. Eine optionale Gruppierung nach
   „Rückfrage nötig“ und „Bereit zum Bestätigen“ zeigt, wo die Bearbeitung beginnen kann.
5. **Browsertests mindestens um Faktor 3 beschleunigen.** Laut aktueller Beobachtung benötigen
   sie etwa 21 Minuten bei nur 20–30 % CPU-Auslastung. Parallelisierung soll die vorhandenen
   Ressourcen besser nutzen und die Laufzeit bei gleichem Testumfang auf höchstens etwa
   7 Minuten senken. Der tatsächliche Beschleunigungsfaktor wird durch Vergleichsmessungen belegt.

**Nicht Teil von 6.0:** neue Einstellungen in `config.yaml`, Änderungen an anderen Prompts,
JavaScript-Pflicht. Alle neuen Bedienwege funktionieren ohne JavaScript.

---

## 2. Befund `/lernen/entscheidungen`

- `.rule-diff` teilt die Karte starr 1:1; links steht die dreispaltige `.compare-table` (Feld,
  Bisher, Neu), rechts das Formular.
- `.compare-table th[scope="row"]` ist fest `9rem` breit; mit `overflow-wrap: anywhere` in
  `.rule-diff section` **und** in `.compare-table th, td` darf der Browser jedes Wort an jeder
  Stelle trennen. Die Spalte „Bisher“ schrumpft dann auf wenige Pixel.
- `main` ist höchstens 1080 px breit. Neben der Seitenleiste bekommt jede Spalte bei 1366 px
  Fensterbreite rund 500 px, bei 1024 px nur rund 360 px.
- Es gibt nur „Diesen Vorschlag übernehmen“. Nicht angekreuzte Vorschläge werden beim nächsten Lauf
  oft gleich wieder vorgeschlagen; `RuleHistory` kennt nur `decision_ids`.

---

## 3. Spezifikation

### 3.1 Layout der Lernseite (6.0.1)

```css
/* Text bricht nur an Wortgrenzen; sehr lange Einzelwörter dürfen notfalls umbrechen. */
.rule-diff section, .compare-table th, .compare-table td { overflow-wrap: break-word; word-break: normal; }
.compare-table thead th { white-space: nowrap; }
.compare-table th[scope="row"] { width: auto; min-width: 6.5rem; max-width: 9.5rem; }
.compare-table td[data-label="Bisher"] { min-width: 6.5rem; }
.compare-table .badge, .compare-table .diff-mark { white-space: nowrap; }

/* Breite nur für die Lernseite; der Themeneditor bleibt schmal. */
@media (min-width: 1024px) { main:has(.rule-review) { max-width: 1600px; } }

/* Der Zweispalter richtet sich nach der Karte, nicht nach dem Fenster. */
.rule-review { container-type: inline-size; }
@container (max-width: 999px) { .rule-diff { grid-template-columns: 1fr; } }
```

- Ab 1000 px Kartenbreite stehen Vergleich und Formular nebeneinander (je mindestens rund 480 px),
  darunter untereinander. Die bisherige Regel `@media (max-width: 720px)` entfällt zugunsten der
  Container-Abfrage.
- Die mobile Kartenansicht der Tabelle (`@media (max-width: 720px)`) bleibt unverändert.

### 3.2 Breitbild-Prüfung (6.0.2)

- Neues Modul `ui_tests/test_ui_widescreen60.py` mit eigener Gerätematrix
  `WIDE = {"qhd": 2560 × 1440, "full_hd": 1920 × 1080}`, jeweils hell und dunkel. Die bestehenden
  Geräte (`desktop`, `mobile`, `narrow`) bleiben unverändert.
- Geprüft werden alle Kernseiten: `/`, `/mails`, `/verlauf`, `/auswertung`, `/auswertung/aufrufe`,
  `/status`, `/berichte`, `/themen`, `/lernen`, `/lernen/entscheidungen` (mit Prüfstand),
  `/einstellungen`. Ein **Wächtertest** vergleicht die Liste mit den Zielen der Hauptnavigation
  (`pages.py`); fehlt eine Seite, scheitert er. So greift die Prüfung automatisch für neue Seiten.
- Je Seite:
  - **Keine Wortzerstückelung:** Kein Wort in Tabellenköpfen, Abzeichen und Schaltflächen steht
    auf mehr als einer Zeile (Zeilenzählung über `Range.getClientRects()`).
  - **Kein waagerechter Überlauf** der Seite.
  - **Ausgewogene Breite:** `main` füllt bei 2560 px mindestens 60 % der Fläche neben der
    Seitenleiste oder erreicht seine festgelegte Höchstbreite.
  - Zugänglichkeitsprüfung (`checks.audit`) und Bildschirmfoto `-qhd`/`-full_hd` unter
    `.test-tmp/ui-screens/`.
- Zusätzlich auf der Lernseite: Spalte „Bisher“ mindestens 100 px breit bei 2560, 1920, 1366 und
  1024 px; Kopf „Bisher“ und Wert „Keine“ einzeilig; Karte bei 2560 px mindestens 1400 px breit.

### 3.3 Ablehnen von Regelvorschlägen

#### 3.3.1 Datenmodell (6.0.3)

```python
class RejectedRuleProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    category: Literal["relevant", "irrelevant"]
    topic_id: str = Field(pattern=r"^[a-z0-9_-]+$", max_length=64)
    topic_name: str = Field(max_length=200)
    action: Literal["modify", "create", "disable"]
    # Normalisierte Änderung: nur, was abgelehnt wurde; keine Begründung, keine Belege.
    changes: RuleChangeSet
    rejected_at: float

class RuleHistory(BaseModel):
    analyzed_at: float = 0
    decision_ids: list[str] = Field(default_factory=list, max_length=10_000)
    rejected: list[RejectedRuleProposal] = Field(default_factory=list, max_length=500)
    rejected_version: int = 0   # Versionsprüfung für „Wieder zulassen“
```

- `RuleChangeSet` beschreibt die Änderung gegenüber der bisherigen Regel: hinzugefügte und
  entfernte Beispiele und Ausschlüsse, geänderter Name, geänderte Beschreibung, Aktivierung.
  Einträge werden für den Vergleich normalisiert (Kleinschreibung, Leerraum zusammengefasst).
- `fingerprint = sha256(JSON[category, topic_id, action, changes])`.
- Alte `RuleHistory` ohne die neuen Felder laden unverändert.

#### 3.3.2 Bedienung (6.0.4)

- Jede Vorschlagskarte hat eine Optionsgruppe **Entscheidung**: *Übernehmen*, *Verwerfen* (nicht
  wieder vorschlagen), *Offen lassen* (Standard). `learning.js` zählt beides:
  *„2 zur Übernahme ausgewählt · 1 zum Verwerfen markiert“*. Ohne JavaScript bleibt die Zahl auf
  der Vorschau sichtbar.
- Die **Vorschau** nennt die übernommenen Änderungen wie bisher und darunter „Wird verworfen und
  nicht wieder vorgeschlagen“ mit Thema und abgelehnter Änderung.
- **Bestätigen** speichert die Ablehnungen in derselben versionsgeprüften, idempotenten Aktion wie
  die Übernahme (Sitzung bei Ausführung erneut geprüft, CSRF, Prüfstand-Version, Schlüssel). Ohne
  übernommene Vorschläge wird keine Regeldatei geschrieben.
- **Zuvor verworfene Vorschläge** stehen am Ende der Seite in einem aufklappbaren Bereich mit
  Datum, Thema, Art und abgelehnter Änderung. **Wieder zulassen** ist ein eigenes `POST` mit CSRF,
  Sitzung, `rejected_version` und Idempotenzschlüssel; eine veraltete Version ändert nichts und
  meldet das.

#### 3.3.3 Wiederholungsschutz (6.0.5)

1. **Prompt:** `payload()` erhält `rejected` mit den abgelehnten Änderungen der übertragenen
   Themen (nur Kategorie, Thema, Art, Änderung). Beide Prompts von `decision_rule_learning`
   weisen an, diese oder sinngemäß gleiche Änderungen nicht erneut vorzuschlagen.
2. **Fester Filter nach dem Modellaufruf:** Für jeden Vorschlag wird die Änderung gegenüber der
   bisherigen Regel bestimmt. Er wird verworfen, wenn sein Fingerabdruck einem abgelehnten gleicht
   **oder** wenn er für dasselbe Thema und dieselbe Art nur Einträge enthält, die schon abgelehnt
   wurden (Teilmenge). Die Zahl unterdrückter Vorschläge steht in der Zusammenfassung des
   Prüfstands; einzelne Inhalte werden nicht protokolliert.
3. Werden alle Vorschläge unterdrückt, endet die Analyse mit „Keine neuen Vorschläge; N bereits
   abgelehnte Vorschläge wurden ausgeblendet.“

### 3.4 Kompakte Werkzeugleiste der Offen-Ansicht (6.0.6)

- Auf der Seite **Offene Entscheidungen** (`/`, einschließlich `/offen`) werden Kopfbereich und
  Filter zu einer kompakten Werkzeugleiste zusammengeführt: Überschrift mit Anzahl, bestehende
  Schnellfilter, Suchfeld und Sortierauswahl stehen unmittelbar beieinander. Auf kleinen
  Bildschirmen werden die Bedienelemente lesbar untereinander angeordnet.
- Die Anzahl benennt die **angezeigten Entscheidungen**, nicht die Zahl der Mails. Bei aktiver
  Suche oder Filterung wird zusätzlich die Gesamtzahl der offenen Entscheidungen angezeigt,
  beispielsweise „4 von 12“. Die bestehenden Schnellfilter bleiben verfügbar.
- Die **Suche** umfasst Vorschlagstitel, Mailbetreff und Absender; bei Relevanzfragen Betreff und
  Absender. Suche und Schnellfilter lassen sich kombinieren. „Zurücksetzen“ stellt die
  ungefilterte Ansicht wieder her. Ohne Treffer bleiben Werkzeugleiste und Rücksetzoption sichtbar.
- Die **Sortierung** bietet „Neueste Mail zuerst“, „Älteste Mail zuerst“ und „Nächster Termin /
  nächste Frist zuerst“. Standard ist „Neueste Mail zuerst“. Bei der Termin-/Fristsortierung
  stehen Entscheidungen ohne Datum am Ende; gleiche Werte erhalten eine stabile Reihenfolge.
- Optional lässt sich **Nach Bearbeitungsbedarf gruppieren** einschalten: „Rückfrage nötig“
  enthält Relevanzfragen und Vorschläge mit offenen Fragen oder Konflikten. „Bereit zum
  Bestätigen“ enthält nur Vorschläge, deren aktueller Zustand eine Bestätigung erlaubt.
  Übrige offene Entscheidungen erscheinen unter „Weitere Prüfung nötig“. Jede Entscheidung
  erscheint genau einmal; Gruppen zeigen ihre Anzahl, die gewählte Sortierung gilt innerhalb
  jeder Gruppe.
- Suche, Filter, Sortierung und Gruppierung werden als URL-Parameter abgebildet und funktionieren
  auch ohne JavaScript. Beim Wechsel eines Bedienelements bleiben die anderen Einstellungen
  erhalten; Neuladen und Zurücknavigation stellen die Ansicht wieder her. Eingaben werden validiert
  und bei der Ausgabe maskiert; unbekannte Auswahlwerte fallen auf die Standardansicht zurück.
- Die Werkzeugleiste verändert ausschließlich die Anzeige. Sie bestätigt keine Vorschläge und
  löst keine Schreibzugriffe auf Google Kalender oder Todoist aus. In der Desktop-Zweiteilung
  folgt die Detailauswahl der sichtbaren Liste; ausgefilterte Entscheidungen bleiben nicht als
  scheinbar ausgewählter Eintrag stehen.

### 3.5 Browsertests parallelisieren (6.0.7)

- **Ausgangslage und Ziel:** Beobachtet sind etwa 21 Minuten Gesamtlaufzeit bei 20–30 %
  CPU-Auslastung. Ziel ist mindestens Faktor 3 Beschleunigung durch parallele Testausführung,
  entsprechend höchstens etwa 7 Minuten für den bisherigen Testumfang auf demselben Rechner.
  Die CPU-Auslastung ist ein Hinweis auf ungenutzte Ressourcen; der Zeitgewinn muss gemessen werden.
- Die Browser-Suite erhält einen parallel ausführbaren Testlauf, beispielsweise über
  `pytest-xdist`. Die Zahl der Worker wird explizit einstellbar; Messungen mit 1, 2, 3 und
  4 Workern ermitteln eine geeignete Voreinstellung unter Berücksichtigung von CPU und
  Arbeitsspeicher. Ein serieller Lauf bleibt für die Fehlersuche verfügbar.
- Jeder Worker erhält isolierte Testdaten, Zustandsverzeichnisse, Serverports, Sitzungen und
  Browserkontexte. Gemeinsam genutzte Dateien und feste Ports werden auf Kollisionen geprüft.
  Screenshots, Logs und Abdeckungsdaten erhalten eindeutige Pfade, damit parallele Läufe keine
  Ergebnisse überschreiben. Externe Dienste bleiben simuliert, Testdaten synthetisch.
- Die bisherige JavaScript-Abdeckungsmessung und sonstige Abdeckungsnachweise werden vollständig
  über alle Worker zusammengeführt und anschließend zentral geprüft. Ein Worker-Ausfall oder
  fehlende Ergebnisdateien lässt den Gesamtlauf scheitern. Die verbindlichen 100 % Zeilen- und
  Branch-Abdeckung für eigenen Anwendungscode bleiben erhalten.
- Beschleunigung entsteht durch Parallelisierung und eine ausgewogene Verteilung langer Tests.
  Testfälle, Gerätematrix, Assertions, Zugänglichkeitsprüfungen und erforderliche Screenshots
  werden dafür nicht reduziert. Pauschal verkürzte Wartezeiten oder automatische Wiederholungen
  dürfen instabile Tests nicht verdecken.
- **Leistungsnachweis:** Seriellen und parallelen Lauf am gleichen Quellstand mit identischem
  Testumfang auf derselben Hardware jeweils dreimal unter vergleichbaren Bedingungen messen.
  Median der Gesamtlaufzeit einschließlich Start, Zusammenführung und Abdeckungsprüfung
  vergleichen: `Median seriell / Median parallel >= 3`. Workerzahl, Hardware, Testanzahl,
  Laufzeiten, CPU-Auslastung und maximaler Speicherbedarf werden in `docs/Release-6.0.md`
  dokumentiert. Zusätzliche Tests aus Version 6.0 werden ebenfalls im vollständigen Lauf
  berücksichtigt; die etwa 7 Minuten beziehen sich auf den bisherigen Umfang.
- Wiederholte vollständige parallele Läufe müssen ohne zusätzliche sporadische Fehler bestehen.
  Isolation, Ergebniszusammenführung und Fehlerweitergabe werden gezielt geprüft. Der unterstützte
  Aufruf und die Worker-Einstellung werden für Windows 11 und Docker auf Linux dokumentiert.

---

## 4. Umsetzungsschritte

| Schritt | Patch | Arbeitspaket | Tests |
| :--- | :--- | :--- | :--- |
| W1 | 6.0.1 | Layout der Lernseite (3.1) | Regression „Bi/sh/er“ und „K/ei/n/e“ bei 2560, 1920, 1366 und 1024 px; Themeneditor unverändert schmal; mobil gestapelt |
| W2 | 6.0.2 | Breitbild-Prüfung (3.2) | Kernseiten bei 2560 und 1920 px, hell und dunkel; Wächtertest für die Navigation |
| W3 | 6.0.3 | Datenmodell, Änderungsmenge, Fingerabdruck | Normalisierung, gleiche und unterschiedliche Fingerabdrücke, Teilmengen, Altbestand, Obergrenze 500 |
| W4 | 6.0.4 | Verwerfen, Vorschau, Bestätigung, Wieder zulassen | Erfolg, nur Ablehnen, Doppelklick, veraltete Version, fremde/abgelaufene Sitzung, CSRF, ohne JavaScript, Neustart |
| W5 | 6.0.5 | Prompt-Feld und fester Filter | Unterdrückung gleicher und Teilmengen-Vorschläge, alle unterdrückt, Wiederzulassung wirkt im nächsten Lauf, Prompt enthält `rejected` |
| W6 | 6.0.6 | Kompakte Werkzeugleiste der Offen-Ansicht (3.4) | Kombinierte Suche und Filter, Zähler, Sortierung einschließlich fehlender/gleicher Daten, optionale Gruppen, leere Trefferliste, URL-Wiederherstellung, ohne JavaScript, mobile und breite Ansicht, Detailauswahl, keine externen Schreibaktionen |
| W7 | 6.0.7 | Browsertests parallelisieren (3.5) | Worker-Isolation, kollisionsfreie Artefakte, vollständige Abdeckungszusammenführung, Worker-Ausfall, wiederholte Gesamtläufe, serieller/paralleler Zeitvergleich mit mindestens Faktor 3 |
| W8 | 6.0.8 | Abnahme und Release | Gesamtprüfung mit 100 % Abdeckung, vollständige parallele UI-Suite, `docs/Release-6.0.md` |

---

## 5. Abnahmekriterien

| Kriterium | Prüfung | Erwartung |
| :--- | :--- | :--- |
| Keine Wortzerstückelung | `/lernen/entscheidungen` bei 2560, 1920, 1366 und 1024 px | „Bisher“ und „Keine“ einzeilig |
| Spalte „Bisher“ | Breite messen | mindestens 100 px |
| Breitennutzung | Karte bei 2560 px | mindestens 1400 px, höchstens 1600 px Seitenbreite |
| Stapeln | Karte schmaler als 1000 px | Vergleich über dem Formular |
| Breitbild-Kernseiten | `test_ui_widescreen60.py` | alle Seiten ohne Überlauf und Wortzerstückelung; Wächter grün |
| Ablehnen | Verwerfen wählen, prüfen, bestätigen | Eintrag in `RuleHistory.rejected`, Prüfstand beendet |
| Keine Wiederholung | gleicher Vorschlag im nächsten Lauf | weder angezeigt noch übernehmbar; Zahl der ausgeblendeten Vorschläge sichtbar |
| Wieder zulassen | in der Liste zulassen | Sperre aufgehoben; Vorschlag darf wieder erscheinen |
| Sicherheit | Doppelklick, veraltete Version, ohne CSRF, abgelaufene Sitzung | keine doppelte oder unautorisierte Änderung |
| Kompakte Werkzeugleiste | Offen-Ansicht auf Mobilgerät, Desktop und Breitbild | Anzahl, Schnellfilter, Suche und Sortierung zusammenhängend bedienbar, ohne waagerechten Überlauf |
| Suche und Sortierung | Suche mit Schnellfilter kombinieren, Sortierung wechseln, keine Treffer | korrekte Treffer und Zähler; stabile Sortierung; Rücksetzen bleibt erreichbar |
| Optionale Gruppierung | gemischte synthetische Entscheidungen | jede Entscheidung genau einmal in der passenden Gruppe; nur bestätigbare Vorschläge unter „Bereit zum Bestätigen“ |
| Ansicht wiederherstellen | URL neu laden und Zurücknavigation, auch ohne JavaScript | Suche, Filter, Sortierung und Gruppierung erhalten; Detailauswahl gehört zur sichtbaren Liste |
| Reine Anzeigeaktionen | Werkzeugleiste bedienen | keine Bestätigung und kein externer Schreibzugriff |
| Beschleunigung der Browsertests | je drei serielle und parallele Läufe, gleicher Quellstand, Umfang und Rechner | Verhältnis der Medianlaufzeiten mindestens 3; bisher etwa 21 Minuten auf höchstens etwa 7 Minuten |
| Parallele Testisolation | wiederholte vollständige Läufe mit mehreren Workern | keine kollidierenden Zustände, Ports oder Artefakte; unveränderter Testumfang und keine zusätzlichen sporadischen Fehler |
| Abdeckung und Fehlerweitergabe im parallelen Lauf | Worker-Ergebnisse zusammenführen; Ausfall oder fehlendes Ergebnis simulieren | vollständiger zentraler Abdeckungsnachweis; fehlende Ergebnisse oder Worker-Fehler lassen den Lauf scheitern |
| Abdeckung | `pytest` | 100 % Zeilen- und Branch-Abdeckung |

---

## 6. Dokumentation und Release

- `README.md`, `CHANGELOG.md`, `docs/Bedienung.md` (Hilfeindex neu erzeugen) und die
  Projektspezifikation werden je Patch aktualisiert.
- `docs/Release-6.0.md` dokumentiert die Abnahme.
- Die Anleitung für Browsertests enthält den parallelen und seriellen Aufruf sowie die
  Worker-Einstellung; der Releasebericht enthält die Vergleichsmessungen gemäß Abschnitt 3.5.
