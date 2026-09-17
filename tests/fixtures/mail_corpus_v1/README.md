# Deutscher Mail-Qualitätskorpus, Version 1

`corpus.json` enthält ausschließlich synthetische Nachrichten und reservierte
`.test`-Adressen. Jede Nachricht besitzt die vollständigen erwarteten strukturierten
Antworten für Relevanz, Zusammenfassung und Aktionen. Die Version ist absichtlich im
Verzeichnisnamen und im Feld `schema_version` festgehalten; fachliche Änderungen
werden nicht still in bestehende Erwartungen übernommen, sondern erzeugen eine neue
Korpusversion.

Der Standardtest `tests/test_quality_corpus.py` speist diese Antworten über einen
simulierten OpenRouter-Adapter in denselben `Analyzer` ein, den die Anwendung nutzt.
Damit ist der Lauf deterministisch, offline und geheimnisfrei. Der Korpus umfasst alle
Relevanzentscheidungen, mehrere Themen, Aufgaben und Termine sowie Widersprüche,
Änderungen, Absagen, bereits erledigte und wiederkehrende Vorgänge und einen
Prompt-Injection-Versuch.
