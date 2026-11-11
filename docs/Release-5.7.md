# Release 5.7 – Lernen und Themenverwaltung

Grundlage: [Planung 5.7](Planung-5.7.md), Ausgangsstand 5.6.0.
Die Arbeitspakete werden einzeln als 5.7.0–5.7.5 committet.

| Paket | Version | Stand |
| --- | --- | --- |
| S1: Gemeinsame Lernübersicht | 5.7.0 | umgesetzt, gezielte Abnahme |
| S2: Themenübersicht | 5.7.1 | umgesetzt, gezielt abgenommen |
| S3: Themenbearbeitung mit Vorschau | 5.7.2 | umgesetzt, gezielt abgenommen |
| S4: Gemeinsame Gestaltung | 5.7.3 | umgesetzt, gezielt abgenommen |
| S5: Dokumentation und Hilfe | 5.7.4 | umgesetzt, gezielt abgenommen |
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

## S4 – Gemeinsame Gestaltung

Themenvorschau und Regellernen zeigen Änderungen mit demselben Vergleich: nur geänderte
Felder offen, Listen zeilenweise als „+ neu“ / „− entfernt“, unveränderte Felder eingeklappt.
Die Prüfansicht des Regellernens hat eine Zusammenfassung mit Sprunglinks, die Auswahl im
Kopf jeder Karte, eine kurze Belegliste mit aufklappbarem Auszug und eine feste Aktionsleiste
mit Auswahlzähler (`learning.js`, ohne Skript serverseitig). Das Lernlauf-Startformular ist
in Schritte gegliedert. Abzeichen tragen ihre Bedeutung als Text.

Abweichung von der Planung: Die Ordner des Lernlaufs bleiben ein Textfeld mit der Liste der
verfügbaren Ordner darunter. Auswahlfelder je Ordner hätten ohne JavaScript nicht zum
gewählten Postfach gepasst; ein Postfachwechsel hätte einen zusätzlichen Seitenaufruf erfordert.
Vollständige Belegauszüge und Antworten bleiben verfügbar, sind aber eingeklappt.

Gefunden und behoben während der Browserprüfung: Die feste Aktionsleiste verdeckte auf
kleinen Bildschirmen das zuletzt in den sichtbaren Bereich gescrollte Bedienelement.
`scroll-padding-bottom` hält gescrollte und fokussierte Elemente oberhalb der Leiste.

Bereits seit 5.7.1 scheiterte die Browserprüfung `test_window55_the_chat_button_stays_usable_over_a_confirmation_form`: Sie öffnete `/themen` und erwartete dort ein Bestätigungsformular, das die Themenübersicht nicht mehr hat. Die Prüfung verwendet jetzt die Bestätigung der Themenvorschau und prüft weiterhin, dass das Formular (als feste Leiste mit z-index 4) unter Hilfefenster und Chatknopf bleibt.

Abnahme S4: 2955 bestehende Python-Tests (Web, Dienste, Unit) bestanden; fünf neue Tests für
Vergleich, Zusammenfassung, Belege und Auswahlzähler; die nicht mehr benötigte Funktion
`value_text` wurde durch den gemeinsamen Vergleich ersetzt und ihr Test übertragen. 25 Browserprüfungen
für Regellernen, Themenbearbeitung und Lernlauf auf Desktop/Mobil/schmal mit Barrierefreiheitsprüfung
(axe, WCAG 2.1 AA), mit und ohne JavaScript. `learning.js` ist Teil der verbindlichen Browser-Coverage.

## S5 – Dokumentation, Hilfe und Suche

Bedienungsanleitung, Web-Einstellungen, Projektspezifikation, README und CHANGELOG
beschreiben die neuen Wege. Der Abschnitt „Aus Entscheidungen lernen“ steht jetzt im
Lernkapitel der Bedienungsanleitung statt unter „Weitere Seiten“; seine Kennung bleibt gleich.
Der Hilfebestand wurde neu erzeugt. Neue deterministische Prüfungen stellen sicher, dass
Fragen zum Regellernen, zur Lernübersicht, zur Themenbearbeitung und zur Themensuche die
passenden Abschnitte erreichen und die Anleitung die tatsächlichen Bedienelemente nennt.

Während der Umsetzung verdrängte das zunächst geplante Synonym „Themenregeln“ wegen seines
Wortstamms („theme“) bei der bestehenden Frage „Wie übernehme ich die gelernten Themen?“ den
richtigen Abschnitt vom ersten Platz. Die bestehende Regression aus 5.5.6 erkannte das; das
Synonym wurde entfernt. „Themenregeln“ findet die Seite weiterhin über ihre Beschreibung.

Nicht durchgeführt: die in der Planung genannte Prüfung des Hilfschats mit dem echten,
kostenpflichtigen Modell. Sie erfordert eine ausdrückliche Freigabe für einen bezahlten Lauf
und kann mit dem Prüfskript aus 5.5.7 nachgeholt werden.

Abnahme S5: 1590 Unit- und Webprüfungen bestanden, darunter 11 neue Prüfungen für Hilfe und Suche.
