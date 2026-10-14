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

**Version:** 3.2.6 · **Python:** 3.12.x · **Lizenz:** MIT

[Installation](#installation) · [Konfiguration](#konfiguration) ·
[Betrieb](#betrieb) · [Docker](#docker) ·
[Datenschutz und Sicherung](#datenschutz-und-sicherung) · [Dokumentation](#dokumentation)

## Funktionen

- **Mehrere Postfächer:** IMAP-Abruf mit getrennten Kontoidentitäten und Wiederaufnahme
  gespeicherter Verarbeitungsschritte nach einem Neustart.
- **Gezielte Analyse:** Themen, ausgeschlossene Themen und Absenderfilter bestimmen,
  welche Nachrichten verarbeitet werden. Dokumente und Bildanhänge können in die
  Analyse einbezogen werden.
- **Aufgaben und Termine:** Vorschläge enthalten Belege und Rückfragen bei fehlenden
  oder widersprüchlichen Angaben. Der Abgleich berücksichtigt vorhandene Einträge
  und offene Entscheidungen, um doppelte Aktionen zu vermeiden.
- **Einstellungen je Postfach:** Eigene Zielprofile, Themen, Signaturen, Ruhezeiten,
  Benachrichtigungen, Termindauern und Aufbewahrungsregeln mit globaler Vererbung.
- **Telegram und Web-App:** Vorschläge prüfen, klären, bearbeiten, bestätigen oder
  verwerfen. Die installierbare Web-App unterstützt auch den Betrieb ohne Telegram.
- **Optionale Unterstützung:** Antwortentwürfe im Ursprungspostfach, Tagesüberblicke,
  Web-Push und Tätigkeitsberichte mit XLSX-Export.

Antwortentwürfe werden nur nach ausdrücklichem Speichern im IMAP-Entwurfsordner
abgelegt. Mailhelp versendet keine E-Mails.

### Unterstützte Dienste

| Bereich | Dienste |
| --- | --- |
| E-Mail | IMAP-Postfächer |
| Kalender | Google Kalender, Outlook / Microsoft 365, CalDAV |
| Aufgaben | Todoist, Microsoft To Do, CalDAV-Aufgabenlisten |
| Zusätzlicher Aufgabenadapter | Apple Erinnerungen über iCloud-CalDAV, soweit die Liste dort verfügbar ist |
| KI-Auswertung | OpenRouter; experimentell Ollama |
| Bedienung | Telegram, lokale Weboberfläche und PWA |

Kalender- und Aufgabendienst werden pro Zielprofil gewählt. Zugangstokens bleiben
zwischen den Profilen getrennt.

## Installation

### Voraussetzungen

- Python **3.12.x** für die native Installation oder Docker mit Compose.
- Ein IMAP-Postfach und Zugangsdaten für die verwendeten Analyse- und Zieldienste.
- Für Telegram: ein Bot sowie die zulässige Nutzer- und Chat-ID.
- Für die Weboberfläche: ein eigener Sitzungsschlüssel in `MAILHELP_WEB_SECRET`.

Die folgenden Schritte gelten für eine Erstinstallation aus diesem Repository.
Für eine Paketinstallation oder ein Update siehe die
[Installations- und Release-Anleitung](docs/Release-1.0.md).

### Windows 11

Im Repository-Verzeichnis mit PowerShell ausführen:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.lock
.venv\Scripts\python -m pip install --no-deps -e .
Copy-Item config.example.yaml config.yaml
Copy-Item .env.example .env
Copy-Item irrelevant-senders.example.json irrelevant-senders.json
```

### Linux

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps -e .
cp config.example.yaml config.yaml
cp .env.example .env
cp irrelevant-senders.example.json irrelevant-senders.json
```

Die nachfolgenden Beispiele verwenden `mailhelp` aus der virtuellen Umgebung.
Ohne Aktivierung lautet der Aufruf unter Windows `.venv\Scripts\mailhelp` und
unter Linux `.venv/bin/mailhelp`.

## Konfiguration

Einstellungen und Geheimnisse liegen getrennt vom Anwendungscode:

| Datei | Inhalt |
| --- | --- |
| `config.yaml` | Postfächer, Ziele, Betriebsart, Zeitzone, Limits, Benachrichtigungen und Aufbewahrung |
| `prompts.yaml` | Prompts, Modelle und LLM-Parameter für die Analyseschritte |
| `decisions_prompts.yaml` | Konfiguration der Standard-Relevanzprüfung |
| `topics.yaml` | Relevante Themen, optional auf einzelne Postfächer begrenzt |
| `irrelevant_topics.yaml` | Ausgeschlossene Themen |
| `irrelevant-senders.json` | Globale und postfachbezogene Absenderfilter |
| `.env` | Zugangsdaten, Tokens und Sitzungsschlüssel; alternativ Prozessumgebung |

[config.example.yaml](config.example.yaml) und [.env.example](.env.example) zeigen
die verfügbaren Einstellungen und Geheimnisnamen. Prozessvariablen haben Vorrang
vor den Werten aus `.env`.

Vor dem ersten Lauf:

1. IMAP-Server, Ordner, Zugangsdaten und den gewünschten historischen Startpunkt
   in `imap.historical_start` festlegen.
2. Kalender, Aufgabenliste und die erforderlichen Providerzugänge einrichten.
3. Themen, Zeitzone und Benachrichtigungskanäle anpassen.
4. Für eine Erprobung `test_mode: true` setzen. Der Testmodus simuliert Kalender-
   und Aufgabenaktionen; Postfachabruf und KI-Auswertung verwenden weiterhin die
   konfigurierten Dienste.

Das Konfigurationsbeispiel verwendet `test_mode: false`. Auch im Produktivbetrieb
erfordert jede Kalender- oder Aufgabenaktion eine ausdrückliche Bestätigung.

### Anmeldung bei Google und Microsoft

```sh
mailhelp --google-auth --config-directory .
mailhelp --microsoft-login --config-directory .
```

Nur den Befehl für den jeweils verwendeten Anbieter ausführen. Google verwendet
eine Browseranmeldung mit lokalem Rückruf; Microsoft eine Anmeldung per Gerätecode.
Mit `--profile 2` wird ein zusätzliches Zielprofil eingerichtet. Die erstmalige
Google-Anmeldung für Docker auf dem Host durchführen.

Die [Anleitung zu Zielprofilen und OAuth](docs/Release-3.2.md) beschreibt
Voraussetzungen, Geheimnisnamen und die sichere Tokenablage.

### Einstellungen je Postfach

Unter **Einstellungen → Postfächer** lassen sich globale Werte gezielt
überschreiben. Themen und Absenderausnahmen können auf einzelne Postfächer
begrenzt werden. Zusätzliche Kalender- und Aufgabenziele werden über Zielprofile
zugeordnet.

Bestehende Vorschläge behalten ihr gespeichertes Ziel. Eine ausdrückliche
Zielumstellung erzeugt eine neue, erneut zu bestätigende Version. Zieländerungen
verändern den Analyse-Fingerprint nicht.

Alle Felder und ihre Wirkung erläutert die
[Einstellungsreferenz](docs/Web-Einstellungen.md).

## Betrieb

### Prüfen und starten

```sh
mailhelp --check --config-directory .
mailhelp --check-access --config-directory .
mailhelp --max-mails 10 --config-directory .
mailhelp --config-directory .
```

- `--check` validiert die Konfiguration ohne Netzwerkzugriff.
- `--check-access` prüft die eingerichteten Zugänge und sendet bei aktiviertem
  Telegram eine Testnachricht. Es erzeugt keine Aufgaben oder Termine.
- `--max-mails 10` begrenzt einen einzelnen Abrufdurchlauf auf höchstens zehn Mails.
- Ohne diese Optionen läuft Mailhelp als Dienst mit regelmäßigen Abrufzyklen.

Relative Daten- und Logpfade beziehen sich auf `--config-directory`.
Fehlende Themen-Dateien werden aus den Paketvorlagen angelegt; vorhandene Dateien
werden nicht überschrieben.

### Weboberfläche

In `config.yaml` `web.enabled: true` setzen und in `.env` einen zufälligen
`MAILHELP_WEB_SECRET` mit mindestens 32 Zeichen hinterlegen. Nach dem Dienststart
ist die Oberfläche standardmäßig unter **http://127.0.0.1:8765** erreichbar.

Ein zweiter Terminalaufruf erzeugt einen lokalen Einmalcode:

```sh
mailhelp --pair --config-directory .
```

Den Code auf der Anmeldeseite eingeben. Die Oberfläche bietet offene Entscheidungen,
Mailansichten, Suche, Verlauf, Auswertung, Berichte und Einstellungen. Die Anmeldung
ist auch über Telegram möglich. Für den Betrieb ausschließlich mit Weboberfläche
`telegram.enabled: false` setzen.

Die [Einrichtungs- und Betriebsanleitung](docs/Einrichtung-und-Qualitaetspruefung.md)
beschreibt auch den mobilen Zugriff und die Einrichtung des Telegram-Bots.

### Themen lernen und Entscheidungen abgleichen

```sh
mailhelp --learn 20 --mailbox 1 --config-directory .
```

Der interaktive Lernmodus liest Nachrichten zur Themen- und Filterpflege.
Bei mehreren aktivierten Postfächern ist `--mailbox NUMMER` oder `--mailbox alle`
erforderlich. Änderungen werden lokal gespeichert; Kalender und Aufgabenlisten
werden dabei nicht beschrieben.

Offene Entscheidungen lassen sich über die Weboberfläche oder Telegram bearbeiten.
Der Abgleich von Vorschlägen und vorhandenen Einträgen ist in der
[Bedienungsanleitung](docs/Release-2.4.md) beschrieben.

## Docker

Die Compose-Konfiguration baut das Image aus diesem Repository. Vor dem Start
`config.yaml`, `.env` und `irrelevant-senders.json` aus den Vorlagen anlegen und
wie oben beschrieben konfigurieren.

Unter Linux die Datenverzeichnisse für den Containerbenutzer vorbereiten:

```sh
mkdir -p data logs
sudo chown 65532:65532 data logs
docker compose build
docker compose run --rm mailhelp --check --config-directory /config
docker compose up -d
```

Die Konfiguration wird schreibgeschützt eingebunden; Daten und Logs bleiben in
persistenten Host-Verzeichnissen. Der Webport wird nur auf `127.0.0.1` des Hosts
veröffentlicht. Für die Weboberfläche im Container `web.host: 0.0.0.0` setzen.

```sh
docker compose logs -f mailhelp
docker compose exec mailhelp mailhelp --pair --config-directory /config
docker compose down
```

Für den Lernmodus mit schreibbarer Konfiguration ist
[compose.learn.yaml](compose.learn.yaml) vorgesehen. Dort werden die
Konfigurationsdateien im Verzeichnis `learning-config` eingebunden.

## Datenschutz und Sicherung

Die normale Mailanalyse liest das Postfach ohne Änderungen an Nachrichten oder
Lesestatus. Bei Verwendung externer KI-Dienste werden ausgewählte Mailinhalte an
die konfigurierten Anbieter übertragen. Die lokale Ausführung der Anwendung
bedeutet daher nicht automatisch eine ausschließlich lokale Datenverarbeitung.

Zustände werden als lesbare JSON-Dateien, Ereignisse als separate JSONL-Logs
gespeichert. Mailzustände (Schema 9) und offene Entscheidungen bleiben über
Neustarts erhalten. Zugangsdaten werden nicht protokolliert; vollständige
LLM-Inhalte sind nur nach ausdrücklicher Aktivierung des entsprechenden Loggings
enthalten. Aufbewahrungsfristen sind konfigurierbar.

Vor einer Sicherung oder Wiederherstellung den Dienst stoppen. Das vollständige
Datenverzeichnis einschließlich `test/` und `production/` sowie Konfiguration,
`.env` und OAuth-Token-Dateien sichern. Die
[Upgrade-Anleitung](docs/Release-3.2.md) beschreibt Migration und Rückkehr zur
vorherigen Version. Beim ersten Start nach dem Upgrade zunächst die bisherigen
Ziele beibehalten, damit alte Analyse-Fingerprints als gleichwertig registriert
werden können.

Externe Schreibaktionen sind an Vorschlagsversion, Ziel und ausdrückliche Freigabe
gebunden. Unklare Schreibresultate werden vor einer Wiederholung abgeglichen.
Webaktionen prüfen Sitzung, CSRF-Schutz, Version und Idempotenz; die Sitzung wird
bei der Ausführung erneut geprüft.

Hinweise für betriebene Instanzen stehen in der
[Datenschutzerklärung](DATENSCHUTZ.md) und den
[Nutzungsbedingungen](NUTZUNGSBEDINGUNGEN.md). Die Vorlagen müssen an den jeweiligen
Betrieb angepasst werden.

## Entwicklung und Qualitätssicherung

Automatisierte Tests verwenden synthetische Daten und simulierte externe Dienste.
Die vollständige Python-Suite erzwingt **100 % Zeilen- und Branch-Abdeckung** des
eigenen Anwendungscodes:

```sh
python -m pytest
python -m pip install -r requirements-lint.lock
python -m ruff check src tests ui_tests
python -m mypy src/mailhelp
```

Mit installiertem Chrome und den Browser-Testabhängigkeiten:

```sh
python -m pip install -e ".[ui]"
python -m pytest ui_tests --no-cov -p no:cacheprovider
```

Die Browserprüfungen umfassen Desktop-, Mobil- und schmale Telefonansichten,
Barrierefreiheitsprüfungen und vollständige JavaScript-Blockabdeckung. Die CI prüft
Windows, Linux, Distributionspakete und Docker-Wiederanläufe.

Entwicklungsregeln stehen in [AGENTS.md](AGENTS.md), technische Verträge in der
[Projektspezifikation](Mailhelp-Projektspezifikation.md).

## Dokumentation

| Anliegen | Anleitung |
| --- | --- |
| Installation, Updates und Paketbetrieb | [Release-Anleitung](docs/Release-1.0.md) |
| Einrichtung, OAuth und Qualitätsprüfung | [Betriebsanleitung](docs/Einrichtung-und-Qualitaetspruefung.md) |
| Web-Einstellungen und Beispiele | [Einstellungsreferenz](docs/Web-Einstellungen.md) |
| Postfachregeln, Zielprofile und Migration | [Zielprofile und Upgrade](docs/Release-3.2.md) |
| Mehrere Postfächer einrichten | [Postfachkonfiguration](docs/Release-3.1.md) |
| Vorschläge abgleichen und ergänzen | [Bedienung und Abgleich](docs/Release-2.4.md) |
| Technische Schnittstellen und Datenmodelle | [Projektspezifikation](Mailhelp-Projektspezifikation.md) |
| Änderungen veröffentlichter Versionen | [Changelog](CHANGELOG.md) |

Die statische Projektwebsite liegt unter [website/](website/).
Die [GitHub-Pages-Anleitung](docs/GitHub-Pages.md) beschreibt ihre Veröffentlichung.

## Lizenz

Mailhelp wird unter der [MIT-Lizenz](LICENSE) bereitgestellt.
