# Manuelle Qualitätsprüfung der LLM-Anfragen

**Prüfdatum:** 8. Oktober 2026  
**Grundlage:** `logs/llm/requests.jsonl`, `prompts.yaml`, `topics.yaml`, `irrelevant_topics.yaml`  
**Ziel:** Beobachtete Ausgaben des protokollierten Laufs manuell bewerten und daraus konkrete Prompt-Verbesserungen ableiten. Es wurden keine Prompts oder Laufzeitdateien geändert.

## Kurzurteil

Die Ausgabeformate sind in diesem Lauf technisch sehr stabil: Für alle 163 empfangenen Antworten ist eine erfolgreiche Schema-Validierung protokolliert. Die wesentlichen Risiken liegen nicht im JSON-Format, sondern in der fachlichen Übereinstimmung zwischen den Prompt-Stufen. Besonders kritisch ist die Terminrevision: Beide beobachteten Antworten ergänzen einen UTC-Offset, obwohl die Revisionseingabe keinen Zeitzonenfakt enthält. In einem Fall widerspricht `+00:00` sogar dem im ursprünglichen Termin genannten `UTC+01:00`.

Die Relevanzprüfung wirkt in den sichtbaren Beispielen gut gegen irrelevante Werbung, Paket- und Plattformbenachrichtigungen abgegrenzt. Die Prüfstichprobe reicht jedoch nicht für eine vollständige Präzisions- oder Recall-Aussage. Bei Aufgaben und Terminen zeigen fünf konkret abgeglichene Nachrichten Abweichungen zwischen Router und Extraktion: viermal zählt der Router einen möglichen Termin, obwohl die Extraktion eine leere Eventliste liefert; einmal zählt die Aufgabenextraktion zwei Kandidaten, obwohl der Router einen meldet.

## Umfang und Aussagekraft

Der Logzeitraum reicht von **05:46:04 bis 05:52:08 UTC**. Er enthält 656 JSONL-Ereignisse, davon 165 gestartete Requests, 163 empfangene Antworten und zwei explizite Request-Fehler. Die 163 Antworten verteilen sich wie folgt:

| Prompt-Stufe | Antworten | Mittlere Prompt-Tokens | Mittlere Laufzeit | Beobachtete Provider |
|---|---:|---:|---:|---|
| Relevanz | 94 | 2.977 | 1,9 s | Together, Sail Research, Friendli, Parasail |
| Aktionsrouter | 18 | 1.823 | 2,5 s | Together, Friendli, Sail Research |
| Zusammenfassung | 18 | 1.801 | 1,3 s | Together, Sail Research, Friendli |
| Terminextraktion | 13 | 2.231 | 3,3 s | Together, Parasail, Friendli |
| Aufgabenextraktion | 6 | 2.171 | 4,2 s | Together, Sail Research |
| Rückfrageauflösung | 12 | 1.579 | 1,8 s | Together, Parasail, Friendli |
| Vorschlagsrevision | 2 | 436 | 2,8 s | Together |

Die 94 Relevanzantworten beziehen sich auf 94 unterschiedliche interne Mail-IDs. Die Stufen nach der Relevanzprüfung wurden nur für einen Teil dieser Nachrichten aufgerufen. Die Messung ist daher eine manuelle Stichprobe der tatsächlich angeforderten Modellschritte und kein unabhängiger Goldstandard für alle bis zu 100 vom CLI-Lauf verarbeiteten Mails.

Die beiden fehlgeschlagenen Requests sind als `PermanentError: Permanente Adapterantwort` protokolliert: einer bei `event_extraction`, einer bei `proposal_revision`. Für diese Requests gibt es keine LLM-Antwort, deren Promptqualität bewertet werden könnte. Das sind zunächst Provider-/Adapterfehler, keine nachgewiesenen Promptfehler.

Die Provider-Auswahl wechselt innerhalb desselben Modellnamens. Da in diesem Lauf kaum identische Eingaben kontrolliert über mehrere Provider geschickt wurden, lässt sich daraus keine belastbare Provider-Rangfolge ableiten. Die angegebenen Token- und Laufzeitwerte sind Log-Messwerte, keine Qualitätswerte.

## Was gut funktioniert

- **Strukturtreue:** Alle 163 `response_received`-Antworten haben anschließend `schema_validation_succeeded`. Das JSON-Schema und die geschlossenen Feldvorgaben sollten beibehalten werden.
- **Irrelevanz bei klarer Massenkommunikation:** Mehrere Werbe- und Newsletter-Mails, automatische Paketmeldungen, Plattformbenachrichtigungen und Rechnungs-/Statusmails wurden mit `irrelevant` und `topic_ids: []` bewertet. Die Begründungen beziehen sich auf den Inhalt und nicht nur auf einzelne Schlüsselwörter.
- **Schutz vor Mail-Instruktionen:** In den geprüften Fällen mit eingebetteten Aufforderungen, Regeln zu ignorieren oder ein vollständiges Proposal auszugeben, blieben die Antworten im geforderten Schema. Die Aufgabenextraktion hat allerdings im Antwortketten-Fall trotzdem eine historische Bitte als zusätzliche aktuelle Aufgabe behandelt; das ist ein Abgrenzungsproblem, kein beobachteter Prompt-Injection-Erfolg.
- **Zusammenfassungen:** Die geprüften Erinnerungen und Einladungen wurden in ein bis zwei knappen Sätzen wiedergegeben. Ausdrückliche Veranstaltungstermine erschienen in den `deadlines`-Listen. Die beobachteten Beispiele liefern keinen ausreichend sicheren Beleg für einen generellen Zusammenfassungsfehler.
- **Rückfrageauflösung:** Bei fehlender Endzeit und bei einer Meta-Frage zur Belegbarkeit wurde korrekt `usable: false` geliefert. Eine ausdrücklich genannte Beginnzeit wurde als `16:00` beziehungsweise `13:00` normalisiert, ohne eine Endzeit zu erfinden.

## Befunde mit Handlungsbedarf

### 1. Kritisch: Terminrevision erfindet einen UTC-Offset

Beide `proposal_revision`-Antworten erzeugen einen vollständigen Zeitstempel mit UTC-Offset, obwohl die Eingabe der Revisionsstufe nur die offene Uhrzeit, das bekannte Datum und Proposal-Felder enthielt. Die Antworten lauten sinngemäß:

- Datum `2026-10-07` plus `16:00` wurde zu `2026-10-07T16:00:00+00:00`.
- Datum `2026-10-07` plus `13:00` wurde zu `2026-10-07T13:00:00Z`.

Der erste Ursprungstermin enthält ausdrücklich `UTC+01:00`. Dieser Fakt wurde der Vorschlagsrevision nicht als bekannter Zeitfakt übergeben. Das Ergebnis verschiebt den Termin bei Interpretation als Zeitpunkt um eine Stunde. Die aktuelle Promptregel verlangt zwar einen eindeutigen Offset, sagt aber nicht ausdrücklich, dass ein fehlender Offset niemals mit UTC aufgefüllt werden darf. Ein Formatgebot allein veranlasst das Modell hier offenbar zum Erfinden.

**Vorschlag für `proposal_revision`:**

> Ergänze niemals einen UTC-Offset, der nicht in den getrennt übergebenen vertrauenswürdigen Zeitfakten, der ausdrücklich zitierten Mail oder einer autoritativen Nutzerzeitzone enthalten ist. `Z` und `+00:00` bedeuten UTC und sind keine neutralen Platzhalter. Übernimm einen explizit bekannten Offset unverändert. Wenn die Frage nur eine lokale Uhrzeit beantwortet und kein autoritativer Offset vorliegt, erzeuge keinen `start`- oder `end`-Zeitstempel. Markiere die Revision als unvollständig und fordere die Anwendung zur Zeitzonenklärung auf.

**Datenvertrag beachten:** Der aktuelle Revisionsvertrag erlaubt nur `answered_question` und `changes` und kennt offenbar kein explizites Ergebnis „weitere Klärung erforderlich“. Damit der letzte Satz maschinell verlässlich umsetzbar ist, sollte die Anwendung entweder den bekannten Termin-Offset bzw. die konfigurierte Nutzerzeitzone als vertrauenswürdigen Fakt übergeben oder das strukturierte Ergebnis um einen expliziten Klärungszustand erweitern. Die Anwendung muss außerdem ISO-Zeitstempel ohne belegte Offset-Quelle ablehnen. Den Offset nicht allein promptseitig „wegzuwünschen“ und danach ungeprüft zu schreiben.

### 2. Hoch: Router und Terminextraktion verwenden nicht dieselbe Event-Grenze

Vier abgeglichene Fälle enthalten einen Router-Kandidaten mit `event_count: 1`, aber die anschließende Terminextraktion gibt `events: []` aus. Die Modellbegründungen zeigen dabei denselben Grenzfall: Eine Teams-/Skype-Mail enthält Beitrittslink, Konferenzkennung und Passcode, aber im übergebenen Nachrichtentext kein Datum, keine Uhrzeit und teils keine erkennbare Einladungs- oder Bestätigungsformulierung. Der Router zählt den Zugangsdatenblock als mögliches Meeting; der Extraktor verwirft ihn mangels Terminzeit.

Das führt je nach nachgelagerter Logik entweder zu unnötigem Router-Aufwand oder dazu, dass ein erkanntes mögliches Ereignis ohne Proposal endet. Die Regeln „Ein ausdrücklich genannter Termin ist ein Terminkandidat“ und „nur ausdrücklich genannte Rohinformationen extrahieren“ klären nicht eindeutig, ob eine unvollständige, aber echte Einladung als Event mit fehlendem Datum ausgegeben werden soll.

**Vorschlag für `action_router` und `event_extraction`:** Eine gemeinsame, konkrete Grenze festlegen und in beiden Prompts mit denselben Gegenbeispielen verwenden:

> Ein Teams-/Skype-Link, eine Besprechungs-ID, ein Passcode oder eine Einwahlnummer allein belegt keinen konkreten Kalendereintrag. Wenn die aktuelle Nachricht nur solche statischen Zugangsdaten enthält und weder einen konkreten Termin noch eine eindeutig aktuelle Einladung nennt, zähle kein Event. Wenn die aktuelle Nachricht dagegen ausdrücklich zu einem identifizierbaren bevorstehenden Treffen einlädt oder dessen Termin ändert, ist genau ein Event-Kandidat vorhanden, auch wenn Datum oder Uhrzeit fehlen; extrahiere dann den belegten Titel und setze nicht genannte Zeitfelder auf `null`, statt das Event zu verwerfen.

Ergänzend sollte der Router bei unklarer Zuordnung nicht automatisch `event_count: 1` aus einem bloßen Zugangsdatenblock ableiten. Falls die Produktentscheidung „unvollständige echte Einladung trotzdem vorschlagen“ lautet, muss die Extraktion dafür einen unvollständigen Event-Datensatz liefern. Die Entscheidung zwischen diesen beiden Pfaden ist fachlich zu bestätigen; die Prompts sollten nicht unterschiedliche Regeln implementieren.

### 3. Hoch: Aufgabenextraktion übernimmt historische Rückmeldungen aus einer Mailkette

Bei einer Mail über die Verschiebung eines Verbandstermins meldete der Router **eine** aktuelle Aufgabe und **ein** Event. Die Aufgabenextraktion gab **zwei** Aufgaben zurück:

1. die neue Verschiebung zur Kenntnis nehmen und einrichten;
2. eine Rückmeldung zur Teilnahme geben.

Die Router-Begründung ordnete die ältere Rückmeldefrist aus der eingebetteten Vorgängermail dem vergangenen Zeitraum zu und zählte sie nicht erneut. Die Extraktion berücksichtigte sie dennoch zusätzlich. Das Risiko entsteht durch fehlende explizite Regeln zur Trennung des aktuellen Nachrichtenteils von zitierten oder weitergeleiteten Vorgängern. Ein vergangenes Fristdatum beweist für sich genommen nicht, dass die Aufgabe erledigt ist; es macht eine historische Bitte aber auch nicht automatisch zu einer neuen Aufgabe.

**Vorschlag für `task_extraction`:**

> Trenne den aktuellen Nachrichtenteil von zitierten, weitergeleiteten oder eingebetteten älteren Nachrichten. Extrahiere eine Bitte aus einer älteren Nachricht nur dann als aktuelle Aufgabe, wenn der aktuelle Nachrichtenteil sie ausdrücklich wiederholt, bestätigt oder erneut an die empfangende Person richtet. Eine historische Bitte oder Frist wird nicht allein durch ihre Aufnahme in den Mailverlauf zu einer neuen Aufgabe. Eine vergangene Frist beweist nicht, dass die Aufgabe erledigt ist; verwende `already_completed` nur bei ausdrücklichem Erledigungsnachweis. Erzeuge pro eigenständiger verlangter Handlung genau einen Kandidaten; mehrere Umschreibungen derselben Handlung in einer Antwortkette sind keine zusätzlichen Aufgaben.

Die Promptregel sollte mit einem Regressionstest für eine Antwortkette getestet werden, in der eine alte Rückmeldefrist zitiert und im aktuellen Teil nur der Termin verschoben wird. Erwartung: nur die aktuelle Handlung, nicht die historische Bitte, wird extrahiert.

### 4. Mittel: Gründe der Relevanzprüfung sind oft unnötig lang

Die Relevanzstufe ist mit 94 Aufrufen die häufigste LLM-Stufe und weist im Log durchschnittlich 2.977 Prompt-Tokens auf; einzelne Requests liegen bei über 8.000 Prompt-Tokens. Die protokollierten Provider-Kosten der Relevanzantworten betragen rund 0,0358 USD. In mehreren irrelevanten Antworten listet `reason` erneut zahlreiche Themen auf, die nicht passen. Für die Anwendung ist diese Wiederholung der ganzen Themenliste kaum zusätzlicher Nutzen gegenüber einer kurzen Inhaltsbegründung.

**Vorschlag für `relevance`:** Die vorhandene 1.000-Zeichen-Grenze auf eine operative Kurzbegründung begrenzen und die Wiederholung nicht passender Themen untersagen:

> `reason` umfasst höchstens 250 Zeichen und nennt genau den entscheidenden Inhaltsbezug oder dessen Fehlen. Bei `irrelevant` fasse den Grund in einem kurzen Satz zusammen; liste nicht alle geprüften Themen auf. Bei `relevant` nenne nur die zugeordneten Themen und den konkreten Mailinhalt, der diese Zuordnung trägt. Bei `unclear` benenne die fehlende Information.

 Das reduziert Antwortballast. Für Prompt-Tokens sollte zusätzlich die tatsächlich an den Relevanzschritt übergebene Themenrepräsentation geprüft werden: kurze, eindeutige Beschreibungen und nur für schwierige Grenzfälle benötigte Beispiele. Beispiele und Ausschlüsse nicht pauschal entfernen, sondern anhand des Qualitätskorpus messen.

### 5. Mittel: Aufgabenregeln enthalten Wiederholungen, aber wenig Thread-Kontext

`task_extraction` wiederholt die Vorgabe, keine Kandidaten zu erfinden oder zu entfernen, unmittelbar an mehreren Stellen. Zugleich fehlt genau die für den beobachteten Fehler relevante Thread-Regel. Das Verhältnis ist ungünstig: Wiederholte allgemeine Mahnungen vergrößern und verwässern den Prompt, während die wichtige Abgrenzung nicht explizit ist.

**Vorschlag:** Die mehrfachen Zähler-/Kandidatensätze auf eine klare Regel mit Verweis auf `expected_count` als Diagnosewert reduzieren. Den gewonnenen Platz für die aktuelle-vs.-historische Mailgrenze und die semantische Deduplizierung nutzen. Sicherheitsregeln, geschlossene Enum-Werte und die ausdrückliche Behandlung freiwilliger konkreter Angebote beibehalten, da sie für Aufgabeninterpretation und Sicherheit wesentlich sind.

### 6. Niedrig: Erfolgreiche Stufen sollten nicht unnötig umgeschrieben werden

Die sichtbaren Zusammenfassungen sind überwiegend knapp und schema-valide; die Relevanzprüfung klassifiziert die klaren Werbe- und Statusbeispiele plausibel; die Rückfrageauflösung trennt belegte Antworten von fehlender Information. Für diese Stufen ist im geprüften Lauf kein ausreichend belastbarer Fehler nachgewiesen, der eine breite Neuformulierung rechtfertigt.

**Vorschlag:** `summary` und `mail_question_resolution` vorerst beibehalten. Neue Regeln nur ergänzen, wenn ein konkreter Regressionstest einen wiederholbaren semantischen Fehler zeigt. Bei `summary` weiterhin besonders testen, dass Veranstaltungstermin und Anmeldefrist getrennt in `deadlines` stehen und die gekürzte Zusammenfassung keine Frist entfernt.

## Priorisierte Umsetzung

1. **Zeitzone absichern:** Bekannte Termin-Offsets an `proposal_revision` übergeben, Offset-Erfindung im Prompt explizit verbieten und die Anwendung so validieren, dass unbelegte ISO-Offsets nicht akzeptiert werden.
2. **Event-Grenze vereinheitlichen:** Entscheidung zu bloßen Zugangsdaten versus unvollständiger echter Einladung treffen; dieselben Beispiele und Kandidatenregeln in Router und Extraktion einsetzen.
3. **Antwortketten absichern:** Aktuellen Nachrichtenteil gegenüber zitierten Vorgängern abgrenzen und semantische Deduplizierung für Aufgaben spezifizieren.
4. **Relevanzkosten gezielt senken:** Begründungen verkürzen und die an den Relevanzschritt übergebenen Topic-Tokens anhand der vorhandenen Grenzfälle optimieren.
5. **Providerweise messen:** Nach jeder Promptänderung dieselben synthetischen Fälle mit dem produktiven Fallback-Verhalten ausführen und Ergebnisse nach Provider auswerten. Keine Qualitätsverbesserung allein aus Schema-Erfolg oder Einzelprovider-Ausgaben ableiten.

## Empfohlene Regressionstests

- Terminrevision: Datum plus Uhrzeit, aber keine Offset-Quelle; es darf weder `Z` noch `+00:00` erfunden werden.
- Terminrevision: ursprüngliche Mail nennt `UTC+01:00`; die Revision erhält diesen Offset unverändert.
- Besprechungsblock ohne Terminangabe: Router und Extraktion liefern dieselbe Kandidatenentscheidung.
- Echte aktuelle Einladung ohne Uhrzeit: ein unvollständiges Event mit `null`-Zeitfeldern oder, falls Produktentscheidung dagegen, in beiden Stufen kein Event.
- Antwortkette: veraltete Rückmeldebitte bleibt historisch, aktuelle Verschiebungsbitte wird genau einmal extrahiert.
- Antwortkette mit aktueller Wiederholung derselben älteren Bitte: genau ein aktueller Aufgabenkandidat.
- Prompt-Injection in Betreff, aktuellem Text und zitiertem Text: keine Regeländerung und keine zusätzliche Ausgabe.
- Relevanzbegründung: irrelevant bleibt kurz und zählt nicht jede nicht passende Themen-ID auf.

**Gesamtbewertung:** Gute technische Formatdisziplin und plausible Relevanzentscheidungen bei klaren Mails. Vor einer weiteren Produktivnutzung sollten vor allem die unbelegte Zeitzonenannahme sowie die abweichenden Kandidatengrenzen zwischen Router und Extraktion abgesichert werden. Die zwei permanenten Adapterfehler sind separat als Betriebs-/Providerproblem nachzuverfolgen.
