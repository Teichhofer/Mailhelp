# Release 5.7 – Lernen und Themenverwaltung

Grundlage: [Planung 5.7](Planung-5.7.md), Ausgangsstand 5.6.0.
Die Arbeitspakete werden einzeln als 5.7.0–5.7.5 committet.

| Paket | Version | Stand |
| --- | --- | --- |
| S1: Gemeinsame Lernübersicht | 5.7.0 | umgesetzt, gezielte Abnahme |
| S2: Themenübersicht | 5.7.1 | umgesetzt, gezielt abgenommen |
| S3: Themenbearbeitung mit Vorschau | 5.7.2 | umgesetzt, gezielt abgenommen |
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

## S2 – Kompakte Themenübersicht

Zwei Reiter, Server- und Sofortsuche, Statusfilter, deaktivierte Themen am Ende und eine
eigene Seite je Thema ersetzen den Formularstapel. Desktop-Tabelle und mobile Karten
wurden mit 48 synthetischen Themen geprüft, auch ohne JavaScript.

Damit die Bearbeiten-Links in dieser Stufe bereits funktionieren, wurden die technischen
Einzelseiten und zwei Datenverlustkorrekturen aus S3 vorgezogen: Ein bestehender
Postfachbereich geht beim Speichern nicht mehr verloren; Semikolons bleiben innerhalb
eines zeilengetrennten Beispiels erhalten. Beide Regressionen scheiterten vor dem Fix.
Vorschau, Feldfehler und die gesonderte Bestätigung werden in S3 ergänzt.

Abnahme S2: 38 relevante Python-Tests, 100 % Zeilen-/Branch-Abdeckung der neuen Themenseite;
zusätzliche Bestandstests (68) und sechs Browserprüfungen auf Desktop/Mobil/schmal mit und
ohne JavaScript. Das neue `topics.js` ist in die verbindliche Browser-Coverage aufgenommen.

## S3 – Themenbearbeitung mit Vorschau

Jedes Thema wird auf einer eigenen Seite bearbeitet: deutsche Beschriftungen mit Kurzhilfe,
ein Eintrag je Zeile, ein Schalter „Aktiv“ und bei neuen Themen eine aus dem Namen
vorgeschlagene ID. „Änderung prüfen“ speichert nur eine sitzungseigene, versionierte
Vorschau und schreibt keine Themendatei. Erst die ausdrückliche Bestätigung auf der
Vorschauseite reiht den bestehenden AdminCommand ein; Sitzung, CSRF, Dateihash,
Entwurfsversion und Idempotenzschlüssel werden dabei erneut geprüft. Feldfehler stehen am
Feld, Konflikte bieten „Neu laden“. Offene Vorschauen erscheinen in der Übersicht und
verfallen nach 24 Stunden; Vorschauen einer älteren Dateirevision gelten als veraltet.
Formulare von vor dem Update speichern weiterhin mit ihren bisherigen Prüfungen.

Zusätzlich behoben: Der Schemasnapshot von `LearningJob` war seit 5.7.0 nicht an das neue
Feld `started_at` angepasst. Das Feld hat einen Standardwert; bestehende Zustände bleiben
gültig, eine Migration ist nicht nötig. Der Snapshot wurde bewusst neu geschrieben.

Abnahme S3: Vollständiger Python-Prüfpfad vor den letzten Ergänzungen 4727 bestanden;
danach 892 Web-, E2E-, Upgrade- und Themenprüfungen bestanden, neue Module 100 % Zeilen und
Branches. 13 neue Python-Tests für Vorschau, Bestätigung, Idempotenz, Sitzungsbindung,
Ablauf, Autorisierung, Konflikte und beschädigte Zustände; vier bestehende Tests auf den
zweistufigen Ablauf umgestellt. 18 Browserprüfungen (Desktop/Mobil/schmal, mit und ohne
JavaScript) für Übersicht, Bearbeitung, Vorschau und ID-Vorschlag.
