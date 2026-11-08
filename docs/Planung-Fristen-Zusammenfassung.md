# Mailhelp – Fristen in der Zusammenfassung

**Zielversion:** 4.5.7 (ursprünglich 4.5.7 bis 4.5.10 geplant)  
**Stand:** 8. November 2026  
**Status:** Umgesetzt in 4.5.7 (alle Schritte in einer Version; Ergebnis in Abschnitt 8)  
**Grundlage:** [Entwicklungsregeln](../AGENTS.md), [Release 4.5](Release-4.5.md) (reale Auswertung),
[Projektspezifikation](../Mailhelp-Projektspezifikation.md)

---

## 1. Befund

Die reale Auswertung vom 8. November 2026 (deepseek-v4.1-flash, Korpus v3, 25 Fälle)
hat in der Zusammenfassung nur 14 von 25 Fällen bestanden. In 11 Fällen war die
Fristliste `deadlines` leer, obwohl das Datum im Zusammenfassungssatz stand, zum Beispiel:

> „Die Unterlagen sollen bis 2026-09-30 bei ihr eingehen.“ – `deadlines: []`

In einem Fall stand das Wort `"deadlines"` als zweiter Satz in `sentences`. Router,
Aufgaben- und Terminextraktion waren in denselben Fällen richtig. Termine und Aufgaben
entstehen aus der Extraktion, nicht aus dieser Liste.

## 2. Wofür die Liste verwendet wird

| Stelle | Verwendung |
| --- | --- |
| Archiv-Detailseite der Weboberfläche | Zeile „Fristen: …“ |
| `mailhelp-evaluate` | Stufe `summary`, Vergleich der Kalenderdaten |
| Telegram-Nachricht, Vorschläge, Kalender, Todoist | **nicht** verwendet |

Der Schaden ist damit begrenzt: Auf der Archivseite fehlt die Fristzeile, und die
Auswertung meldet die Zusammenfassung als abweichend. Dadurch fallen echte Fehler in
anderen Stufen weniger auf.

## 3. Ursachen

1. **Feld im Schema nicht Pflicht (wahrscheinlichste Ursache).** Das an OpenRouter
   übergebene JSON-Schema (`Summary.model_json_schema()`, `strict: true`) führt nur
   `sentences` als `required`. `deadlines` hat in `domain/extraction.py` den Standardwert
   `[]`. Lässt das Modell das Feld weg, ist die Antwort gültig, und Mailhelp füllt
   stillschweigend `[]` ein. Ein Auslassen ist von „keine Frist“ nicht zu unterscheiden.
   Dazu passt der Fall mit `"deadlines"` als Satz: Das Modell wollte das Feld ausgeben,
   das Schema bot ihm aber keinen verbindlichen Platz.
2. **Reihenfolge und Länge des Prompts.** Die Regeln zu `deadlines` stehen nach rund 30
   Zeilen Stilregeln. Das Modell läuft mit `reasoning: low`. Das Schema nennt
   `sentences` zuerst, die Daten werden also erst nach dem Kürzen der Sätze verlangt.
3. **Korpuserwartungen teils uneinheitlich.** Der Prompt verlangt auch Anmeldefristen.
   Fall 32 erwartet aber nur das Veranstaltungsdatum, obwohl das Modell richtig auch die
   Anmeldefrist 20.11.2026 nannte. Fall 30 erwartet `22.09.2026`, das Modell nannte die
   Sitzungstermine. Diese Erwartungen sind vor jeder Prompt-Änderung zu prüfen.

Nicht die Ursache sind die Änderungen aus 4.5: Die Zusammenfassung erhält keine
Perspektive, und die Fehler treten genauso bei Mails Dritter auf.

## 4. Lösungswege

| Weg | Inhalt | Vorteil | Nachteil |
| --- | --- | --- | --- |
| **A (empfohlen)** | Feld im Antwortschema Pflicht, `deadlines` vor `sentences`, Prompt straffen | behebt die wahrscheinliche Ursache, kleine Änderung | braucht reale Nachprüfung (Kosten) |
| B | Fristen deterministisch aus dem Mailtext lesen (`DEADLINE_DATE_PATTERN`) | ohne Modell, ohne Kosten | übernimmt zitierte, alte und Prompt-Injection-Daten, kein Wortlaut für relative Angaben |
| C | Feld abschaffen und die Archivzeile entfernen | einfachste Lösung | verliert eine Anzeige; Spezifikationsänderung |

Weg A zuerst; B oder C nur, wenn A die Abnahme in 5.4 nicht erreicht.

## 5. Umsetzungsschritte

| Schritt | Version | Inhalt | Prüfung |
| --- | --- | --- | --- |
| **F.1** Diagnose | 4.5.7 | Die Auswertung meldet je Fall, ob das Modell `deadlines` **weggelassen** oder leer ausgegeben hat (`summary_deadlines_omitted`). Dafür wird die Rohantwort vor dem Auffüllen des Standardwerts geprüft. Gespeichert werden nur Ja/Nein, keine Inhalte. Eine reale Nachprüfung der 11 betroffenen Fälle (Grenze 15 Aufrufe, rund 0,01 $) bestätigt oder widerlegt Ursache 1. | Unit-Tests mit simulierter Antwort mit und ohne Feld; 100 % Abdeckung |
| **F.2** Antwortschema | 4.5.8 | Eigenes Antwortmodell für den Modellaufruf, in dem `deadlines` Pflicht ist und vor `sentences` steht. Gespeicherte Zustände und `Summary` behalten den Standardwert `[]`, damit alte Mails ohne Migration lesbar bleiben. Fehlt das Feld, gilt die Antwort als Schemafehler und läuft in die vorhandene Validierungswiederholung. | Schema-Snapshot, Test für fehlendes Feld, Wiederholung, Neustart mit alten Zuständen |
| **F.3** Korpus prüfen | 4.5.9 | Alle erwarteten Fristen in Korpus v3 gegen die Prompt-Regeln prüfen, zuerst die Fälle 30 und 32. Anmeldefristen werden ergänzt; strittige Fälle erhalten `accept`-Alternativen. | Offline-Prompt-Gate 34/34; Baseline fortschreiben |
| **F.4** Prompt straffen | 4.5.9 | Die Fristregeln an den Anfang des Ausgabeabschnitts, Wiederholungen streichen, ein Beispiel mit Satz und Liste („bis 30.09.2026“ in beiden). Nur falls F.1/F.2 allein nicht reichen: `reasoning: medium` für `summary`. | Prompt-Tests; Kostenvergleich vor und nach der Änderung |
| **F.5** Reale Abnahme | 4.5.10 | Vollständiger Lauf über alle 34 Fälle (rund 150 bis 180 Aufrufe, geschätzt 0,10 bis 0,15 $). Er braucht eine eigene Freigabe. | Bericht in `docs/Release-4.5.md` |

## 6. Abnahmekriterien

- Zusammenfassung im realen Lauf in mindestens 31 von 34 Fällen bestanden.
- Kein Fall mit weggelassenem Feld (`summary_deadlines_omitted` überall nein).
- Router, Aufgaben- und Terminextraktion nicht schlechter als in der Auswertung vom
  8. November 2026.
- Bestehende Zustände ohne `deadlines` bleiben lesbar; keine Neuanalyse alter Mails.
- 100 % Zeilen- und Branch-Abdeckung, Regressionstest für das weggelassene Feld.

## 7. Entscheidungen

1. **Anmeldefrist bei bestehender Anmeldung (entschieden 8. November 2026):** entfällt.
   Ist die nutzende Person schon angemeldet, gehört nur das Veranstaltungsdatum in die
   Liste.
2. **Reale Läufe:** freigegeben bis 200 Aufrufe; verbraucht 137.
3. **Offen:** Soll die Fristzeile zusätzlich in der Telegram-Zusammenfassung erscheinen?
   Das wäre eine neue Funktion und gehört nicht zu dieser Korrektur.

## 8. Ergebnis (4.5.7)

- **F.1 Diagnose:** Statt eines Berichtsfelds lief ein einmaliges Diagnoseskript: 11
  reale Zusammenfassungsaufrufe, ausgewertet wurde nur, ob das Feld in der Rohantwort
  vorkommt. In 6 von 11 Antworten fehlte `deadlines` ganz; Ursache 1 ist bestätigt. Ein
  dauerhaftes Berichtsfeld ist nicht mehr nötig, weil das Weglassen seit F.2 ein
  Schemafehler ist. Dabei fiel auf: Beim Elternabend stand das Datum der
  Weiterleitungs-Kopfzeile als Frist in der Liste.
- **F.2:** Antwortschema `SummaryAnswer` (`deadlines` Pflicht und zuerst).
- **F.3:** Fall 30 korrigiert (elf Sitzungstermine statt des aus Fall 03 kopierten
  Datums). Fall 32 erwartet nach Entscheidung 1 nur das Veranstaltungsdatum.
- **F.4:** Fristregeln vor den Satzregeln, eigene Liste dessen, was keine Frist ist,
  Perspektive für eigene Notizen. Beispiele bewusst ohne Bezug zu Korpusfällen.
  `reasoning` unverändert `low`.
- **F.5 Reale Abnahme:** alle 34 Fälle, 126 Aufrufe, 0,07 $.

| Stufe | 8.11. vor 4.5.6 (25 Fälle) | 4.5.7 (34 Fälle) |
| --- | --- | --- |
| Zusammenfassung | 14 / 25 | **31 / 34** |
| Aktionsrouter | 25 / 25 | 33 / 34 |
| Aufgabenextraktion | 25 / 25 | 34 / 34 |
| Terminextraktion | 22 / 25 | 31 / 34 |
| Relevanz | 22 / 25 | 29 / 34 |

Abnahmekriterium „mindestens 31 von 34“ erreicht. Kein Fall lief in einen Schemafehler.
Die drei Abweichungen der Zusammenfassung (22, 25, 27) sind Werbemails: Das Modell
nennt Aktionszeiträume wie „nur bis zum 30.09.2026“ oder „im September“. Der Prompt
verlangt jede genannte Zeitangabe, der Korpus erwartet `[]`. Im Betrieb ohne Folge: Diese
Mails sind irrelevant, und irrelevante Mails erhalten keine Zusammenfassung.

Die übrigen Abweichungen betreffen Stufen, die diese Änderung nicht berührt: zusätzliche
Themen bei 04, 08, 20, 21 und 26; bei 23 `required_unknown` statt `all_day` bei richtigem
Zeitraum; 24 (Stornierung einer Buchung) ohne Termin; 30 als sichere eigene Termine statt
„unklar“. Die Fälle 21 bis 29 liefen am 8. November zum ersten Mal real, ein Vergleich
mit früher ist für sie nicht möglich.
