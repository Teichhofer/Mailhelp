# Release 5.8 – Umsetzung und Abnahme

Status: Version 5.8.0 vollständig umgesetzt und automatisiert abgenommen, 11. November 2026.
Plan: [Planung 5.8](Planung-5.8.md).

Vorhandene Änderungen für 5.7.6 werden erhalten. Die UI-Arbeit baut auf diesem Arbeitsstand auf.
## Umgesetzte Arbeitspakete

| Paket | Ergebnis |
| --- | --- |
| S1 / UI-01, UI-06 | Bearbeiten → serverseitiger Prüfstand → ausdrückliche Übernahme. Feld- und YAML-Werte werden wirklich verglichen; die Bestätigung liest ausschließlich den beständigen Prüfstand. Neue Analyse unterhalb der offenen Vorschläge. |
| S2 / UI-02, UI-10 | Sichtbare Eingaben bleiben nach Schätzung und Fehlern erhalten. Ordnerauswahl je Postfach, zusätzlicher Freitext, lesender GET-Schritt ohne JavaScript. Konfigurierte Modelle und manuelle Preisannahme erkennbar. |
| S3 / UI-03, UI-11 | Deutsche Validierung, verknüpfte Hilfe und Fehler, fokussierte Zusammenfassung und kompakte Feldgruppen. Keine doppelte Bereichsnavigation auf der Einstellungsübersicht; Kacheln bleiben direkt erreichbar. |
| S4 / UI-04, UI-05 | Themenkopf und Filter verkürzt. Erste Themenzeile in allen drei Größen im ersten Bildschirm. Sekundäre Karteneinordnung und vollständige Fragen bleiben aufklappbar; aktuelle Rückfrage und Bestätigungsaktionen erreichbar. |
| S5 / UI-07, UI-08, UI-09, UI-12 | Einstellungsvergleich mit bisherigem/neuem Wert und konkreter Wirkung. Statusübersicht mit nächsten Schritten; aktuelle IMAP-Fehler weiterhin sofort sichtbar. Kompakte Lernkarten, korrekter Erstzustand, authentifizierte lesende Statusaktualisierung. Entscheidungstexte erläutern Zuordnen, Behalten, Verwerfen und Erledigt. |
| S6 | README, CHANGELOG, Spezifikation, Bedienung, Web-Einstellungen und eingebauter Hilfebestand aktualisiert. Abschließende Prüfresultate werden unten festgehalten. |

## Sicherheits- und Regressionstests

Die drei ursprünglichen Fehler für Regelvorschau, Eingabeerhalt und Formularfehler
wurden vor dem Fix reproduziert (`.test-tmp/ui58-red.log`) und danach bestanden
(`.test-tmp/ui58-green.log`). Der falsche Erstzustand ist ebenfalls vor/nach dem Fix
geprüft. Eine bestehende Browserregression erkannte während der Umsetzung, dass
aktuelle IMAP-Fehler durch das Einklappen der Betriebsdetails verschwanden; sie stehen
wieder außerhalb der technischen Details (`.test-tmp/ui58-imap-red.log`).

Neue Tests prüfen insbesondere:

- Geänderte Felder und vollständiges YAML, mehrere ausgewählte Themen einschließlich Neuanlage.
- Keine Regeländerung durch die Vorschau; keine Modellaufrufe durch Schätzung, Ordnerladen oder Übersicht.
- Nachträglich manipulierte Formwerte ersetzen den bestätigten Prüfstand nicht.
- „Weiter bearbeiten“ erhält Auswahl, Feldwerte und vollständiges YAML; Autorisierungsdaten werden nicht als Bearbeitungswerte gespeichert.
- Ersetzte Schlüssel, veraltete Version, fehlende Bestätigung und neue Analyse blockieren alte Vorschauen.
- Dateiänderung oder abgelaufene Sitzung vor Ausführung verhindert die Übernahme.
- Neustart und identische Wiederholung führen nicht zu einer zweiten Übernahme.
- Fehlerhafte Ablage, fehlende Postfächer, Eingabefehler und übergroße Abfragen bleiben ohne Schreibwirkung.
- Tastaturfokus, Fehlerlinks, Hell/Dunkel, drei Bildschirmgrößen und zentrale Abläufe ohne JavaScript.

Gemeinsame Testhilfen liegen unter `tests/fakes`; die bestehende Architekturprüfung
verhindert direkte Abhängigkeiten zwischen Testmodulen. Der bisherige Renderer-Vertrag
bleibt als Referenz erhalten: Alle alten Wörter und Bedienziele müssen einschließlich
ihrer Häufigkeit vorkommen; zusätzliche Erklärungstexte und umsortierte Metadaten sind erlaubt.

## Messungen

Synthetischer Vergleich mit dem Audit von 5.7.5; die Werte sind keine Aussage über
jede denkbare Mail oder jede Scrollposition.

| Messung | Vorher | 5.8 |
| --- | --- | --- |
| Erste Themenzeile, 390 × 844 | etwa 900 px ab Seitenanfang | im ersten Bildschirm |
| Erste Themenzeile, 320 × 640 | etwa 972 px ab Seitenanfang | im ersten Bildschirm |
| Drei Vorschlagskarten, 390 px Breite | 576 / 549 / 737 px hoch | 556 / 533 / 705 px hoch |
| Drei Vorschlagskarten, 320 px Breite | 685 / 605 / 793 px hoch | 641 / 589 / 761 px hoch |

Eine komplexe Karte kann weiterhin höher als ein kleiner Bildschirm sein. Vollständige
Belege, Rückfragen und notwendige Bestätigungen werden dafür nicht entfernt.

Visuell geprüfte Beispiele des Themenkatalogs: [Mobil hell](ui-5.8/themen-mobil-hell.png),
[Mobil dunkel](ui-5.8/themen-mobil-dunkel.png), [Desktop hell](ui-5.8/themen-desktop-hell.png),
[Desktop dunkel](ui-5.8/themen-desktop-dunkel.png). Ausschließlich synthetische Themen.

## Gesamtabnahme

Die verbindlichen Coverage-Grenzen bleiben bei 100 % Zeilen und 100 % Branches.
Zwischenläufe sind Diagnose und gelten nicht als abschließende Freigabe.

| Prüfung | Ergebnis |
| --- | --- |
| Windows, Python 3.12.10, `devtools.check full --workers 8` | 4799 bestanden, 1 plattformbedingter Skip; 100 % Zeilen und Branches (30437 Anweisungen, 8846 Branch-Ziele); 2 Lasttests bestanden. |
| Linux/Docker, Python 3.12.10, gleicher vollständiger Prüfpfad | 4800 bestanden; 100 % Zeilen und Branches (30437 Anweisungen, 8846 Branch-Ziele); 2 Lasttests bestanden. |
| Browser, Desktop/Mobil/schmal | 513 bestanden, 2 bestehende Skips; axe und Bedienprüfungen. 100 % JavaScript-Blockabdeckung in `app.js`, `sw.js`, `setup.js`, `topics.js` und `learning.js`. |
| Ruff, Mypy | Fehlerfrei; 287 Quelldateien typgeprüft. |
| Deterministische Hilfesuche und Prompt-Gate | Bestanden; Bestandteil der vollständigen Python-Abnahme. |

Nachweise: `.test-tmp/ui58-full5.log`, `.test-tmp/ui58-linux-full3.log`,
`.test-tmp/ui58-ui-full4.log`, `.test-tmp/ui58-ruff-all.log` und `.test-tmp/ui58-mypy.log`.
Der Linux-Lauf verwendet das vorhandene Testimage `mailhelp-test:5.6.0` mit einem
isolierten aktuellen 5.8-Quellstand unter `/workspace`, `PYTHONPATH=/workspace/src`
und ausgeschaltetem Netzwerk; getestet wird der aktuelle Quellstand, nicht der alte Image-Code.

Die letzte Synchronisationskorrektur betrifft einen bestehenden Test: Ausführung und
Annahmeprotokollierung werden über getrennte Warteschlangen bedient. Der Test wartet
auf das tatsächlich geschriebene Annahmeereignis, bevor er den Operator stoppt; die
Prüfung der parallelen Ausführung und ihre Zeitgrenze bleiben bestehen.

Der Anwendungscode blieb während der finalen Läufe bytegleich; SHA-256-Vergleich mit
`.test-tmp/ui58-source-hashes.csv`. Die Beispiele und Tests arbeiten ausschließlich
mit synthetischen Daten. Die drei ursprünglichen UI-Fehler sowie der Erstzustand,
die Checkbox-Fehlerzuordnung und die Rückkehr zur Bearbeitung sind durch Regressionen abgesichert.

Für eine bereits laufende Mailhelp-Instanz ist ein Neustart erforderlich, damit der neue
Python- und Oberflächencode verwendet wird. Die bisherigen Bestätigungsregeln gelten weiter.

## Grenzen

Alle automatisierten Prüfungen verwenden synthetische Daten und simulierte externe
Dienste. Keine echten Mails wurden übertragen, keine kostenpflichtigen Modelltests
gestartet und keine externen Kalendereinträge oder Aufgaben angelegt.

Die Browsergrößen sind Chromium-Emulation. Eine manuelle Prüfung mit echtem
iPhone/Safari, VoiceOver/NVDA und echtem Browserzoom 200/400 % ist damit nicht belegt.
Die automatisierte Linux-/Docker-Abnahme ist oben belegt; sie ersetzt keine manuelle
Echtgeräte- oder Screenreaderprüfung.
