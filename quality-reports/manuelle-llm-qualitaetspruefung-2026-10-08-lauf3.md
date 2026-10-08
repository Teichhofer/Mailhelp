# Manuelle Qualitätsprüfung der LLM-Anfragen – Lauf 3

**Prüfdatum:** 8. Oktober 2026
**Grundlage:** `logs/llm/requests.jsonl` (Lauf 09:59:14–10:12:07 UTC, 688 Ereignisse, 172 Aufrufe), `prompts.yaml` in Commit `42203a1` (09:57 UTC, unverändert im Arbeitsstand), `logs/application.jsonl`, gespeicherte Vorschläge in `data/production`, Anwendungscode
**Methode:** Lauf 3 verarbeitet dieselben 19 relevanten Mails wie Lauf 2. Deshalb wurden alle Stufenausgaben je Mail direkt mit Lauf 2 verglichen. Grundlage für Lauf 2 sind die vollständigen Aufbereitungen aus der vorigen Prüfung; das Rohlog wurde durch den neuen Lauf überschrieben. Zusätzlich wurden die resultierenden Vorschläge in `data/production` und die Orchestrator-Ereignisse geprüft. Es wurden keine Prompts oder Laufzeitdateien geändert.
**Vorgänger:** [Lauf 2](manuelle-llm-qualitaetspruefung-2026-10-08-lauf2.md). Dessen Befunde K1–N2 werden hier nur noch mit ihrem Status aufgeführt.

## Kurzurteil

Die Änderungen aus `42203a1` wirken genau dort, wo sie ansetzen:
- Alle vier Kalendererinnerungen liefern jetzt `timezone_offset_text: null`.
- Der gespeicherte Vorschlag steht korrekt auf `2026-10-07T13:00:00+02:00`, nicht mehr auf 14:00 Uhr. K1 ist von der Extraktion bis zum Vorschlag behoben.
- Bei der Verschiebung „in den Nachmittag“ übernimmt die Terminextraktion nicht mehr die aufgehobene Uhrzeit 11:45–12:30.

Der Lauf zeigt aber vier Probleme, die schwerer wiegen als die Promptformulierungen:

1. **Revisionen dürfen Felder außerhalb von `allowed_changes` ändern (Anwendungsfehler).** Die Revision zu „Welches konkrete Datum ist mit ‚Morgen oder am Mittwoch‘ gemeint?“ (nur `start`, `end`, `all_day` erlaubt) lieferte `{"responsibility":"unclear"}`. Die Anwendung hat das übernommen. Version 2 des Vorschlags hat danach fünf offene Fragen, darunter eine neue Zuständigkeitsfrage.
2. **Gelöste Zeitangaben gehen verloren, die Frage gilt trotzdem als erledigt.** In 4 von 7 Revisionen wurde nichts geändert. Der Orchestrator protokolliert dennoch `mail_question_resolved`. Die aus der Mail gewonnenen Angaben (Datum 07.10.2026, Uhrzeit 13:00, Datum 02.10.2026) stehen in keinem gespeicherten Vorschlag. Stattdessen wird der Nutzer allgemein „Wann beginnt der Termin?“ gefragt.
3. **Die Ergebnisse sind nicht reproduzierbar.** Bei 9 der 19 relevanten Mails weicht mindestens ein fachlich wirksames Ergebnis von Lauf 2 ab, obwohl Router- und Aufgabenprompt Wort für Wort gleich geblieben sind und `temperature` 0 ist. Allein der Router entscheidet bei 5 Mails anders. Ursache ist das freie OpenRouter-Provider-Routing: In Lauf 3 kamen zusätzlich Friendli (40 Aufrufe) und Fireworks (11) zum Einsatz.
4. **K2 (Phishing) ist unverändert offen.** Der Router stuft die Spam-Mail jetzt sogar als `task` ein. Sein Reasoning lautet wörtlich: „likely spam; still, per rules, a concrete request = task.“ Das Modell erkennt den Spam und folgt trotzdem dem Prompt, weil die Ausnahme fehlt.

## Kennzahlen

| Stufe | Aufrufe L3 | Prompt-Tokens | Kosten (USD) | Schema ok | Δ zu Lauf 2 |
|---|---:|---:|---:|---:|---|
| relevance | 93 | 288.392 | 0,0383 | 93/93 | gleiche Entscheidungen bei allen gemeinsamen Mails; bei 4 Mails andere `topic_ids` |
| summary | 19 | 34.360 | 0,0058 | 19/19 | `deadlines` jetzt immer vorhanden |
| action_router | 19 | 39.699 | 0,0065 | 19/19 | 5 von 19 andere Entscheidungen bei identischem Prompt |
| task_extraction | 6 | 11.313 | 0,0026 | 6/6 | 4 von 6 andere Ergebnisse |
| event_extraction | 11 | 29.207 | 0,0057 | 11/11 | Offset 4/4 korrekt null; neue Fehlklassifikation `already_completed` |
| mail_question_resolution | 16 | 23.597 | 0,0041 | 16/16 | 7 von 16 weiter Meta-/Hinweisfragen |
| proposal_revision | 8 | 4.747 | 0,0012 | 6/8 | 2 Schemafehler (beide Friendli); 4 Revisionen ohne Wirkung; 1 unerlaubte Feldänderung übernommen |
| **Summe** | **172** | **431.315** | **0,0641** | **170/172** | |

Provider in Lauf 3: Together 86, Friendli 40, OpenInference 19, Parasail 16, Fireworks 11. In Lauf 2 waren es Together 77, Parasail 72, OpenInference 16, Sail Research 8.

## Status der Befunde aus Lauf 2

| Befund | Status in Lauf 3 | Beleg |
|---|---|---|
| K1 Zeitzonenbezeichnung als Offset | **behoben** | 4/4 Erinnerungen `tz=null`; Vorschlag e02f `13:00+02:00` |
| K2 Phishing → Aufgabe | **offen, schlechter** | Router `task` statt `unclear`; Aufgabe „Verlinkte Seite anschauen und testen“ `user/certain/new` |
| K3 Zeitrevision ohne Offset | **offen, Folgeschaden belegt** | siehe B2 |
| H1 Nutzeridentität fehlt | **offen, als Ursache für Schwankungen belegt** | fb2a: Aufgabe für Daniela jetzt `user` statt `other`; e6ed: Newsletter-Weiterleitung jetzt `unclear` statt `user` |
| H2 Kalendererinnerungen | entschieden: Vorschläge bleiben; vergangene Termine weiterhin offen | — |
| H3 zitierte Teile / alte Zeiten | **teilweise behoben** | 9cb2: keine alte Uhrzeit mehr; `evidence` mit „…“ weiterhin bei 030a, 199e, 5c1c |
| H4 Floskel-Aufgabe | zufällig nicht aufgetreten | 9cb2: Router (Friendli) ohne Aufgabe, gleicher Prompt wie in Lauf 2 |
| M1 Meta-Fragen an Rückfrageauflösung | **offen** | 7 von 16 Aufrufen |
| M2 unverbindliche Terminabsprachen | **offen** | 30da: jetzt Aufgabe „Kurze Videokonferenz …“ `certain/new`; b39c: Event „Morgen oder am Mittwoch“ |
| M3 Zusammenfassungen | teilweise besser | kein reiner Anhangssatz mehr; Nutzer weiter in 3. Person („Herr Hartmann wird … gebeten“); 50e6 weiter falsche Zuordnung |
| N1/N2 | offen | Provider-Effekte stärker als in Lauf 2, siehe B3 |

## Neue Befunde

### B1 – Kritisch (Anwendung): `allowed_changes` wird bei der Revision nicht durchgesetzt

**Beobachtung (Mail b39cc458, Vorschlag `p_f4f42a71…`).**
- Frage: „Welches konkrete Datum ist mit ‚Morgen oder am Mittwoch‘ gemeint?“, `allowed_changes: ["start","end","all_day"]`.
- Antwort von Friendli: `{"changes":{"responsibility":"unclear"}}`.
- Die Anwendung protokolliert `proposal_revision_delta_applied`.
- Die gespeicherte Version 2 hat `responsibility: "unclear"` und die zusätzliche offene Frage „Ist die Nutzerin oder der Nutzer für diesen Eintrag zuständig?“.

Derselbe Provider versuchte bei 9cb2 zweimal `{"responsibility":"user", "start":…, "all_day":true}`. Dort scheiterte die Antwort nur zufällig an einer anderen Regel (Ende nicht nach Beginn).

**Ursache.** In [analysis.py](../src/mailhelp/analysis.py) (`revise_proposal` → `validate_delta`) wird das Delta gegen `ProposalRevisionDelta` validiert. Dieses Schema erlaubt alle Geschäftsfelder. Die Liste `allowed` steuert nur, welchen Kontext das Modell sieht. Gegen das Ergebnis wird sie nicht geprüft.

**Bewertung.** Das widerspricht der Projektregel, LLM-Ausgaben als nicht vertrauenswürdig zu behandeln. Ein Modell kann so bei jeder Rückfrage Zuständigkeit, Sicherheit, Klassifikation, Titel oder Ziel verändern. Eine Promptregel allein schützt dagegen nicht.

**Empfehlung (Anwendung, mit Regressionstest):** In `validate_delta` jedes gesetzte Feld in `delta.changes` außerhalb von `allowed` als Validierungsfehler behandeln. Der Fehler geht damit in die vorhandene Reparaturschleife, statt übernommen zu werden. Zusätzlich das Antwortschema je Aufruf auf `allowed` einschränken (`json_schema` mit nur den erlaubten Eigenschaften), damit strikte Provider unerlaubte Felder schon beim Erzeugen ausschließen.

**Ergänzend im Prompt `proposal_revision`:**

> changes enthält ausschließlich Felder aus allowed_changes. Andere Felder wie responsibility, certainty, classification, title oder target darfst du nie ausgeben, auch wenn die Antwort dazu Hinweise enthält. Wenn die Antwort keine Änderung an einem erlaubten Feld ermöglicht, gib "changes": {} aus.

### B2 – Hoch (Anwendung + Prompt): Gelöste Rückfragen ohne Wirkung werden als erledigt markiert, die Information geht verloren

**Beobachtung (gespeicherte Vorschläge nach dem Lauf):**

| Mail | Aus der Mail gelöst | Revision | gespeicherter Vorschlag |
|---|---|---|---|
| 29c0f8df Skype-Termin | Uhrzeit „13:00“ und Beginn „2026-10-07T13:00:00+02:00“ | 2× `changes: {}`, 2× `mail_question_resolved` | v3: `start: null`; offene Fragen „Wann endet der Termin?“, „Wann beginnt der Termin?“ |
| 030a20e4 Verschiebung | Datum „morgen“ = 2026-10-07 | `changes: {}`, `mail_question_resolved` | v2: `temporal_fact.normalized_date: null`; offene Fragen u. a. „Wann beginnt der Termin?“ |
| 5c1c7fe1 Treffen Freitag 8 Uhr | Datum „kommenden Freitag“ = 2026-10-02, Uhrzeit 08:00 bekannt | `changes: {}`, `mail_question_resolved` | v2: `normalized_date: null`, nur `start_time 08:00` |
| 9cb2b16b Verschiebung | Datum „morgen“ = 2026-10-07 | 1× `changes: {}`, dann 2× Schemafehler | `schema_validation_failed` für die ganze Mail |

Der Nutzer muss damit Angaben, die bereits eindeutig aus der Mail gelesen wurden, erneut und vollständiger eingeben: Statt „Ist 13:00 korrekt?“ fragt Mailhelp „Wann beginnt der Termin?“. Das ist der in Lauf 2 als K3 vorhergesagte Folgeschaden, jetzt anhand der Daten belegt.

**Ursache.**
- `proposal_revision` darf ohne vertrauenswürdigen Offset keinen Zeitpunkt bilden. `user_timezone` wird nicht übergeben, und `temporal_fact` ist schreibgeschützt.
- Der Orchestrator wertet eine erfolgreiche, aber leere Revision trotzdem als gelöste Frage.

**Empfehlung (Anwendung, Reihenfolge):**
1. Antworten von `mail_question_resolution` auf Datums- und Uhrzeitfragen deterministisch übernehmen, ohne `proposal_revision`. Datum, Uhrzeit und `user_timezone` werden per `zoneinfo` zu einem Zeitpunkt; ein gelöstes Datum wird als `temporal_fact.normalized_date` bzw. `known_temporal_facts` gespeichert. Der deterministische Parser für Telegram-Antworten existiert bereits.
2. `mail_question_resolved` nur protokollieren, wenn die betroffene Frage danach tatsächlich nicht mehr offen ist. Sonst `mail_question_unanswered` mit dem Grund `revision_without_effect`.
3. Fällt die Revision in die Schemareparatur (9cb2), darf das nicht die gesamte Mail mit `schema_validation_failed` beenden. Die Frage bleibt dann einfach für Telegram offen.

**Prompt `mail_question_resolution`** (unverändert gültig aus Lauf 2, Befund K3): einheitliche lokale Formate ohne Offset, z. B. „JJJJ-MM-TT HH:MM“. In Lauf 3 kam wieder `2026-10-07T13:00:00+02:00` mit einem Offset aus Weltwissen.

### B3 – Hoch (Konfiguration): Provider-Routing macht die Ergebnisse nicht reproduzierbar

**Beobachtung.** Router- und Aufgabenprompt sind zwischen Lauf 2 und Lauf 3 identisch, `temperature` ist 0, die Mails sind dieselben. Trotzdem weichen fachlich wirksame Ergebnisse ab:

| Mail | Lauf 2 | Lauf 3 | Provider L2 → L3 |
|---|---|---|---|
| 9cb2 Verschiebung | Router `task_and_event` (Floskel-Aufgabe) | `event` | Parasail → Friendli |
| 29b8 Teams-Block | `none` | `unclear`, 0/0 | Parasail → Fireworks |
| 30da Videokonferenz-Vorschlag | `unclear`, Event | `unclear`, Aufgabe `certain/new` | Together → Together |
| b39c Videokonferenz-Vorschlag | `unclear`, t=1 | `unclear`, t=1 e=1 (zählt die erwähnte Mitgliederversammlung mit) | OpenInference → OpenInference |
| 8ffd Phishing | `unclear` | `task` | Parasail → Friendli |
| fb2a Postkarten an Daniela | Aufgabe `other/certain` | Aufgabe `user/uncertain`, Frist 02.11. | Parasail → Together |
| e6ed Newsletter weiterleiten | Aufgabe `user` | Aufgabe `unclear` → Zuständigkeitsfrage | Parasail → Together |
| e02f Erinnerung 13:00 | Event `new` | Event `already_completed` | Together → Together |
| 27b8 Jour Fixe | Event `recurring` | Event `new` | OpenInference → OpenInference |

Auch bei gleichem Providernamen schwanken die Ergebnisse (30da, b39c, e02f). Die Grenzfälle sind im Prompt also nicht eindeutig genug geregelt, und das Modell entscheidet sie zufällig. Wechselnde Provider verstärken das.

**Empfehlungen:**
- **Provider fixieren** für die entscheidungsrelevanten Stufen (`action_router`, `task_extraction`, `event_extraction`, `proposal_revision`) über die vorhandenen `routes` in `prompts.yaml`:

  ```yaml
  action_router:
    routes:
      - provider: openrouter
        model: z-ai/glm-5.3-flash
        parameters: {temperature: 0.0, max_tokens: 10000, reasoning: {effort: medium}}
        provider_preferences:
          order: [Together, Parasail]
          allow_fallbacks: false
          require_parameters: true
  ```

  Welche Provider fixiert werden, sollte eine mehrfache Korpus-Auswertung je Provider entscheiden. Friendli fiel in diesem Lauf mit beiden Schemafehlern und der unerlaubten Feldänderung auf.
- **Grenzfälle schärfen**, die in der Tabelle schwanken: Regeln aus Lauf 2 zu H1 (Zuständigkeit), H4 (Floskeln), M2 (unverbindliche Abstimmung) und K2 (Phishing) umsetzen. Erst dann hat der Router eindeutige Kriterien statt einer Ermessensentscheidung.
- **Qualitätsmessung** künftig mit mindestens drei Wiederholungen je Korpusfall und Ausweis der Übereinstimmungsquote. Ein einzelner Lauf zeigt keine Verbesserung.

### B4 – Mittel (Prompt): `already_completed` für eine bevorstehende Erinnerung

**Beobachtung (e02fa30f).** Die Erinnerung wurde am 07.10. um 10:30 UTC (12:30 Uhr MESZ) verschickt, der Termin beginnt um 13:00 Uhr. Die Extraktion klassifiziert `already_completed`. Folge: Der Vorschlag ist blockiert mit dem Hinweis „Der Eintrag ist bereits abgeschlossen und nicht direkt ausführbar.“, und dieser Hinweistext geht zusätzlich als „Frage“ an die Rückfrageauflösung.

**Ursache.** Der Prompt sagt „already_completed nur für vergangene oder ausdrücklich erledigte Termine“, legt aber keinen Bezugszeitpunkt fest. Das Modell hat vermutlich den Verarbeitungszeitpunkt oder eigenes Weltwissen herangezogen.

**Vorschlag für `event_extraction`** (ersetzt den Teilsatz zu `already_completed`):

> "already_completed" gilt nur, wenn die Mail selbst ausdrücklich sagt, dass der Termin bereits stattgefunden hat oder erledigt ist („hat stattgefunden“, „danke für die Teilnahme gestern“). Beurteile nicht selbst, ob ein Termin in der Vergangenheit liegt; das entscheidet die Anwendung anhand von Mail-Datum und Verarbeitungszeitpunkt. Einladungen, Erinnerungen, Bestätigungen und Verschiebungen sind nie "already_completed".

Die Anwendung entscheidet „vergangen“ deterministisch (Befund H2 aus Lauf 2).

### B5 – Mittel (Prompt): Rückfrageauflösung akzeptiert Alternativen als eindeutige Antwort

**Beobachtung (b39cc458).** Auf „Welches konkrete Datum ist mit ‚Morgen oder am Mittwoch‘ gemeint?“ antwortete die Stufe `usable: true`, `normalized_answer: "06.10.2026 oder 07.10.2026"`. In Lauf 2 wurde dieselbe Frage zu einer anderen Mail korrekt mit `usable: false` beantwortet („nennt nur zwei Alternativen“).

**Vorschlag für `mail_question_resolution`:**

> usable=true verlangt genau einen Wert. Nennt die Mail mehrere Alternativen, eine Spanne möglicher Tage oder eine noch offene Auswahl („morgen oder Mittwoch“, „an beiden Tagen nachmittags“), liefere usable=false und nenne die Alternativen in reason.

### B6 – Niedrig (Prompt): `unclear` ohne Kandidat

**Beobachtung (29b841a5, Fireworks).** Für einen reinen Teams-Zugangsdatenblock liefert der Router `action_state: "unclear"` mit `task_count: 0, event_count: 0`. Die Anwendung sendet bei `unclear` den Hinweis „Mögliche Aufgabe oder möglicher Termin benötigt fachliche Klärung: …“. Das ist Rauschen ohne Handlungsmöglichkeit.

**Vorschlag für `action_router`:**

> Verwende "unclear" nur, wenn mindestens ein möglicher Aufgaben- oder Terminkandidat besteht (task_count oder event_count größer 0). Ohne jeden Kandidaten ist die Antwort "none", auch wenn die Mail unvollständig wirkt.

### B7 – Niedrig (Prompt): Router zählt Erwähnungen statt Einladungen

**Beobachtung (b39cc458, Lauf 3).** Der Router zählt „Mitgliederversammlung am 17.10.“ als Event. Die Mail erwähnt nur, dass eine dritte Person dort etwas besprechen wollte. Die neue Regel zu zitierten Teilen steht nur in `event_extraction`; der Router hat dieselbe Grenze nur für Aufgaben.

**Vorschlag für `action_router`:** Den neuen Absatz aus `event_extraction` sinngemäß übernehmen und ergänzen:

> Die bloße Erwähnung einer Veranstaltung, bei der andere Personen etwas besprechen wollen, ist ohne Einladung, Bestätigung oder ausdrücklichen Bezug zur nutzenden Person kein Terminkandidat.

## Konsolidierte Promptänderungen (Stand nach Lauf 3)

Weiterhin gelten alle Vorschläge aus Lauf 2 außer K1. Neu oder präzisiert:

| Stufe | Änderung | Befund |
|---|---|---|
| relevance | Spam-/Phishing-Regel mit Beispiel | K2 (L2) |
| action_router | Phishing-Ausnahme; `unclear` nur mit Kandidat; Erwähnung ≠ Einladung; Regeln zu Floskeln, unverbindlichen Abstimmungen und Identität | K2, B6, B7, H4, M2, H1 |
| task_extraction | Phishing-Ausnahme; Titel als Handlung; `due_text` nur echte Frist | K2, H4 |
| event_extraction | `already_completed` nur bei ausdrücklicher Aussage der Mail; `evidence` als ein wörtlicher Abschnitt ohne „…“ | B4, H3 |
| mail_question_resolution | genau ein Wert für `usable=true`; lokale Formate ohne Offset | B5, K3 |
| proposal_revision | ausdrückliches Verbot von Feldern außerhalb `allowed_changes` (nur ergänzend zu B1) | B1 |

## Voraussetzungen in der Anwendung (priorisiert)

1. **B1:** Felder außerhalb von `allowed_changes` in `validate_delta` ablehnen; Antwortschema je Aufruf auf `allowed_changes` beschränken. Regressionstest: Delta `{"responsibility":"unclear"}` bei erlaubten Zeitfeldern führt zur Reparatur oder Ablehnung, nie zur Übernahme.
2. **B2/K3:** Datum und Uhrzeit aus der Rückfrageauflösung deterministisch übernehmen; `mail_question_resolved` nur bei tatsächlich geschlossener Frage; Revisionsfehler nicht auf die ganze Mail ausweiten. Regressionstest: Mail „morgen (07.10.2026) um 13.00 Uhr“ ergibt `start = 2026-10-07T13:00:00+02:00` ohne Telegram-Rückfrage zum Beginn.
3. **B3:** Provider-Präferenzen für entscheidungsrelevante Stufen setzen und Korpus mehrfach je Provider auswerten.
4. **K2:** Kurzlink- und Phishing-Vorprüfung (aus Lauf 2).
5. **H1:** `user_profile` → `recipient_context`, `to`/`cc` im Payload (aus Lauf 2; Freigabe durch den Nutzer liegt vor).
6. **M1:** Nur Sachfragen an `mail_question_resolution`; Hinweise wie „Der Eintrag ist bereits abgeschlossen …“ nie als Frage behandeln.
7. **H2:** Vergangene Termine nicht zur Bestätigung vorlegen; Erinnerungen bleiben laut Entscheidung Vorschläge.

## Zusätzliche Regressionstests (synthetisch)

| Nr. | Stufe | Eingabe | Erwartung |
|---|---|---|---|
| 20 | Anwendung | Revisionsdelta mit nicht erlaubtem Feld | Ablehnung bzw. Reparatur, Vorschlag unverändert |
| 21 | Anwendung | `changes: {}` auf eine Datumsfrage | Frage bleibt offen, kein `mail_question_resolved` |
| 22 | Anwendung | Rückfrageauflösung „2026-10-07“ + bekannte Startzeit 08:00 | `start = 2026-10-07T08:00:00+02:00` |
| 23 | event_extraction | Erinnerung 12:30 Uhr verschickt, Termin 13:00 Uhr | nicht `already_completed` |
| 24 | mail_question_resolution | „Gerne morgen oder am Mittwoch“ | `usable: false` |
| 25 | action_router | nur Teams-Zugangsdaten | `none` (nicht `unclear` mit 0/0) |
| 26 | action_router | Phishing-Mail aus Lauf 2 (synthetisch nachgebildet) | `none` |
| 27 | Korpus | je Fall 3 Wiederholungen je fixiertem Provider | Übereinstimmung ≥ 95 % bei Router-Entscheidung |

## Priorisierte Reihenfolge

1. B1 (Integrität der Revision) – kleiner Codeeingriff, schließt eine echte Lücke bei nicht vertrauenswürdiger LLM-Ausgabe.
2. B2/K3 (deterministische Zeitübernahme) – beseitigt den größten Nutzen-Verlust: korrekt gelesene Termine werden heute erneut erfragt.
3. K2 (Phishing) – Prompt und Vorprüfung.
4. B3 (Provider fixieren und mehrfach messen) – Voraussetzung, damit weitere Promptänderungen überhaupt messbar werden.
5. H1, B4–B7, M1, M2 – Grenzfälle schärfen, danach erneut mit mehreren Läufen prüfen.
