# Mailhelp

Python-Assistent zur LLM-basierten Auswertung von IMAP-Mails über OpenRouter. Telegram zeigt Zusammenfassungen und versionsgebundene Einzelvorschläge; erst eine ausdrückliche Bestätigung erlaubt einen Schreibzugriff auf Todoist oder Google Kalender.

## Installation (Windows 11 und Linux)

Voraussetzung ist exakt Python **3.12.x**; `.python-version` legt für Versionsmanager 3.12.10 fest und `pyproject.toml` verhindert versehentliche Installation unter einer anderen Minor-Version.
Direkte und transitive Laufzeit-/Testabhängigkeiten sind in `requirements.lock`
festgeschrieben; das Container-Image installiert genau diese Versionen.

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e ".[test]"
Copy-Item .env.example .env
```

Unter Linux werden die letzten beiden Befehle mit `.venv/bin/python` und `cp` ausgeführt. `config.yaml`, `prompts.yaml`, `topics.yaml` und `irrelevant_topics.yaml` anpassen; echte Geheimnisse ausschließlich in `.env` oder der Prozessumgebung setzen. Laufzeitvariablen haben Vorrang. Danach validiert `mailhelp --check` alle Dateien, ohne Netzwerkzugriff. Ohne `--config-directory` verwendet Mailhelp ein vollständiges Konfigurationsset im aktuellen Arbeitsverzeichnis. Fehlt dort eine der vier Dateien, wird bei einer editierbaren Installation zusätzlich die Wurzel des Checkouts geprüft. Ein ausdrücklich angegebenes Konfigurationsverzeichnis wird nie ersetzt. Fehlen `topics.yaml` oder `irrelevant_topics.yaml`, werden sie aus den mitgelieferten Vorlagen neu angelegt; vorhandene Dateien werden nie überschrieben.

Mit `mailhelp --check-access` lässt sich anschließend ein reiner Zugriffstest
starten. Er prüft nacheinander die Anmeldung bei IMAP und den Nur-Lese-Zugriff auf
alle konfigurierten Ordner, den OpenRouter-Key über dessen authentifizierten Status, den
Telegram-Bot über `getMe` sowie den Zugriff auf das konfigurierte Todoist-Projekt.
Der Zugriffstest prüft außerdem OAuth-Anmeldung und Nur-Lese-Zugriff auf den konfigurierten Google Kalender. Nach erfolgreichem `getMe` sendet die Telegram-Prüfung
eine Nachricht mit `Test`, Datum, Uhrzeit und konfigurierter Zeitzone an den
konfigurierten Chat. Der Test ruft keine Mails ab, liest keine Telegram-Updates,
führt keinen LLM-Auftrag aus und erzeugt weder Aufgaben noch Termine. Für jeden
Dienst erscheint `OK` oder `FEHLER`; sobald mindestens eine
Prüfung fehlschlägt, endet der Prozess mit Status 1. Im Container kann derselbe
Test mit `docker compose run --rm mailhelp --check-access` ausgeführt werden.
Auch wenn bereits die Verbindung oder Anmeldung bei IMAP fehlschlägt, werden die
übrigen Dienste geprüft und anschließend alle Einzelergebnisse ausgegeben.
Zur gezielten Fehlersuche zeigt
`mailhelp --check-access --show-imap-credentials` den nach Auswertung von `.env`
und Prozessumgebung tatsächlich an IMAP übergebenen Benutzernamen und das Passwort
einmalig im Terminal an. Die Werte werden JSON-quotiert, damit auch Leer- und
Steuerzeichen erkennbar sind, und niemals in die Logs geschrieben. Dieser Schalter
legt das Passwort im Terminal offen und darf deshalb nur bewusst in einer privaten
Sitzung verwendet werden; ohne `--check-access` wird er abgelehnt.
Punkte und Bindestriche im IMAP-Benutzernamen werden unverändert an den Server
übergeben und sind für sich genommen kein Anmeldehindernis. Eine erfolgreiche
Webmail-Anmeldung beweist nicht, dass IMAP für dasselbe Postfach freigeschaltet ist
oder dass der IMAP-Server dieselbe Anmeldekennung akzeptiert. Bei
`IMAP-Anmeldung vom Server abgelehnt` sind deshalb **für das betroffene Postfach**
insbesondere die primäre vollständige E-Mail-Adresse statt eines Alias, ein
möglicherweise separates App-Passwort sowie eine postfachbezogene
IMAP-Freischaltung zu prüfen. Funktioniert ein anderes Postfach beim selben
Anbieter, bestätigt das lediglich Host, Port und Verbindungsmodus; die Ablehnung
bleibt postfach- beziehungsweise zugangsdatenbezogen.

Unter PowerShell sollte außerdem geprüft werden, ob eine ältere Prozessvariable
den gerade in `.env` eingetragenen Wert überschreibt:

```powershell
Test-Path Env:IMAP_USERNAME
Test-Path Env:IMAP_PASSWORD
Remove-Item Env:IMAP_USERNAME, Env:IMAP_PASSWORD -ErrorAction SilentlyContinue
```

Die beiden `Test-Path`-Befehle zeigen nur an, ob ein Override existiert, und geben
keine Zugangsdaten aus. Nach `Remove-Item` liest ein neuer Mailhelp-Aufruf die Werte
aus `.env`. Sollen Prozessvariablen absichtlich verwendet werden, müssen sie im
selben PowerShell-Prozess auf die gewünschten Werte gesetzt sein.
Für diesen Diagnosebefehl aktiviert Mailhelp unabhängig von der Logging-Konfiguration
das Datei- und Konsolenlogging auf `DEBUG`. Beginn, Erfolg und Fehler jeder einzelnen
Prüfung werden protokolliert; Fehler enthalten einen bereinigten Stacktrace. Die
Geheimnisbereinigung bleibt dabei uneingeschränkt aktiv.
Meldet die Telegram-Prüfung `Chat nicht erreichbar`, fragt der Diagnosebefehl
einmalig die letzten Telegram-Updates ab. Hat die konfigurierte `telegram.user_id`
dort `/start` gesendet, nennt die Fehlermeldung die dabei erkannte numerische
Chat-ID und den abweichenden Konfigurationswert. Andernfalls weist sie gezielt auf
einen falschen Bot-Token oder eine falsche User-ID hin. Der konfigurierte Bot muss
im Zielchat zunächst mit `/start` gestartet werden; bei Gruppen muss er außerdem
Mitglied sein. Die Bot-ID aus `getMe`, ein Nutzername oder eine Telefonnummer sind
keine Chat-ID. Im normalen Zugriffstest werden weiterhin keine Telegram-Updates
abgerufen; diese eingeschränkte Diagnose erfolgt ausschließlich nach `chat not found`.
`targets.todoist_project` erwartet dabei die echte Todoist-Projekt-ID, nicht den
Projektnamen, eine URL oder einen Alias. Bei Todoist bedeutet HTTP 401, dass das
Token abgelehnt wurde (Authentifizierungsfehler), HTTP 403, dass dem Token die
Berechtigung für das Zielprojekt fehlt, und HTTP 404, dass das konfigurierte
Zielprojekt nicht erreichbar ist. Diese Diagnosen geben weder Token oder
Authorization-Header noch vollständige Antwortinhalte aus.
Mailhelp verwendet dafür die aktuelle Todoist-API unter `/api/v1`; der frühere
REST-v2-Endpunkt wird von Todoist nicht mehr verwendet.

### Todoist-Zugangsdaten einrichten

Die Todoist-Anwendungsdaten werden ausschließlich über die `.env` oder gleichnamige
Prozessumgebungsvariablen eingelesen. Nach dem Kopieren von `.env.example` sind dort
`TODOIST_CLIENT_ID` und `TODOIST_CLIENT_SECRET` mit der Client-ID beziehungsweise
dem Client-Schlüssel der Todoist-Anwendung zu befüllen. Das für die REST-API als
Bearer-Token verwendete `TODOIST_TOKEN` wird ebenfalls dort gespeichert; Client-ID
und Client-Schlüssel ersetzen dieses Zugriffstoken nicht. Keiner dieser Werte
gehört in `config.yaml`, Zustandsdateien oder Logs.

### Google Kalender einrichten

Nach der versionsbezogenen Telegram-Bestätigung legt Mailhelp den Termin direkt im
unter `targets.google_calendar` konfigurierten Google Kalender an. Dafür müssen
`GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET` und
`GOOGLE_OAUTH_REFRESH_TOKEN` ausschließlich in `.env` oder als Prozessvariablen
vorliegen. Der Refresh-Token benötigt Schreibzugriff auf Google Calendar. Ort,
Beschreibung, Videolink, ganztägige Intervalle und Zeitpunkte werden über die
Calendar API übertragen. Ein privater Idempotenzschlüssel erlaubt den Abgleich vor
dem Schreiben und nach unklaren Resultaten; ein unklarer Schreibzugriff wird nicht
automatisch wiederholt. Auch im Testmodus wird ein ausdrücklich bestätigter Termin
real angelegt, während Todoist-Aufgaben simuliert bleiben.

`config.yaml` besitzt geschlossene Modelle für IMAP, Telegram, Ziele, Limits, Wiederholungen, Timeouts und Logging. `poll_interval_seconds` steuert den Abstand zwischen regulären IMAP-Zyklen. Solange eine Telegram-Entscheidung offen ist, wird dagegen nach jedem beendeten `getUpdates`-Long-Poll unmittelbar der nächste Long-Poll gestartet; dessen Server-Timeout begrenzt die Abfragerate. Fehlgeschlagene Telegram-Polls erhalten einen begrenzten, durch Shutdown unterbrechbaren Backoff. Die LLM-Wiederholungen für ungültige Providerantworten, JSON-Reparatur und Schema-Reparatur sind getrennt begrenzt. IMAP, Telegram, OpenRouter, Todoist und Google Kalender haben jeweils eigene Werte für Timeout, Retry-Anzahl sowie initialen und maximalen Backoff. Validiert werden insbesondere Port, Polling, Adaptertimeouts, Mailgröße, LLM-Rate, Wiederholungszahlen, IANA-Zeitzone, eindeutige nichtleere Ordner, sichere Pfade und die Log-Level `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. Unbekannte Schlüssel und falsche Typen werden abgelehnt.
Auch die Wurzel von `topics.yaml` ist geschlossen: Sie enthält ausschließlich die
Liste `topics`; diese muss mindestens ein aktiviertes Thema besitzen und alle
stabilen Themen-IDs müssen eindeutig sein.
`irrelevant_topics.yaml` hat dasselbe geschlossene Format und eindeutige IDs, darf
aber anfangs eine leere Themenliste enthalten.

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
persistiert; ein Neustart deutet den Zeitpunkt daher innerhalb derselben
UIDVALIDITY nicht anhand einer geänderten Windows-/Container-Zeitzone oder eines
inzwischen gewachsenen Postfachs neu aus. Nach einem UIDVALIDITY-Wechsel wird die
absolute Grenze dagegen mit `INTERNALDATE` in der neuen UID-Generation erneut
ermittelt und zusammen mit ihr gespeichert, bevor ein `BODY.PEEK[]` erfolgt.
Die mitgelieferte `config.yaml` setzt diese Grenze auf den 15. September 2026 um
00:00 Uhr in `Europe/Berlin` (`2026-09-15T00:00:00+02:00`), sodass ältere
Nachrichten beim erstmaligen Aufbau des Abrufpunkts nicht verarbeitet werden.
Mit `imap.batch_size` (Standard `25`, erlaubt `1..1000`) lädt Mailhelp pro
Ordner und Polling-Zyklus nur eine begrenzte Zahl von Nachrichten. Der Abruf
arbeitet fest **neueste zuerst mit dauerhaftem Backlog**: Noch offene UIDs werden
absteigend gewählt, und neu eingetroffene höhere UIDs haben beim nächsten Poll
Vorrang, ohne dass ältere Lücken verloren gehen. Die Ereignisse
`messages_discovered` und `message_fetched` zeigen Anzahl und Fortschritt, sodass
insbesondere der erste Abruf eines großen Postfachs nicht mehr still erscheint.
Bei einem einmaligen Lauf mit `--max-mails N` ersetzt das nach Wiederaufnahmen
noch verbleibende Budget für diesen Abruf `imap.batch_size`. Damit kann ein
begrenzter Testlauf ausdrücklich auch mehr als die regulären 25 Nachrichten
verarbeiten; zugleich werden keine vollständigen Nachrichten geladen, die der
aktuelle Lauf anschließend gar nicht verarbeitet.

Mit `imap.global_newest_first: true` werden alle unter `imap.folders`
konfigurierten Ordner als ein gemeinsames Postfach behandelt. Mailhelp ermittelt
dafür zunächst ausschließlich UID und `INTERNALDATE` aller noch offenen
Nachrichten, sortiert diese Metadaten ordnerübergreifend absteigend und lädt nur
die für den aktuellen Lauf ausgewählten vollständigen Nachrichten. Im
Dauerbetrieb gilt `imap.batch_size` dann als gemeinsames Kontingent für das ganze
Postfach; `--max-mails N` und `--learn N` wählen ebenfalls die global neuesten
`N` Nachrichten. Eigene Checkpoints je Ordner bleiben erhalten. Bei `false`
bleibt das bisherige Verhalten bestehen: Die Ordner werden in
Konfigurationsreihenfolge jeweils neueste UID zuerst bearbeitet.
Die mitgelieferte WEB.DE-Konfiguration umfasst mit `INBOX`, `Drafts`, `Sent`,
`Spam` und `Trash` alle Standardordner und verarbeitet damit nicht nur den
Posteingang. Selbst angelegte Ordner müssen zusätzlich mit ihrem exakten
IMAP-Namen in `imap.folders` eingetragen werden.

`logging.console`, `logging.file` und `logging.llm` besitzen eigene Aktivierungs- und
Level-Schalter; `logging.modules` überschreibt das Datei-Grundlevel für einzelne
Anwendungsmodule. Dateiname, Format (`text` oder `jsonl`), maximale Dateigröße,
Backup-Anzahl und Aufbewahrung in Tagen sind konfigurierbar. Das LLM-Log filtert
unabhängig von `logging.modules.openrouter`. Die mitgelieferte `config.yaml` aktiviert
`logging.llm.include_requests` und `include_responses` ausdrücklich: Das LLM-Log enthält
damit die vollständige Anfrage einschließlich Systemprompt und Usernachricht sowie die
vollständige Modellantwort. Wer diese Inhalte nicht protokollieren möchte, setzt beide
Schalter auf `false`; sie werden niemals auf die Konsole gespiegelt. Alle
Logfelder, einschließlich Fehler und Stacktraces, durchlaufen die rekursive
Geheimnisbereinigung. Alte aktive Logs und nummerierte Rotationen werden beim Start
und vor Schreibzugriffen ausschließlich innerhalb ihres konfigurierten Verzeichnisses
entfernt.
Nach erfolgreichem Laden der Konfiguration schreibt jeder Programmstart das
Ereignis `application_started` einschließlich der wirksamen CLI-Parameter
(`config_directory`, `log_directory`, `check`, `check_access` und `max_mails`) in das Anwendungslog.
Dabei werden ausschließlich die geparsten, bekannten Optionen und keine rohe
Befehlszeile oder Umgebungsvariablen protokolliert.

Unter `retention` steuern `full_mail_days` und `debug_llm_days` getrennt die
Aufbewahrung vollständiger Maildaten beziehungsweise abgeleiteter Debug-/LLM-Daten
(Relevanzbegründung, Zusammenfassung, LLM-Aufruf-IDs und Validierungsdiagnosen).
Erlaubt sind `1` bis `3650` volle Tage, `disabled` für die sofortige Minimierung
beim nächsten Bereinigungslauf und `unlimited` für unbegrenzte Aufbewahrung.
Die Frist läuft ab `updated_at`; die Bereinigung läuft einmal pro Polling-Zyklus
und ist bei Wiederholung wirkungsgleich.

Nur Transportfehler sowie HTTP 408, 425, 429, 500, 502, 503 und 504 werden bei lesenden beziehungsweise idempotenten Zugriffen begrenzt wiederholt. `Retry-After` wird bis zur konfigurierten Backoff-Obergrenze berücksichtigt. Schreibzugriffe werden vorab persistiert und bei Transportfehlern oder vorübergehenden HTTP-Antworten als unklar behandelt. Ein unklarer Schreibzugriff wird bei Neustarts nur abgeglichen und niemals automatisch erneut geschrieben; dafür wäre eine ausdrückliche Betreiberentscheidung erforderlich. Das OpenRouter-Minutenbudget wird im Datenverzeichnis persistiert, bleibt deshalb über Neustarts erhalten und stellt betroffene Mails bis zum nächsten zulässigen Zeitpunkt zurück.

### Fehlerdiagnose im Testlauf

* `openrouter` / `retry_failed` mit HTTP `401 Unauthorized` bedeutet, dass
  OpenRouter den Wert von `OPENROUTER_API_KEY` abgelehnt hat. Der Schlüssel muss
  in der `.env` im verwendeten Konfigurationsverzeichnis oder in der Umgebung des
  tatsächlich gestarteten Prozesses beziehungsweise Containers korrigiert und der
  Dienst danach neu gestartet werden. `mailhelp --check` prüft nur, ob das
  Geheimnis vorhanden ist; der Befehl führt bewusst keinen Netzwerkaufruf aus und
  kann daher weder Gültigkeit noch Guthaben des Schlüssels bestätigen. Ein 401 ist
  nicht wiederholbar, weshalb trotz des allgemeinen Ereignisnamens nur
  `attempt: 1` erscheint. `Permanente Adapterantwort` ist die zusammengefasste
  Folge dieses Authentifizierungsfehlers, nicht ein zusätzlicher Telegram-Fehler.
* `mime_limit_exceeded` mit `max_mail_bytes` bedeutet, dass die MIME-Nachricht
  nach dem Entfernen erkannter Anhänge größer als `limits.max_mail_bytes` ist.
  Große Anhänge und deren Transferkodierung verhindern die Verarbeitung des
  verbleibenden Mailtexts nicht. Den Wert nur dann in
  `config.yaml` erhöhen, wenn diese Nachrichten bewusst verarbeitet werden sollen;
  die zusätzlichen MIME-, Text-, HTML- und LLM-Nutzlastgrenzen bleiben weiterhin
  wirksam. Alternativ muss der eigentliche Nachrichtentext vor der Verarbeitung
  verkleinert werden.
  Vor der vollständigen MIME-Aufbereitung liest Mailhelp ausschließlich den bis
  `limits.max_header_bytes` begrenzten, vollständig abgeschlossenen Headerblock,
  um `From` und `Subject` sicher in der Telegram-Fehlermeldung anzuzeigen. Diese
  eingeschränkte Headeranzeige ist **keine** erfolgreiche oder vollständige
  MIME-Verarbeitung und gelangt nicht an das LLM; fehlende, abgeschnittene oder
  überlange Werte erscheinen als `—`. Das Ereignis `mime_limit_exceeded` enthält
  weiterhin im Feld `limit` die konkret überschrittene Grenze, etwa
  `max_mime_parts` oder `max_decoded_text_bytes`.
* Wiederholte `configuration_changed`-Ereignisse sind eine absichtliche
  Schutzsperre: Offene Zustände wurden mit einer anderen Kombination aus
  `config.yaml`, `prompts.yaml` und `topics.yaml` erzeugt. Nicht durch Löschen
  einzelner Zustandsdateien umgehen, sondern entweder die ursprüngliche
  Konfiguration wiederherstellen oder nach Sicherung des gesamten
  Zustandsverzeichnisses eine bewusste Neuverarbeitung beginnen. Die beiden
  Fingerprints im Ereignis erlauben dabei die eindeutige Zuordnung.
* `cleanup_completed` mit einem hohen `protected_count` ist in einem solchen Lauf
  erwartbar: Nicht abgeschlossene oder fehlgeschlagene Zustände werden von der
  Aufbewahrungsbereinigung geschützt. `mail_count: 0` sagt deshalb nicht aus, dass
  keine Nachrichten gefunden wurden, sondern dass in diesem Lauf keine
  vollständigen Mailinhalte minimiert wurden.
* `telegram` / `send_started` direkt nach einem Verarbeitungsfehler ist die
  beabsichtigte einmalige Fehlerbenachrichtigung. Erst ein nachfolgendes
  `send_failed` oder `poll_failed` weist auf ein Telegram-Problem hin.

Vor Änderungen oder einer Bereinigung den Dienst stoppen und das vollständige
`data`-Verzeichnis sichern. Zustandsdateien nicht einzeln löschen: Abrufstände,
Fehlermarkierungen und Idempotenzinformationen gehören zusammen. Für einen bewusst
frischen Testlauf darf nach der Sicherung ausschließlich der gesamte isolierte
`data/test`-Zustand entfernt werden; `data/production` bleibt unberührt.

### Migration älterer Vorschlagszustände

Vorschläge werden nun unter `proposal-<mail-id>-<proposal-id>.json` (und versioniert
mit `-v<version>`) gespeichert. Callback, Rückfragedialog und Idempotenzschlüssel
enthalten ebenfalls Mail-ID, Vorschlags-ID und Version. Alte `proposal-<id>.json`,
`proposal-<id>-v<version>.json`, alte `telegram-dialog.json`-Referenzen und
Schreibreferenzen ohne `mail_id` dürfen deshalb **nicht automatisch übernommen
oder bestätigt** werden.

Für eine sichere Umstellung: Mailhelp stoppen, das Datenverzeichnis sichern und
alle bereits abgeschlossenen externen Schreibvorgänge anhand Todoist abgleichen und bereits angelegte Google-Kalendertermine anhand ihres Idempotenzschlüssels prüfen. Danach alte Vorschlagsdateien und einen alten
`telegram-dialog.json` in ein schreibgeschütztes Archiv außerhalb des aktiven
Zustandsverzeichnisses verschieben. Betroffene, noch nicht ausgeführte Mails werden
anschließend aus ihrer unveränderten Quelle neu eingelesen und erhalten neue interne
Vorschlags-IDs; sie müssen in Telegram erneut in der angezeigten Version bestätigt
werden. Einen Status `writing` oder `uncertain` niemals in `confirmed` umschreiben:
erst den alten Idempotenzschlüssel extern abgleichen, damit kein doppelter Eintrag
entsteht. Test- und Produktionszustände bleiben dabei getrennt zu behandeln.

## Betrieb und Sicherheit

* IMAP wird im Nur-Lese-Modus mit einem gemeinsamen `BODY.PEEK[] INTERNALDATE`-Abruf gelesen; die nicht geheime Konto-ID, Ordner, UIDVALIDITY und UID bilden die technische Identität. `INTERNALDATE` wird strikt als zeitzonenbehafteter Empfangszeitpunkt geparst. Die Konto-ID ist ein gekürzter SHA-256-Hash aus normalisiertem Server, Port und Benutzernamen und trennt auch gleichnamige Ordner verschiedener Konten.
* Die Analyse erhält vier getrennte Datumsinformationen: den unveränderten, bereinigten `Date`-Header (`date_header_original`), seine nur bei explizitem Offset verfügbare Parseform (`date_header_parsed`), `imap_received_at` sowie die konfigurierte IANA-`user_timezone`. `date_context_status` kennzeichnet fehlende, ungültige, naive und um mehr als sieben Tage vom Empfang abweichende Angaben. Ein solcher Kontext erzwingt bei Terminen und Aufgaben mit Frist eine offene Rückfrage und verhindert damit die Bestätigung und Speicherung; Aufgaben ohne Frist bleiben davon unberührt.
* Nach der schema-validierten Roh-Extraktion entsteht an der Proposal-Grenze ein
  `temporal_fact`: `raw_text` bewahrt die Mailformulierung, `normalized_date` ein
  sicher aufgelöstes ISO-Datum, `year_source` dessen Herkunft und `status` den
  Auflösungszustand. Ein fehlendes Jahr wird nur aus validiertem Mailkontext
  abgeleitet; liegt Monat/Tag bereits zurück, gilt das unmittelbar folgende Jahr.
  Ein explizites vierstelliges Mailjahr hat Vorrang, widersprechende explizite
  Jahre bleiben unbestätigbar. Zusammenfassungen sind keine Datumsquelle. Der
  Fakt wird Telegram-Interpretation und Revision begrenzt weitergereicht, sodass
  `2026-10-21` nicht wieder zu `21. Oktober` degradiert wird.
* `Proposal.due` ist eine streng validierte Union: `YYYY-MM-DD` bezeichnet ein reines Fälligkeitsdatum und wird unverändert als Todoist-`due_date` übertragen. Ein Fälligkeitszeitpunkt enthält Datum und Uhrzeit samt explizitem UTC-Offset (zum Beispiel `2026-10-01T17:00:00+02:00`) und wird als `due_datetime` übertragen. Naive Zeitpunkte werden abgelehnt und reine Daten niemals stillschweigend in Mitternacht umgewandelt.
* Der JSON-Zustand wird atomar ersetzt und durch eine betriebssystemseitige, an den laufenden Prozess gebundene Einzelinstanz-Sperre geschützt. Die `.lock`-Datei bleibt nach dem Schließen als Diagnoseinformation erhalten; ausschließlich die vom Betriebssystem gehaltene Sperre entscheidet, ob eine Instanz aktiv ist. Syntaktisch beschädigte Dateien werden als `.corrupt`, schemawidrige Dateien als `.invalid` isoliert; Meldungen nennen Datei und Schlüsselpfad, nicht den Inhalt. Mailzustände (Schema 9), Abrufpositionen, Telegram-Dialoge und Duplikatindex (Schema 1) sowie Vorschläge (Schema 2) werden vor jeder Verwendung validiert.
* OpenRouter-, Telegram-, Todoist- und Google-Calendar-Antworten werden nach HTTP-Erfolg strikt auf JSON-Struktur, Pflichtfelder und IDs geprüft. Bei OpenRouter werden eine ungültige Provider-Hülle (`provider_response_invalid` samt inhaltsfreiem Grund), ungültige JSON-Syntax (`invalid_json`) und ein Verstoß gegen das stufenspezifische Pydantic-Schema (`schema_validation_failed`) getrennt behandelt und jeweils unabhängig begrenzt wiederholt. Provider-Retries senden den unveränderten fachlichen Payload, JSON-Reparaturen nur einen JSON-Formathinweis und ausschließlich Schema-Reparaturen die konkrete vorherige Validierungsabweichung. Die flache Steuerung begrenzt die Gesamtzahl auf einen Erstaufruf plus die drei konfigurierten Retry-Zahlen. Providerfehler werden nicht als Schemafehler in `validation_errors` gespeichert. Reservierte OpenRouter-Felder können nicht über YAML überschrieben werden.
* Jeder LLM-Versuch trägt die vom Analyzer fest vorgegebene Stufe, Modell,
  OpenRouter-Backend-Provider (bei fehlender Metadatenangabe `null`), Call-ID,
  HTTP-Status, Finish-Reason, ausschließlich Länge und Vorhandensein des Inhalts,
  JSON-/Schemaergebnis sowie Retry-Typ und -Nummer. Das Schemaergebnis wird erst
  nach der Analyzer-Validierung als eigenes Abschlussereignis protokolliert;
  `content: null`, ungültiges JSON und Schemafehler bleiben getrennte Ereignisse.
  Zusätzlich hält `token_usage_recorded` den vom Provider gemeldeten Tokenverbrauch
  je Call-ID fest; `token_usage_available: false` kennzeichnet fehlende Angaben.
* Bei Terminen bleiben der physische Ort und ein optionaler, ausschließlich per HTTP/HTTPS erlaubter Videolink getrennte Vorschlagsfelder und werden vor der Bestätigung beide in Telegram angezeigt. Google Calendar erhält Ort, Beschreibung und Videolink; zeitgebundene Werte behalten ihren eindeutigen Offset und ganztägige Enddaten bleiben exklusiv.
* Externe Aktionen verlangen eine Persistenzfunktion: `writing` wird vor dem API-Aufruf dauerhaft gespeichert. Unklare Resultate werden als `uncertain` angehalten und nur abgeglichen. Ausschließlich ein externer Treffer überführt sie in `created`; ein neuer Schreibversuch setzt eine ausdrücklich modellierte manuelle Betreiberentscheidung voraus.
* Jede Mail besitzt die schema-validierten Schritte `preparation`, `relevance`,
  `summary`, `summary_notification`, `action_detection`, `action_router`,
  `task_extraction`, `event_extraction`, `normalization`, `proposal_building`, `proposal_notification`
  und `completion`. Nach jedem Schritt
  wird atomar gespeichert; nach einem Neustart laufen ausschließlich ausstehende
  Schritte. Relevante Mails speichern und versenden die Summary vor der
  Action-Erkennung. Ein erschöpfter Action-Fehler
  beendet die Mail als Teilfehler und bleibt gezielt wiederholbar; Summary und deren
  Versand werden dabei nicht wiederholt. Versand wird vor dem Telegram-Aufruf als
  `sending` markiert, damit ein Abbruch danach keinen unkontrollierten Doppelversand
  auslöst. Nicht benötigte Schritte sind ausdrücklich `skipped`.
  **Abgeschlossen mit Action-Fehler** bedeutet daher nicht, dass alle Aktionen
  verarbeitet wurden: Die Mail und ihre Zusammenfassung sind abgeschlossen, die
  betroffene Action-Teilstufe bleibt jedoch `failed` und gezielt wiederaufnehmbar.
  Beim Wiederaufnehmen werden weder Relevanz und Zusammenfassung noch eine bereits
  versandte Zusammenfassung oder eine erfolgreiche Schwester-Extraktion wiederholt.
* Jeder Vorschlag trägt die streng validierten Felder `responsibility` (`user`, `other`, `unclear`), `certainty` (`certain`, `uncertain`, `contradictory`) und `classification` (`new`, `non_binding`, `already_completed`, `change`, `cancellation`, `recurring`, `unsupported`). Ausschließlich `new` + `user` + `certain` ist bestätigbar und extern anlegbar. Alle anderen Einordnungen erscheinen als manuell zu prüfende Information; offene Zuständigkeit, Unsicherheit und Widerspruch erzwingen `needs_clarification`.
* Termine tragen zusätzlich `time_requirement`: Nur explizite Mail-Evidenz darf
  `all_day` setzen; `timed` bezeichnet einen zeitgebundenen Termin und
  `required_unknown` die konservative Wahl bei unklarer Zeitsemantik. Ein bekanntes
  Datum ohne Uhrzeit wird in `known_temporal_facts` bewahrt und löst eine konkrete
  Frage nach dem Beginn aus, statt stillschweigend einen Ganztagstermin zu erzeugen.
  Ein bekannter Beginn löst nur noch die Frage nach dem Ende aus; Uhrzeit, Ende und
  Dauer werden niemals ergänzt.
  Eine an die Nutzerin oder den Nutzer gerichtete, noch auszuführende einmalige
  Bitte, Aufforderung oder Verpflichtung wird als `new` klassifiziert. Eine
  sachliche, automatisch erzeugte oder indirekte Formulierung macht die Aufgabe
  nicht `non_binding` oder `unsupported`.
  Ein ausdrücklich angekündigter, einmaliger künftiger Termin oder eine
  Einladung dazu wird als `new` klassifiziert. Der reine Informationscharakter
  oder der Versand durch ein externes Veranstaltungssystem macht den Termin
  nicht `non_binding` oder `unsupported`.
* Vorschläge werden zusätzlich zur Maildatei versionsweise und als aktueller Stand
  gespeichert. Bestätigte Schreibvorgänge werden nach Neustarts wiederaufgenommen;
  externe ID und Link sowie `created`, `failed` oder `uncertain` werden im
  konfigurierten Telegram-Chat sichtbar gemeldet. Aufgaben werden im Testmodus
  stattdessen vor der Meldung mit dem Abschlusszustand `simulated` ohne externe ID
  oder Link atomar gespeichert. Google-Kalendertermine werden auch im Testmodus tatsächlich
  angelegt und als `created` gespeichert. `simulation_notified`
  hält anschließend dauerhaft fest, dass die
  eindeutig als Simulation bezeichnete Meldung versandt wurde. Mehrfach-Polls und
  Neustarts führen deshalb weder die Simulation erneut aus noch melden sie erneut;
  ein zwischen Speichern und Meldung erfolgter Abbruch kann die noch ungemeldete
  Simulation dagegen sicher zu Ende melden. Entsprechend wird auch die Meldung eines
  unverändert unklaren Ergebnisses dauerhaft markiert.
* Erfolgreich angelegte Termine und Aufgaben werden zusätzlich im validierten,
  menschenlesbaren `action-ledger.json` verbucht. Erkennt Mailhelp bei einer späteren
  Bestätigung dieselbe fachliche Aktion, bleibt der Vorschlag zunächst offen und
  Telegram verlangt über eine eigene versionsgebundene Schaltfläche eine zweite,
  ausdrückliche Freigabe. Ohne diese Freigabe erfolgt kein erneuter Schreibzugriff.
* `data_directory` bezeichnet das gemeinsame Stammverzeichnis. Mailhelp verwendet darunter automatisch `test/` bei `test_mode: true` und `production/` bei `test_mode: false`. Beide Namensräume besitzen eine eigene `.lock`-Datei und enthalten jeweils sämtliche IMAP-Checkpoints, Mailzustände, Telegram-Offsets und -Dialoge, Vorschläge, externe Ergebniszustände sowie das persistierte LLM-Zeitfenster. Identische IDs können deshalb nicht zwischen Test- und Produktivbetrieb kollidieren.
* Ein schema-validierter `duplicate-index.json` hält ausschließlich technische
  IMAP-Identitäten, normalisierte Message-IDs, interne Mail-IDs und SHA-256-
  Inhaltsfingerprints aus stabilen Absender-, Betreff-, Datums- und Textmerkmalen.
  Gleiche einzelne Message-ID plus gleicher Fingerprint wird vor einem LLM-Aufruf
  übersprungen. Fehlende/mehrfache Message-IDs, wiederverwendete IDs, noch offene
  Kandidaten und reine Fingerprinttreffer werden als `ambiguous` gespeichert und
  weiterhin verarbeitet. Das Ereignis enthält nur Entscheidung und interne IDs.
* Die Inhaltsbereinigung arbeitet ausschließlich im ausgewählten Namensraum und
  an abgeschlossenen Vorgängen. Offene Relevanzdialoge, Rückfragen und
  Bestätigungen sowie `confirmed`, `writing` oder `uncertain` werden geschützt.
  Bei bereinigten Abschlüssen bleiben IMAP-Identität, Zeitpunkte, Schritte,
  Vorschlagsversionen, externe IDs/Links und Schreibreferenzen samt
  Idempotenzschlüsseln erhalten. Ein Restore kann so weiterhin Ergebnisse
  zuordnen und Duplikate verhindern; entfernte Inhalte sind nicht
  wiederherstellbar. Logs nennen nur Mail-ID, Laufzeitpunkt und Zähler.
* Im `test_mode` findet kein Todoist-Schreibzugriff statt; Aufgaben werden als Simulation abgeschlossen. Bestätigte Termine werden dagegen wie im Produktivmodus tatsächlich über die Google Calendar API angelegt.
* JSONL-Anwendungs- und LLM-Logs sind getrennt. Die Beispielkonfiguration protokolliert vollständige LLM-Anfragen und -Antworten; beide Inhaltsarten lassen sich unabhängig abschalten und Geheimnisfelder werden stets maskiert.
* `.env` unterstützt einfache `NAME=WERT`-Zeilen und einfache/doppelte Anführungszeichen, aber bewusst keine Shell-Erweiterung. Prozessvariablen überschreiben gleichnamige Werte aus der Datei.

### Alte Mailzustände kontrolliert verarbeiten

Mailzustands-Schema 9 migriert Schema 6, 7 und 8 ausdrücklich, indem der früher gemeinsame
Benachrichtigungsstatus konservativ auf Summary- und Vorschlagsversand abgebildet
die getrennten Extraktions-Teilstatus ergänzt und vorhandene Vorschläge mit versionierten Versandmarkern übernommen werden; die Datei wird sofort
atomar als Schema 9 gespeichert. Schema 9 bleibt gegenüber
Schema 3 bewusst inkompatibel. **Für Schema 3 findet keine automatische Migration
statt.** Beim Laden wird eine solche Datei
als schemawidrig erkannt und neben den Zustandsdateien mit der Endung `.invalid`
isoliert. Mailhelp rekonstruiert insbesondere die in neueren Schemata erforderlichen
Zeitpunkte, Konfigurations-Fingerprints und Schreibreferenzen nicht, weil dies
bereits ausgeführte Aktionen fälschlich wiederholen könnte.

Betreiber führen eine erneute Verarbeitung deshalb ausschließlich kontrolliert
durch:

1. Mailhelp stoppen und eine vollständige Sicherung des betroffenen
   Modusverzeichnisses (`data/test/` oder `data/production/`) einschließlich der
   `.invalid`-Datei und der IMAP-Checkpoints erstellen.
2. Anhand von Konto, Ordner, UIDVALIDITY und UID der gesicherten Datei die
   Ursprungsmail sowie den zugehörigen IMAP-Checkpoint eindeutig bestimmen und
   prüfen, ob bereits Todoist-Aufgaben oder Kalendertermine erzeugt wurden.
3. Den Checkpoint für genau dieses Konto und diesen Ordner bei gestopptem Dienst
   bewusst auf eine UID vor der betroffenen Mail zurücksetzen. Die
   `.invalid`-Datei als Nachweis gesichert lassen und nicht in Schema 9
   umetikettieren oder manuell mit erfundenen Pflichtfeldern ergänzen.
4. Mailhelp mit der aktuellen Version starten, die Mail neu als Schema 9 einlesen
   lassen und alle neu vorgeschlagenen Schreibaktionen erneut über Telegram
   prüfen und versionsbezogen bestätigen. Anschließend kontrollieren, dass der
   Checkpoint wieder vorgerückt ist und keine doppelte externe Aktion entstand.

Wenn diese Prüfung oder ein sicherer Checkpoint-Rücklauf nicht möglich ist, darf
die Datei nicht erneut verarbeitet werden. Stattdessen kann der Vorgang mit der
vorherigen, Schema 3 unterstützenden Programmversion in einer gesicherten
Umgebung abgeschlossen werden.

Ohne `--check` startet der CLI-Einstieg den Dienst. Er liest alle konfigurierten
IMAP-Ordner und Telegram per Long-Polling. Abrufstände werden pro Ordner mit
Konto-ID, UIDVALIDITY, einmaligem Start-UID, informativer höchster UID und
normalisierten Bereichen der bereits dauerhaft übernommenen UIDs persistiert.
Deshalb kann eine hohe neue UID eine ältere offene UID nicht überspringen; nach
einem Neustart werden sowohl Backlog als auch Lücken fortgesetzt. Ein
UIDVALIDITY-Wechsel verwirft nur die Bereiche des betroffenen Ordners und löst
eine konfigurierte historische Zeitgrenze in der neuen UID-Namenswelt erneut
auf. Er erscheint als eigenes strukturiertes Ereignis `uidvalidity_changed`. SIGINT und
SIGTERM fordern ein kontrolliertes Ende an; Netzwerkclients und die
Einzelinstanz-Sperre werden auch bei Fehlern geschlossen. `Strg+C` beendet auch
die Einmalmodi (`--check`, `--check-access`, `--learn` und `--clear`) kontrolliert
mit Exit-Code 130 und ohne Python-Traceback. Unmittelbar vor dem
Beenden sendet der Bot in den konfigurierten Telegram-Chat eine Laufzusammenfassung
mit der Gesamtzahl der bearbeiteten sowie der erfolgreich abgeschlossenen,
wartenden und fehlgeschlagenen Verarbeitungsversuche. Die Zusammenfassung wird
auch bei einem Laufzeitfehler versucht; ein Versandfehler wird protokolliert und
verdeckt einen bereits aufgetretenen Fehler nicht.

Für einen begrenzten Testlauf verarbeitet beispielsweise `mailhelp --max-mails 50`
in genau einem Abrufdurchlauf höchstens 50 Mails, auch wenn `imap.batch_size` auf
dem Standardwert 25 steht (einschließlich fälliger, nach einem
Neustart fortzusetzender Mails), fragt anschließend einmal Telegram ab und
beendet sich. Nicht verbrauchtes Kontingent führt nicht zu einem weiteren Poll;
`--max-mails` muss mindestens `1` sein. Bereits bestätigte externe Schreibaktionen
behalten auch in diesem Modus ihre normalen Sicherheits- und Abgleichsregeln.
Wenn Arbeit auf Eingabe wartet, weist die abschließende Telegram-Zusammenfassung
darauf hin, dass erst nach diesem einmaligen Abruf eingehende Antworten beim
nächsten Start verarbeitet werden. Für laufende Dialoge ohne dieses begrenzte
Antwortfenster ist der Dauerbetrieb ohne `--max-mails` vorgesehen.
Offene Bestandszustände mit einem anderen Konfigurationsfingerprint werden ohne
IMAP-Abruf und ohne Fortsetzung als blockiert gemeldet. Sie verbrauchen das
Verarbeitungskontingent nicht; pro Lauf werden zusätzlich höchstens
`--max-mails` solcher Zustände gescannt und gemeldet, damit ein großer alter
Bestand weder neue Mails verdrängt noch den Lauf unbegrenzt verlängert.
Im dauerhaften Betrieb ohne `--max-mails` endet dieser zusätzliche Scan nach
1.000 blockierten Zuständen je Abrufdurchlauf.

### Alle Laufzeitdaten löschen

`mailhelp --clear` löscht die vollständigen Zustände der Test- und
Produktionsnamensräume sowie sämtliche Dateien im konfigurierten Logverzeichnis.
Der Dienst muss dafür beendet sein; eine noch aktive Instanz verhindert das
Löschen über ihre Datensperre. Da auch Checkpoints, offene Bestätigungen,
Duplikatschutz und externe Ergebnisreferenzen unwiderruflich verloren gehen,
verlangt der Befehl im Terminal die exakte Eingabe `ALLE DATEN LOESCHEN`.
Ein leerer oder abweichender Text bricht ohne Änderung mit Status 1 ab.

Für einen bewusst nicht interaktiven Aufruf steht `mailhelp --clear --yes` zur
Verfügung. `--yes` ist ohne `--clear` unzulässig. `--log-directory PFAD`
überschreibt auch beim Löschen das konfigurierte Logverzeichnis. Konfiguration,
Prompts, Themen und Geheimnisse werden nicht gelöscht.

### Interaktiver Lernmodus

`mailhelp --learn 20` ruft bis zu 20 der neuesten Mails schreibfrei mit
`BODY.PEEK[]` aus den konfigurierten Ordnern ab. Jede Mail wird zuerst in einer
gemeinsamen LLM-Anfrage gegen die aktivierten Einträge aus `topics.yaml` und
`irrelevant_topics.yaml` geprüft. Bereits
zuordenbare Mails werden übersprungen. Nur Mails, die zu keiner der beiden Listen
gehören, werden ohne vorgegebene Themenliste durch den in `prompts.yaml` konfigurierten Schritt
`learning_classification` klassifiziert. Die unabhängigen Relevanzprüfungen und
Einzelklassifikationen dieser ersten Stufe laufen mit der in `config.yaml` unter
`learning.parallel_llm_calls` eingestellten maximalen Parallelität. Die Reihenfolge
der Ergebnisse bleibt dabei stabil. Ein einzelner weiterer Aufruf über
`learning_abstraction` fasst die Ergebnisse zu höchstens 20 allgemeineren Themen
zusammen. Kurze Beschreibungen und höchstens zwei Beispiele je Thema begrenzen die
JSON-Ausgabe. Für die vorgeschaltete Relevanzprüfung sowie für Einzelklassifikation und
Abstraktion überschreibt `prompts.yaml` das globale Ausgabelimit mit größeren
Budgets, damit Reasoning-Provider ihre interne Verarbeitung und das abschließende
JSON nicht vorzeitig bei `finish_reason=length` abbrechen. Die Abstraktion erhält
mit 16.000 Tokens das größte Budget.
Antwortet ein Provider dennoch mit syntaktisch ungültigem JSON, wird der
begrenzte Reparaturversuch zusätzlich durch eine Systemanweisung erzwungen;
die Anweisung im Nutzdatenobjekt allein könnte sonst als nicht vertrauenswürdiger
Mailinhalt behandelt und ignoriert werden.
Anschließend zeigt das Programm jede vorgeschlagene Kategorie ausschließlich im
Terminal an und verlangt dort eine Antwort mit `j` oder `n`. Bestätigte
Kategorien werden aktiviert und atomar in `topics.yaml`, abgelehnte Kategorien
atomar in `irrelevant_topics.yaml` ergänzt; IMAP-Checkpoints
und Telegram werden in diesem Modus nicht verwendet. `--learn` muss mindestens
`1` sein.

Zusätzlich führt Mailhelp im jeweiligen Zustandsnamensraum die lesbare Datei
`irrelevant-senders.json`. Ihre `addresses` werden im Lernlauf automatisch um die
Absender von Nachrichten ergänzt, die einer abgelehnten Kategorie zugeordnet
wurden. Unter `domains` können vollständige Absenderdomains ohne `@` eingetragen
werden, etwa `newsletter.example`. Exakte Adressen und Domains werden bereits vor
der inhaltlichen LLM-Relevanzprüfung verglichen; passende Nachrichten gelten ohne
Übermittlung ihres Inhalts an das LLM als irrelevant. Alle Einträge sind
kleingeschrieben, sortiert und eindeutig. Da die Datei Zustand ist, wird sie von
`--clear` gemeinsam mit den übrigen Zustandsdaten entfernt.

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

Telegram-Transportantworten werden an der Eingangsgrenze durch Pydantic-Schemata
validiert: Die von Mailhelp verwendeten Pflichtfelder bleiben streng typisiert,
während zusätzliche Telegram-Felder ignoriert und insbesondere nicht in interne
Zustände übernommen werden. Bei Telegram-API-Fehlern wird
das dokumentierte `description`-Feld vollständig in die Fehlermeldung übernommen;
Antwortkörper und Bot-Token werden dabei nicht ausgegeben. Die internen Modelle für
Vorschlags- und Relevanzentscheidungen bleiben dagegen geschlossen und lehnen
unbekannte Felder ab. Der atomar gespeicherte Offset verhindert nach einem Neustart
die erneute Verarbeitung bereits behandelter Updates. Vorschlagsaktionen verwenden
einen kryptografisch zufälligen, kurzen Callback-Token. Seine atomar gespeicherte
Zuordnung enthält ausschließlich Mail-ID, Vorschlags-ID, Version und Aktion und
bleibt nach einem Neustart auflösbar; insbesondere fließen keine LLM-Inhalte in den
Token ein. Vor jedem Telegram-Aufruf prüft Mailhelp jedes `callback_data` auf die
zulässigen 1 bis 64 UTF-8-Bytes. Alte, eindeutig validierbare Vorschlagscallbacks
werden innerhalb derselben Bytegrenze weiterhin angenommen. Nur der konfigurierte
Nutzer im konfigurierten Chat darf eine Aktion auslösen. Jede angezeigte Version
wird vor ihren Schaltflächen gespeichert. Aufgabenvorschläge bieten `Bestätigen`,
`Ändern` und `Verwerfen`; vollständige Terminvorschläge bieten ausschließlich
`Anlegen` und `Verwerfen`. `Anlegen` schreibt den Termin über die Google Calendar API in den konfigurierten Zielkalender. Die Aktionen werden getrennt behandelt,
während veraltete oder fehlerhafte Schaltflächen keinen Zustand verändern.
Callback-Klicks werden sofort bei Telegram quittiert. Erst nach erfolgreicher
fachlicher Annahme entfernt Mailhelp zentral die gesamte Inline-Tastatur der
ursprünglichen Nachricht mit `editMessageReplyMarkup` und sendet anschließend
eine kurze Bestätigung der gewählten Aktion in den Chat. Bei einem Fehler wird
stattdessen eine kurze Fehlermeldung gesendet; die Schaltflächen bleiben für
einen erneuten Versuch erhalten.
Antworten auf Rückfragen werden zuerst in einem eigenen LLM-Schritt mit der
konkret erfragten Information verglichen und bei eindeutiger Zuordnung in die für
die Überarbeitung benötigte Form normalisiert. Erst danach erzeugen sie eine neue,
erneut zu bestätigende Version. Ist die Antwort nicht eindeutig nutzbar, erzeugt
ein zweiter, getrennt schematisierter LLM-Aufruf eine konkrete Rückfrage; Vorschlag
und Dialog bleiben dabei unverändert.
Eine nutzbare Antwort wird nicht als Telegram-Freitext, sondern als normalisierter
Wert in einem eigenen, versionsgebundenen Klärungszustand (Schema 2) gespeichert.
Dieser unterscheidet `question_status`, `answer_status` und
`proposal_revision_status`. Die konkrete Frage gilt mit diesem atomaren Schreiben
dauerhaft als beantwortet; erst danach wird der aktive Telegram-Dialog geschlossen
und die Revision aufgerufen. Provider-, Tokenlimit-, JSON- oder Schemafehler ändern
nur den Revisionsstatus in `retry_required`. Beim nächsten Lauf wird die Revision
aus der gespeicherten normalisierten Antwort wiederaufgenommen, ohne erneut nach
einer Telegram-Antwort zu fragen. Auch ein Absturz zwischen Antwortpersistenz und
Revision verliert die Antwort daher nicht; spätere Nachrichten wie „Ok“ können
nicht mehr der alten Frage zugeordnet werden.
Die Fehlergrenze unterscheidet dabei ausdrücklich unvollständige Benutzereingaben,
fachlich widersprüchliche Revisionen und technische Revisionsfehler. Nur eine als
unvollständig validierte Eingabe erhält eine konkrete fachliche Rückfrage. Provider-,
Transport-, Retry-, Tokenlimit-, JSON- und Schemafehler erhalten höchstens einen
neutralen Verzögerungshinweis; ein gemeinsamer `ValueError` dient nicht als
fachliche Entscheidungsgrenze. Das strukturierte, inhaltsfreie Ereignis nennt
Fehlerklasse, versionsgebundene Proposal-Referenz und Revisionsstatus.
Ein autorisiertes, syntaktisch verarbeitetes Telegram-Update wird durch Fortschreiben
des Offsets konsumiert. Ist seine semantisch gültige normalisierte Antwort bereits
persistiert, bleibt sie auch bei einem späteren technischen Revisionsfehler beantwortet
und wird nach Neustart aus dem Zustand wiederholt; die Chatnachricht wird nie nochmals
als neue Antwort ausgewertet. Ein vorausgehender erfolgreicher Telegram-HTTP-Aufruf
bleibt dabei ein separater Erfolg und wird nicht als Revisionsfehler protokolliert.
Telegram wird ausschließlich für Nachrichten und Callback-Aktionen abgefragt;
bereits wartende, nicht unterstützte Update-Arten werden einzeln verworfen und
blockieren nachfolgende Antworten nicht. Meldet Telegram dagegen, dass
nur die kurzlebige Callback-Bestätigung bereits abgelaufen ist, gilt das fachlich
verarbeitete Update als abgeschlossen: Der Offset wird fortgeschrieben, damit die
alte Callback-Query nicht dauerhaft alle neueren Antworten blockiert. Inhaltsfreie
strukturierte Ereignisse unter `telegram.dialog` dokumentieren Update-Art,
Verarbeitungsphase, Dialogreferenz und Ablehnungs- oder Fehlergrund, ohne
Nachrichtentext oder Callback-Inhalt zu protokollieren.
Die kompakte Mailnachricht nennt ohne interne Mail-ID zuerst den Absender, direkt
darunter den Betreff und danach einen oder höchstens zwei Zusammenfassungssätze. Jeder
Zusammenfassungsaufruf verlangt ausschließlich ein JSON-Objekt mit den beiden
Feldern `sentences` (ein bis zwei deutsche Sätze) und `deadlines` (immer eine
Liste, gegebenenfalls leer); Markdown, Begleittext und weitere Felder sind nicht
zulässig. Die Sätze verdichten zusammengehörige Einzelheiten zu Oberbegriffen und
geben nur Anlass, Kernaussage sowie wesentliche Folgen oder Handlungen wieder.
Namen, Unterpunkte, Anlagen und andere Details erscheinen nur, wenn sie dafür
unverzichtbar sind; bloße Betreff-Paraphrasen und unbelegte Aussagen zum
Handlungsbedarf bleiben ausgeschlossen. Mailinhalte bleiben dabei ausdrücklich
nicht vertrauenswürdige Daten.
Jeder Vorschlag nennt in jedem Nachrichtenteil den Absender und Betreff der
Ursprungsmail, zeigt aber keine internen Mail- oder Vorschlags-IDs. Er zeigt vor
den Schaltflächen alle entscheidungsrelevanten Felder in
einer
festen Reihenfolge; Termine nennen dabei auch die konfigurierte Zeitzone. Lange
Vorschläge tragen in jedem Teil Absender, Betreff und Teilnummer. Solange
offene Fragen bestehen, werden nur Klären und Verwerfen angeboten.
Unklare Relevanz wird vor dem Senden als schema-versionierter Dialog direkt im
Mailzustand gespeichert. Die sichtbare Rückfrage nennt Absender und Betreff, aber
keine interne Mail-ID. Erst nach der Auswahl `Relevant` werden Zusammenfassung und
Aktionserkennung erzeugt und die kompakte Mailnachricht versendet. Die unsichtbaren
Callback-Daten enthalten ausschließlich die stabile interne Mail-ID, Dialogversion
und `relevant` beziehungsweise `irrelevant`; Mailtext wird nicht in Callback-Daten
übernommen. Entscheidung und verarbeiteter Telegram-Offset stehen
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
Ein begrenzter Testlauf ist beispielsweise mit
`docker compose run --rm mailhelp --max-mails 10 --config-directory /config`
möglich.

Konfiguration wird schreibgeschützt eingebunden, Daten und Logs bleiben in getrennten persistenten Host-Verzeichnissen. `.env`, Zustand und Logs gelangen dank `.dockerignore` nicht in den Build-Kontext.
Relative Daten- und Logpfade aus `config.yaml` beziehen sich auf das aktuelle
Arbeitsverzeichnis (im Container `/app`).
Mit `--log-directory PFAD` lässt sich das konfigurierte Logverzeichnis pro Aufruf
überschreiben. Das ist insbesondere bei schreibgeschütztem Arbeitsverzeichnis
nötig; der CI-Container schreibt bei der Konfigurationsprüfung nach
`/tmp/mailhelp/logs`. Im Dauerbetrieb sollte stattdessen ein beschreibbares,
persistent eingebundenes Verzeichnis verwendet werden.

## Zustand sichern

Mailhelp stoppen und anschließend das gesamte konfigurierte Datenverzeichnis einschließlich der Unterverzeichnisse `test/` und `production/` kopieren. Zur Wiederherstellung den Dienst stoppen, das komplette Verzeichnis zurückspielen und erst danach starten. Offene Vorgänge dürfen nicht einzeln bereinigt werden.

## Tests

```sh
python -m pytest
```

Die Standardkonfiguration erzwingt ohne Rundung 100 % Zeilen- **und** Branch-Abdeckung für `src/mailhelp`.

### Reproduzierbare Qualitätsprüfungen

Alle folgenden Standardläufe sind offline, verwenden nur synthetische Daten und
benötigen keine Geheimnisse:

```sh
# Gesamtsuite: 100 % Zeilen- und Branch-Abdeckung des eigenen Anwendungscodes
python -m pytest --cov=mailhelp --cov-branch --cov-fail-under=100

# Versionierter deutscher Qualitätskorpus mit simuliertem OpenRouter-Adapter
python -m pytest tests/test_quality_corpus.py --cov=mailhelp --cov-branch --cov-fail-under=100

# Simulierter Ablauf IMAP → LLM → Telegram-Bestätigung → Todoist/Calendar
python -m pytest tests/test_e2e_simulated.py --cov=mailhelp --cov-branch --cov-fail-under=100

# CLI- und POSIX-/Windows-Pfadvarianten
python -m pytest tests/test_cli_paths.py --cov=mailhelp --cov-branch --cov-fail-under=100

# Windows PowerShell (dieselbe Suite und Coverage-Grenze)
py -3.12 -m pytest --cov=mailhelp --cov-branch --cov-fail-under=100

# Lokaler Container-Smoke-Test (entspricht dem separaten CI-Job)
docker build --tag mailhelp:smoke .
docker run --rm --env-file .env \
  -v "$PWD/config.yaml:/config/config.yaml:ro" \
  -v "$PWD/prompts.yaml:/config/prompts.yaml:ro" \
  -v "$PWD/topics.yaml:/config/topics.yaml:ro" \
  mailhelp:smoke --check --config-directory /config \
  --log-directory /tmp/mailhelp/logs
```

Die fokussierten Pytest-Befehle behalten die produktweit verbindlichen Optionen
`--cov-branch --cov-fail-under=100` bei. Weil ein fokussierter Test naturgemäß nicht
den gesamten Anwendungscode ausführt, kann er allein an der globalen
100-%-Schwelle scheitern; das fachliche Ergebnis steht dann dennoch im Testbericht,
während die Gesamtsuite der maßgebliche Coverage-Gate ist.

Eine Bewertung mit einem realen Modell ist bewusst **nicht Teil dieser Suite** und
wird derzeit auch nicht als optionales Skript angeboten. Dadurch gibt es keinen
versehentlichen Netzwerkzugriff und keine implizite Verwendung eines
`OPENROUTER_API_KEY`. Soll eine solche Integration später ergänzt werden, muss sie
über einen ausdrücklich benannten Opt-in-Schalter aktiviert werden, außerhalb des
Standard-Pytest-Laufs liegen und als Erfolgskriterium dieselben vollständigen
strukturierten Erwartungen aus `tests/fixtures/mail_corpus_v1/corpus.json` erfüllen.

### Sichere Proposal-Revision

Proposal-Überarbeitungen verwenden ein geschlossenes, minimales Delta statt eines
erneut vom Modell erzeugten Gesamt-Proposals. IDs, Version, Status, unveränderte
Felder und offene Fragen bleiben unter Kontrolle der Anwendung. Nach einem
eindeutigen, bereits validierten Datum-und-Uhrzeit-Ergebnis baut Mailhelp den
Zeitpunkt direkt aus dem bekannten Datum und der konfigurierten IANA-Zeitzone; ein
zweiter LLM-Aufruf ist dafür nicht erforderlich. Abweichende Modelldaten werden vor
dem Anwenden abgewiesen. Nach einem
`output_token_limit` wird eine kürzere, feldreduzierte Route verwendet. Scheitern
alle technischen Versuche, speichert Mailhelp die normalisierte Antwort als
`retry_required` und setzt sie nach einem Neustart fort, ohne erneut zu fragen.
