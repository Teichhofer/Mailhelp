# Release 5.6 – Themenregeln aus Entscheidungen

Version 5.6.0, 11. November 2026. Grundlage: [Planung 5.6](Planung-5.6.md).
Ausgangsstand: 5.5.7. Die Arbeitspakete E1–E6 werden gemeinsam als 5.6.0 ausgeliefert.

## Verhalten

Unter `/themen/lernen` werden vorhandene Entscheidungen aus
`<data_directory>/<test|production>/learning/decisions.jsonl` ausgewertet. Test- und
Produktionsbestand bleiben getrennt. Es werden keine Mails abgerufen. Der Miner liest höchstens das letzte
Megabyte, betrachtet höchstens 200 vollständige Zeilen und verwendet höchstens 100
eindeutige verwertbare Belege, neueste zuerst. Fehlerhafte Zeilen einschließlich ungültigem
UTF-8 werden übersprungen. Ablehnung eines Vorschlags bedeutet nicht automatisch irrelevante
Mail; „bereits erledigt“ bleibt ein positives Relevanzsignal. Korrekturen, explizite
Relevanzabweichungen und Bestätigungen ohne Themenzuordnung werden getrennt gezählt.

Erst eine authentifizierte Bestätigung startet die möglicherweise kostenpflichtige
Übertragung begrenzter Betreff-/Textauszüge, Antworten, Korrekturen und Themenregeln.
Bekannte Zugangsdaten werden vor der Übertragung entfernt; dies ist kein allgemeiner
Detektor für beliebige vertrauliche Angaben in Mailtexten. Der optionale Prompt
`decision_rule_learning` verwendet die aktive Modellroute `action_router`, vorhandene
Provider, Budgets, Nutzlastgrenzen und Wiederholungsregeln. Es gibt keinen eigenen
Modellclient. Sitzungsberechtigung und Dateihashes werden vor jedem Modellversuch erneut
geprüft. Alte eigene `prompts.yaml` bleiben gültig; für diese Funktion muss der neue
Promptblock aus dem mitgelieferten Beispiel übernommen werden.

Die KI liefert höchstens 20 streng validierte Vorschläge mit vorhandenen Beleg-IDs.
Links steht die bisherige Regel, rechts die bearbeitbare Fassung mit markierten Änderungen;
Begründung und Belege sind einsehbar. Nur ausgewählte, gesondert bestätigte Vorschläge
werden übernommen. Vollständiges Themen-YAML kann die Formularwerte ersetzen. Der gesamte
Ablauf funktioniert auch ohne JavaScript. Eine neue Analyse ersetzt einen bisherigen
Prüfentwurf; laufende Analysen und unvollständige Übernahmen blockieren weitere Starts.

## Validierung und Wiederaufnahme

Vor jedem Schreiben werden beide vollständigen Dokumente geparst und gegen
`TopicsConfig`, `IrrelevantTopicsConfig` und das strengere `RuleTopic` geprüft. Unbekannte
Felder, doppelte YAML-Schlüssel, unsichere Tags und nicht passende Typen werden abgewiesen.
IDs müssen dokumentübergreifend eindeutig sein, `[a-z0-9_-]+` entsprechen und höchstens
64 Zeichen haben. Bestehende IDs und Postfachbereiche bleiben unverändert; neue Bereiche
müssen konfigurierte Postfächer referenzieren. Name und Beschreibung sind nicht leer und
höchstens 200 bzw. 1000 Zeichen lang. Beispiele und Ausschlüsse enthalten jeweils höchstens
30 nicht leere Einträge mit maximal 500 Zeichen. Mindestens ein relevantes Thema bleibt
aktiv. Die Serialisierung vereinheitlicht die Formatierung beider Themendateien;
YAML-Kommentare werden nicht übernommen. Parser-, Schema- und Revisionsfehler schreiben keine Themendatei; Eingaben bleiben
zur Korrektur im Formular erhalten.

Webaktionen benötigen Sitzung, CSRF, Auftragsversion, Idempotenzschlüssel und ausdrückliche
Bestätigung. Die zwei Themendateien und `config.yaml` werden vor und nach der Validierung
auf Änderungen geprüft. Erst danach wird das geprüfte Übernahmejournal dauerhaft gespeichert.
Jede einzelne Datei wird atomar ersetzt. Dies ist keine gleichzeitige Betriebssystem-
Transaktion über zwei Dateien: Bei einem Schreibabbruch kann eine Datei schon aktualisiert
sein. Das Journal erlaubt nach erneuter Anmeldung und ausdrücklicher Bestätigung das sichere
Abschließen. Bereits geschriebene eigene Inhalte werden erkannt; fremde Änderungen verhindern
das Fortsetzen. Dabei gibt es keinen weiteren Modellaufruf. Doppelte identische Bestätigungen
werden nicht erneut ausgeführt.

Die relevanten Themen werden am nächsten sicheren Verarbeitungspunkt für neue Analysen
aktiviert. Bestehende Vorschläge oder externe Einträge werden nicht verändert. Die Datei
`irrelevant_topics.yaml` behält ihre bisherige Bedeutung in Lern- und Entscheidungstestmodi;
für normale Mailanalysen gelten relevante Themen einschließlich ihrer Ausschlüsse.

Ein Auftrag gehört seiner Websitzung. Fremde Sitzungen sehen keine privaten Belege. Nach
24 Stunden werden private Auftragsinhalte verworfen; die leere Revision bleibt dauerhaft
erhalten, damit alte Startbestätigungen auch nach Neustart nicht wieder gültig werden.
Die Ablaufprüfung läuft unter derselben Zustandsperre. Das minimale Journal einer bereits bestätigten
unvollständigen Übernahme bleibt zur Wiederaufnahme bestehen. Nach Prozessneustart werden
wartende und laufende Analysen als unterbrochen markiert und nicht automatisch wiederholt.
Es entstehen keine Kalender-, Todoist- oder sonstigen externen Schreibaktionen.
Späte KI-Antworten werden nur bei weiterhin passender Eigentümersitzung, laufendem Status
und unveränderter Auftragsversion gespeichert; sie ersetzen keinen neueren Auftrag.

## Abnahme

Die automatisierten Prüfungen verwenden synthetische Entscheidungen und simulierte Anbieter.
Es wurden keine echten Entscheidungsprotokolle an ein Modell übertragen.

| Prüfung | Ergebnis |
| --- | --- |
| Windows, Python 3.12.10, `devtools.check full --workers 8` | 4702 bestanden, 1 plattformbedingter Skip; danach 2 Lasttests bestanden |
| Linux/Docker, Python 3.12.10, derselbe vollständige Prüfpfad | 4703 bestanden; danach 2 Lasttests bestanden; Container ohne Netzwerk während der Tests |
| Gesamter eigener Python-Code einschließlich Devtools | 29792 Anweisungen und 8680 Branch-Ziele, jeweils 100 %, keine fehlenden Zweige, keine neuen Coverage-Ausschlüsse |
| Abschließende Python-Nachprüfung | 101 bestanden unter Windows und Linux; neue Module jeweils 100 % Zeilen und Branches |
| Ruff (`src`, `devtools`, `tests`, `ui_tests`) und Mypy | fehlerfrei; Mypy: 276 Quelldateien |
| Paket-/Hilfebestand | Wheel und Sdist gebaut, Hilfebestand aktuell; Planspezifikation und Releasebericht im Sdist enthalten |
| Neue Browserabläufe | Analysefreigabe, Vergleich, Hand-Edit, YAML-Fehler, Dateikonflikt und Übernahme auf Desktop/Mobil/schmal, auch ohne JavaScript geprüft |
| Gesamte Browserprüfung | 471 bestanden, 2 vorgesehene Skips; 100 % JavaScript-Blöcke in `app.js`, `sw.js` und `setup.js`; unveränderte 300-ms-Suchlatenzprüfung bestanden |

Der letzte Schutz gegen verspätete Antworten wurde nach dem Gesamtlauf mit allen 101
Regellern-Tests erneut geprüft. Unter Windows wurde diese Nachprüfung an die vollständige
Coverage-Messung angehängt: unverändert 100 % des gesamten eigenen Codes. Unter Linux wurde
nach Wegfall des temporären WSL-Verzeichnisses ein frischer öffentlicher Snapshot verwendet;
die Nachprüfung der betroffenen Module erreicht ebenfalls 100 %.

Der abschließende vollständige Browserlauf ist fehlerfrei. Im ersten Lauf unter paralleler
Windows-/Linux-Testlast verfehlte der bestehende Suchlatenztest die unveränderte 300-ms-Grenze
(66 von 100, p95 400,3 ms). Ein bestehender Desktop-Profilwechseltest verwendete außerdem
einen globalen Statusselektor, obwohl Liste und Detailansicht dieselbe Rückmeldung zeigen.
Dieser Test wurde auf den ausgewählten Vorgang eingegrenzt; der Fehler wurde vorher
reproduziert und die drei Bildschirmvarianten bestehen danach. Die Produktfunktion und
ihre gesonderte Bestätigung bleiben unverändert.
Ein weiterer bestehender Resize-Test wartet jetzt auf die tatsächlich erreichte Fensterposition
innerhalb des Viewports, bevor er dieselben Grenzen prüft; die vorherige sofortige Abfrage
konnte vor dem Browserereignis erfolgen. Alle drei Varianten bestehen. Der synthetische
Testserver meldet Fehlerklasse und Route eines fehlgeschlagenen Requests für die Diagnose.

Zusätzliche Regressionen wurden vor und nach den jeweiligen Korrekturen ausgeführt:
wiederholte identische Webübernahme, ungültiges UTF-8 im Protokoll, Geheimnisentfernung beim
Kürzen großer Nutzlasten, dauerhafte Revision nach Auftragsablauf, späte Antworten bei neuerem
Auftrag und getrennte Beschriftungen im Vergleichsformular. Die Prüfung
umfasst Abmeldung vor Ausführung, Sitzungsentzug während Validierung, alte Versionen,
veränderte Dateien, korrupte Zustände, Neustarts und unvollständiges Schreiben beider Dateien.
