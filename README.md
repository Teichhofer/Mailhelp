# Mailhelp

Python-Assistent zur LLM-basierten Auswertung von IMAP-Mails über OpenRouter. Telegram zeigt Zusammenfassungen und versionsgebundene Einzelvorschläge; erst eine ausdrückliche Bestätigung erlaubt einen Todoist-Schreibzugriff oder den Versand einer Kalenderdatei.

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

Mit `mailhelp --check-access` lässt sich anschließend ein reiner Zugriffstest
starten. Er prüft nacheinander die Anmeldung bei IMAP und den Nur-Lese-Zugriff auf
alle konfigurierten Ordner, den OpenRouter-Key über dessen authentifizierten Status, den
Telegram-Bot über `getMe` sowie den Zugriff auf das konfigurierte Todoist-Projekt.
Die Kalenderdatei benötigt keinen Google-Zugang. Nach erfolgreichem `getMe` sendet die Telegram-Prüfung
eine Nachricht mit `Test`, Datum, Uhrzeit und konfigurierter Zeitzone an den
konfigurierten Chat. Der Test ruft keine Mails ab, liest keine Telegram-Updates,
führt keinen LLM-Auftrag aus und erzeugt weder Aufgaben noch Termine. Für jeden
Dienst erscheint `OK` oder `FEHLER`; sobald mindestens eine
Prüfung fehlschlägt, endet der Prozess mit Status 1. Im Container kann derselbe
Test mit `docker compose run --rm mailhelp --check-access` ausgeführt werden.
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

### Kalendertermine auf iOS übernehmen

Nach der versionsbezogenen Telegram-Bestätigung erzeugt Mailhelp eine UTF-8-
`*.ics`-Datei und sendet sie als Telegram-Dokument. Ein Antippen auf iOS öffnet
die Kalenderübernahme; Mailhelp greift weder lesend noch schreibend auf Google
Calendar zu. Ort, Beschreibung, Videolink, ganztägige Intervalle und Zeitpunkte
werden in der Datei abgebildet. Ein möglicherweise erfolgreicher, aber technisch
unklarer Dokumentversand wird nicht automatisch wiederholt, um Duplikate zu
vermeiden. Google-OAuth-Geheimnisse und eine Zielkalender-ID sind nicht nötig.

`config.yaml` besitzt geschlossene Modelle für IMAP, Telegram, Ziele, Limits, Wiederholungen, Timeouts und Logging. IMAP, Telegram, OpenRouter und Todoist haben jeweils eigene Werte für Timeout, Retry-Anzahl sowie initialen und maximalen Backoff. Validiert werden insbesondere Port, Polling, Adaptertimeouts, Mailgröße, LLM-Rate, Wiederholungszahlen, IANA-Zeitzone, eindeutige nichtleere Ordner, sichere Pfade und die Log-Level `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. Unbekannte Schlüssel und falsche Typen werden abgelehnt.
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
Die Metadaten-Auswertung akzeptiert dabei die von `imaplib` gelieferten direkten
Bytes-Elemente ebenso wie das erste Bytes-Element eines Antwort-Tupels, überspringt
strukturelle Abschlussfragmente und erkennt `INTERNALDATE` unabhängig von der
Groß-/Kleinschreibung.
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
Bei einem einmaligen Lauf mit `--max-mails N` wird auch der IMAP-Abruf auf das nach
Wiederaufnahmen noch verbleibende Budget begrenzt. So werden keine vollständigen
Nachrichten geladen, die der aktuelle Lauf anschließend gar nicht verarbeitet.

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
* `mime_limit_exceeded` mit `max_mail_bytes` bedeutet, dass die vollständige
  rohe MIME-Nachricht größer als `limits.max_mail_bytes` ist. Dabei zählen auch
  Header, HTML, Anhänge und deren Transferkodierung. Den Wert nur dann in
  `config.yaml` erhöhen, wenn diese Nachrichten bewusst verarbeitet werden sollen;
  die zusätzlichen MIME-, Text-, HTML- und LLM-Nutzlastgrenzen bleiben weiterhin
  wirksam. Alternativ müssen Nachricht oder Anhänge vor der Verarbeitung verkleinert
  werden.
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
alle bereits abgeschlossenen externen Schreibvorgänge anhand Todoist abgleichen und bereits versendete Kalenderdateien manuell prüfen. Danach alte Vorschlagsdateien und einen alten
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
* `Proposal.due` ist eine streng validierte Union: `YYYY-MM-DD` bezeichnet ein reines Fälligkeitsdatum und wird unverändert als Todoist-`due_date` übertragen. Ein Fälligkeitszeitpunkt enthält Datum und Uhrzeit samt explizitem UTC-Offset (zum Beispiel `2026-10-01T17:00:00+02:00`) und wird als `due_datetime` übertragen. Naive Zeitpunkte werden abgelehnt und reine Daten niemals stillschweigend in Mitternacht umgewandelt.
* Der JSON-Zustand wird atomar ersetzt und durch eine betriebssystemseitige, an den laufenden Prozess gebundene Einzelinstanz-Sperre geschützt. Die `.lock`-Datei bleibt nach dem Schließen als Diagnoseinformation erhalten; ausschließlich die vom Betriebssystem gehaltene Sperre entscheidet, ob eine Instanz aktiv ist. Syntaktisch beschädigte Dateien werden als `.corrupt`, schemawidrige Dateien als `.invalid` isoliert; Meldungen nennen Datei und Schlüsselpfad, nicht den Inhalt. Mailzustände (Schema 6), Abrufpositionen, Telegram-Dialoge und Duplikatindex (Schema 1) sowie Vorschläge (Schema 2) werden vor jeder Verwendung validiert.
* OpenRouter-, Telegram- und Todoist-Antworten werden nach HTTP-Erfolg strikt auf JSON-Struktur, Pflichtfelder und IDs geprüft. LLM-Antworten werden strikt gegen feste Pydantic-Schemata validiert. Reservierte OpenRouter-Felder können nicht über YAML überschrieben werden.
* Bei Terminen bleiben der physische Ort und ein optionaler, ausschließlich per HTTP/HTTPS erlaubter Videolink getrennte Vorschlagsfelder und werden vor der Bestätigung beide in Telegram angezeigt. Die iCalendar-Datei enthält Ort, Beschreibung und Videolink; zeitgebundene Werte werden eindeutig in UTC serialisiert, ganztägige Enddaten bleiben exklusiv.
* Externe Aktionen verlangen eine Persistenzfunktion: `writing` wird vor dem API-Aufruf dauerhaft gespeichert. Unklare Resultate werden als `uncertain` angehalten und nur abgeglichen. Ausschließlich ein externer Treffer überführt sie in `created`; ein neuer Schreibversuch setzt eine ausdrücklich modellierte manuelle Betreiberentscheidung voraus.
* Jede Mail besitzt die schema-validierten Schritte `preparation`, `relevance`,
  `summary`, `action_detection`, `notification` und `completion`. Nach jedem Schritt
  wird atomar gespeichert; nach einem Neustart laufen ausschließlich ausstehende
  Schritte. Relevante Mails erreichen `completion` erst nach Analyse und Telegram-
  Benachrichtigung, während nicht benötigte Schritte ausdrücklich `skipped` sind.
* Jeder Vorschlag trägt die streng validierten Felder `responsibility` (`user`, `other`, `unclear`), `certainty` (`certain`, `uncertain`, `contradictory`) und `classification` (`new`, `non_binding`, `already_completed`, `change`, `cancellation`, `recurring`, `unsupported`). Ausschließlich `new` + `user` + `certain` ist bestätigbar und extern anlegbar. Alle anderen Einordnungen erscheinen als manuell zu prüfende Information; offene Zuständigkeit, Unsicherheit und Widerspruch erzwingen `needs_clarification`.
* Vorschläge werden zusätzlich zur Maildatei versionsweise und als aktueller Stand
  gespeichert. Bestätigte Schreibvorgänge werden nach Neustarts wiederaufgenommen;
  externe ID und Link sowie `created`, `failed` oder `uncertain` werden im
  konfigurierten Telegram-Chat sichtbar gemeldet. Im Testmodus wird stattdessen vor
  der Meldung der Abschlusszustand `simulated` ohne externe ID oder Link atomar
  gespeichert. `simulation_notified` hält anschließend dauerhaft fest, dass die
  eindeutig als Simulation bezeichnete Meldung versandt wurde. Mehrfach-Polls und
  Neustarts führen deshalb weder die Simulation erneut aus noch melden sie erneut;
  ein zwischen Speichern und Meldung erfolgter Abbruch kann die noch ungemeldete
  Simulation dagegen sicher zu Ende melden. Entsprechend wird auch die Meldung eines
  unverändert unklaren Ergebnisses dauerhaft markiert.
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
* Im `test_mode` findet kein externer Schreibzugriff statt; Ergebnisse tragen `simulation: true` und der Vorschlag bleibt `confirmed`, statt einen echten Eintrag vorzutäuschen.
* JSONL-Anwendungs- und LLM-Logs sind getrennt. Die Beispielkonfiguration protokolliert vollständige LLM-Anfragen und -Antworten; beide Inhaltsarten lassen sich unabhängig abschalten und Geheimnisfelder werden stets maskiert.
* `.env` unterstützt einfache `NAME=WERT`-Zeilen und einfache/doppelte Anführungszeichen, aber bewusst keine Shell-Erweiterung. Prozessvariablen überschreiben gleichnamige Werte aus der Datei.

### Mailzustände aus Schema 3 kontrolliert erneut verarbeiten

Mailzustands-Schema 6 ist gegenüber älteren Schemata bewusst inkompatibel. **Es findet
keine automatische Migration statt.** Beim Laden wird eine Datei mit Schema 3
als schemawidrig erkannt und neben den Zustandsdateien mit der Endung `.invalid`
isoliert. Mailhelp rekonstruiert insbesondere die in Schema 6 erforderlichen
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
   `.invalid`-Datei als Nachweis gesichert lassen und nicht in Schema 6
   umetikettieren oder manuell mit erfundenen Pflichtfeldern ergänzen.
4. Mailhelp mit der aktuellen Version starten, die Mail neu als Schema 6 einlesen
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
Einzelinstanz-Sperre werden auch bei Fehlern geschlossen. Unmittelbar vor dem
Beenden sendet der Bot in den konfigurierten Telegram-Chat eine Laufzusammenfassung
mit der Gesamtzahl der bearbeiteten sowie der erfolgreich abgeschlossenen,
wartenden und fehlgeschlagenen Verarbeitungsversuche. Die Zusammenfassung wird
auch bei einem Laufzeitfehler versucht; ein Versandfehler wird protokolliert und
verdeckt einen bereits aufgetretenen Fehler nicht.

Für einen begrenzten Testlauf verarbeitet `mailhelp --max-mails 10` in genau
einem Abrufdurchlauf höchstens zehn Mails (einschließlich fälliger, nach einem
Neustart fortzusetzender Mails), fragt anschließend einmal Telegram ab und
beendet sich. Nicht verbrauchtes Kontingent führt nicht zu einem weiteren Poll;
`--max-mails` muss mindestens `1` sein. Bereits bestätigte externe Schreibaktionen
behalten auch in diesem Modus ihre normalen Sicherheits- und Abgleichsregeln.
Offene Bestandszustände mit einem anderen Konfigurationsfingerprint werden ohne
IMAP-Abruf und ohne Fortsetzung als blockiert gemeldet. Sie verbrauchen das
Verarbeitungskontingent nicht; pro Lauf werden zusätzlich höchstens
`--max-mails` solcher Zustände gescannt und gemeldet, damit ein großer alter
Bestand weder neue Mails verdrängt noch den Lauf unbegrenzt verlängert.
Im dauerhaften Betrieb ohne `--max-mails` endet dieser zusätzliche Scan nach
1.000 blockierten Zuständen je Abrufdurchlauf.

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
die erneute Verarbeitung bereits behandelter Updates. Aktionen enthalten immer
Vorschlags-ID, Version und Aktion; nur der konfigurierte Nutzer im konfigurierten
Chat darf sie auslösen. Jede angezeigte Version wird vor ihren Schaltflächen
gespeichert. `Bestätigen`, `Ändern` und `Verwerfen` werden getrennt behandelt,
während veraltete oder fehlerhafte Schaltflächen keinen Zustand verändern.
Antworten auf Rückfragen erzeugen eine neue, erneut zu bestätigende Version.
Die kompakte Mailnachricht nennt ohne interne Mail-ID zuerst den Absender, direkt
darunter den Betreff und danach zwei bis vier Zusammenfassungssätze. Jeder
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
