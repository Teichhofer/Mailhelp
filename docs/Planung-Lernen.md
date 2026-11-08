# Mailhelp – Lernmodus in der Weboberfläche reparieren

**Zielversion:** 4.9.7 und 4.9.8  
**Stand:** 8. November 2026  
**Status:** In Umsetzung (L.1–L.6 in 4.9.7)  
**Grundlage:** [Entwicklungsregeln](../AGENTS.md), [Projektspezifikation](../Mailhelp-Projektspezifikation.md)

---

## 1. Anlass

Ein Lernlauf lässt sich über `/lernen` nicht starten. Am 8. November 2026 um 07:58 Uhr
endeten beide Startversuche mit HTTP 409 und `LearningConflict`
(`logs/application.jsonl.1`). Eine Zustandsdatei `web-learning` existiert nicht: Über die
Weboberfläche hat noch nie ein Lauf begonnen. Die Seite meldet nur „Auswahl ungültig oder
inzwischen geändert“.

## 2. Befund

| # | Stelle | Problem |
| --- | --- | --- |
| 1 | `runtime/learning_worker.py`, `estimate` | Je Mail werden vier Aufrufe mit jeweils 2 × `max_llm_payload_bytes` (500.000) + größtem `max_tokens` (16.000) + 65.536, mal 4 Versuche, mal HTTP-Wiederholungen angesetzt. Mit der aktuellen Konfiguration sind das 17 bis 69 Mio. Tokens je Mail, für 20 Mails rund 346 Mio. Tokens oder 173 bis 692 USD bei 0,5 USD je Million. |
| 2 | `runtime/learning_jobs.py`, `_action("start")` | Lehnt den Start ab, sobald diese Schätzung das Budget übersteigt („Budget reicht für den geschätzten Lauf nicht aus“). Jedes realistische Budget scheitert. |
| 3 | `runtime/learning_worker.py`, `LearningCompleter.complete` | Reserviert je Aufruf die Anfragegröße **plus** die volle Obergrenze `max_llm_payload_bytes`, also die Nutzlast doppelt. Selbst ein großes Budget wäre nach wenigen Aufrufen erschöpft; der Lauf pausiert. Ungenutzte Reserve wird nie zurückgegeben. |
| 4 | `web/learning_site.py`, `act` | Der konkrete Grund der Ablehnung wird weder angezeigt noch protokolliert (`action_rejected` enthält nur die Fehlerklasse). |
| 5 | `web/learning_site.py`, `start_form` | Der Start-Knopf erscheint auch dann, wenn die gezeigte Schätzung das Budget übersteigt. |
| 6 | Pausierter Lauf nach Konfigurationsänderung | „Fortsetzen“ wird abgelehnt („Konfiguration geändert“), ein neuer Start ebenfalls („offener Lernlauf“). Nur „Abbrechen“ führt weiter; die Seite erklärt das nicht. |

Der Budget-Grund ist sehr wahrscheinlich, aber wegen Befund 4 nicht aus dem Log belegt.
Die übrigen Gründe für `LearningConflict` passen nicht: Ohne gespeicherten Zustand gibt es
weder einen veralteten Stand noch einen offenen Lauf oder einen Idempotenzkonflikt. Ein
unbekannter Ordner ist beim vorbelegten `INBOX` unwahrscheinlich.

## 3. Schritte

| Schritt | Inhalt | Prüfung |
| --- | --- | --- |
| L.1 | **Nachweis:** Regressionstest mit den Werten der aktuellen Konfiguration (500.000 Bytes Nutzlast, 16.000 Ausgabetokens, je eine Wiederholung) und 1 USD Budget für 20 Mails. Er scheitert vor der Korrektur und besteht danach; er bestätigt, welcher Ablehnungsgrund greift. | Test schlägt vor dem Fix fehl |
| L.2 | **Grund sichtbar:** Die 409-Seite zeigt die Meldung des `LearningConflict`, das Log enthält sie. Es sind feste Texte von Mailhelp ohne Mailinhalte. | Test je Ablehnungsgrund |
| L.3 | **Realistische Schätzung:** aus der tatsächlichen Größe der ausgewählten Mails (gekappt auf `max_llm_payload_bytes`) und den Ausgabetokens je Stufe; die Seite zeigt „typisch“ und „höchstens“ getrennt. Der harte Schutz bleibt die Reservierung je Aufruf. | Unit-Tests, Grenzwerte |
| L.4 | **Reservierung korrigieren:** je Aufruf nur Anfragegröße plus `max_tokens`, mal Versuche; nach dem Aufruf auf die vom Anbieter gemeldeten Tokens heruntergerechnet. | Budgetgrenze, Pause, Neustart |
| L.5 | **Startknopf nur, wenn startbar:** liegt die Schätzung über dem Budget, erscheint statt des Knopfs der benötigte Betrag. | Web-Test |
| L.6 | **Pausiert und Konfiguration geändert:** klare Erklärung und „Abbrechen und neu starten“ in einem Schritt. | Web-Test, Versions- und CSRF-Prüfung |
| L.7 | **Abnahme:** simulierte Läufe für Start, Pause, Neustart, Budgetgrenze, alle Ablehnungsgründe und einen zweiten Lauf nach „Übernommen“; 100 % Zeilen- und Branch-Abdeckung; Browser-Suite für `/lernen`. Danach ein kleiner echter Lernlauf (etwa 5 Mails, wenige Cent) nur nach ausdrücklicher Freigabe. | Windows, Docker, Browser |

## 4. Abnahmekriterien

- Ein Lernlauf mit realistischem Budget (etwa 1 USD für 20 Mails) startet und läuft durch.
- Jede Ablehnung nennt ihren Grund auf der Seite und im Log.
- Das Budget wird nie überschritten; ungenutzte Reserve verfällt nicht.
- Nach „Übernommen“ und nach „Abgebrochen“ lässt sich ein weiterer Lauf starten.
- Lernen liest weiterhin nur und legt keine Termine oder Aufgaben an.
