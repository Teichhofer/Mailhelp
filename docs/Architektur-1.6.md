# Architektur ab Mailhelp 1.6

Version 1.6 trennt bestehende Verantwortlichkeiten. Sie führt weder neue
Nutzerfunktionen noch neue Zustandsformate oder Konfigurationswerte ein.

## Composition und Mailbox-Lauf

`application.py` baut Adapter, Store, Analyse und Dialoge zusammen und schließt
die Ressourcen. `Application` startet und beendet Telegram-Empfang und Webserver,
verarbeitet Eingaben im Hauptthread und steuert die Wartezeiten. Die vorhandene
Stop-Handshake-Logik bleibt in `lifecycle.py`.

`MailboxRunService` in `mailbox_run.py` erhält Settings, Store, Logger, IMAP,
Orchestrator, Stop-Event und die Mailverarbeitung als expliziten Callback. Er
hängt nicht von `Application` oder deren privaten Methoden ab. Er übernimmt:

- Wiederaufnahme fälliger Mailzustände mit eigenem Budget für blockierte Zustände;
- Metadata-Discovery über alle Ordner und Sortierung nach Empfangszeit;
- Materialisierung und Speicherung der vollständigen deduplizierten UID-Queue
  vor dem ersten Mailbody-Abruf;
- Queue-Übergänge, UIDVALIDITY und atomare Checkpoints mit vollständigen UID-Bereichen;
- Teilfehler, Timeout, unterbrochene Läufe und den bis zum Neustart geltenden
  Verarbeitungshalt nach einem nicht isolierbaren Fehler;
- Mail-Budget und die aus dem gespeicherten Run berechnete Laufzusammenfassung.

Die Nachricht der Laufzusammenfassung verschickt weiterhin `Application`, weil
sie die offene Telegram-Relevanzfrage berücksichtigen muss. Die bekannten
Application-Einstiegsmethoden delegieren an den Service. Live-Settings werden
auch an dessen Settings-Referenz weitergegeben. Der Service benötigt für einen
Test oder Neustart keinen Telegram-Controller; dessen Verhalten wird über den
Analyse-Callback angebunden.

## Web-Renderer

`web/review_pages.py` rendert Vorschlagskarten, Relevanzfragen, Maildetails und
offene Entscheidungen. `web/status_pages.py` enthält `ServiceInfo`, Statusseite,
Laufzeitinformationen, Dienstkontakte und Zeit-/Dauerformatierung. `web/site.py`
verwendet beide Renderer direkt. Die bisherigen Statusimporte aus
`review_pages.py` bleiben als kompatible Re-Exports verfügbar.

Escaping, Layout und allgemeine Hinweise bleiben zentral in `web/pages.py`.
Die HTTPS-Linkregel für Vorschlagskarten bleibt in `review_pages.py`; Mailtext
wird weiterhin nur als Text angezeigt. Die Renderer lesen Views und erzeugen
HTML; sie kontaktieren keine Dienste und schreiben keine Zustände.

## Externe Integrationen

| Modul unter `external/` | Verantwortung |
| --- | --- |
| `contracts.py` | Validierte Providerantworten, Fehlerklassen, Token-/Writer-Ports und vorbereitete Schreiboperation |
| `oauth.py` | Google-Tokenbezug, Erneuerung, Invalidierung und ausschließlich flüchtige Tokenhaltung |
| `calendar.py` | Kalenderabfrage, Pagination, Duplikatvergleich, Zeitänderungen und Event-Payloads/PATCH |
| `todoist.py` | Aufgabenabfrage, Pagination, Idempotenzsuche und Task-Payloads |
| `ical.py` | UTF-8/RFC-5545-Serialisierung und Kalenderdateizustellung über Telegram |
| `transport.py` | Gemeinsamer HTTP-Transport, Auth-Header, Lesecache und Dienstfehlerklassifikation |
| `http_writer.py` | Kompatibler `HttpWriter`-Konstruktor, Dispatch und gemeinsame HTTP-Neuanlage |
| `confirmed.py` | Versionsbezogener bestätigter Schreibpfad und Abgleich unklarer Ergebnisse |

`HttpWriter` verwendet die Kalender-/Todoist-Operationsklassen und den Transport
mit genau einem HTTP-Client, einer Retry-Policy und einem Lesecache je Instanz.
Die Operationsklassen sind interne Bausteine, keine separat zu instanziierenden
öffentlichen Adapter. `integrations.py` exportiert die bisherigen Klassen,
Funktionen und Fehler unverändert. `isinstance(writer, HttpWriter)` bleibt im
bestätigten Schreibpfad wirksam.

Die Reihenfolge bleibt: vollständige bestätigte Vorschlagsversion prüfen, Ziel
prüfen, ggf. Trockenlauf, Idempotenzabgleich, lesende Vorbereitung und
Payloadvalidierung, durable Schreibgrenze, externe Operation, Ergebnis speichern.
Ein unklarer früherer Schreibversuch wird weiterhin ausschließlich abgeglichen.
OAuth- und Providerfehler enthalten keine Zugangsdaten.

## Telegram-Revisionen

| Modul | Verantwortung |
| --- | --- |
| `revision_contracts.py` | Ports für Interpretation, Rückfrage, Revision und sichere Logs |
| `answer_interpretation.py` | Bereits durable autorisierte Antwort interpretieren, deterministische Zeit-/Klassifikationsfälle, Rückfragen und Interpretations-Retry |
| `revision_successor.py` | Nachfolge-Vorschlag bauen und Identität, Versionsfolge sowie fachliche Änderungsregeln validieren; ohne Store oder Transport |
| `revision_recovery.py` | Fällige durable Interpretationen/Revisionen und ältere Dialog-Recovery fortsetzen |
| `revisions.py` | Autorisierte Antwort übernehmen, Revision koordinieren, persistieren, zustellen und nächste offene Frage anzeigen |

Der koordinierende `ProposalRevisionProcessor` behält seinen Konstruktor und
`answer()`/`resume()`. Interpretation und Recovery erhalten explizite Ports und
Callbacks statt Zugriff auf einen Controller. Die aktuellen Retry-/Zeitzonenwerte
werden beim Aufruf übergeben. Die rohe autorisierte Antwort erreicht den Store
vor dem ersten falliblen Interpretationsaufruf; das validierte Ergebnis vor dem
Entfernen der Frage und vor der Revision. Nachfolge-Vorschläge werden vor
Schaltflächenzustellung persistiert. Eine Unterbrechung zwischen diesen Schritten
bleibt über die vorhandenen Zustände wiederaufnehmbar. Antworten sind keine
Bestätigung für einen externen Schreibzugriff.

## Geschützte Verträge

Die vollständige synthetische Suite schützt Reihenfolge, UIDVALIDITY, optionale
Ordner, Budgets, Neustart, Timeout, Teilfehler, externe Autorisierung, Pagination,
Retries, unklare Resultate, Idempotenz, Versionsfolge und Recovery.
`tests/test_refactoring_v16.py` prüft zusätzlich die Importfassaden, eine unabhängig
von Application wiederaufgenommene durable Mailbox-Queue und die unveränderten
Renderer. Die Renderer-Referenzwerte wurden aus dem unveränderten 1.5-Code vor
dem Refactoring mit festen synthetischen Views erzeugt
(`tests/renderer_v15_hashes.json`). Sie umfassen Review, Mail, Vorschlag mit
bösartigem Inhalt und Status mit/ohne Laufzeitdaten.

Alle Python-Tests messen weiterhin Zeilen- und Branch-Coverage und scheitern unter
100 %. Die Browser-Suite prüft Desktop und Smartphone einschließlich JavaScript.
Es wurden keine Coverage-Ausschlüsse hinzugefügt.

## Hinweis für Folgearbeiten

`ConfirmedWriteExecutor.resume()` speichert zur Reparatur unterbrochener
Projektionen auch unveränderte aktuelle Vorschläge erneut. Diese bestehenden
Schreibvorgänge erhöhen `JsonStore.revision` und können damit einen Web-Reload
auslösen, obwohl sich keine Entscheidung geändert hat. Version 1.6 behält dieses
Verhalten bei. Eine spätere Optimierung muss die Crash-Reparatur weiterhin
gewährleisten, bevor unveränderte Schreibvorgänge entfallen dürfen.

Die synthetische Browser-Hauptschleife führt Recovery beim Start und danach bei
eingehenden Webbefehlen aus. So prüft der Frontend-Test „unveränderter Stand“
tatsächlich einen unveränderten Stand statt gleichzeitiger Recovery-Schreibvorgänge.
Die Python-Suite prüft den produktiven Polling-/Recovery-Pfad separat vollständig.
