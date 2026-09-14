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

`config.yaml` besitzt geschlossene Modelle für IMAP, Telegram, Ziele, Limits, Wiederholungen, Timeouts und Logging. IMAP, Telegram, OpenRouter, Todoist und Google Calendar haben jeweils eigene Werte für Timeout, Retry-Anzahl sowie initialen und maximalen Backoff. Validiert werden insbesondere Port, Polling, Adaptertimeouts, Mailgröße, LLM-Rate, Wiederholungszahlen, IANA-Zeitzone, eindeutige nichtleere Ordner, sichere Pfade und die Log-Level `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. Unbekannte Schlüssel und falsche Typen werden abgelehnt.

Das globale `logging.level` kann über `logging.module_levels` je Modul überschrieben
werden. Strukturierte Anwendungs- und LLM-Ereignisse werden getrennt als JSONL
geschrieben; Rohprompt und Rohantwort bleiben standardmäßig aus und werden nur durch
`include_llm_requests` beziehungsweise `include_llm_responses` unabhängig aktiviert.
Alle Logfelder durchlaufen eine rekursive Geheimnisbereinigung.

Nur Transportfehler sowie HTTP 408, 425, 429, 500, 502, 503 und 504 werden bei lesenden beziehungsweise idempotenten Zugriffen begrenzt wiederholt. `Retry-After` wird bis zur konfigurierten Backoff-Obergrenze berücksichtigt. Schreibzugriffe werden vorab persistiert und bei Transportfehlern oder vorübergehenden HTTP-Antworten als unklar behandelt; vor einem erneuten Schreiben erfolgt ein Abgleich. Das OpenRouter-Minutenbudget wird im Datenverzeichnis persistiert, bleibt deshalb über Neustarts erhalten und stellt betroffene Mails bis zum nächsten zulässigen Zeitpunkt zurück.

## Betrieb und Sicherheit

* IMAP wird im Nur-Lese-Modus mit `BODY.PEEK[]` gelesen; UIDVALIDITY und UID bilden die technische Identität.
* Der JSON-Zustand wird atomar ersetzt und durch eine Einzelinstanz-Sperre geschützt. Syntaktisch beschädigte Dateien werden als `.corrupt`, schemawidrige Dateien als `.invalid` isoliert; Meldungen nennen Datei und Schlüsselpfad, nicht den Inhalt. Mailzustände (Schema 2), Abrufpositionen, Telegram-Dialoge und Vorschläge (Schema 1) werden vor jeder Verwendung validiert.
* OpenRouter-, Telegram-, Todoist- und Google-Calendar-Antworten werden nach HTTP-Erfolg strikt auf JSON-Struktur, Pflichtfelder und IDs geprüft. LLM-Antworten werden strikt gegen feste Pydantic-Schemata validiert. Reservierte OpenRouter-Felder können nicht über YAML überschrieben werden.
* Externe Aktionen verlangen eine Persistenzfunktion: `writing` wird vor dem API-Aufruf dauerhaft gespeichert. Unklare Resultate werden als `uncertain` angehalten; vor einem neuen Versuch suchen die Adapter nach dem versionsbezogenen Idempotenzschlüssel.
* Jede Mail besitzt die schema-validierten Schritte `preparation`, `relevance`,
  `summary`, `action_detection`, `notification` und `completion`. Nach jedem Schritt
  wird atomar gespeichert; nach einem Neustart laufen ausschließlich ausstehende
  Schritte. Relevante Mails erreichen `completion` erst nach Analyse und Telegram-
  Benachrichtigung, während nicht benötigte Schritte ausdrücklich `skipped` sind.
* Vorschläge werden zusätzlich zur Maildatei versionsweise und als aktueller Stand
  gespeichert. Bestätigte Schreibvorgänge werden nach Neustarts wiederaufgenommen;
  externe ID und Link sowie `created`, `failed`, `uncertain` oder eine Testmodus-
  Simulation werden im konfigurierten Telegram-Chat sichtbar gemeldet.
* Im `test_mode` findet kein externer Schreibzugriff statt; Ergebnisse tragen `simulation: true` und der Vorschlag bleibt `confirmed`, statt einen echten Eintrag vorzutäuschen.
* JSONL-Anwendungs- und LLM-Logs sind getrennt. Rohprompts und Rohantworten sind unabhängig und standardmäßig ausgeschaltet; Geheimnisfelder werden maskiert.
* `.env` unterstützt einfache `NAME=WERT`-Zeilen und einfache/doppelte Anführungszeichen, aber bewusst keine Shell-Erweiterung. Prozessvariablen überschreiben gleichnamige Werte aus der Datei.

Ohne `--check` startet der CLI-Einstieg den Dienst. Er liest alle konfigurierten
IMAP-Ordner und Telegram per Long-Polling. Abrufstände werden pro Ordner mit
UIDVALIDITY und UID persistiert und nach einem Neustart fortgesetzt. SIGINT und
SIGTERM fordern ein kontrolliertes Ende an; Netzwerkclients und die
Einzelinstanz-Sperre werden auch bei Fehlern geschlossen.

Noch nicht abgeschlossene `mail-*.json`-Zustände bleiben unabhängig vom
IMAP-Abrufstand erreichbar. Beim Start und vor jedem regulären IMAP-Poll werden
fällige Zustände per gezieltem, schreibfreiem `BODY.PEEK[]`-Abruf fortgesetzt;
`deferred_until` verschiebt diesen Versuch. Das Verarbeitungsergebnis unterscheidet
explizit zwischen `completed`, `waiting` und `failed`.

Telegram-Updates werden an der Eingangsgrenze durch geschlossene Pydantic-
Schemata validiert. Der atomar gespeicherte Offset verhindert nach einem Neustart
die erneute Verarbeitung bereits behandelter Updates. Aktionen enthalten immer
Vorschlags-ID, Version und Aktion; nur der konfigurierte Nutzer im konfigurierten
Chat darf sie auslösen. Jede angezeigte Version wird vor ihren Schaltflächen
gespeichert. `Bestätigen`, `Ändern` und `Verwerfen` werden getrennt behandelt,
während veraltete oder fehlerhafte Schaltflächen keinen Zustand verändern.
Antworten auf Rückfragen erzeugen eine neue, erneut zu bestätigende Version.
Lange Vorschläge tragen in jedem Teil Mail-ID, Vorschlags-ID und Teilnummer.

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
