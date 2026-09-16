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

### Google Calendar OAuth einrichten

Mailhelp verwendet den OAuth-2.0-Refresh-Token-Ablauf; ein manuell erzeugtes,
langfristiges Access-Token wird nicht unterstützt. Die Einrichtung ist für Windows
11 und Docker identisch:

1. In einem Google-Cloud-Projekt die **Google Calendar API** aktivieren, den
   OAuth-Zustimmungsbildschirm konfigurieren und bei einer Anwendung im Testmodus
   das eigene Google-Konto als Testnutzer eintragen.
2. Einen OAuth-Client vom Typ **Desktop-App** anlegen. Bei einem stattdessen als
   Webanwendung angelegten Client muss eine lokale Loopback-URI (beispielsweise
   `http://127.0.0.1:8080/`) exakt als autorisierte Redirect-URI eingetragen sein.
3. Im Browser eine Autorisierungsanfrage mit dieser Client-ID, der exakt passenden
   Redirect-URI, `response_type=code`,
   `scope=https://www.googleapis.com/auth/calendar.events`,
   `access_type=offline` und `prompt=consent` öffnen. Nach Zustimmung den nur
   kurzfristig gültigen Code aus dem lokalen Redirect entnehmen. `offline` und
   `consent` sind erforderlich, damit Google beim erstmaligen Tausch einen
   Refresh-Token liefert.
4. Den Code einmalig per HTTPS am Google-Endpunkt
   `https://oauth2.googleapis.com/token` gegen Tokens tauschen (`grant_type` ist
   `authorization_code`; außerdem Code, Client-ID, Client-Secret und dieselbe
   Redirect-URI senden). Den zurückgegebenen Refresh-Token sicher übernehmen;
   Antwort und Befehlszeile nicht in Shell-Verlauf, Tickets oder Logs kopieren.
5. `.env.example` nach `.env` kopieren und `GOOGLE_OAUTH_CLIENT_ID`,
   `GOOGLE_OAUTH_CLIENT_SECRET` und `GOOGLE_OAUTH_REFRESH_TOKEN` dort befüllen.
   `config.yaml` enthält weiterhin nur die nicht geheime Kalender-ID unter
   `targets.google_calendar`. Die Berechtigung `calendar.events` erlaubt Mailhelp,
   Ereignisse in den für das Konto zugänglichen Kalendern zu lesen und zu ändern;
   weitergehende Calendar-Berechtigungen sind nicht erforderlich.

Unter Windows sollte `.env` nur für das eigene Benutzerkonto lesbar sein. Für
Docker Compose wird sie über `env_file` zur Laufzeit übergeben und weder ins Image
kopiert noch in ein Volume mit den JSON-Zuständen gelegt. In produktiven
Umgebungen können die drei Werte stattdessen als Prozessumgebungsvariablen aus
einem Secret-Store injiziert werden. Access-Tokens existieren nur im Speicher,
werden mit Sicherheitsabstand erneuert und landen weder in JSON-Zustand noch Logs.
Nach Widerruf oder Rotation muss lediglich der Refresh-Token ersetzt und der
Prozess beziehungsweise Container neu gestartet werden.

`config.yaml` besitzt geschlossene Modelle für IMAP, Telegram, Ziele, Limits, Wiederholungen, Timeouts und Logging. IMAP, Telegram, OpenRouter, Todoist und Google Calendar haben jeweils eigene Werte für Timeout, Retry-Anzahl sowie initialen und maximalen Backoff. Validiert werden insbesondere Port, Polling, Adaptertimeouts, Mailgröße, LLM-Rate, Wiederholungszahlen, IANA-Zeitzone, eindeutige nichtleere Ordner, sichere Pfade und die Log-Level `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. Unbekannte Schlüssel und falsche Typen werden abgelehnt.
Auch die Wurzel von `topics.yaml` ist geschlossen: Sie enthält ausschließlich die
Liste `topics`; diese muss mindestens ein aktiviertes Thema besitzen und alle
stabilen Themen-IDs müssen eindeutig sein.

Für `imap.connection_mode` sind ausschließlich `ssl` (TLS ab dem ersten Byte,
typischerweise Port 993), `starttls` (zunächst IMAP, dann zwingendes STARTTLS,
typischerweise Port 143) und `plain` (unverschlüsselt) erlaubt. `plain` ist nur für
gezielt abgesicherte lokale Netze gedacht. Die Auswahl wirkt unter Windows und im
Linux-Docker-Container identisch und benötigt keine betriebssystemspezifischen
Schalter. `imap.historical_start` ist entweder `null` (bestehendes Verhalten: alle
verfügbaren UIDs) oder ein ISO-8601-Zeitpunkt **mit explizitem UTC-Offset**, etwa
`2025-01-15T08:30:00+01:00`. Der Server wird ausschließlich mit Nur-Lese-`SELECT`,
`UID SEARCH` und `UID FETCH INTERNALDATE` abgefragt. Die sekundengenaue Grenze wird
in UTC verglichen und ihr ermittelter UID-Ausgangspunkt sofort je Konto und Ordner
persistiert; ein Neustart deutet den Zeitpunkt daher nicht anhand einer geänderten
Windows-/Container-Zeitzone oder eines inzwischen gewachsenen Postfachs neu aus.

Das globale `logging.level` kann über `logging.module_levels` je Modul überschrieben
werden. Strukturierte Anwendungs- und LLM-Ereignisse werden getrennt als JSONL
geschrieben; Rohprompt und Rohantwort bleiben standardmäßig aus und werden nur durch
`include_llm_requests` beziehungsweise `include_llm_responses` unabhängig aktiviert.
Alle Logfelder durchlaufen eine rekursive Geheimnisbereinigung.

Nur Transportfehler sowie HTTP 408, 425, 429, 500, 502, 503 und 504 werden bei lesenden beziehungsweise idempotenten Zugriffen begrenzt wiederholt. `Retry-After` wird bis zur konfigurierten Backoff-Obergrenze berücksichtigt. Schreibzugriffe werden vorab persistiert und bei Transportfehlern oder vorübergehenden HTTP-Antworten als unklar behandelt. Ein unklarer Schreibzugriff wird bei Neustarts nur abgeglichen und niemals automatisch erneut geschrieben; dafür wäre eine ausdrückliche Betreiberentscheidung erforderlich. Das OpenRouter-Minutenbudget wird im Datenverzeichnis persistiert, bleibt deshalb über Neustarts erhalten und stellt betroffene Mails bis zum nächsten zulässigen Zeitpunkt zurück.

## Betrieb und Sicherheit

* IMAP wird im Nur-Lese-Modus mit `BODY.PEEK[]` gelesen; die nicht geheime Konto-ID, Ordner, UIDVALIDITY und UID bilden die technische Identität. Die Konto-ID ist ein gekürzter SHA-256-Hash aus normalisiertem Server, Port und Benutzernamen und trennt auch gleichnamige Ordner verschiedener Konten.
* Der JSON-Zustand wird atomar ersetzt und durch eine Einzelinstanz-Sperre geschützt. Syntaktisch beschädigte Dateien werden als `.corrupt`, schemawidrige Dateien als `.invalid` isoliert; Meldungen nennen Datei und Schlüsselpfad, nicht den Inhalt. Mailzustände (Schema 3), Abrufpositionen, Telegram-Dialoge und Vorschläge (Schema 1) werden vor jeder Verwendung validiert.
* OpenRouter-, Telegram-, Todoist- und Google-Calendar-Antworten werden nach HTTP-Erfolg strikt auf JSON-Struktur, Pflichtfelder und IDs geprüft. LLM-Antworten werden strikt gegen feste Pydantic-Schemata validiert. Reservierte OpenRouter-Felder können nicht über YAML überschrieben werden.
* Google-Calendar-Access-Tokens werden aus den drei ausschließlich zur Laufzeit
  übergebenen OAuth-Geheimnissen bezogen und frühzeitig erneuert. HTTP 401 ist ein
  eindeutiger Authentifizierungsfehler, kein unklares Schreibergebnis; der
  betroffene Schreibzugriff wird deshalb nicht mit einem neuen Token wiederholt.
* Externe Aktionen verlangen eine Persistenzfunktion: `writing` wird vor dem API-Aufruf dauerhaft gespeichert. Unklare Resultate werden als `uncertain` angehalten und nur abgeglichen. Ausschließlich ein externer Treffer überführt sie in `created`; ein neuer Schreibversuch setzt eine ausdrücklich modellierte manuelle Betreiberentscheidung voraus.
* Jede Mail besitzt die schema-validierten Schritte `preparation`, `relevance`,
  `summary`, `action_detection`, `notification` und `completion`. Nach jedem Schritt
  wird atomar gespeichert; nach einem Neustart laufen ausschließlich ausstehende
  Schritte. Relevante Mails erreichen `completion` erst nach Analyse und Telegram-
  Benachrichtigung, während nicht benötigte Schritte ausdrücklich `skipped` sind.
* Vorschläge werden zusätzlich zur Maildatei versionsweise und als aktueller Stand
  gespeichert. Bestätigte Schreibvorgänge werden nach Neustarts wiederaufgenommen;
  externe ID und Link sowie `created`, `failed`, `uncertain` oder eine Testmodus-
  Simulation werden im konfigurierten Telegram-Chat sichtbar gemeldet. Die Meldung
  eines unverändert unklaren Ergebnisses wird dauerhaft markiert und nicht bei jedem
  Neustart erneut gesendet.
* `data_directory` bezeichnet das gemeinsame Stammverzeichnis. Mailhelp verwendet darunter automatisch `test/` bei `test_mode: true` und `production/` bei `test_mode: false`. Beide Namensräume besitzen eine eigene `.lock`-Datei und enthalten jeweils sämtliche IMAP-Checkpoints, Mailzustände, Telegram-Offsets und -Dialoge, Vorschläge, externe Ergebniszustände sowie das persistierte LLM-Zeitfenster. Identische IDs können deshalb nicht zwischen Test- und Produktivbetrieb kollidieren.
* Im `test_mode` findet kein externer Schreibzugriff statt; Ergebnisse tragen `simulation: true` und der Vorschlag bleibt `confirmed`, statt einen echten Eintrag vorzutäuschen.
* JSONL-Anwendungs- und LLM-Logs sind getrennt. Rohprompts und Rohantworten sind unabhängig und standardmäßig ausgeschaltet; Geheimnisfelder werden maskiert.
* `.env` unterstützt einfache `NAME=WERT`-Zeilen und einfache/doppelte Anführungszeichen, aber bewusst keine Shell-Erweiterung. Prozessvariablen überschreiben gleichnamige Werte aus der Datei.

Ohne `--check` startet der CLI-Einstieg den Dienst. Er liest alle konfigurierten
IMAP-Ordner und Telegram per Long-Polling. Abrufstände werden pro Ordner mit
Konto-ID, UIDVALIDITY, UID und einmaligem Start-UID persistiert und nach einem Neustart fortgesetzt. Ein UIDVALIDITY-Wechsel erscheint als eigenes strukturiertes Ereignis `uidvalidity_changed`. SIGINT und
SIGTERM fordern ein kontrolliertes Ende an; Netzwerkclients und die
Einzelinstanz-Sperre werden auch bei Fehlern geschlossen.

Fehler werden im Mail-Zustand ausschließlich mit sicherem Fehlercode, betroffener
Verarbeitungsstufe, Zeitstempel und optionaler Wiederholbarkeit gespeichert. Eine vor
dem Telegram-Versand persistierte Markierung verhindert doppelte Fehlermeldungen nach
einem Neustart; technische Details und Stacktraces erscheinen nur redigiert im JSONL-Log.

Noch nicht abgeschlossene `mail-*.json`-Zustände bleiben unabhängig vom
IMAP-Abrufstand erreichbar. Beim Start und vor jedem regulären IMAP-Poll werden
fällige Zustände per gezieltem, schreibfreiem `BODY.PEEK[]`-Abruf fortgesetzt;
`deferred_until` verschiebt diesen Versuch. Das Verarbeitungsergebnis unterscheidet
explizit zwischen `completed`, `waiting` und `failed`. Auch bewusst wartende und
fehlgeschlagene Versuche besitzen bereits einen dauerhaften Mailzustand, sodass
der IMAP-Abrufstand weiterlaufen und spätere UIDs verarbeiten kann; ein unerwartet
abgebrochener Versuch ohne garantiert gespeicherten Zustand hält den Abrufstand
dagegen fest. Polling- und Wiederaufnahme-Durchläufe geben ihre Einzelergebnisse
an den Aufrufer zurück.

Telegram-Updates werden an der Eingangsgrenze durch geschlossene Pydantic-
Schemata validiert. Der atomar gespeicherte Offset verhindert nach einem Neustart
die erneute Verarbeitung bereits behandelter Updates. Aktionen enthalten immer
Vorschlags-ID, Version und Aktion; nur der konfigurierte Nutzer im konfigurierten
Chat darf sie auslösen. Jede angezeigte Version wird vor ihren Schaltflächen
gespeichert. `Bestätigen`, `Ändern` und `Verwerfen` werden getrennt behandelt,
während veraltete oder fehlerhafte Schaltflächen keinen Zustand verändern.
Antworten auf Rückfragen erzeugen eine neue, erneut zu bestätigende Version.
Die Zusammenfassung nennt Absender, Betreff, zugeordnete Themen, zwei bis vier
Zusammenfassungssätze, wichtige Fristen und den erkannten Handlungsbedarf. Jeder
Vorschlag zeigt vor den Schaltflächen alle entscheidungsrelevanten Felder in einer
festen Reihenfolge; Termine nennen dabei auch die konfigurierte Zeitzone. Lange
Vorschläge tragen in jedem Teil Mail-ID, Vorschlags-ID und Teilnummer. Solange
offene Fragen bestehen, werden nur Klären und Verwerfen angeboten.
Unklare Relevanz wird vor dem Senden als schema-versionierter Dialog direkt im
Mailzustand gespeichert. Die Telegram-Auswahl enthält nur stabile interne Mail-ID,
Dialogversion und `relevant` beziehungsweise `irrelevant`; Mailtext wird nicht in
Callback-Daten übernommen. Entscheidung und verarbeiteter Telegram-Offset stehen
atomar im selben Mailzustand. Freitext wird nur bei genau einem offenen
Relevanzdialog zugeordnet, veraltete und doppelte Antworten werden sichtbar
abgelehnt. `relevant` setzt die Verarbeitung bei Zusammenfassung und
Aktionserkennung fort; `irrelevant` markiert diese Schritte und die Benachrichtigung
als `skipped` sowie den Abschluss als `completed`.

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

Mailhelp stoppen und anschließend das gesamte konfigurierte Datenverzeichnis einschließlich der Unterverzeichnisse `test/` und `production/` kopieren. Zur Wiederherstellung den Dienst stoppen, das komplette Verzeichnis zurückspielen und erst danach starten. Offene Vorgänge dürfen nicht einzeln bereinigt werden.

## Tests

```sh
python -m pytest
```

Die Standardkonfiguration erzwingt ohne Rundung 100 % Zeilen- **und** Branch-Abdeckung für `src/mailhelp`.
