# Mailhelp

Python-Assistent zur LLM-basierten Auswertung von IMAP-Mails über OpenRouter. Telegram zeigt Zusammenfassungen und versionsgebundene Einzelvorschläge; erst eine ausdrückliche Bestätigung erlaubt einen Todoist- oder Kalender-Schreibzugriff.

## Installation (Windows 11 und Linux)

Voraussetzung ist exakt Python **3.12.x**; `.python-version` legt für Versionsmanager 3.12.10 fest und `pyproject.toml` verhindert versehentliche Installation unter einer anderen Minor-Version.

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e ".[test]"
Copy-Item .env.example .env
```

Unter Linux werden die letzten beiden Befehle mit `.venv/bin/python` und `cp` ausgeführt. `config.yaml`, `prompts.yaml` und `topics.yaml` anpassen; echte Geheimnisse ausschließlich in `.env` oder der Prozessumgebung setzen. Laufzeitvariablen haben Vorrang. Danach validiert `mailhelp --check` alle Dateien, ohne Netzwerkzugriff.

## Betrieb und Sicherheit

* IMAP wird im Nur-Lese-Modus mit `BODY.PEEK[]` gelesen; UIDVALIDITY und UID bilden die technische Identität.
* Der JSON-Zustand wird atomar ersetzt und durch eine Einzelinstanz-Sperre geschützt. Beschädigte Dateien werden als `.corrupt` isoliert.
* LLM-Antworten werden strikt gegen feste Pydantic-Schemata validiert. Reservierte OpenRouter-Felder können nicht über YAML überschrieben werden.
* Unklare externe Schreibresultate werden als `uncertain` angehalten. Vor einem neuen Versuch suchen die Adapter nach dem versionsbezogenen Idempotenzschlüssel.
* Im `test_mode` findet kein externer Schreibzugriff statt; Ergebnisse tragen `simulation: true`.
* JSONL-Anwendungs- und LLM-Logs sind getrennt. Rohprompts und Rohantworten sind unabhängig und standardmäßig ausgeschaltet; Geheimnisfelder werden maskiert.

Derzeit stellt der CLI-Einstieg die vollständige Konfigurationsprüfung bereit. Die austauschbaren Adapter und der `Orchestrator` sind für die Einbindung in einen Dienstprozess ausgelegt.

## Docker

```sh
cp .env.example .env
docker compose build
docker compose run --rm mailhelp
```

Konfiguration wird schreibgeschützt eingebunden, Daten und Logs bleiben in getrennten persistenten Host-Verzeichnissen. `.env`, Zustand und Logs gelangen dank `.dockerignore` nicht in den Build-Kontext.

## Zustand sichern

Mailhelp stoppen und anschließend das gesamte konfigurierte Datenverzeichnis kopieren. Zur Wiederherstellung den Dienst stoppen, das komplette Verzeichnis zurückspielen und erst danach starten. Offene Vorgänge dürfen nicht einzeln bereinigt werden.

## Tests

```sh
python -m pytest
```

Die Standardkonfiguration erzwingt ohne Rundung 100 % Zeilen- **und** Branch-Abdeckung für `src/mailhelp`.
