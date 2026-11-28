# Frühere Anwesenheit: begrenzte Promptprüfung am 26.11.2026

Die Änderung betrifft ausschließlich `event_extraction` in `prompts.yaml` und
der identischen Paketvorlage. Ausdrückliche frühere Anwesenheit der teilnehmenden
Person bestimmt den Beginn; freiwillige Angebote und Aufbau anderer Rollen nicht.
Keine Produktivbereitstellung und keine Änderung bestehender Kalendereinträge.

Der Nutzer hat ausdrücklich höchstens 60 kostenpflichtige OpenRouter-Aufrufe
freigegeben. Verwendet wurden ausschließlich synthetische Nachrichten: vier neue
Anwesenheitsfälle sowie fünf unveränderte Kontrollfälle aus dem bestehenden Korpus
(`04_task_and_event`, `13_pure_invitation`, `14_invitation_registration`,
`19_invitation_time_pending`, `36_change_later_start`).
Der tatsächlich verwendete Korpus liegt in
`event-arrival-corpus-2026-11-26.json`, der unveränderte Messbericht mit Modellrouten,
Fingerabdrücken, Antworten und Vergleichen in `event-arrival-2026-11-26.json`.
Ausführung über den Einstiegspunkt `mailhelp.llm.evaluation.main` mit
`--allow-network --corpus quality-reports/event-arrival-corpus-2026-11-26.json
--prompts prompts.yaml --output <Bericht> --max-calls 60`, ohne Legacy-Relevanz.
Der API-Schlüssel wird ausschließlich aus der geheimen Umgebung bereitgestellt.
Gemessene Konfiguration: `deepseek/deepseek-v4.1-flash` für die generativen Stufen,
`typesafe/jev-1.13` für Relevanz, mit den unveränderten Parametern aus den beiden
Promptdateien (vollständig im Rohbericht aufgeführt).

## Ergebnis und fachliche Prüfung

39 Aufrufe, 122.742 Tokens, gemeldete Kosten 0,035458 USD; keine fehlenden
Verbrauchsangaben. Keine weiteren Aufrufe und keine produktiven Nachrichten.

| Stufe | Bestandene Fälle |
| --- | ---: |
| Relevanz | 9/9 |
| Zusammenfassung | 4/9 |
| Aktionszuordnung | 9/9 |
| Aufgabenextraktion | 9/9 |
| Terminextraktion | 9/9 |

Die vier neuen Terminantworten wurden zusätzlich fachlich gelesen:
Ankommen 13:40 statt Begrüßung 14:00; Check-in 09:10 statt Vortrag 09:45;
freiwilliger Kaffee 09:20 bleibt bei Beginn 10:00; Technikaufbau 09:30 bleibt
für den Gast bei Beginn 11:00. Endzeiten bleiben erhalten. Beschreibungen und
Belege unterscheiden Ankommen, Programm und Rollen korrekt. Normale Einladung,
Anmeldung, noch offene Uhrzeit und Verschiebung auf einen späteren Beginn bleiben
in den Kontrollfällen korrekt. Es werden keine Fahrtzeiten erfunden.

Der Gesamtlauf ist ausdrücklich **nicht bestanden**: In den vier neuen Fällen
und `36_change_later_start` liefert die unveränderte Zusammenfassungsstufe neben
dem Datum zusätzliche Uhrzeiten in `deadlines`. Der Vergleich normalisiert diese
zu einem zusätzlichen `<ohne Datum>` und weicht damit vom Soll ab. Die Rohantworten
und fehlgeschlagenen Vergleiche bleiben unverändert erhalten; weder Sollwerte noch
Bewertungslogik wurden angepasst. Die Terminextraktion ist davon separat bewertet.

Die Promptbaseline bleibt unverändert beim bisherigen Konfigurationsvertrag mit
`model_quality_proven: false`. Die begrenzte Prüfung belegt diese Terminregel,
keine vollständige Modell- oder Pipelineabnahme. Die erste Prüfung misst keine
Erfolgsquoten auf produktiven Mails oder Anhängen unterschiedlicher Formate;
der ergänzende vollständige synthetische v4-Vergleich ist unten dokumentiert.
Offline-Regressionen prüfen zusätzlich die Promptbeispiele und Normalisierung bis
zum unbestätigten Vorschlag; sie ersetzen die hier dokumentierte Modellevaluation
nicht. Die vor der Änderung fehlgeschlagenen Regressionen und die vollständigen
lokalen Prüfungen werden im Abschlussstand dokumentiert.

## Lokale Gesamtprüfung

`python -m devtools.check full --workers 12` baute beide Pakete und führte
6.576 Tests aus: 6.571 bestanden, einer übersprungen, vier fehlgeschlagen
(788,10 Sekunden). Die kombinierte Abdeckung erreichte 99,55 %, somit scheitert
die verbindliche 100-%-Schwelle. Die fehlenden Bereiche liegen in parallel
bearbeiteten Kunden-/Verbrauchsseiten; diese Promptänderung enthält keinen
Anwendungscode. Der Arbeitsstand änderte sich während des Laufs.

Fehler: `test_quality_baseline` vergleicht zusätzlich die eingefrorene
Gesamtqualitätsbaseline `baseline-5.1.json` mit dem aktuellen Promptvertrag.
Diese historische Baseline bleibt unverändert: Ihre Vorher-/Nachher-Abnahme auf
dem vollständigen v4-Korpus ist durch neun ausgewählte Fälle nicht erbracht.
Die begrenzte Konfigurationsprüfung ersetzt diesen Qualitätsnachweis nicht.
Nach Prüfung der strengeren Vorgabe wurde die vorläufige Aktualisierung von
`prompt-baseline.json` zurückgenommen. Beide Baselines bleiben unverändert;
das Prompt-Gate verweigert deshalb weiterhin die Übernahme des Entwurfs.
Weitere Fehler betreffen englische Texte und
Kundenrouten in parallelen Änderungen sowie einen Windows-Zugriffsfehler beim
Umbenennen eines synthetischen Demo-Verzeichnisses. Das lokale Laufprotokoll
liegt unter `.test-tmp/arrival-full.log` (nicht in Git).

Damit ist die Änderung lokal implementiert und gezielt geprüft, jedoch **nicht
vollständig zur Veröffentlichung abgenommen**. Die eingefrorene Qualitätsbaseline
und die Coverage-Grenze werden nicht angepasst, um den Lauf grün erscheinen zu lassen.

Browserprüfung anschließend separat mit sechs Workern:
`python -m pytest ui_tests -n 6 --dist worksteal --no-cov` (zusätzlich frisches
`--basetemp` und eigener Cache wegen Windows-Zugriffsrechten). Ergebnis:
976 bestanden, 234 übersprungen, 22 fehlgeschlagen, neun Testfehler,
946,59 Sekunden. Betroffen sind Kunden-Lernseiten, OAuth, Charts, Hilfefenster,
Notion, Suche, Demo und WebKit/iOS; mehrere synthetische OAuth-Zielseiten melden
`ERR_CONNECTION_REFUSED`. Der Browserlauf ist nicht bestanden.
Bei den WebKit/iOS-Fehlern fehlt konkret das Playwright-Browserprogramm
`webkit-2336/Playwright.exe` in der lokalen Installation.
Protokoll: `.test-tmp/arrival-ui.log` (nicht in Git). Der erste Start scheiterte schon an
einem nicht zugänglichen alten Tempverzeichnis; erst der zweite ist der hier
berichtete vollständige Lauf. Die Promptänderung enthält keine UI-Änderungen;
die Ursachen dieser allgemeinen Fehler werden nicht ohne Einzelprüfung der
Promptänderung zugeschrieben.

Für die v4-Vorher-/Nachher-Prüfung wurde eine zusätzliche, ausdrückliche Netzwerk-
und Budgetfreigabe für höchstens 600 zusätzliche Aufrufe erteilt. Die vollständige
Auswertung folgt unten. Schwellen, Korpus und Baselines bleiben wegen der nicht
bestandenen Prüfung unverändert.
Alle hier beschriebenen Änderungen sind lokal und noch nicht committed oder
gepusht. Es gab keine Server- oder Kalenderänderung.

Abschließende gezielte Nachprüfung nach Rücknahme der Baseline-Aktualisierung:
acht Anwesenheitsregressionen, vier Tests der eingefrorenen Qualitätsbaseline
und drei Prompt-Gate-Tests. 14 bestanden, ein erwarteter Fehler im Prompt-Gate:
Der Entwurf hat noch keine neue vollständig freigegebene Baseline. Protokoll
`.test-tmp/arrival-final.log`. Die frühere gezielte Prüfung von Extraktion,
Normalisierung, Promptkonfiguration und Dokumentation bestand mit 151 Tests.

## Vollständiger v4-Vergleich nach zusätzlicher Freigabe

Beide Läufe verwenden dieselben 46 synthetischen Fälle des eingefrorenen v4-Korpus,
dieselbe Relevanzkonfiguration, dieselben Modelle und Parameter und jeweils höchstens
300 Aufrufe. Der Vorher-Prompt stammt aus dem bisherigen Git-Stand; der Nachher-Prompt
enthält ausschließlich die zusätzliche Anwesenheitsregel mit Beispielen. Korpus- und
Relevanzfingerabdrücke stimmen überein; der Nachher-Fingerabdruck wurde gegen den
lokalen Entwurf geprüft, ebenso die Übereinstimmung mit der Paketvorlage.

| Lauf | Fälle | Aufrufe | Gemeldete Kosten USD |
| --- | ---: | ---: | ---: |
| Vorher | 46 | 175 | 0,106811 |
| Nachher | 46 | 174 | 0,095685 |
| Zusätzlich insgesamt | 92 | 349 von höchstens 600 | 0,202496 |

Mit der ersten gezielten Evaluation wurden insgesamt 388 Aufrufe und 0,237954 USD
verwendet. Es gab in beiden vollständigen Läufen keine technischen Ausfälle oder
unlesbaren Antworten. Nicht verbrauchte Freigaben wurden nicht ausgeschöpft.

Die unveränderte Aktionsbewertung `quality_metrics` ergibt:

| Automatischer Messwert | Vorher | Nachher |
| --- | ---: | ---: |
| Aufgaben erkannt / erwartet | 7/16 | 8/16 |
| Aufgaben übersehen | 9 | 8 |
| Aufgaben-Fehlalarme | 8 | 7 |
| Termine erkannt / erwartet | 35/38 | 35/38 |
| Termine übersehen | 3 | 3 |
| Termin-Fehlalarme | 2 | 3 |

Alle sieben kritischen Fälle bleiben ohne vorgeschlagene Aktion. Die vollständige
Abnahme ist dennoch **nicht bestanden**: vorher scheitern Aufgaben-Erkennungsrate
und Aufgaben-Fehlalarme; nachher zusätzlich die Termin-Fehlalarmgrenze und der
Vorher-/Nachher-Vergleich der Termin-Fehlalarme. Die Baselines bleiben unverändert,
der Entwurf wird weder veröffentlicht noch auf den Server übertragen.

Die Aufgabenbewertung vergleicht Titel mit mindestens 50 % Wortüberschneidung.
Sie zählt deshalb teilweise fachlich ähnliche Benennungen als verpasst und als
Fehlalarm, etwa „Reisekostenbelege einreichen“ gegenüber „Belege für
Reisekostenabrechnung einreichen“. Es gibt außerdem tatsächlich fehlende oder
zusätzliche Aufgaben. Die Rohzählungen werden beibehalten; weder Titel-Sollwerte
noch Vergleichsalgorithmus oder Schwellen wurden für diese Änderung angepasst.

Der zusätzliche Termin-Fehlalarm entsteht ausschließlich in
`23_booking_confirmation`: vorher kein Termin, nachher „Buchung Stellplatz 3“
mit Zeitart `required_unknown` und Zuständigkeit `other`. Erwartet ist
„Stellplatzbuchung Familie Weber“, `all_day`, Zuständigkeit `user`.
Neben der fehlenden Titelzuordnung gibt es also fachliche Abweichungen bei
Zeitart und Zuständigkeit. Aus einem einzelnen Vorher-/Nachher-Lauf lässt sich
ihre Ursache nicht sicher der Promptänderung zuschreiben; für die Abnahme zählt
der dokumentierte ungünstigere Messwert. Die 46 semantischen Terminvergleiche
haben in beiden Läufen dieselben Bestehenswerte (42/46); das ersetzt die strengere
Aktionsprüfung nicht. Die neun gezielten Terminextraktionen bleiben bestanden.

Maschinenlesbare Zusammenfassung: `event-arrival-v4-comparison-2026-11-26.json`.
Unveränderte Modellantworten und Stufenvergleiche:
`event-arrival-v4-before-2026-11-26.json` und
`event-arrival-v4-after-2026-11-26.json`.
Abgeleitete echte Antworten (`*-answers-*`) und Bewertungsberichte
(`*-metrics-*`) liegen daneben. Die Auswertung erfolgt mit `--source model`,
`--baseline quality-reports/baseline-5.1.json` und für Nachher zusätzlich
`--before quality-reports/event-arrival-v4-before-metrics-2026-11-26.json`.
Der Exitcode des Nachher-Qualitätsgates ist 1; der umgebende Messlauf wurde
ordnungsgemäß abgeschlossen. Es folgten keine kostenpflichtigen Wiederholungen.

Nach dem vollständigen Vergleich wurden Anwesenheitsregressionen, eingefrorene
Qualitätsbaseline, Prompt-Gate und Dokumentationsprüfung erneut ausgeführt:
22 bestanden, ein erwarteter Fehler des unveränderten Prompt-Gates wegen der
fehlenden erfolgreichen Gesamtabnahme (13,48 Sekunden). Protokoll:
`.test-tmp/arrival-v4-check.log`. Keine erneute vollständige Python-/Browserprüfung,
weil Prompt und Anwendungscode in dieser Phase unverändert blieben und lediglich
Messberichte und Dokumentation ergänzt wurden; die allgemeinen Fehler der oben
berichteten Gesamtprüfungen werden dadurch nicht als behoben dargestellt.
