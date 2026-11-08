# Mailhelp – Fristen in der Zusammenfassung

**Zielversion:** 4.5.7 bis 4.5.10 (Patchversionen vor 4.6)  
**Stand:** 8. November 2026  
**Status:** In Planung  
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

## 7. Offene Entscheidungen

1. Gehören Anmeldefristen in die Liste, auch wenn die nutzende Person schon angemeldet
   ist (Fall 32)? Der Prompt sagt heute ja.
2. Freigabe der realen Läufe in F.1 (etwa 15 Aufrufe) und F.5 (etwa 180 Aufrufe).
3. Soll die Fristzeile zusätzlich in der Telegram-Zusammenfassung erscheinen? Das wäre
   eine neue Funktion und gehört nicht zu dieser Korrektur.
