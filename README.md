# Mailhelp

Python-Assistent zur LLM-basierten Auswertung von IMAP-Mails über OpenRouter. Telegram zeigt Zusammenfassungen und versionsgebundene Einzelvorschläge; erst eine ausdrückliche Bestätigung erlaubt einen Todoist- oder Kalender-Schreibzugriff.

## Installation (Windows 11 und Linux)

Voraussetzung ist exakt Python **3.12.x**; `.python-version` legt für Versionsmanager 3.12.10 fest und `pyproject.toml` verhindert versehentliche Installation unter einer anderen Minor-Version.
Direkte und transitive Laufzeit-/Testabhängigkeiten sind in `requirements.lock`
festgeschrieben; das Container-Image installiert genau diese Versionen.

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
* Externe Aktionen verlangen eine Persistenzfunktion: `writing` wird vor dem API-Aufruf dauerhaft gespeichert. Unklare Resultate werden als `uncertain` angehalten; vor einem neuen Versuch suchen die Adapter nach dem versionsbezogenen Idempotenzschlüssel.
* Im `test_mode` findet kein externer Schreibzugriff statt; Ergebnisse tragen `simulation: true` und der Vorschlag bleibt `confirmed`, statt einen echten Eintrag vorzutäuschen.
* JSONL-Anwendungs- und LLM-Logs sind getrennt. Rohprompts und Rohantworten sind unabhängig und standardmäßig ausgeschaltet; Geheimnisfelder werden maskiert.
* `.env` unterstützt einfache `NAME=WERT`-Zeilen und einfache/doppelte Anführungszeichen, aber bewusst keine Shell-Erweiterung. Prozessvariablen überschreiben gleichnamige Werte aus der Datei.

Ohne `--check` startet der CLI-Einstieg den Dienst. Er liest alle konfigurierten
IMAP-Ordner und Telegram per Long-Polling. Abrufstände werden pro Ordner mit
UIDVALIDITY und UID persistiert und nach einem Neustart fortgesetzt. SIGINT und
SIGTERM fordern ein kontrolliertes Ende an; Netzwerkclients und die
Einzelinstanz-Sperre werden auch bei Fehlern geschlossen.

## Docker

```sh
cp .env.example .env
docker compose build
docker compose run --rm mailhelp
```

Der Container startet standardmäßig den Dienst. Für eine reine Prüfung kann
`docker compose run --rm mailhelp --check --config-directory /config` verwendet
werden.

Konfiguration wird schreibgeschützt eingebunden, Daten und Logs bleiben in getrennten persistenten Host-Verzeichnissen. `.env`, Zustand und Logs gelangen dank `.dockerignore` nicht in den Build-Kontext.
Relative Daten- und Logpfade aus `config.yaml` beziehen sich auf das aktuelle
Arbeitsverzeichnis (im Container `/app`).

## Zustand sichern

Mailhelp stoppen und anschließend das gesamte konfigurierte Datenverzeichnis kopieren. Zur Wiederherstellung den Dienst stoppen, das komplette Verzeichnis zurückspielen und erst danach starten. Offene Vorgänge dürfen nicht einzeln bereinigt werden.

## Tests

```sh
python -m pytest
```

Die Standardkonfiguration erzwingt ohne Rundung 100 % Zeilen- **und** Branch-Abdeckung für `src/mailhelp`.
