# Release 5.7 – Lernen und Themenverwaltung

Grundlage: [Planung 5.7](Planung-5.7.md), Ausgangsstand 5.6.0.
Die Arbeitspakete werden einzeln als 5.7.0–5.7.5 committet.

| Paket | Version | Stand |
| --- | --- | --- |
| S1: Gemeinsame Lernübersicht | 5.7.0 | umgesetzt, gezielte Abnahme |
| S2: Themenübersicht | 5.7.1 | ausstehend |
| S3: Themenbearbeitung mit Vorschau | 5.7.2 | ausstehend |
| S4: Gemeinsame Gestaltung | 5.7.3 | ausstehend |
| S5: Dokumentation und Hilfe | 5.7.4 | ausstehend |
| S6: Gesamtabnahme | 5.7.5 | ausstehend |

## S1 – Lernen an einem Ort

Die Übersicht `/lernen` führt zu `/lernen/postfach` und `/lernen/entscheidungen`.
Die Karten zeigen Zweck, Zustand, Kennzahl und einen eingeklappten Kostenhinweis.
Kein GET startet einen Modellaufruf. Eine fehlende `decision_rule_learning`-Konfiguration
wird hier bereits erklärt. Der Entscheidungszähler bezieht sich auf den aus 5.6 bekannten
begrenzten Ausschnitt (höchstens 100 Belege), nicht auf ein unbegrenzt eingelesenes Archiv.
Analysierte IDs werden ohne private Belege als begrenzte Metadaten gespeichert.

Alte GET-Links werden dauerhaft weitergeleitet; alte POST-Formulare werden ohne Ausführung
abgewiesen. Die neue Seite verlangt eine frische ausdrückliche Bestätigung.
Neue und bestehende Lernseiten wurden mit synthetischen Daten und simulierten Anbietern
geprüft, einschließlich Sitzung, CSRF, Fremdsitzung, Historie und alten Formularen.

Abnahme S1: 154 relevante Python-Tests mit 100 % Zeilen-/Branch-Abdeckung der geprüften
Lernmodule; 42 Navigations-, Such- und Dokumentationsprüfungen; 19 Browserprüfungen einschließlich
der Lernübersicht auf Desktop/Mobil/schmal und ohne JavaScript. Ruff und Mypy sind fehlerfrei.
