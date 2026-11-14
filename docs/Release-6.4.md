# Mailhelp 6.4 – Umsetzung und Abnahme

Zielstand: 6.4.5. Prüfung läuft; noch nicht auf dem Produktivserver installiert.

Die Arbeitspakete D1 bis D4 aus der Planung sind implementiert. Fünf Versuche insgesamt
bedeuten vier Wartezeiten; die im Entwurf zusätzlich genannte 12-Stunden-Pause entfällt.
Die Fehlerbegrenzung betrifft Mailverarbeitung, niemals unklare externe Schreibresultate.
Nicht mehr vorhandene Analyse-Daten bleiben durch die Regel aus 6.3.2 geschützt.

Die Regression für Benachrichtigungen schlägt mit der ursprünglichen
`Orchestrator.failure`-Implementierung fehl und besteht mit der neuen Implementierung.
Gezielte Tests prüfen fünf Versuche, Neustarts, Konfigurations- und Fehlerwechsel,
Rate-Limit, Aufgeben, kein IMAP/Budget während einer Pause, Aktionen mit Version,
Idempotenz, Sitzung bei Annahme und Ausführung, CSRF und wiederaufgenommene Befehle.
Der synthetische Tageslauf mit zwanzig Ordnern bleibt unter 2 MB; wiederholte Fehler
bleiben unter 120 Zeilen pro Tag. Alle drei Browsergrößen bestehen den neuen Ablauf
ohne JavaScript. Vollständige Suites und Abdeckungsprüfung laufen noch.

Offen nach Auslieferung: Protokollvolumen am echten Bestand nach einer Woche nachmessen.
