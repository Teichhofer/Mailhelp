# Restprüfungen der letzten Promptfassung – 26.11.2026

Die angeforderten restlichen Prüfungen wurden ausgeführt. Die **Gesamtabnahme ist
nicht bestanden**. Prompts, Anwendungscode, Bewertungsgrenzen und eingefrorene
Korpora wurden während dieser Prüfphase nicht verändert. Zwei veraltete
Prompt-Vertragstests wurden korrigiert und gezielt nachgeprüft. Kein Deployment,
keine Kalenderänderung, kein Commit oder Push.

Grundlage: Git `cfe394f`, Python 3.12.10, Windows, letzte Promptfassung aus der
[vorherigen Verfeinerung](prompt-refinement-2026-11-26.md). Der Modellfingerabdruck
stimmt mit dieser Fassung und dem aktuellen Prompt überein; die Paketvorlage ist
identisch. Maschinenlesbare Ergebnisse: `remaining-tests-2026-11-26.json`.

## Vollständige Python-Prüfung

`python -m devtools.check full --workers 12` baute die Release-Pakete und führte
6.623 Tests aus: **6.619 bestanden, drei fehlgeschlagen, einer übersprungen**
in 696,79 Sekunden. **100 % Zeilen- und 100 % Branch-Abdeckung**:
42.500 Anweisungen ohne fehlende Zeile, 11.934 Branches ohne Teilabdeckung.

Die drei Fehler waren:

1. Das Prompt-Gate lehnt die geänderten Prompts ohne erfolgreich freigegebene
   Gesamtbaseline weiterhin korrekt ab. Es bleibt unverändert.
2. `test_perspective` verlangte weiterhin die alte pauschale Aussage zum eigenen
   Absender. Der Test prüft nun den bekannten eigenen Absender, `headers.to` und
   den Ausschluss eines Selbstauftrags für nach außen versandte Bitten. Die
   positiven Kontrollen für echte eigene Notizen bleiben erhalten.
3. `test_reply_needed` verlangte genau zwei Promptbeispiele. Nach Ergänzung der
   Beispiele prüft er stattdessen alle Beispielantworten auf explizite Antwortfelder
   und vollständige Gültigkeit nach `ActionRouteAnswer`. Kein Beispiel wird ausgelassen.

Nach diesen reinen Testkorrekturen bestanden **38 gezielte Tests** für Perspektive,
Antwortbedarf und die Promptregressionen (4,77 Sekunden). Der vollständige Lauf
wurde nicht nachträglich als grün umgedeutet oder mit neu berechneten Summen ersetzt.
Anwendungscode und Prompts blieben unverändert; der verbleibende Gatefehler ist offen.
Ruff und `git diff --check` bestehen für die beiden Teständerungen.

Da `devtools.check full` bei den Fehlern vor dem getrennten Lasttestschritt endet,
wurden die beiden vorgesehenen Lasttests anschließend separat ausgeführt:

`python -m pytest tests/services/test_load_action_start.py tests/services/test_load_result_latency.py --no-cov -q -s`

**2 bestanden**, 35,31 Sekunden. Median der Ergebnislatenz bei 2.000 Mails:
438,65 ms; maximale gemessene Ergebnislatenz 679,91 ms. Die unveränderten
Tests bewerten den Lauf als bestanden.

Lokale Protokolle: `.test-tmp/remaining-full.log`, `remaining-target.log` und
`remaining-load.log`. Die 100-%-Abdeckung wurde im vollständigen Lauf gemessen,
nicht aus den Tests ohne Coverage abgeleitet.

## Vollständige Browsersuite und JavaScript-Abdeckung

Erst nach Abschluss der Python- und Lasttests:
`python -m pytest ui_tests -n 6 --dist worksteal --no-cov`, mit frischem
`--basetemp` und eigenem Cache wegen früherer Windows-Zugriffsprobleme.
Der erforderliche WebKit-Browser `webkit-2336` wurde im lokalen ignorierten
Playwright-Cache bereitgestellt. Die früheren fehlenden WebKit-Programmdateien
blockieren die Prüfung damit nicht mehr.

**1.006 bestanden, 234 übersprungen, ein fehlgeschlagener Test**, keine Testfehler,
601,30 Sekunden. Fehlgeschlagen ist ausschließlich die Desktop-Latenzprüfung der
Einstellungssuche: gefordert sind mindestens 95 von 100 Suchläufen innerhalb
300 ms, gemessen wurden **76/100**, Median 269,3 ms, P95 356,4 ms.

Eine isolierte Nachprüfung ohne parallele Browserlast ergab **100/100**, Median
230,6 ms, P95 243,8 ms. Das belegt eine Lastabhängigkeit; es ersetzt den
fehlgeschlagenen Parallelbetrieb nicht. Die einzelne Testassertion bestand.
Der isolierte Befehl endete dennoch mit 1, weil der unveränderte Suite-Hook bei
dieser einzelnen Auswahl naturgemäß unvollständige JavaScript-Gesamtabdeckung
meldet. Dieser Exitcode wird nicht als erfolgreicher Suite-Lauf dargestellt.

Wegen des Latenzfehlers beendet der Hook auch die vollständige Suite vor seiner
zusätzlichen JavaScript-Abnahme. Deshalb wurden die sechs vorhandenen Workerberichte
des vollständigen Laufs separat mit den unveränderten Funktionen
`merge_worker_coverage` und `COVERAGE.uncovered` geprüft. Alle sechs Berichte sind
vorhanden und gültig. Ergebnis: **JavaScript-Abdeckung nicht vollständig**;
`settings.js` meldet noch die Zeilen **57 und 75** im Bereich des Änderungszählers
(verborgene Formularelemente und Zählertext). Es wurden keine Bereiche ausgeschlossen
oder wirkungslose Abdeckungstests ergänzt.

Details: `remaining-js-coverage-2026-11-26.json`. Lokale Protokolle:
`.test-tmp/remaining-ui.log` und `remaining-ui-latency-recheck.log`.

## Vollständige Modellevaluation der letzten Fassung

Der Nutzer genehmigte ausdrücklich bis zu **300 weitere kostenpflichtige
OpenRouter-Aufrufe**. Verwendet wurden die unveränderten Modelle und Parameter
aus `prompts.yaml` und `decisions_prompts.yaml`, ausschließlich der unveränderte
synthetische v4-Korpus mit 46 Fällen. Der Vergleich nutzt die ursprüngliche echte
Vorher-Messung und die eingefrorene Baseline. Weder Sollwerte, Alternativen noch
Schwellen wurden angepasst.

| Stufe | Bestandene Vergleiche |
| --- | ---: |
| Relevanz | 37/46 |
| Zusammenfassung | 40/46 |
| Aktionsrouter | 44/46 |
| Aufgabenextraktion | 45/46 |
| Terminextraktion | 41/46 |

Die strengere, unveränderte Aktionsbewertung ergibt sieben erkannte und neun
übersehene Aufgaben sowie sechs Aufgaben-Fehlalarme. Bei Terminen sind es
33 erkannte, drei übersehene und drei Fehlalarme. Ein Fall mit technischem Fehler
wird separat gezählt und nicht in die Erkennungsquote der erfolgreich bewerteten
Fälle eingerechnet. Insbesondere zählt der Titelvergleich weiterhin auch
abweichende Benennungen; die Unterschiede zu den akzeptierten Stufenalternativen
bleiben unverändert. Beide Ergebnisse sind dokumentiert, keines ersetzt das andere.

**Alle sieben kritischen Sicherheitsfälle bleiben ohne vorgeschlagene Aktion.**
Buchungsbestätigung und Stornierung bestehen nun vollständig einschließlich
Zeitart, Kalenderzuständigkeit und Ortsfeld. Die Gesamtprüfung scheitert dennoch an:

- Aufgaben-Erkennungsrate unter 90 %;
- mehr als zwei Aufgaben-Fehlalarmen;
- mehr als zwei Termin-Fehlalarmen und mehr Termin-Fehlalarmen als vorher;
- einem technischen Ausfall durch `LlmTokenLimitExceeded` bei
  `26_personal_schedule_plan`.

Der Tagesplan wurde einmal unverändert isoliert nachgeprüft. Dabei trat kein
Ausgabelimitfehler mehr auf, aber Relevanz und Terminextraktion weichen weiterhin
vom Soll ab. Der ursprüngliche Vollbericht mit seinem Ausfall bleibt unverändert;
die Einzelwiederholung wurde weder hineingemischt noch zur Freigabe verwendet.

| Messung | Aufrufe | Gemeldete Kosten USD |
| --- | ---: | ---: |
| Vollständiger letzter Prompt | 174 | 0,103075 |
| Einmalige technische Nachprüfung | 4 | 0,007020 |
| Diese Prüfphase | **178/300** | **0,110095** |

Über alle bisherigen Phasen: **814 Aufrufe, 0,503094 USD**. Vom vorherigen
Zusatzbudget waren 597/600 verwendet; die 178 Aufrufe stammen aus der neuen
gesonderten Freigabe. Es gibt keine weiteren kostenpflichtigen Wiederholungen.

Unveränderte Modellantworten und Vergleiche:
`prompt-final-full-v4-2026-11-26.json`, abgeleitete Antworten und Bewertung unter
`*-answers-*` und `*-metrics-*`. Die gesonderte technische Nachprüfung liegt in
`prompt-final-technical-recheck-2026-11-26.json`; ihr synthetischer Einzelkorpus
liegt daneben. Der Nachher-Qualitätsgate-Exitcode ist 1.

## Offene Abnahmebefunde

Die angeforderten Testläufe sind abgeschlossen. Für eine erfolgreiche Freigabe
müssen die Modell-Qualitätsbefunde, die Suchlatenz im Parallelbetrieb und die
JavaScript-Abdeckungslücken bearbeitet und erneut geprüft werden. Die beiden
Baselines bleiben unverändert. Alle Änderungen und Berichte sind lokal und noch
nicht committed oder gepusht; der Server wurde nicht verändert.
