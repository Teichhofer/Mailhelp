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

**Version:** 4.0.2 · **Python:** 3.12.x · **Lizenz:** MIT

Version 4.0 bündelt die abgenommenen Stände 3.6 bis 3.8 zum Haupt-Release: Einrichtung,
Anmeldung, OAuth, Lernen und Neuladen laufen vollständig im Browser. Einrichtung, Upgrade und
Rückkehr: [Release 4.0](docs/Release-4.0.md). 4.0.1 behebt eine Verklemmung, bei der
Weboberfläche und Mailabruf nach einer Web-Aktion dauerhaft hängen blieben, während `/health`
weiter antwortete. 4.0.2 ergänzt das Thema „Behörden und Auflagen für Betrieb und
Biogasanlage“ in `topics.yaml`.

Version 3.8 ergänzt den Web-Lernmodus unter `/lernen`: Umfang und Preisannahme prüfen,
lesenden Lauf ausdrücklich starten, pausieren oder abbrechen und die bearbeiteten
Themen, Ausschlüsse, Absender und Ordner gemeinsam übernehmen. `/dienst/neu-laden`
aktiviert gespeicherte Verbindungs- und Analyseänderungen ohne Prozessneustart;
`/dienst/selbsttest` prüft die Komponenten lesend. Der Abschluss der Ersteinrichtung
wechselt im selben Prozess in den Normalbetrieb und verlinkt den Lernmodus.
Die Gesamtabnahme (Windows, Linux, Docker, installiertes Paket, Anbietermatrix) ist
bestanden. Details, Betriebsgrenzen und Abschlussbericht: [Release 3.8](docs/Release-3.8.md).

Version 3.7 startet ohne `config.yaml` einen geschützten Einrichtungsassistenten.
Den automatisch im Terminal ausgegebenen Einmalcode im Browser eingeben und
Web-Passwort, Zeitzone, Postfach, KI-Anbieter und Ziele einrichten. Terminal-Codes
über `mailhelp --pair`, Telegram-Codes und Web-Passwort sind reguläre Anmeldewege.
Google lässt sich mit der eingebauten Playground-Anleitung oder einem registrierten
Webanwendungs-Client verbinden, Microsoft über einen Gerätecode im Browser.
Details: [Release 3.7](docs/Release-3.7.md).

Version 3.6 sichert gleichzeitige Entscheidungen und Wiederherstellung nach harten
Prozessabbrüchen ab. Web-Freigaben bleiben über Neustarts an ihre Sitzung gebunden;
identische Wiederholungen zeigen denselben Vorgang und sein Ergebnis. Fehlende oder
beschädigte maßgebliche Akten blockieren unsichere Wiederholungen.
Details: [Zustandsregeln und Tests](docs/Zustandsregeln-3.6.md), [Release 3.6](docs/Release-3.6.md).

[Installation](#installation) · [Konfiguration](#konfiguration) ·
[Betrieb](#betrieb) · [Docker](#docker) ·
[Datenschutz und Sicherung](#datenschutz-und-sicherung) · [Dokumentation](#dokumentation)

## Funktionen

- **Mehrere Postfächer:** IMAP-Abruf mit getrennten Kontoidentitäten und Wiederaufnahme
  gespeicherter Verarbeitungsschritte nach einem Neustart.
  Neue Postfächer lassen sich mit Server, Ordnern und Zugangsdaten gemeinsam prüfen und
  aktivieren. Nach erfolgreicher Prüfung beginnt der Abruf ohne Dienstneustart.
  Die Startgrenze ist mit dem heutigen Datum vorbelegt; leer bedeutet alle Mails.
- **Gezielte Analyse:** Themen, ausgeschlossene Themen und Absenderfilter bestimmen,
  welche Nachrichten verarbeitet werden. Dokumente und Bildanhänge können in die
  Analyse einbezogen werden. Als irrelevant aussortierte Mails lassen sich nach einer
  Themenänderung in Maildetail und Archiv mit „Erneut prüfen“ neu analysieren.
- **Aufgaben und Termine:** Vorschläge enthalten Belege und Rückfragen bei fehlenden
  oder widersprüchlichen Angaben. Der Abgleich berücksichtigt vorhandene Einträge
  und offene Entscheidungen, um doppelte Aktionen zu vermeiden.
- **Einstellungen je Postfach:** Eigene Zielprofile, Themen, Signaturen, Ruhezeiten,
  Benachrichtigungen, Termindauern und Aufbewahrungsregeln mit globaler Vererbung.
  Die globale Einstellungsübersicht bietet Kacheln, thematische Bereiche und eine Suche.
  Gespeicherte, noch nicht aktive Änderungen werden an den Bereichskacheln angezeigt.
- **Lernbestand:** Jede manuelle Entscheidung wird mit Mail, KI-Ergebnissen sowie
  ursprünglichem und entschiedenem Vorschlag in `data/<Betriebsart>/learning/decisions.jsonl`
  abgelegt. Die Frist steht in `retention.decision_learning_days` (Standard unbegrenzt).
- **Telegram und Web-App:** Vorschläge prüfen, klären, bearbeiten, bestätigen oder
  verwerfen; Aktionen werden sofort ausgeführt, auch während Mails analysiert werden.
  Eine fehlgeschlagene Dublettenprüfung lässt sich direkt an der Karte wiederholen. Die installierbare Web-App unterstützt auch den Betrieb ohne Telegram.
  Die Statusseite führt alle konfigurierten IMAP-, IServ-, Kalender-, Aufgaben- und
  Telegram-Konten einzeln auf, einschließlich deaktivierter Konten und noch ausstehender Neustarts.
- **IServ-Elternbriefe:** Briefe aus dem IServ-Elternbriefmodul werden wie Mails
  verarbeitet, einschließlich Anhängen, und gelten immer als relevant.
  Schuladresse und Zugangsdaten lassen sich gemeinsam prüfen und aktivieren; der Abruf
  beginnt im nächsten sicheren Mailzyklus ohne manuellen Dienstneustart.
  Die Startgrenze im IServ-Webformular akzeptiert auch `01.09.2026` oder `2026-09-01`;
  reine Datumsangaben gelten ab 00:00 Uhr in der konfigurierten Zeitzone.
- **Optionale Unterstützung:** Antwortentwürfe im Ursprungspostfach, Tagesüberblicke,
  Web-Push und Tätigkeitsberichte mit XLSX-Export.

Antwortentwürfe werden nur nach ausdrücklichem Speichern im IMAP-Entwurfsordner
abgelegt. Mailhelp versendet keine E-Mails.

### Unterstützte Dienste

| Bereich | Dienste |
| --- | --- |
| E-Mail | IMAP-Postfächer |
| Schule | IServ-Elternbriefe (Lesezugriff über die Weboberfläche, keine offizielle API) |
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

Für die Browser-Ersteinrichtung die Kopierschritte auslassen und `mailhelp` starten:
Ohne `config.yaml` erscheint der geschützte Assistent mit Terminal-Code.
Die Kopierschritte oben bleiben die Alternative für manuelle Konfiguration.
Bei Einmalprüfungen wie `--check` melden fehlende Dateien weiterhin Exitcode 2;
eine vorhandene Konfiguration ohne `prompts.yaml` wird ebenfalls ausdrücklich gemeldet.

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

Im Browser sind die Verbindungen unter **Einstellungen → Zielprofile** erreichbar.
Für Google erklärt die [Playground-Anleitung](docs/Google-OAuth-Playground.md), wie
eigene Clientdaten und Refresh-Token entstehen. Die zusätzliche direkte Anmeldung
verwendet einen Webanwendungs-Client: `web.google_redirect_uri` muss exakt als
Weiterleitungsadresse registriert sein (für entfernte Rechner HTTPS).
Microsoft zeigt Gerätecode, Kopierknopf, Anmeldelink und Fortschritt im Browser.
Nach geänderten Zugangsdaten „Konfiguration neu laden“ ausdrücklich bestätigen;
Web-Sitzungsschlüssel und Web-Einstellungen benötigen einen kontrollierten Neustart. Prozessvariablen
haben weiterhin Vorrang vor `.env`.

Die bisherigen CLI-Alternativen bleiben verfügbar:

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
- Pro Datenverzeichnis läuft nur eine Instanz. Ein weiterer Start meldet
  „Mailhelp läuft bereits …“; die laufende Instanz zuerst über **Beenden** in der
  Weboberfläche oder mit Strg+C in ihrem Terminal beenden.
- Nach einem Update oder Wechsel des Codestands Mailhelp neu starten. Bis dahin
  liefert die Weboberfläche weiter Seiten und Dateien der laufenden Version aus.
- Unter **Einstellungen → Mailhelp neu starten** steht neben „Mailhelp beenden“
  ein Neustart mit eigener Bestätigungsseite bereit. Er stoppt den laufenden Dienst
  kontrolliert und startet denselben Python-Interpreter mit denselben Startoptionen
  neu. Gespeicherte Konfiguration, Zugangsdaten und aktualisierter Code werden neu
  geladen; offene Vorgänge bleiben erhalten. Danach die Weboberfläche erneut öffnen.
  Unter Windows bleibt der ursprüngliche Prozess im Terminal und startet Mailhelp
  als Kindprozess neu; Strg+C beendet weiterhin beide.

Relative Daten- und Logpfade beziehen sich auf `--config-directory`.
Fehlende Themen-Dateien werden aus den Paketvorlagen angelegt; vorhandene Dateien
werden nicht überschrieben.

### IServ-Elternbriefe

Anhänge werden bis einschließlich **5 MB (5.000.000 Bytes) je Datei** automatisch
ausgewertet (`limits.max_attachment_bytes`). Bei größeren Anhängen erscheint die
Nachricht immer als Vorschlag **„Nachricht manuell prüfen“** in der Vorschlagsliste,
auch bei sonst irrelevanten Nachrichten und ohne KI-Aufruf. Der Vorschlag nennt die
betroffenen Dateien. Er wird lokal gespeichert und erzeugt erst nach ausdrücklicher
Bestätigung eine Aufgabe im Zieldienst. Weitere Nachrichten werden weiter abgerufen.
Der Vorschlag lässt sich wie jeder andere bestätigen oder verwerfen, im Web und in
Telegram (behoben in 3.8.27). Bei IServ werden zu große Dateien nicht vollständig heruntergeladen; die Originale
bleiben dort verfügbar. Die Grenze für den Nachrichtentext ist davon unabhängig.

In der Weboberfläche unter **Einstellungen → IServ-Konten** (`/einstellungen/iserv`) je
Elternkonto Adresse der Schule, Postfach, Startgrenze und Zugangsdaten eintragen und
**Verbindung prüfen und Konto aktivieren** wählen. Leere Zugangsfelder verwenden die
bereits hinterlegten Werte. Erst nach erfolgreicher Anmeldung werden das Konto und
die Zugangsdaten gespeichert. Der laufende Dienst lädt die IServ-Verbindungen im
nächsten sicheren Mailzyklus; offene Relevanzrückfragen gegebenenfalls zuerst beantworten.
Andere offene Änderungen bleiben als Entwurf erhalten. Verbindungsfehler erscheinen direkt
auf der Seite; Kennwörter werden nie wieder angezeigt. Unter **Weitere Aktionen und Entwurf**
bleibt der bisherige Ablauf mit separater Diagnose und Übernahme verfügbar;
alternativ in `config.yaml` unter `iserv.accounts` `id`, `server` (HTTPS-Adresse der Schule)
und `mailbox` eintragen. Die Zugangsdaten stehen in `.env` als
`ISERV_<id>_USERNAME` und `ISERV_<id>_PASSWORD`. Mailhelp meldet sich wie ein Browser
an, liest neue Briefe samt Anhängen und verarbeitet sie mit Zielprofil und Standards
des angegebenen Postfachs, ohne Relevanzprüfung. Briefe vor `historical_start` (ohne
Angabe: die Grenze des Postfachs) bleiben unberührt. Mailhelp bestätigt, beantwortet
oder archiviert in IServ nichts. Zwei-Faktor-Anmeldung und auf mehrere Seiten verteilte
Briefübersichten werden noch nicht unterstützt; der Abruf meldet sie als Fehler.
`--check-access` und die Diagnose der Weboberfläche prüfen auch die IServ-Anmeldung;
die Einrichtung zeigt, ob die Zugangsdaten hinterlegt sind.

### Weboberfläche

In `config.yaml` `web.enabled: true` setzen und in `.env` einen zufälligen
`MAILHELP_WEB_SECRET` mit mindestens 32 Zeichen hinterlegen. Nach dem Dienststart
ist die Oberfläche standardmäßig unter **http://127.0.0.1:8765** erreichbar.

Auf großen Bildschirmen ordnet eine Seitenleiste die Navigation nach Arbeitsbereich,
Einblicken und Verwaltung. Auf dem Handy ist die kompakte Navigationsleiste horizontal
wischbar. Vorschlagskarten zeigen die wichtigsten Angaben zuerst; Beschreibung und
Beleg lassen sich aufklappen. Direkte Bereichslinks erleichtern die Suche in den
globalen Einstellungen.

Bestätigen und Verwerfen lassen sich 5 Sekunden rückgängig machen. Währenddessen
bleibt die Vorgangsauswahl per Maus und Tastatur gesperrt; nach dem Rückgängigmachen
ist sie sofort wieder verfügbar.

Die Seite **Status** zeigt den aktuellen Verarbeitungsschritt und je Dienst den letzten
erfolgreichen Kontakt. Beim Start prüft Mailhelp OpenRouter, Telegram und die
Kalender- und Aufgabenziele im Hintergrund nur lesend; das IMAP-Postfach erscheint
nach dem ersten Mailabruf.

Ein zweiter Terminalaufruf erzeugt einen lokalen Einmalcode:

```sh
mailhelp --pair --config-directory .
```

Unter **Einstellungen** sind auch Abrufreihenfolge und -menge, Telegram-Bindung, Antwortentwürfe,
Bildauswertung, Tagesüberblick, Tätigkeitsberichte, Lernmodus, Sitzungsdauer und Protokollierung
änderbar; die Einrichtung enthält je Postfach die Startgrenze `historical_start`.

Zugangsdaten (IMAP, IServ, OpenRouter, Telegram, Kalender- und Aufgabendienste) lassen sich
unter **Einstellungen → Zugangsdaten** eintragen oder ersetzen. Die Seite zeigt nur, ob ein
Wert hinterlegt ist, nie den Wert selbst; jede Änderung wird ausdrücklich bestätigt und nur
die betroffene Zeile in `.env` ersetzt. In Docker muss `.env` dafür beschreibbar eingebunden
sein. Der Mailabruf verwendet neue Werte nach bestätigtem Neuladen der Konfiguration.

Den Code auf der Anmeldeseite eingeben. Die Oberfläche bietet offene Entscheidungen,
Mailansichten, Suche, Verlauf, Auswertung, Berichte und Einstellungen. Die Auswertung zeigt
KI-Aufrufe, Kosten und Dauer auch als Diagramme je Tag, Schritt und Modell. Ein Klick auf ein
Diagramm öffnet eine große Ansicht. Balken zeigen ihre Details beim Darüberfahren, Fokussieren
oder Antippen; Escape oder „Schließen“ beendet die große Ansicht. Die Anmeldung
ist auch über Telegram möglich. Für den Betrieb ausschließlich mit Weboberfläche
`telegram.enabled: false` setzen.

Die [Einrichtungs- und Betriebsanleitung](docs/Einrichtung-und-Qualitaetspruefung.md)
beschreibt auch den mobilen Zugriff und die Einrichtung des Telegram-Bots.

Der Bereich **Zugangsdaten** auf der Einstellungsseite bietet einen Schnellzugriff
auf die eingerichteten Dienste. **Alle Zugangsdaten und neue Konten** öffnet die
vollständige Kontenübersicht einschließlich IServ und noch nicht übernommener
Einrichtungsentwürfe. Dort gespeicherte Werte stehen der Diagnose sofort zur Verfügung;
Werte aus der Prozessumgebung haben weiterhin Vorrang.

Die Statusseite zeigt IMAP-Abruffehler je Postfach und Ordner auch dann, wenn noch
keine Mail zur Analyse geladen werden konnte. Erst ein erfolgreicher Abruf desselben
Ordners entfernt den Hinweis. „Keine Fehler bei gespeicherten Mails“ betrifft nur
die Mailanalyse.

Beim ersten Abruf nach jedem Start speichert Mailhelp die Ordnerliste jedes Postfachs
in `mailbox-folders.json` im Datenverzeichnis: Name, Rolle (z. B. `junk` für den
Spam-Ordner), ob der Ordner abgerufen wird, und konfigurierte, aber auf dem Server
fehlende Ordner. Ein Fehlschlag wird einmal protokolliert und beim nächsten Abruf
wiederholt; der Mailabruf läuft davon unabhängig weiter.

Bereits ausgeschlossene UIDs werden auch dann vor dem Abruf gefiltert, wenn der
IMAP-Server seine höchste vorhandene UID erneut zurückgibt. Alte Warteschlangeneinträge
können nach einem Neustart abgeschlossen werden, ohne die gespeicherte Startgrenze
zu verändern.

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

Für eine neue Installation ohne vorbereitete Dateien:

```sh
docker compose -f compose.setup.yaml up --build
```

Den ausgegebenen Einmalcode unter `http://localhost:8765/anmelden` eingeben.
Konfiguration, Zugangsdaten, Zustände und Logs bleiben im benannten Volume
`mailhelp-config`. Details und Wiederherstellung: [Release 3.7](docs/Release-3.7.md).

Die bestehende `compose.yaml` verwendet weiter die manuelle Konfiguration und
baut das Image aus diesem Repository. Vor dem Start
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

Die ausgelieferte `config.example.yaml` aktiviert vollständige KI-Anfrage- und
Antwortlogs ausdrücklich. Für einen Betrieb ohne diese Inhaltslogs
`logging.llm.include_requests` und `logging.llm.include_responses` auf `false` setzen.

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

ruff begrenzt die McCabe-Komplexität jeder Funktion auf 15. mypy prüft alle
Funktionsrümpfe; für die Kernpakete (Domäne, Persistenz, Normalisierung,
Konfiguration, Laufschleife, Telegram, Review) gelten strikte Typregeln,
die in `pyproject.toml` aufgeführt sind.

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
| Einstellungsbereiche und Postfächer im Betrieb aktivieren | [Release 3.5](docs/Release-3.5.md) |
| IServ-Elternbriefe, Zugangsdaten und Einstellungen im Web | [Release 3.4](docs/Release-3.4.md) |
| Weboberfläche und technische Konsolidierung | [Release 3.3](docs/Release-3.3.md) |
| Postfachregeln, Zielprofile und Migration | [Zielprofile und Upgrade](docs/Release-3.2.md) |
| Mehrere Postfächer einrichten | [Postfachkonfiguration](docs/Release-3.1.md) |
| Vorschläge abgleichen und ergänzen | [Bedienung und Abgleich](docs/Release-2.4.md) |
| Technische Schnittstellen und Datenmodelle | [Projektspezifikation](Mailhelp-Projektspezifikation.md) |
| Änderungen veröffentlichter Versionen | [Changelog](CHANGELOG.md) |
| Fundament und Absicherung in 3.6 | [Planung und Abnahme 3.6](docs/Planung-3.6.md) |
| Ersteinrichtung und OAuth im Browser | [Planung 3.7](docs/Planung-3.7.md), [Release 3.7](docs/Release-3.7.md) |
| Web-Lernmodus, Neuladen und Anbietermatrix | [Planung 3.8](docs/Planung-3.8.md), [Release 3.8](docs/Release-3.8.md) |
| Gesamtfahrplan und Release 4.0 | [Planung 4.0](docs/Planung-4.0.md), [Release 4.0](docs/Release-4.0.md) |

Die statische Projektwebsite liegt unter [website/](website/).
Die [GitHub-Pages-Anleitung](docs/GitHub-Pages.md) beschreibt ihre Veröffentlichung.

## Lizenz

Mailhelp wird unter der [MIT-Lizenz](LICENSE) bereitgestellt.
