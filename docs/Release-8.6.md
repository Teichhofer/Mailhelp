# Mailhelp 8.6 – Umsetzung und Freigabestand

Stand: 24. November 2026. Version 8.6.2. Grundlage: [Planung 8.6](Planung-8.6.md).

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
