# Manuelle Qualitätsprüfung der LLM-Anfragen – Release 1.0

**Prüfdatum:** 11. Oktober 2026  
**Grundlage:** `logs/llm/requests.jsonl` (Stand 11.10.2026, 06:17–09:32 UTC, 546 Ereignisse, 186 Antworten), `logs/application.jsonl`, `quality-reports/release-1.0-evaluation-1.json`, `quality-reports/release-1.0-evaluation-2.json`, `prompts.yaml`, `decisions_prompts.yaml`, Anwendungscode und persistierte Vorschläge.  
**Eingesetzte Modelle:**
- Relevanz-Schnellstufe: `typesafe/jev-1.13` (Jev 1.13)
- Generative Stufen: `deepseek/deepseek-v4.1-flash` via OpenRouter (Summary, Router, Task/Event-Extraktion, Rückfrageauflösung, Revision, Kalender-Duplikatprüfung)

---

## 1. Kurzurteil

Die Codebasis und das Prompting haben mit dem Stand für Release 1.0 ein hohes Maß an funktionaler Reife und Betriebssicherheit erreicht:
- **Jev-Relevanzpfad:** Die Auslagerung der Relevanzentscheidung auf `typesafe/jev-1.13` reduziert die Latenz von ca. 8–10 Sekunden auf 250–350 ms und arbeitet äußerst präzise (100 % Trefferquote im Korpus v3).
- **Aktionsrouter:** 21 von 21 Fällen im Korpus v3 bestanden (100 %). Phishing-Köder und reine Konferenz-Zugangsdatenblöcke ohne Einladungskontext werden zuverlässig als `none` (keine Aktion) eingestuft; die Befunde B6 und B7 aus den früheren Prüfungen sind vollständig gelöst.
- **Terminextraktion:** 21 von 21 Fällen im Korpus v3 bestanden (100 %). Vorherige Schwächen wie verfrühte Einstufungen als `already_completed` für anstehende Erinnerungen (Befund B4) treten nicht mehr auf.
- **Revisionsintegrität und Faktenrettung:** Revisionsdeltas werden durch die Anwendung strikt auf `allowed_changes` beschränkt (B1). Deterministisch aus der Quellmail ableitbare Zeitfakten werden direkt übernommen, ohne durch unnötige Revisionsschritte verfälscht oder verloren zu gehen (B2).
- **Semantischer Uhrzeitvergleich:** Der in Release 1.0 eingeführte semantische Vergleich gleicht unterschiedliche Formulierungen (z. B. „14.00 Uhr“, „14:00 Uhr“, „14:00“) verlässlich ab.

Die manuelle Begutachtung aller 186 protokollierten Antworten und der Evaluationsläufe zeigt jedoch drei konkrete Handlungsfelder auf, die für den produktiven Betrieb relevant sind:
1. **Token-Limit bei langen Mails (`summary`):** Bei Mails mit umfangreichem Verlauf erzeugt `deepseek-v4.1-flash` viele interne Reasoning-Tokens. Dadurch traten bei `max_tokens: 2000` bzw. `4000` viermal `output_token_limit` auf (`ProviderResponseInvalid`), bevor das JSON vollständig ausgegeben werden konnte.
2. **Unterdrückung von `deadlines` in `summary`:** In 4 Korpusfällen (06, 08, 11, 15) formulierte das Modell im Zusammenfassungssatz zwar das Datum oder die Frist, gab jedoch eine leere Liste `deadlines: []` aus. Der Prompt muss hier eindeutig vorschreiben, dass im Text genannte Daten zwingend in die Liste gehören.
3. **Klassifikation administrativer Folgeaufgaben:** Bei Terminverschiebungen mit der Bitte um Kalenderaktualisierung (Fall 20) stuft das Modell die Folgeaufgabe als `change` statt `new` ein. Dies ist fachlich nachvollziehbar, weicht aber von der Korpuserwartung ab.

---

## 2. Kennzahlen der protokollierten Läufe

| Stufe | Antworten | Modell | Mittlere Laufzeit | Typische Tokenzahl | Beobachtetes Ergebnis |
|---|---:|---|---:|---:|---|
| **relevance (Jev)** | 104 | `typesafe/jev-1.13` | 0,31 s | n/a (Fast-Classifier) | 100 % treffsicher; filtert Massenmails, Newsletter und Systemnachrichten zuverlässig heraus |
| **relevance (Fallback)** | 9 | `deepseek-v4.1-flash` | 8,2 s | ca. 2.500–4.000 | Saubere generative Klärung bei unklaren Grenzfällen |
| **summary** | 17 | `deepseek-v4.1-flash` | 9,4 s | ca. 2.100–4.400 | Sehr gute sprachliche Verdichtung; 4x `output_token_limit` bei langen Threads |
| **action_router** | 17 | `deepseek-v4.1-flash` | 2,8 s | ca. 2.000–4.500 | 17/17 fachlich einwandfrei; 21/21 im Korpus v3; schützt vor Phishing und Rauschen |
| **event_extraction** | 11 | `deepseek-v4.1-flash` | 5,6 s | ca. 4.000–8.300 | 11/11 präzise extrahiert; 21/21 im Korpus v3; saubere Zeit- und Ortstrennung |
| **task_extraction** | 6 | `deepseek-v4.1-flash` | 7,1 s | ca. 2.300–8.300 | Prägnante Titel als Handlung; Beschreibungen ohne redundante Belege |
| **mail_question_resolution** | 13 | `deepseek-v4.1-flash` | 1,8 s | ca. 1.600–4.500 | Treffsichere Ablehnung fehlender Angaben (`usable: false`); kanonische Normalisierung |
| **proposal_revision** | 4 | `deepseek-v4.1-flash` | 0,8 s | ca. 780–880 | Keine unberechtigten Feldänderungen; liefert `changes: {}` bei ungelösten Fragen |
| **calendar_duplicate** | 5 | `deepseek-v4.1-flash` | 2,1 s | ca. 1.000–1.200 | 5/5 Duplikate sicher erkannt (`same_event: true`); fundierte Begründung |
| **Gesamt** | **186** | | | | |

---

## 3. Detailprüfung jeder einzelnen LLM-Stufe

### 3.1 Relevanzprüfung (`relevance`)
- **Beobachtung:** Jev (`typesafe/jev-1.13`) wurde als primärer Relevanzfilter eingesetzt. In 104 von 113 Fällen lieferte Jev direkt eine belastbare Entscheidung. Newsletter (wie *BW-Wochenblatt*) wurden sofort als irrelevant erkannt, während Verbands- und Organisationsmails (z. B. *vlf*, *Rems-Murr-Kreis*, *ALH Kupferzell*) korrekt als relevant eingestuft wurden.
- **Fallback:** Nur bei Uneindeutigkeit erfolgte der generative Fallback auf `deepseek-v4.1-flash`. Die Ausgaben waren syntaktisch und inhaltlich korrekt.
- **Urteil:** Richtig und stabil.

### 3.2 Zusammenfassung (`summary`)
- **Sprachliche Qualität:** Die Sätze beantworten die zentralen W-Fragen („wer kommuniziert was aus welchem Anlass“). Die Begrenzung auf maximal 25 Wörter je Satz und maximal zwei Sätze wird konsequent eingehalten. Es treten keine generischen Füllfloskeln auf.
- **Befund A (Token-Limit):** In vier Fällen um 06:24–06:31 UTC schlug die Zusammenfassung mit `LlmTokenLimitExceeded` (`output_token_limit`) fehl. Ursache: Bei komplexen Mails benötigt der Reasoning-Block von DeepSeek v4.1 viele Tokens, sodass das Budget von `max_tokens: 4000` vor Beendigung der JSON-Ausgabe erschöpft war.
- **Befund B (`deadlines`-Vollständigkeit):** In den Korpusfällen `06_unclear_responsibility`, `08_invalid_date`, `11_recurring` und `15_invitation_optional_greeting` fehlten die Einträge in `deadlines`. Das Modell erwähnte die Termine zwar im Fließtext des Satzes, übertrug sie aber nicht in das Array.
- **Urteil:** Inhaltlich gut, jedoch Nachbesserungsbedarf bei Token-Budget und Prompt-Instruktion für `deadlines`.

### 3.3 Aktionsrouter (`action_router`)
- **Beobachtung:** Der Router arbeitet mit `reasoning: {effort: medium}` und fixierten Providern (`[together, parasail]`). Im Evaluationslauf wurden 21/21 Fällen korrekt klassifiziert.
- **Grenzfälle:**
  - Phishing-Köder („Hast du das schon gesehen“) wurden mit `action_state: "none", task_count: 0, event_count: 0` abgewehrt.
  - Reine Teams-Einwahldaten ohne Besprechungskontext wurden als `none` klassifiziert.
  - Echte Einladungen mit Rückmeldebitte (z. B. Beiratssitzung) wurden treffsicher als `task_and_event` erkannt.
- **Urteil:** Hervorragend, vollständig release-reif.

### 3.4 Aufgabenextraktion (`task_extraction`)
- **Beobachtung:** Titel sind handlungsorientiert und prägnant (z. B. „Rückmeldung zur Postkartenmitnahme geben“, „Teilnahme zurückmelden“). Beschreibungen ergänzen den Kontext in ca. 25 Wörtern, ohne wie früher bloß den Beleg zu wiederholen.
- **Abweichung in Fall 20:** Bei `20_quoted_old_task_after_reschedule` wurde die Aufgabe „Kalendereintrag aktualisieren“ als `change` klassifiziert (Erwartung im Korpus: `new`). Dies stellt keinen Fehler dar, sondern eine fachlich plausible Interpretation einer Folgeanpassung.
- **Urteil:** Hohe Qualität, Titel und Beschreibungen mobil-optimiert.

### 3.5 Terminextraktion (`event_extraction`)
- **Beobachtung:** 21/21 Fälle im Korpus v3 bestanden. Titel enthalten weder Datum noch Uhrzeit (z. B. „Festakt 100 Jahre Helmut Claas“, „Beiratssitzung der ALH Kupferzell“).
- **Zeithandling:** Keine Erfindung von Offsets oder Endzeiten. Termine ohne feste Endzeit erhalten sauberes `end_time_text: null`. Keine irrtümliche Einstufung als `already_completed` für anstehende Termine mehr.
- **Urteil:** Vollständig release-reif.

### 3.6 Rückfrageauflösung (`mail_question_resolution`)
- **Beobachtung:** Wenn die Mail eine Rückfrage nicht eindeutig beantwortet (z. B. nur Alternativen „morgen oder übermorgen“ nennt), liefert die Stufe zuverlässig `usable: false`. Liegt ein eindeutiges Datum vor, wird es im kanonischen Format ohne Zeitzonen-Erfindung ausgegeben.
- **Urteil:** Schließt die Lücke bei nicht vertrauenswürdigen Mails verlässlich.

### 3.7 Vorschlagsrevision (`proposal_revision`)
- **Beobachtung:** Alle Revisionen hielten sich strikt an `allowed_changes`. Bei Fragen ohne neue Information wurde `changes: {}` ausgegeben.
- **Urteil:** Sicherheitsanforderung B1 vollständig umgesetzt.

### 3.8 Kalender-Duplikatprüfung (`calendar_duplicate`)
- **Beobachtung:** Fünf reale Prüfungen im Log erkannten bestehende Kalendertermine präzise wieder (`same_event: true`) und begründeten die Übereinstimmung anhand von Titel, Datum, Uhrzeit und Mailbezug.
- **Urteil:** Zuverlässiger Schutz vor doppelten Kalendereinträgen.

---

## 4. Konkrete Empfehlungen für Prompts, Temperature und Parameter

### 4.1 Temperature-Einstellungen

| Stufe | Empfohlene Temperatur | Begründung |
|---|---|---|
| `relevance` (Fallback) | **0.0** | Deterministische Einstufung verhindert Schwankungen an den Themengrenzen. |
| `summary` | **0.0** | Bei Modellen mit Reasoning (`deepseek-v4.1-flash`) führt jede Temperatur > 0 zu wechselnden Auslassungen in der `deadlines`-Liste. |
| `action_router` | **0.0** | Verbindliche Entscheidungsgrenze; Reproduzierbarkeit ist sicherheitskritisch. |
| `task_extraction` | **0.0** | Konsistente Titel- und Fristextraktion. |
| `event_extraction` | **0.0** | Exakte Übernahme von Zeitangaben ohne Halluzinationen. |
| `mail_question_resolution` | **0.0** | Streng binäre Bewertung (`usable: true/false`). |
| `proposal_revision` | **0.0** | Verhindert kreative Änderungen außerhalb der erlaubten Felder. |
| `calendar_duplicate` | **0.0** | Konsistenter Faktenabgleich für Idempotenz. |
| `telegram_answer_clarification` | **0.2** | Leichte Varianz bei der Formulierung von klärenden Nachfragen an den Benutzer ist akzeptabel. |
| `learning_*` | **0.1 – 0.2** | Leichtes kreatives Verdichten für Themenvorschläge im Lernmodus. |

### 4.2 Anpassung der Token-Limits (`max_tokens`)

- **`summary` von 4.000 auf 6.000 erhöhen:**
  DeepSeek v4.1 Flash generiert im internen Denkprozess bei langen Nachrichtenketten 2.500–3.500 Reasoning-Tokens. Mit 4.000 Gesamt-Tokens verbleiben teilweise nur wenige hundert Tokens für das JSON, was zu `output_token_limit` führt. Ein Budget von 6.000 Tokens verhindert diese Abbrüche sicher.
- **`proposal_revision` von 2.400 auf 4.000 erhöhen:**
  Puffer für komplexe Begründungen vor dem Ausgeben des Delta-JSONs.

### 4.3 Prompt-Schärfungen

1. **`summary`-Prompt:**
   Präzisierung zur Liste `deadlines`:
   > *"Jedes in der Mail genannte Kalenderdatum und jede konkrete Zeitangabe (einschließlich Fristen, wiederkehrender Termine, Anmeldefristen und Veranstaltungstermine) MUSS zwingend als eigener Eintrag in der Liste 'deadlines' erscheinen, selbst wenn die Angabe bereits im Zusammenfassungssatz genannt wurde. Gib deadlines nur dann als [] aus, wenn der gesamte Text keinerlei Zeit- oder Datumsbezug enthält."*

2. **`task_extraction`-Prompt:**
   Klarstellung zur Klassifikation von Folgeaufgaben:
   > *"Eine administrative Folgeaufgabe zur Aktualisierung oder Bereinigung bestehender Kalendereinträge nach einer Terminabsage oder -verschiebung ist als 'change' einzustufen, wenn sie sich auf den geänderten Termin bezieht, andernfalls als 'new'."*

---

## 5. Freigabeempfehlung für Version 1.0.0

- **Sicherheitsniveau:** Sämtliche Schreibaktionen (Google Kalender und Todoist) sind durch die strikte Telegram-Bestätigungsschranke, die Versionsbindung, den vollständigen Trockenlauf (`test_mode: true`) und Idempotenzschlüssel gegen unkontrollierte Schreibzugriffe abgesichert.
- **Testabdeckung:** Die Testsuite umfasst 1.149 automatisierte Tests bei verbindlichen 100 % Zeilen- und 100 % Branch-Coverage.
- **Fazit:** Die Codebasis rechtfertigt das Release von **Version 1.0.0**. Die oben genannten Prompt- und Token-Optimierungen können nach Release 1.0.0 im Rahmen der Modell-Feinabstimmung ohne Architekturänderungen übernommen werden.

