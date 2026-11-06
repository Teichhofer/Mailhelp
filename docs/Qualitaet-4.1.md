# Qualitätsprüfung 4.1

Stand: 6. November 2026, Version 4.1.11. Die Umsetzung umfasst alle Schritte
9.1 bis 9.14; die vereinbarte Zeitabnahme gilt für gezielte TDD-Tests.

## Reproduzierbare Aufgaben

Voraussetzung: Repository-Checkout, Python 3.12 und die Projektabhängigkeiten aus `requirements.lock`
und `requirements-lint.lock`; für den Paketbau zusätzlich `hatchling==1.27.0`.
Unter Linux wird für die vollständige Abhängigkeitssperrprüfung außerdem
`requirements-mutation.lock` installiert. Unter Windows sind dessen Einträge über
Plattformmarker deaktiviert.
Browserprüfungen verwenden die in `pyproject.toml` festgelegten UI-Abhängigkeiten und Chrome.

| Befehl | Prüfung |
| --- | --- |
| `python -m devtools.check tdd <Testdatei oder Node-ID>` | Ausdrückliche TDD-Auswahl; Gesamtzeit strikt unter 15 s |
| `python -m devtools.check fast` | Alle nicht als `slow`, `process` oder `e2e` markierten Tests mit xdist und Workstealing; Laufzeitbericht |
| `python -m devtools.check full` | Aktuelle Pakete bauen, danach sämtliche Python-Tests mit 100 % Zeilen- und Branch-Abdeckung einschließlich `devtools` |
| `python -m devtools.check ui` | Lokaler Playwright-Smoke |
| `python -m devtools.check prompts` | Synthetischer Evaluierungspfad und konservativer Fingerprint-Schutz |
| `python -m devtools.check mutation` | Linux: vollständiger Kern-Mutationslauf, JSON-Export und mindestens 90 % getötete Mutanten insgesamt und je Kernbereich |

`fast --workers 2` begrenzt die Workerzahl. Die Zeitmessung umfasst den Start aller
Worker und deren Abschluss. `.test-tmp/fast-report.json` speichert das Ergebnis;
`.test-tmp/tdd-report.json` dokumentiert die gezielte Auswahl einschließlich Startzeit.
Nach den Messungen wurde gemeinsam festgelegt, das 15-Sekunden-Ziel auf gezielte
TDD-Tests zu beschränken und die gesamte Schnellsuite anhand ihrer Messwerte zu
bewerten. Die Testauswahl der gesamten Schnellsuite wird dafür nicht verkleinert.
`--max-seconds` setzt eine ausdrückliche eigene Zeitgrenze.
Vor einem Schnelltest nach Paketänderungen einmal `python -m hatchling build`
ausführen: Die enthaltene Paketprüfung vergleicht die aktuellen Artefakte.
`full` erledigt den Paketbau automatisch. `full --workers 4` parallelisiert
gewöhnliche Tests mit `loadgroup`; sämtliche Prozess- und E2E-Tests erhalten
eine gemeinsame Gruppe und laufen darin nacheinander. Ohne Workerangabe bleibt
der Volltest sequenziell. Die Schnellsuite verwendet weiterhin Workstealing.

Die VS-Code-Tasks in `.vscode/tasks.json` verwenden den ausgewählten Python-Interpreter.
Die vollständige CI prüft weiterhin Windows und Ubuntu; `.github/workflows/mutation.yml`
ergänzt den wöchentlichen und manuell auslösbaren Linux-Mutationslauf.

## Mutationsverfahren

Installation unter Linux/WSL: `python -m pip install -r requirements.lock -r requirements-mutation.lock`
und `python -m pip install --no-deps -e .`.
Die festgeschriebene Werkzeugversion ist mutmut 3.8.0. Der Mutationsumfang bleibt
`domain`, `storage.py` und `external/confirmed.py`. Prozess- und Containerprüfungen
bleiben Teil der vollständigen Abnahme und laufen nicht gegen Mutationen, die ihre
Kindprozesse nicht sehen. Protokollsignaturen ohne Funktionskörper werden nicht mutiert.
Es werden keine Coverage-Ausschlüsse eingeführt.
`max_stack_depth = 4` begrenzt die Zuordnung zufälliger indirekter Aufrufe zu einer
Mutation. Direkte Modell-, Speicher- und Bestätigungsprüfungen bleiben relevant;
die vollständige Suite prüft unverändert alle Anwendungspfade. Der Wert schließt
keine Quelldatei und keine Anwendungszeile von der Coverage aus.
Die Mutationsauswahl führt die direkten Kernprüfungen aus `test_mutation_invariants.py`,
`test_core.py`, `test_validation_boundaries.py`, `test_v13_domain.py` und
`test_mail_timestamps.py` aus. Sämtliche
erzeugten Kern-Mutanten müssen eine Testzuordnung erhalten; ungetestete Mutanten lassen
die Schranke scheitern. Die vollständige Python-Suite bleibt die eigenständige
100-%-Abnahme. Direkte Invariantentests laufen innerhalb des Mutationslaufs zuerst.

`mutants/mutmut-cicd-stats.json` ist der maschinenlesbare Bericht.
`python -m mutmut results` nennt überlebende Mutanten,
`python -m mutmut show <Mutantenname>` zeigt deren Änderung.
Die Schranke berechnet ausschließlich `killed / total`; Timeouts und ungetestete
Mutanten werden nicht als erkannt gezählt. Ein Lauf ohne Mutanten ist ungültig.
Der Linux-Benutzer darf nicht Root sein, da Root die Rechteprüfung schreibgeschützter
Konfigurationsverzeichnisse umgeht.

## Prompt-Regressionsschutz

Der synthetische Evaluierungstest prüft Verarbeitung, Stufen, Routen und aktive
Korpusthemen. Vorgegebene Antworten belegen keine echte Modellqualität. Deshalb
verweigert der ergänzte Fingerprint-Schutz jede Änderung an `prompts.yaml`,
`topics.yaml`, `decisions_prompts.yaml` oder Korpus v3 gegenüber der überprüften
Konfigurationsbasis. Windows- und Linux-Zeilenenden werden gleich behandelt.

Die Ausgangsbasis trägt ausdrücklich `model_quality_proven: false`. Eine neue
Baseline darf erst nach fachlicher Prüfung und echter, budgetierter Evaluation
freigegeben werden. Automatisierte Tests bleiben vollständig offline und verwenden
synthetische Daten. Ein grüner Offline-Test wird nicht als gemessene
Erkennungsquote eines echten Modells ausgegeben.

## Abnahme und Messungen

Die vollständige Windows-Abnahme mit vier Workern und sequenzieller Prozessgruppe
bestand mit **3.436 Tests in 364,78 s**. Der entsprechende Quelltextstand erreicht
**100 % Zeilen- und 100 % Branch-Abdeckung**: 23.927 Statements und 6.906 Branches,
einschließlich `devtools`. Die abschließende Linux-Vollabnahme mit vier Workern
und derselben sequenziellen Prozessgruppe bestand mit **3.458 Tests in 256,48 s**
bei derselben vollständigen Abdeckung; sie enthält auch alle zuletzt ergänzten Invarianten.
Die neuen Qualitätswerkzeuge erreichen separat ebenfalls 100 % Zeilen- und
Branch-Abdeckung (36 Tests, 83 Statements, 28 Branches).

Die endgültige TDD-Auswahl `tests/unit/test_mutation_invariants.py` bestand unter
Windows (Python 3.12.10) mit **144 Tests in 4,09 s einschließlich Prozessstart**;
ein ausschließlich für POSIX-Dateirechte geltender Fall wird unter Windows übersprungen.
Damit ist die vereinbarte 15-Sekunden-Schranke erfüllt. Das ursprüngliche Ziel für
die gesamte Schnellsuite wurde nicht erreicht und ausdrücklich gemeinsam angepasst.
Die endgültige Linux-TDD-Auswahl bestand in **2,15 s einschließlich Prozessstart**.
Die vollständige Schnellsuite bestand unter Windows mit 3.327 Tests und einem
plattformbedingten Skip in **68,13 s einschließlich Prozessstart**; unter Linux
bestand sie in **59,72 s einschließlich Prozessstart**. Das sind Messwerte dieser
Entwicklungsmaschine, keine Laufzeitgarantien. Die JSON-Zeitberichte werden unter
`.test-tmp/` erzeugt; die festgehaltenen Abnahmewerte stehen zusätzlich im
[maschinenlesbaren Abschlussbericht](../quality-reports/quality-4.1.json).
Tests mit veralteten lokalen Paketartefakten wurden nach deren Neubau wiederholt;
fehlgeschlagene Zwischenläufe werden nicht als bestandene Abnahme gewertet.

Der Browser-Smoke bestand mit **18 Fällen in 44,62 s**. Docker-Prüfungen mit
synthetischer Konfiguration und gesperrtem Netzwerk bestanden für Konfigurationsprüfung,
Dienststart und Neustart, Lernmodus und dessen Neustart sowie **28 harte
Prozessabbrüche mit Anbieteradaptern und Wiederaufnahme**. Ruff prüft `src`, `tests`,
`ui_tests` und `devtools`; mypy prüft 229 Quelldateien. Vorhandene unabhängige
OCR-/Download-Hilfsprojekte unter `.tools` gehören nicht zu dieser Mailhelp-Abnahme.

Der vollständige Mutationslauf besteht mit **1.001 von 1.011 getöteten Mutanten
(99,01 %)**. `domain`: 99,41 %, `storage`: 99,15 %, `confirmed`: 97,33 %.
Kein Mutant ist ungetestet oder wegen Timeout, Abbruch oder Segfault unbewertet.
Alle zehn Überlebenden sind im [Einzelbericht](../quality-reports/mutation-4.1.md)
analysiert; sie bleiben im Nenner. Der [JSON-Bericht](../quality-reports/mutation-4.1.json)
enthält vollständige Diffs und Quelltext-Fingerprints. Die frühere unvollständige
Baseline ist kein vergleichbarer Vorher-Score.

Zwei echte Fehler wurden mit vor der Korrektur fehlschlagenden Regressionstests
abgesichert: Die Testbereinigung konnte fremde Coverage-Dateien entfernen, und
ungültiges UTF-8 umging die Behandlung beschädigter Zustandsdateien. Volltests
erhalten nun einen eigenen Coverage-Pfad. Schreibfreies Lesen beschädigter Akten
meldet `CorruptState`, normales Laden isoliert unveränderte ursprüngliche Bytes.
Windows-Plattformsimulationen ersetzen nur die OS-Sicht des Speichermoduls.

Unbeschränkt parallele Prozessprüfungen waren unter Windows nicht stabil. Deshalb
serialisiert die parallele Vollabnahme Prozess- und E2E-Tests gemeinsam; der
anschließende vollständige Windows-Lauf mit dieser Strategie bestand. Ein einzelner
grüner Lauf ist kein Beweis für dauerhafte Freiheit von Flakiness. CI-Schleifen,
Mutationsworkflow und die bestehenden Abbruch-/Neustarttests sichern Folgeänderungen.
Alle automatisierten Prüfungen verwenden synthetische Daten und simulierte externe
Dienste. Tatsächliche Modellgenauigkeit ist weiterhin gesondert zu evaluieren.
