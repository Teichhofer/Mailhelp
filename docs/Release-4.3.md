# Release 4.3 – Aufgaben ohne Mengenfragen und sichere Terminserien

Version 4.3.0, 6. November 2026. Umsetzung und automatisierte Plattformabnahme abgeschlossen.

## Aufgaben und Zähler

Router und Aufgabenextraktor schließen rein werbliche Lese-/Downloadangebote und
unverbindliche Höflichkeitsweiterleitungen ausdrücklich aus. Eine echte persönliche
Verantwortung oder Frist bleibt eine Aufgabe. Positive Extraktionsergebnisse erhalten
keine Mengenfrage. Abweichende Zähler bleiben als `ExtractionCountConflict` in Zustand
und Diagnoseprotokoll. Liefert die Extraktion trotz positivem Routerzähler gar keinen
Vorschlag, erscheint einmalig ein verständlicher Hinweis zur manuellen Mailprüfung.
Andere Extraktionsarten und bereits gewonnene Vorschläge bleiben erhalten.

## Terminserien bedienen

Gleichnamige Termine derselben Quellmail erhalten einen normalisierten Serienschlüssel.
Bei mehreren Terminen ergänzt der Builder aufgelöste Daten im Titel. Der Grundtitel
bleibt für lokale und externe Dublettenprüfungen sowie Aktionsschlüssel erhalten.
Bestehende Akten erhalten die optionalen Metadaten beim Lesen ohne neue Version.

Eine eindeutige Zeitantwort in Telegram öffnet „Für alle N offenen Termine dieser Serie
übernehmen?“ mit „Alle“ und „Nur diesen“. Erst die Auswahl speichert neue Versionen.
Beginn- und Endfragen bleiben unterscheidbar; jeder Termin behält sein Datum.
Geänderte oder abgeschlossene Versionen werden ausgelassen und benannt. Andere offene
Telegram-Dialoge bleiben erhalten. Wiederholung und Neustart erzeugen keine zweite Revision.

Die Webübersicht fasst Serien in aufklappbaren Gruppen zusammen. Die Serienseite zeigt
Titel, Datum, Vorschlags-ID und Version. Beginn und optional Ende werden gemeinsam
gespeichert; einzelne Termine lassen sich ausnehmen oder separat bearbeiten. Ohne
JavaScript funktionieren dieselben Formulare. Nach einer geänderten Auswahl erscheint
die genaue neue Liste vor einer externen Sammelbestätigung nochmals.

Fehlt ein Ende, gilt die konfigurierte Standarddauer nur bei belegter Teilnahmeart.
Für Präsenztermine sind dies standardmäßig 180 Minuten. Unbekannte Teilnahmearten oder
fehlende Daten werden weiterhin fachlich geklärt. Explizite Zeiten haben Vorrang und
bleiben wie andere manuelle Angaben vor späterem Mailabgleich geschützt.

## Bestätigung und Wiederaufnahme

Speichern autorisiert keine Anlage. „Alle N Termine anlegen“ ist eine separate,
personen- beziehungsweise sitzungsgebundene Entscheidung über die angezeigte Liste.
Vor dem ersten Schreiben werden alle Versionen, offenen Fragen, Zielprofile und
Dublettenlagen geprüft. Eine Abweichung verwirft die gesamte Vorprüfung. Externe
Vorprüfungen halten keine gemeinsame Ablagesperre.

Ein dauerhaftes Serienjournal bewahrt die ausdrücklich freigegebenen Versionen und
den Fortschritt. Jeder Termin nutzt den bestehenden Schreibdienst mit eigenem
Idempotenzschlüssel und Abgleich unklarer Resultate. Bei einem Teilfehler können schon
angelegte Termine bestehen bleiben; eine atomare Transaktion über externe Kalender
gibt es nicht. Eine nach Beginn geänderte Version oder ungültige Sitzung stoppt die
übrigen Anlagen. Vor einem weiteren Versuch werden die einzelnen Ergebnisse geprüft.
CSRF und die erneute Sitzungsprüfung unmittelbar vor Schreibzugriffen bleiben verbindlich.

Vor dem Upgrade die gesamte Zustandsablage sichern. Eine Rückkehr zu 4.2 erfordert
deren passende Sicherung: Ältere strikte Leser kennen die neuen optionalen Felder und
Serienbefehle nicht. Neue Dateien heißen `series-offer-*`, `series-presentation-*` und
`series-receipt-*`; sie gehören zur dauerhaften Zustandsablage.

## Qualitätsnachweise

Der Korpus enthält 31 synthetische Fälle. Der Offline-Evaluierungspfad verwendet die
echte Schema-, Routing- und Normalisierungslogik mit simulierten Modellantworten.
Damit wird die bisherige Vertragsabdeckung erhalten; eine bessere Erkennungsrate
kostenpflichtiger Modelle oder Aussagen über private Produktionsmails folgen daraus
nicht. Die überprüfte Konfigurationsbaseline behält `model_quality_proven=false`.

| Prüfung | Ergebnis |
| --- | --- |
| Windows 11, Python 3.12.10 | 3.589 bestanden, ein POSIX-spezifischer Skip; 479,33 s |
| Ubuntu/WSL, Python 3.12.3 | 3.590 bestanden; 310,08 s |
| Python-Abdeckung auf beiden Plattformen | 24.431 Statements, 7.074 Branches; jeweils 100 % |
| Vollständige Browser-Suite | 237 bestanden; 555,17 s; 100 % JavaScript-Blöcke in `app.js`, `sw.js`, `setup.js` |
| Docker: neue Funktionen und bestehende Sicherheitsregressionen | 161 bestanden; 31,39 s; Netzwerk gesperrt |
| Docker: harte Prozessabbrüche und Wiederaufnahme | 28 bestanden; 65,68 s; zusätzlich Konfigurationsprüfung, Dienst- und Lernmodus-Neustarts bestanden |
| Ruff / mypy | Keine Befunde; mypy prüft 236 Quelldateien |
| Kern-Mutationsaudit | 1.039 / 1.065 getötet (97,56 %); 26 Überlebende einzeln bewertet; jeder Kernbereich über 90 % |

Die Regressionen für Mengenfragen, vorzeitige beziehungsweise erst spät blockierte
Sammelbestätigungen, Schutz manueller Zeitfakten, Änderungen während einer Anlage,
Erhalt eines anderen Telegram-Dialogs, Paketprompts und lesbare Datumsanzeigen
schlugen vor der jeweiligen Korrektur fehl und bestehen danach. Die vorgegebenen
Architekturgrenzen bleiben erhalten: gemeinsame Testhelfer liegen in `tests/fakes`,
der Revisionsschutz ist kanalunabhängig und neue Persistenztypen sind explizit registriert.

Die vollständigen Zahlen und Quelltext-Fingerprints stehen in der
[Gesamtabnahme](../quality-reports/quality-4.3.json), die einzelnen Mutanten im
[Mutationsaudit](../quality-reports/mutation-4.3.md) und der synthetische
[Offline-Evaluierungsbericht](../quality-reports/evaluation-4.3-offline.json) separat.
Alle automatisierten Dienste und Daten sind simuliert; es erfolgten keine echten
externen Anlagen oder kostenpflichtigen Modellaufrufe.
