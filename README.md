# Mailhelp

<p align="center">
  <img src="src/mailhelp/assets/logo.png" alt="Mailhelp" width="280">
</p>

Mailhelp analysiert E-Mails und erstellt überprüfbare Vorschläge für Aufgaben und
Termine. Die Freigabe erfolgt über Telegram oder die authentifizierte Weboberfläche.
Erst eine ausdrückliche Bestätigung der jeweiligen Vorschlagsversion erlaubt das
Schreiben in den Kalender oder die Aufgabenliste.

Die Anwendung läuft lokal unter Windows 11 oder als Docker-Dienst unter Linux.
Für die KI-Auswertung verwendet sie OpenRouter; ein experimenteller Betrieb mit
einem lokalen Ollama-Server ist ebenfalls verfügbar.

**Version:** 7.0.15 · **Python:** 3.12.x · **Lizenz:** MIT

7.0.15 prüft alle lebenden Dokumente gegen Code und Oberfläche (Protokoll in `docs/Pruefung-Dokumentation-7.0.md`), korrigiert 25 veraltete Abschnitte, ergänzt dauerhafte automatische Dokumentationsprüfungen und kürzt dieses README auf Einstieg und Verweise.

Alle Änderungen früherer Versionen stehen im [CHANGELOG](CHANGELOG.md).

## Funktionen

- **Mehrere Postfächer:** IMAP-Abruf mit getrennten Kontoidentitäten und Wiederaufnahme
  gespeicherter Verarbeitungsschritte nach einem Neustart. Neue Postfächer werden mit Server,
  Ordnern und Zugangsdaten gemeinsam geprüft und ohne Dienstneustart aktiviert.
- **Gezielte Analyse:** Themen, ausgeschlossene Themen und Absenderfilter bestimmen, welche
  Nachrichten verarbeitet werden. Dokumente und Bildanhänge können einbezogen werden.
- **Aufgaben und Termine:** Vorschläge enthalten Belege und Rückfragen bei fehlenden oder
  widersprüchlichen Angaben. Der Abgleich berücksichtigt vorhandene Einträge und offene
  Entscheidungen, um doppelte Aktionen zu vermeiden. Angelegte Einträge werden durch einen
  frischen Abruf beim Anbieter nachgeprüft.
- **Einstellungen je Postfach:** Eigene Zielprofile, Themen, Signaturen, Ruhezeiten,
  Benachrichtigungen, Termindauern und Aufbewahrungsregeln mit globaler Vererbung.
- **Telegram und Web-App:** Vorschläge prüfen, klären, bearbeiten, bestätigen oder verwerfen,
  auf dem Telefon auch per Wischgeste. Die installierbare Web-App funktioniert auch ohne Telegram
  und bietet Verlauf, Auswertung, Lernen, Einstellungssuche und einen Hilfschat.
- **IServ-Elternbriefe:** Briefe aus dem IServ-Elternbriefmodul werden wie Mails verarbeitet,
  einschließlich Anhängen, und gelten immer als relevant.
- **Optional:** Antwortentwürfe im Ursprungspostfach, Postfach-Briefings, Web-Push und
  Tätigkeitsberichte mit XLSX-Export.

Antwortentwürfe werden nur im IMAP-Entwurfsordner abgelegt. Mailhelp versendet keine E-Mails.

### Unterstützte Dienste

| Bereich | Dienste |
| --- | --- |
| E-Mail | IMAP-Postfächer |
| Schule | IServ-Elternbriefe (Lesezugriff über die Weboberfläche, keine offizielle API) |
| Kalender | Google Kalender, Outlook / Microsoft 365, CalDAV |
| Aufgaben | Todoist, Microsoft To Do, CalDAV-Aufgabenlisten, Apple Erinnerungen über iCloud-CalDAV |
| KI-Auswertung | OpenRouter; experimentell Ollama |
| Bedienung | Telegram, lokale Weboberfläche und PWA |

## Schnellstart

Voraussetzungen: Python **3.12.x** oder Docker mit Compose, ein IMAP-Postfach und Zugangsdaten
für die verwendeten Dienste.

### Windows 11

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.lock
.venv\Scripts\python -m pip install --no-deps -e .
.venv\Scripts\mailhelp
```

### Linux

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/mailhelp
```

Ohne `config.yaml` startet ein geschützter Einrichtungsassistent. Das Terminal zeigt einen
Code; damit koppelt der Browser unter **http://127.0.0.1:8765** und führt durch Web-Zugang,
Postfach, KI-Anbieter, Kalender und Aufgaben. Schritt für Schritt beschreibt das die
[Ersteinrichtung](docs/Ersteinrichtung.md).

Für eine manuelle Konfiguration stattdessen `config.example.yaml` nach `config.yaml`,
`.env.example` nach `.env` und `irrelevant-senders.example.json` nach
`irrelevant-senders.json` kopieren und anpassen.

### Docker

```sh
docker compose -f compose.setup.yaml up --build
```

Den ausgegebenen Einmalcode unter `http://localhost:8765/anmelden` eingeben. Konfiguration,
Zugangsdaten, Zustände und Logs bleiben im benannten Volume `mailhelp-config`. Die
`compose.yaml` verwendet eine manuell angelegte Konfiguration; Einzelheiten stehen in
[Betrieb und Update](docs/Betrieb.md).

### Prüfen und starten

```sh
mailhelp --check --config-directory .
mailhelp --check-access --config-directory .
mailhelp --max-mails 10 --config-directory .
mailhelp --config-directory .
```

`--check` prüft die Konfiguration ohne Netzwerkzugriff, `--check-access` die Zugänge (ohne
Aufgaben oder Termine anzulegen). `--max-mails 10` begrenzt einen einzelnen Durchlauf; ohne
diese Optionen läuft Mailhelp als Dienst. Pro Datenverzeichnis läuft nur eine Instanz.

## Konfiguration

| Datei | Inhalt |
| --- | --- |
| `config.yaml` | Postfächer, Ziele, Betriebsart, Zeitzone, Limits, Benachrichtigungen und Aufbewahrung |
| `prompts.yaml` | Prompts, Modelle und LLM-Parameter für die Analyseschritte |
| `decisions_prompts.yaml` | Konfiguration der Standard-Relevanzprüfung |
| `topics.yaml` | Relevante Themen, optional auf einzelne Postfächer begrenzt |
| `irrelevant_topics.yaml` | Ausgeschlossene Themen |
| `irrelevant-senders.json` | Globale und postfachbezogene Absenderfilter |
| `.env` | Zugangsdaten, Tokens und Sitzungsschlüssel; alternativ Prozessumgebung |

[config.example.yaml](config.example.yaml) und [.env.example](.env.example) zeigen alle
Einstellungen und Geheimnisnamen. Prozessvariablen haben Vorrang vor `.env`. Fast alles lässt
sich auch in der Weboberfläche unter **Einstellungen** ändern; jede Einstellung erklärt die
[Einstellungsreferenz](docs/Web-Einstellungen.md). Mit `test_mode: true` werden Kalender- und
Aufgabenaktionen nur simuliert.

## Datenschutz und Sicherheit

Die Mailanalyse liest das Postfach, ohne Nachrichten oder Lesestatus zu ändern. Bei externen
KI-Diensten werden ausgewählte Mailinhalte an die konfigurierten Anbieter übertragen; lokale
Ausführung bedeutet daher nicht automatisch ausschließlich lokale Verarbeitung.

Zustände werden als lesbare JSON-Dateien, Ereignisse als getrennte JSONL-Logs gespeichert.
Mailzustände (Schema 9) und offene Entscheidungen bleiben über Neustarts erhalten.
Zugangsdaten werden nicht protokolliert. Die ausgelieferte `config.example.yaml` schaltet
vollständige KI-Anfrage- und Antwortlogs ausdrücklich ein; für einen Betrieb ohne diese
Inhalte `logging.llm.include_requests` und `logging.llm.include_responses` auf `false` setzen.

Externe Schreibaktionen sind an Vorschlagsversion, Ziel und ausdrückliche Freigabe gebunden;
unklare Schreibresultate werden vor einer Wiederholung abgeglichen. Webaktionen prüfen
Sitzung, CSRF-Schutz, Version und Idempotenz. Hinweise für betriebene Instanzen stehen in der
[Datenschutzerklärung](DATENSCHUTZ.md) und den [Nutzungsbedingungen](NUTZUNGSBEDINGUNGEN.md);
beide Vorlagen müssen an den jeweiligen Betrieb angepasst werden.

## Entwicklung

Automatisierte Tests verwenden synthetische Daten und simulierte externe Dienste. Die
vollständige Prüfung baut die Pakete und erzwingt **100 % Zeilen- und Branch-Abdeckung**
des eigenen Codes einschließlich der Entwicklungswerkzeuge:

```sh
python -m devtools.check full --workers 12
python -m devtools.check fast
python -m devtools.check tdd tests/unit/test_core.py
python -m pytest ui_tests -n 6 --dist worksteal --no-cov
```

`--workers` an die Zahl der Rechenkerne anpassen; ohne Angabe läuft die vollständige Prüfung
seriell. Python- und Browserprüfung nicht gleichzeitig starten, weil die Zeitmessungen sonst
unzuverlässig werden. Lint und Typprüfung:

```sh
python -m pip install -r requirements-lint.lock
python -m ruff check src tests ui_tests devtools
python -m mypy
```

mypy verlangt für jede Funktion vollständige Typangaben; Schichten, Funktionslänge und
Parameterzahl prüfen `tests/unit/test_layers.py` und `tests/unit/test_limits.py`. Die
Browsertests decken Desktop-, Mobil- und schmale Telefonansichten, große Bildschirme,
Barrierefreiheit und 100 % der JavaScript-Blöcke ab.

Entwicklungsregeln stehen in [AGENTS.md](AGENTS.md), der Aufbau in der
[Architektur](docs/Architektur.md), technische Verträge in der
[Projektspezifikation](Mailhelp-Projektspezifikation.md).

## Dokumentation

Das [Inhaltsverzeichnis](docs/README.md) führt alle aktuellen Anleitungen auf:
[Ersteinrichtung](docs/Ersteinrichtung.md) · [Konten verwalten](docs/Konten-verwalten.md) ·
[Kalender und Aufgaben verbinden](docs/Ziele-einrichten.md) · [Bedienung](docs/Bedienung.md) ·
[Fehler beheben](docs/Fehlerbehebung.md) · [Betrieb und Update](docs/Betrieb.md) ·
[Einstellungen](docs/Web-Einstellungen.md). Abgeschlossene Pläne und Release-Berichte liegen
im [Archiv](docs/archiv/). Die statische Projektwebsite liegt unter [website/](website/).

## Lizenz

Mailhelp wird unter der [MIT-Lizenz](LICENSE) bereitgestellt.
