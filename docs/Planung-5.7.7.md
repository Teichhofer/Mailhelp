# Mailhelp 5.7.7 – Regellernen mit kleiner, verlässlicher KI-Antwort

**Zielversion:** 5.7.7 (Bugfix)

**Stand:** 11. November 2026

**Status:** Umgesetzt (12. November 2026), Abnahme mit echtem Modell offen

**Ausgangsstand:** 5.7.6 (Auswahl „Nur neue“ / „Alle bisherigen“, `max_tokens: 16000`, konkrete Fehlerursachen)

---

## 1. Befund

Im Betrieb scheitert „Aus Entscheidungen lernen“ weiterhin:

| Lauf | Belege | `max_tokens` | Dauer je Versuch | Ergebnis |
| --- | --- | --- | --- | --- |
| 21:57 (5.7.5) | 34 | 4000 | 15 s | 2 × `finish_reason: length`, kein Inhalt |
| 22:30 (5.7.6, „Alle bisherigen“) | 184 | 16000 | 23–25 s | 2 × `finish_reason: length`, kein Inhalt |

Die Vervierfachung des Limits hat nichts geändert. Das Modell
(`deepseek/deepseek-v4.1-flash` über den Anbieter Parasail) schreibt jedes Mal bis zum Limit.
Ein größeres Limit allein ist deshalb keine Lösung.

**Was die Protokolle nicht zeigen:** Bei einem Abbruch am Limit verwirft der OpenRouter-Client
die Antwort, bevor Tokenverbrauch (`usage`) und Länge der Teilantwort erfasst werden.
`content_length: 0` ist nur der Vorgabewert. Ob die Tokens für das Nachdenken (Reasoning),
für eine sehr lange Antwort oder für eine Endlosschleife verbraucht wurden, ist daher nicht
belegt.

**Wahrscheinliche Ursachen im Ablauf** (aus Aufbau von Prompt und Antwortschema):

1. **Die Antwort ist zu groß angelegt.** Jeder Vorschlag muss das *vollständige* Thema
   zurückgeben: alle Beispiele und Ausschlüsse (bis zu 30 × 500 Zeichen), dazu Begründung und
   Beleg-IDs. Bei bis zu 20 Vorschlägen sind das schnell über 10 000 Tokens, plus Reasoning.
   Das Kopieren langer Listen ist zugleich die typische Stelle, an der Modelle in
   Wiederholungsschleifen geraten (vgl. Hilfschat 5.5.7).
2. **Die Eingabe ist ungünstig zusammengesetzt.** 168 der 184 Belege sind „Vorschlag
   abgelehnt“. Laut Prompt ist das allein kein Beleg, das Modell muss sie dennoch einzeln
   durchgehen, je mit bis zu 1000 Zeichen Mailtext. Dazu kommen alle 48 Themen vollständig.
   Das treibt das Reasoning.
3. **Der zweite Versuch ist identisch.** Nach dem Abbruch wird dieselbe Anfrage
   wiederholt. Das kostet doppelt, ohne dass ein anderes Ergebnis zu erwarten ist. Der
   vorhandene Mechanismus `output_token_retry` (kleinere Nutzlast, knapper Prompt) ist für
   diesen Schritt nicht eingerichtet.
4. **Der Hinweis in der Meldung führt in die Irre.** „weniger Entscheidungen wählen“
   verringert die *Eingabe*; abgeschnitten wird aber die *Ausgabe*.

## 2. Ziel

Eine Analyse liefert auch mit 200 Belegen zuverlässig eine gültige, kleine Antwort.
Fehlschläge sind anhand der Protokolle eindeutig zu erklären. Sicherheit, Bestätigungen und
Validierung bleiben unverändert.

## 3. Arbeitspakete

### B1 – Abbrüche messbar machen (Voraussetzung)

- Bei `output_token_limit` protokolliert der Client die gemeldeten Tokenzahlen
  (`usage.completion_tokens`, `usage.completion_tokens_details.reasoning_tokens`,
  `prompt_tokens`) sowie Länge und Hash der Teilantwort. Den Inhalt protokolliert er nicht,
  außer bei ausdrücklich zugeschaltetem Inhaltslogging.
- Gilt für alle KI-Schritte, nicht nur für das Regellernen. Ein Regressionstest mit einer
  simulierten abgeschnittenen Antwort prüft, dass `usage` und Länge im Protokoll stehen.
- Danach kann *ein* Diagnoselauf mit echtem Modell zeigen, ob Reasoning oder Ausgabe das
  Limit verbraucht. Dieser Lauf kostet wenige Cent und braucht deine ausdrückliche Freigabe.

### B2 – Antwort als Änderung statt als vollständiges Thema (Kernänderung)

Das Modell liefert je Vorschlag nur noch, *was sich ändert*:

```json
{"topic_id": "schule", "category": "relevant", "action": "modify",
 "rationale": "…", "evidence": ["…"],
 "changes": {"add_examples": ["…"], "remove_examples": ["…"],
             "add_exclusions": ["…"], "remove_exclusions": ["…"],
             "description": "… (nur wenn geändert)", "name": "… (nur neu/geändert)",
             "enabled": false}}
```

- Mailhelp setzt das vollständige Thema daraus selbst zusammen: aus der aktuellen Datei und
  den Änderungen. Danach folgt dieselbe strenge Prüfung wie bisher (`RuleTopic`, beide
  Dokumente, IDs, Postfachbereiche). Die Prüfansicht (Vergleich, Hand-Edit, YAML) bleibt
  unverändert, weil sie ohnehin mit dem zusammengesetzten Thema arbeitet.
- `create` braucht `name`, `description` und Beispiele; `disable` braucht keine weiteren
  Felder. Unbekannte zu entfernende Einträge sind ein Validierungsfehler.
- Grenzen der Antwort: höchstens 10 Vorschläge, je höchstens 10 neue Einträge und
  10 Beleg-IDs, Begründung höchstens 500 Zeichen. Prompt und JSON-Schema werden angepasst
  (`prompts.yaml` und mitgelieferte Vorlage).
- Erwartete Antwortgröße: wenige hundert Tokens je Vorschlag statt mehrerer tausend.

### B3 – Eingabe verdichten

- Die Belege werden lokal nach Thema und Signal gruppiert und vorab gezählt. Dem Modell geht
  je Gruppe die Anzahl zu, dazu höchstens 5 repräsentative Belege mit gekürztem Text
  (300 statt 1000 Zeichen). Korrekturen, Relevanzabweichungen und „bereits erledigt“
  werden vollständig übertragen; sie sind die starken Signale.
- Themen ohne Belege gehen nur mit `id`, `name` und `description` hinein.
- Die Zusammenfassung zeigt „x Belege in y Gruppen übertragen“.
- Wirkung: Bei 168 Ablehnungen sinkt die Eingabe von rund 230 KB auf geschätzt 30–50 KB.

### B4 – Sinnvolle Wiederholung statt Doppelversuch

- `output_token_retry` für `decision_rule_learning` einrichten: Bei einem Abbruch folgt
  genau ein Versuch mit knapperem Prompt („höchstens 5 Vorschläge“) und halbierter
  Belegmenge. Eine identische Wiederholung entfällt.
- Reasoning begrenzen: `reasoning: {effort: low, max_tokens: 4000}`, sofern Route und
  Anbieter das unterstützen. Sonst bleibt `effort: low`; das wird beim Diagnoselauf (B1)
  geprüft.
- `max_tokens` danach auf einen begründeten Wert (voraussichtlich 8000) zurücksetzen, statt
  pauschal hoch zu lassen.

### B5 – Meldungen und Dokumentation

- Neuer Text der Fehlermeldung: „Die KI-Antwort wurde am Ausgabelimit abgeschnitten.
  Die Analyse wurde mit weniger Vorschlägen erneut versucht und ist ebenfalls gescheitert.
  Später erneut versuchen oder ‚Nur neue Entscheidungen‘ wählen.“ Den irreführenden Hinweis
  „weniger Entscheidungen wählen“ als Lösung für das Ausgabelimit gibt es nicht mehr.
- Aktualisiert werden Bedienung, Spezifikation, Konfigurationsbeispiel, CHANGELOG, README und
  der Hilfebestand.

## 4. Tests

- **Regressionen, die vor dem Fix scheitern:**
  - B1: Bei einer abgeschnittenen Antwort fehlt `usage` im Protokoll.
  - B4: Nach einem Abbruch folgt eine identische zweite Anfrage.
  - B2: Das Antwortschema verlangt vollständige Themen.
- **B2:**
  - Zusammensetzen aus Änderungen für `modify`, `create` und `disable`.
  - Entfernen nicht vorhandener Einträge, doppelte Einträge, Grenzen.
  - Postfachbereich und ID bleiben unverändert.
  - Fremde Beleg-IDs werden weiterhin abgewiesen.
- **B3:**
  - Gruppierung, Zählung und Auswahl repräsentativer Belege.
  - Starke Signale werden immer übertragen.
  - Die Nutzlastgrenze greift weiterhin.
- **B4:**
  - Genau ein verkleinerter Folgeversuch.
  - Kein Folgeversuch nach Sitzungsentzug oder Dateikonflikt.
- **Bestehendes:** Bestehende Web- und Browserprüfungen für Vergleich, Hand-Edit, YAML,
  Konflikt und Übernahme laufen unverändert weiter.
- **Pflichtprüfungen:** 100 % Zeilen- und Branch-Abdeckung, vollständiger Browserlauf.
- **Echtes Modell:** Abnahme mit einem Lauf über die realen 184 Entscheidungen, nur nach
  ausdrücklicher Freigabe. Erwartet werden eine gültige Antwort unter 8000 Ausgabetokens und
  Kosten im Centbereich.

## 5. Reihenfolge und offene Entscheidung

1. B1 umsetzen, danach ein freigegebener Diagnoselauf (klärt Reasoning oder Ausgabe).
2. B2 und B3. Sie lösen das Problem unabhängig vom Diagnoseergebnis, weil sie Aus- und
   Eingabe verkleinern.
3. B4 und B5, Abnahme mit echtem Modell.

**Offene Entscheidung:** Ob das Modell gewechselt wird (z. B. eines ohne Reasoning für diesen
einen Schritt über `model_route`), hängt vom Diagnoselauf ab. Empfehlung: zuerst B2/B3 mit
dem bisherigen Modell. Erst wenn der Diagnoselauf zeigt, dass schon das Reasoning allein das
Limit füllt, wird das Modell gewechselt.

## 6. Umsetzung

- **B1, B2, B3 und B5** sind wie geplant umgesetzt (`llm/openrouter.py`, `rule_learning/changes.py`,
  `rule_learning/service.py`, Prompts, Prüfansicht, Dokumentation).
- **B4:** Ein verkleinerter Folgeversuch (`output_token_retry`) ersetzt die identische
  Wiederholung. Wie vorhandene Folgeversuche verkleinert er `max_tokens` nicht.
- **Zurückgestellt bis zum freigegebenen Diagnoselauf:** die Begrenzung des Reasonings
  (`reasoning.max_tokens`) und die Senkung von `max_tokens` unter 16000. Ohne Messwerte aus
  dem echten Modell wäre beides geraten. Die Obergrenze kostet nur, was tatsächlich verbraucht
  wird. Ab 5.7.7 zeigt das KI-Protokoll die nötigen Werte (`completion_tokens`,
  `reasoning_tokens`).
- Noch offen ist die Abnahme mit echtem Modell über die realen Entscheidungen. Sie braucht
  eine ausdrückliche Freigabe und den Neustart des Dienstes.
