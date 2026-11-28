# Mailhelp 8.9 – Umsetzung und Freigabestand

Stand: 28. November 2026. Grundlage: [Planung 8.9](Planung-8.9.md), [Bewertungsvertrag v5](Bewertungsvertrag-v5.md).

> **Plan abgeschlossen mit 8.9.5, nicht ausgeliefert.** AP1–AP6 sind mit 8.9.1–8.9.5 umgesetzt; der Vorher-/Nachher-
> Vergleich besteht das Qualitätsgate nach Vertrag 5. Produktion, Demo und `kunde` laufen mit 8.8.7.

## Entscheidungen des Betreibers (28.11.2026)

- Planung 8.9 umsetzen, nach der Auslieferung von 8.8.7 auf Produktion, Demo und `kunde`.
- Modellbudget für AP4/AP6: bis zu **1.200 OpenRouter-Aufrufe** mit den unveränderten Modellen aus `prompts.yaml`
  und `decisions_prompts.yaml` (`deepseek/deepseek-v4.1-flash`, Jev `typesafe/jev-1.13`), ausschließlich auf dem
  synthetischen Korpus v5: zuerst höchstens drei gezielte Runden mit je bis zu 20 Fällen, dann je ein voller
  Vorher- und Nachher-Lauf.
- AP5: Die Suchlatenz wird wie seit 8.7.11 ab dem Eingabeereignis im Browser gemessen; die Grenze bleibt 95 von
  100 Suchläufen innerhalb von 300 ms im vollständigen Browserlauf mit sechs Workern. Zusätzlich werden Wartezeit,
  Anfrage und Darstellung sowie die Python-Wanduhr ausgewiesen.

## Umgesetzt in 8.9.1 – AP1 Bewertungsvertrag und Korpus v5

| Punkt | Umsetzung |
| --- | --- |
| Vertrag | `docs/Bewertungsvertrag-v5.md`: sechs Fachregeln, getrennte Bewertung von Identität, Fakten und Formulierung, Reviews, Ende-zu-Ende-Wirkung, Freigabegrenzen |
| Korpus | `tests/fixtures/mail_corpus_v5/corpus.json`: 46 v4-Fälle mit unveränderten Mails und begründeter Migration (Fall 20, Themen von sieben Fällen, Zusammenfassungen von sechs Fällen, Alternativen in 26 und 45), Aliase der neun Auditpaare (Diagnose), 22 neue Kontrollfälle |
| Baseline | `quality-reports/baseline-8.9.json`: Prüfsumme, unveränderte Grenzen, zehn kritische Keine-Aktion-Fälle |
| Tests | `tests/evaluation/test_corpus_v5.py` |

## Umgesetzt in 8.9.2 – AP2 Prüfer und Qualitätsgate

| Punkt | Umsetzung |
| --- | --- |
| Identität | `llm/action_matching.py`: Verbgruppen, Vereinheitlichung des Gegenstands, Aliase, verifizierter Quellenbeleg, reihenfolgeunabhängige beste Zuordnung (ungarische Methode), Reviews bei gleich guten Zuordnungen |
| Fakten | `quality_metrics`: jede Alternative als Ganzes; Klassifikation, Zuständigkeit, Sicherheit, Frist, Beginn/Ende/Tagesbereich, Zeitart, Zeitzone, Ort, Link, Bezugsdatum, Beleg |
| Ende-zu-Ende | `irrelevant` beendet wie im Produktivpfad; erwartete Aktionen zählen als verloren |
| Gate | sperrt zusätzlich bei Feldfehlern, Reviews, Verlusten, fehlender Relevanzstufe und fremdem Vertrag |
| Evaluation | `llm/stage_contract.py`: Themenvertrag, Zeitangaben-Bestandteile, Aktionsidentität; `end_to_end_lost` |
| Prompt-Gate | `prompt-baseline.json` eingefroren; aktiv nur `model_approved_baseline` über `quality-reports/active-baseline.json` |
| Tests | vier neue Testdateien; vor dem Fix 23 von 24 Prüferfällen rot |

## Umgesetzt in 8.9.3 – AP3 Wochentag der Quelle

| Punkt | Umsetzung |
| --- | --- |
| Quelle | `text/source_dates.py`: aktueller Mailteil ohne Zitat und Anhangstexte; nur Stellen mit demselben Tag |
| Prüfung | Einzeltermin, beide Grenzen eines Zeitraums und Aufgabenfrist; `invalid_date` mit der Quellenstelle als `temporal_fact.raw_text`; bekannte Uhrzeit bleibt |
| Format | „Wochentag, den TT.MM.JJJJ“ unterstützt |
| Rückfrage | Wochentagsfrage zuerst; eine Antwort ohne neuen Tag lässt sie offen; Neustart und erneute Verarbeitung ändern nichts |
| Tests | `tests/unit/test_source_weekday.py` |

## Umgesetzt in 8.9.4 – AP5 Suchlatenz

| Punkt | Umsetzung |
| --- | --- |
| Messung | Ab dem Eingabeereignis im Browser (Entscheidung vom 28.11.2026); zusätzlich Wartezeit, Anfrage, Darstellung (Resource Timing) und Python-Wanduhr, bei Überschreitung in der Fehlermeldung |
| Ergebnis | Vollständiger Browserlauf mit sechs Workern: 100/100 in 300 ms, Median 169 ms, P95 176 ms; davon Debounce 160 ms (bewusst 150 ms), Anfrage 8 ms, Darstellung 1 ms; Python-Wanduhr Median 239 ms, P95 311 ms. Der Engpass ist die Eingabeverzögerung, nicht der Server; keine Optimierung nötig |
| JavaScript | 100 % der Blöcke (Lücken seit 8.7.11 geschlossen) |
| Bericht | `mailhelp-quality-report` liest Berichte von `mailhelp-evaluate` direkt; Ortsvergleich ohne Artikel und Possessivpronomen |

## Umgesetzt in 8.9.5 – AP4 Promptregeln und AP6 Abnahme

| Punkt | Umsetzung |
| --- | --- |
| Regeln | Siehe Spezifikation „Promptregeln der Extraktion (seit 8.9.5)“; Beispiele neutral, nicht aus dem Bewertungskorpus (Fallbeispiele mit Korpusformulierungen wurden vor der Messung ersetzt) |
| Anwendung | „Anreise …, Abreise …“ als Zeitraum (`tests/unit/test_stay_ranges.py`) |
| Baseline | `quality-reports/prompt-baseline-8.9.json` (`model_approved_baseline`) über `quality-reports/active-baseline.json`; das Gate wird offline aus den gespeicherten Berichten erneut geprüft |

### Modellläufe (synthetisch, `deepseek/deepseek-v4.1-flash`, Jev `typesafe/jev-1.13`)

| Lauf | Fälle | Aufrufe | USD | Ergebnis |
| --- | ---: | ---: | ---: | --- |
| Vorher (Prompts 8.9.4) | 68 | 260 | 0,165 | Gate nicht bestanden |
| Gezielt, Runde 1 | 20 | 73 | 0,063 | K15 Ort |
| Gezielt, Runde 2 | 20 | 73 | 0,053 | 38, 41, K06 |
| Gezielt, Runde 3 | 20 | 73 | 0,056 | K06 Ausgabelimit |
| Diagnose Einsatzpläne (26, K06 je 3×, 10.000/16.000 Token, Regelkorrektur) | 18 | 80 | 0,108 | höheres Tokenlimit hilft nicht |
| Nachher, erster Lauf | 68 | 263 | 0,154 | 1 Feldfehler (K11, Zeitraumformat) |
| Nachher, unabhängig (nach Fix) | 68 | 263 | 0,137 | **Gate bestanden** |
| Summe | | **1.085 / 1.200** | **0,74** | |

| Größe | Vorher | Nachher (unabhängig) |
| --- | --- | --- |
| Aufgaben erkannt / übersehen / Fehlalarme | 19 / 0 / 4 | 20 / 0 / 0 |
| Termine erkannt / übersehen / Fehlalarme | 50 / 1 / 2 | 51 / 0 / 2 |
| Feldfehler erkannter Aktionen | 54 | 0 |
| Reviews / Ende-zu-Ende-Verluste / Ausfälle | 0 / 2 / 0 | 0 / 0 / 0 |
| Kritische Keine-Aktion-Fälle (10) | ohne Aktion | ohne Aktion |
| Stufen bestanden (Relevanz, Zusammenfassung, Router, Aufgaben, Termine) | 63, 66, 61, 64, 58 | 62, 66, 67, 68, 67 |

Die Vorher-Zahlen sind mit dem Prüfstand von 8.9.5 bewertet (gleicher Code für beide Läufe). Der erste Nachher-Lauf
zeigte das Zeitraumformat „14.05.2027, Abreise 17.05.2027“; weil der Fix daraus abgeleitet ist, gilt erst der
anschließende, vom Betreiber freigegebene unabhängige Lauf als Abnahme.

**Offen ausgewiesen (keine Gate-Grenze, nicht nachträglich angepasst):** Die Relevanzstufe ordnet in sechs Fällen
zusätzliche Themen zu (04, 09, 35, 36: zusätzlich „Persönliche Termine“ bei Änderungen eigener Arbeitstermine;
K14: zusätzlich „Arbeit“ und „Persönliche Termine“; K06: nur „Arbeit“ statt „Persönliche Termine“). Die Zusammenfassung
nennt in 22 die Monatsangabe und in K22 das Datum der eingeschleusten Anweisung nicht. K05 (allgemeine Spieltermine)
ergibt zwei Termin-Fehlalarme (Grenze 2). Eine Präzisierung der Themenverträge wäre eine neue Vertragsversion.

Berichte: `quality-reports/v5-before-2026-11-28.json`, `v5-after-2026-11-28.json`, `v5-after-final-2026-11-28.json`
und die Metriken `v5-before-metrics-…`, `v5-after-final-metrics-…`.

## Prüfergebnis

Getrennt ausgeführt am 28.11.2026 für 8.9.5: `python -m devtools.check full --workers 12` mit 6.794 Tests, 100 %
Zeilen- und Branch-Abdeckung; der einzige rote Vertragstest prüfte noch die durch Regel 2 ersetzte Formulierung und
wurde angepasst. Das Prompt-Gate besteht erstmals seit dem Entwurf vom 26.11.2026 (aktive modellgeprüfte Baseline).
Lasttests 4 bestanden. `python -m pytest ui_tests -n 6 --dist worksteal --no-cov`: 1.013 bestanden, 234 übersprungen
(Geräteansichten ohne den jeweiligen Test), JavaScript-Abdeckung 100 %.

## Auslieferung

Nicht ausgeliefert. Produktion, Demo und `kunde` laufen mit 8.8.7; eine Auslieferung von 8.9.5 braucht die
Freigabe des Betreibers.

