# Mailhelp 1.6 – Stabilisieren und Entflechten

Mailhelp 1.6.0 ordnet die interne Architektur für die Arbeiten an Version 2.0.
Der Funktionsumfang und die Nutzerabläufe aus 1.5 bleiben erhalten.

## Änderungen

- Review- und Statusrenderer sind getrennt.
- Discovery, durable Mail-Queue, Checkpoints und Wiederaufnahme liegen in einem
  eigenen Mailbox-Service; Application koordiniert Prozess und Eingaben.
- OAuth, Kalender, Todoist, ICS und bestätigte Schreibausführung besitzen klare
  Modulgrenzen; bisherige Integrationsimporte und Konstruktoren bleiben verfügbar.
- Telegram-Antwortinterpretation, Nachfolge-Vorschlag und Recovery sind vom
  koordinierenden Revisionsdienst getrennt.

Die Struktur und Sicherheitsgrenzen erläutert [Architektur-1.6.md](Architektur-1.6.md).
Grundlage ist [Planung-1.6.md](Planung-1.6.md).

## Upgrade von 1.5

Mailhelp geordnet beenden und Konfiguration sowie Zustandsverzeichnis sichern.
Anschließend das Paket auf 1.6.0 aktualisieren beziehungsweise das Docker-Image
neu bauen und mit denselben bestehenden Volumes starten. Ein Container-Neubau
ist erforderlich, damit die neuen Python-Module im Image enthalten sind.

Es sind keine Datenmigration, Änderung an `config.yaml`, Themen, Prompts,
Zugangsdaten, CLI-Optionen oder Compose-Volumes nötig. Vorhandene offene Fragen,
Vorschlagsversionen, UID-Queues, Checkpoints und unklare Schreibresultate werden
über dieselben gespeicherten Schemas fortgesetzt. Die Bestätigungsschranke wird
nicht verändert; Bearbeiten und Speichern allein autorisieren keine externe Anlage.

## Prüfung

```powershell
python -m pytest -q --tb=short
python -m pytest ui_tests --no-cov -p no:cacheprovider -q --tb=short
python -m hatchling build
```

Die Baseline und jeder der vier Refactoring-Schritte wurden mit der vollständigen
Python-Suite bei 100 % Zeilen- und Branch-Coverage geprüft. Alle externen Dienste
und Daten in den Tests sind simuliert beziehungsweise synthetisch. Reale
API-Schreibzugriffe sind kein Teil der Abnahme.

Die CI-Matrix prüft weiterhin Windows und Linux, Browser, installierte Pakete sowie
Container-Neustart mit Produktionsmounts. Lokale Windows-Prüfung ersetzt keinen
auf Linux tatsächlich ausgeführten CI-/Docker-Lauf.
