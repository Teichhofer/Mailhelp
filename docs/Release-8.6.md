# Mailhelp 8.6 – Umsetzung und Freigabestand

Stand: 25. November 2026. Version 8.6.3. Grundlage: [Planung 8.6](Planung-8.6.md).

## Umgesetzt in 8.6.1

| Arbeitspaket | Umsetzung |
| --- | --- |
| AP1 Workflows | `python-version: '3.12'` an allen sieben `actions/setup-python`-Schritten in `ci.yml`, `mutation.yml`, `release.yml` und `weekly.yml` |
| AP2 Artefakte | `ui-screenshots` (`ci.yml`) und `mutation-results` (`mutation.yml`) mit `if-no-files-found: ignore`; bei regulärem Lauf und Testfehlschlag werden sie wie bisher hochgeladen |
| AP3 Basisimages | `Dockerfile` und `ops/auth/Dockerfile` auf `python:3.12.16-slim` (am 24.11.2026 aktueller Stand von `python:3.12-slim`, Build vom 5.11.2026) |
| AP4 Regressionstest | `tests/release/test_ci_workflows.py`: Python-Kanal `3.12` an jedem Setup-Schritt, `if-no-files-found: ignore` bei jedem Upload mit `if: always()`, Zahl der geprüften Setup-Schritte, gemeinsames Basisimage ab 3.12.16 |
| AP5 Dokumentation | Version, Änderungen, README, Dokumentenübersicht und Hilfeindex |

`.python-version` bleibt bei `3.12.10`: Die Datei beschreibt den lokalen Windows-Entwicklungsstand und
wird von keinem Workflow gelesen. `requires-python` und alle Sperrdateien sind unverändert.

## Bugfix 8.6.2

Die Veröffentlichung auf GitHub Pages scheiterte bei den Pushes von 8.5.4 und 8.6.1 (und vereinzelt am
21. und 22.11.) in „Publish website“ mit „No artifacts named github-pages were found“. Die Pages-Actions
liefen noch in den Node.js-20-Versionen (`configure-pages@v5`, `upload-pages-artifact@v4`,
`deploy-pages@v4`) und werden jetzt in den aktuellen Hauptversionen v6, v5 und v5 verwendet.
Regressionstest: `test_regression_pages_actions_use_node24_majors`.

**Korrektur (8.6.3):** Die Umstellung hat den Fehler nicht behoben. Auch der Lauf von 8.6.2 scheiterte gleich.
Laut Artefaktliste wurde `github-pages` (rund 900 KB) in jedem Lauf hochgeladen, auch in den gescheiterten.
Mit den alten Versionen lief die Veröffentlichung am 24.11. um 06:41 noch erfolgreich. Die Ursache liegt
also nicht in der Workflow-Konfiguration, sondern beim Abruf des Artefakts durch GitHub. Die Fehlermeldung
empfiehlt selbst einen erneuten Lauf. Abhilfe: „GitHub Pages“ unter Actions erneut ausführen. Die aktuellen
Action-Versionen bleiben bestehen.

## Bugfix 8.6.3

Der CI-Job `tests` scheiterte seit dem 20.11.2026 auf Ubuntu und Windows, lokal unter Windows nicht. Mit
einer Vollprüfung unter WSL-Ubuntu 24.04 (Python 3.12.3, `--workers 8`) nachgestellt:

| Befund | Ursache | Behebung |
| --- | --- | --- |
| `test_every_relative_link_of_a_document_resolves` | `landing/ASSETS.md` verlinkte `C:/Users/…/SKILL.md`; die Datei gibt es nur auf dem Entwicklungsrechner | Link durch Text ersetzt; lokale absolute Pfade gelten überall als defekt (Regressionstest `test_regression_a_local_absolute_path_is_broken_even_where_it_exists`) |
| `test_unsafe_or_unusable_keys_are_refused`, Abdeckung 99,99 % | Die ungültige Testschlüsseldatei war für andere lesbar und wurde unter Linux vor der Inhaltsprüfung abgewiesen | Testdatei mit Modus `0600` angelegt |
| `test_a_read_only_config_mount_gives_a_clear_result_and_changes_nothing` | Nur in WSL als root: root umgeht den Schreibschutz | Keine Änderung; unter einem normalen Benutzer besteht der Test, der CI-Runner läuft nicht als root |

## Prüfung

| Nr. | Szenario | Ergebnis |
| --- | --- | --- |
| 1 | Regressionstest vor AP1–AP3 | 7 Fehlschläge (vier Workflows mit `3.12.10`, zwei Uploads ohne `if-no-files-found`, Basisimage) |
| 2 | Regressionstest danach | 13 bestanden |
| 3 | `python -m devtools.check full --workers 12` | siehe unten |
| 4–6 | GitHub Actions `CI`, `Mutation audit`, `Weekly` | siehe unten |
| 7 | Docker-Build beider Images | Auf dem Server als Probe gebaut (ohne Umstellung, danach entfernt): Mailhelp-Image mit Python 3.12.16 und Version 8.6.1, Offline-`--check` gegen die Produktionskonfiguration „Konfiguration ist gültig.“; Auth-Image mit Python 3.12.16 gebaut und importierbar |

## Auslieferung

Produktion und Demo laufen mit 8.5.4 (Commit `1ea1c98`, Details in [Betrieb](Betrieb.md)). Ein Update auf das neue Basisimage folgt erst nach grünem `CI`- und
`container-smoke`-Lauf und ausdrücklicher Freigabe.
