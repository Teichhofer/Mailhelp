# Qualitätskorpus Version 4 (5.1)

Enthält alle 38 synthetischen Fälle aus Korpus v3 mit unveränderten Mails und Erwartungen
sowie acht Fälle für die Fallgruppen der Planung 5.1. Jeder Fall nennt in `purpose` seinen
Zweck und in `expected` die Sollfelder für Relevanz, Zusammenfassung, Aktionsrouter,
Aufgaben- und Terminextraktion.

| Fall | Zweck |
| --- | --- |
| 39 | Besprechung mit ausdrücklichem Vorbereitungsauftrag: Termin und Aufgabe |
| 40 | Reine Besprechungsinformation: Termin ohne Aufgabe |
| 41 | Anmeldung und Unterlagenversand mit zwei Fristen: zwei Aufgaben |
| 42 | Aufgabe übernimmt ausdrücklich eine andere Person: keine Aktion |
| 43 | Eigene versandte Bitte an andere: keine eigene Aufgabe |
| 44 | Datum ohne Uhrzeit: ganztägiger Termin ohne erfundene Uhrzeit |
| 45 | Wochentag und Datum widersprechen sich: Termin als widersprüchlich |
| 46 | Vorgetäuschte Schreibfreigabe in Werbung: irrelevant, keine Aktion |

Alle Adressen liegen unter `example.test`; es gibt keine persönlichen Mails und keine
aufgerufenen Links. Korpus v3 bleibt unverändert Grundlage des Prompt-Fingerabdrucks.

`recorded_answers.json` enthält aufgezeichnete synthetische Antworten: die Sollwerte mit
bekannten Fehlern (falsche Frist in 39, übersehene zweite Aufgabe in 41, Fehlalarm bei
fremder Zuständigkeit in 42, erfundene Uhrzeit in 44, technischer Ausfall in 46,
unlesbare Antwort in 12). Ein Bericht daraus belegt den reproduzierbaren Vergleich, nicht
die Qualität eines Modells.

```sh
mailhelp-quality-report tests/fixtures/mail_corpus_v4/corpus.json tests/fixtures/mail_corpus_v4/recorded_answers.json quality-report.json --source recorded
```
