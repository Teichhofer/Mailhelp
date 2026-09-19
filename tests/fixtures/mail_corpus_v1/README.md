# Deutscher Mail-Qualitätskorpus, Version 1

`corpus.json` enthält ausschließlich synthetische Nachrichten und reservierte
`.test`-Adressen. Jede Nachricht besitzt getrennte Erwartungen für Relevanz,
Zusammenfassung, Router, Task-Extraktion, Event-Extraktion, deterministische
Normalisierung und Proposal-Builder. Die Version ist absichtlich im
Verzeichnisnamen und im Feld `schema_version` festgehalten; fachliche Änderungen
werden nicht still in bestehende Erwartungen übernommen, sondern erzeugen eine neue
Korpusversion.

Der Standardtest `tests/test_quality_corpus.py` speist diese Antworten über einen
simulierten OpenRouter-Adapter in denselben `Analyzer` ein, den die Anwendung nutzt.
Damit ist der Lauf deterministisch, offline und geheimnisfrei. Zwölf explizit
benannte Akzeptanztests decken keine Action, reine Aufgabe, reinen Termin, Aufgabe
und Termin, unklare Action, unklare Zuständigkeit, relative Frist, ungültiges Datum,
Änderung, Absage, Wiederholung und Prompt-Injection ab. Der reine Terminfeldfall
ist eine synthetische, datenschutzsichere Gemeinderats-Mail; geprüft werden ihre
Routerausgabe, ausschließliche Event-Extraktion, Datumsnormalisierung und
`needs_clarification`.
