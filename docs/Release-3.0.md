# Mailhelp 3.0 – Einrichtung, Diagnose und Benachrichtigungen

Stand: 14. Oktober 2026. Version 3.0.0. Die Veröffentlichung als Release-Tag `v3.0.0` erfolgt erst,
wenn die CI-Matrix (Windows, Linux, Docker, Browser) für diesen Stand erfolgreich war.
Mehrere Postfächer folgen mit 3.1 ([Planung 3.1](Planung-3.1.md)).

## Einstieg

Die Verbindungsvoraussetzungen bleiben Python 3.12, eine lokale Konfiguration und Geheimnisse
in `.env` oder der Prozessumgebung. `web.enabled: true` und `MAILHELP_WEB_SECRET` mit mindestens
32 Zeichen aktivieren die Oberfläche. Es gibt keine Webbearbeitung von Passwörtern oder Tokens.

Nach dem Start lässt sich am lokalen Host ausdrücklich ein Einmalcode anfordern:

```powershell
mailhelp --pair --config-directory .
```

```sh
docker compose exec mailhelp mailhelp --pair --config-directory /config
```

Der CLI-Aufruf authentifiziert sich mit dem lokalen Webgeheimnis gegenüber dem laufenden Dienst
auf `127.0.0.1`. Die signierte Anfrage ist kurzlebig und nur einmal verwendbar. Der Code erscheint
ausschließlich im aufrufenden Terminal; nach zehn Minuten oder einmaliger Verwendung ist er ungültig.
In `/anmelden` eingeben. Rate-Limits und Sitzungssperren gelten unverändert.
Bei aktiviertem Telegram bleiben dessen Kopplungsabläufe verfügbar.

## Einrichtung und Diagnose

`/einrichtung` führt durch Betriebsart, Postfach, Analyse/Ziele, Web/Geräte,
Benachrichtigungen und Prüfung/Übernahme. Vorhandene Werte bleiben erhalten.
Jeder gespeicherte Schritt aktualisiert `setup-state.json`, nicht die aktive `config.yaml`.
Ein Neustart erhält den Entwurf, jedoch keine Übernahmebestätigung.
Die Änderungsliste kennzeichnet sofort geltende Profile und Änderungen mit notwendigem Neustart.
„Einstellungen übernehmen“ erfordert eine neue Bestätigung, Sitzung, CSRF, Entwurfsversion,
Dateihash und Idempotenzschlüssel. Die Ausführung prüft Sitzung und Datei erneut.
Bei parallelen Änderungen neu einlesen, Differenz prüfen und erneut bestätigen.

Auch ein beim Dienststart nicht erreichbares oder abgelehntes Postfach lässt bei aktiviertem Web
die Einrichtung verfügbar. Die Diagnose zeigt den sicheren Fehlercode; nach Korrektur und Übernahme
Mailhelp neu starten. Die Basiskonfiguration und lokal hinterlegte Geheimnisse werden vor dem Start geladen.

`/diagnose` startet jede Prüfung einzeln. IMAP verwendet eine eigene Verbindung, `LIST` und
lesende Ordnerauswahl. Google Kalender und Todoist prüfen ihre Ziele lesend.
Der LLM-Basistest validiert lokal die Modellkonfiguration; der ausdrücklich gekennzeichnete
synthetische Test benötigt den optionalen Prompt `diagnostic_test` und kann Kosten verursachen.
Es werden keine Maildaten dafür übertragen. Telegram-Zugang und Testnachricht sind getrennt.
Push-Tests erreichen ausschließlich das aktuelle angemeldete Gerät.
Dateisystemtests verwenden eigene temporäre synthetische Dateien.

Die Antwortzeit ist pro Diagnose auf zehn Sekunden begrenzt. Ein noch laufender, abgelaufener
Probe-Thread sperrt weitere Prüfungen derselben Komponente bis zum Dienstneustart;
andere Komponenten und Mailverarbeitung laufen weiter. Adapter schließen ihre eigenen Ressourcen.
Späte Antworten überschreiben kein Timeout-Ergebnis. Ein unterbrochener Prüflauf benötigt einen neuen Start.
Ein lesbarer Entwurfsordner beweist keine APPEND-Berechtigung. Kein Diagnoseablauf erzeugt
Termine, Aufgaben oder IMAP-Entwürfe.

Der Export `/diagnose/bericht` enthält Programmversion, Betriebssystemklasse, Komponentenstatus,
Prüfzeiten, Dauer und sichere Fehlercodes. Rohfehler, Zugangsdaten, Mailinhalte, private Pfade,
Kopplungscodes und Push-Endpunkte fehlen. Er wird ausschließlich lokal heruntergeladen.

Die Formulare sind ohne JavaScript bedienbar. Push-Browserberechtigungen und Abonnements
benötigen Browserunterstützung, JavaScript und HTTPS beziehungsweise localhost.
Auf iOS muss die Anwendung zunächst zum Home-Bildschirm hinzugefügt werden.

## Benachrichtigungen

`/einstellungen/benachrichtigungen` bearbeitet dieselben `notifications`-YAML-Felder über den
Einrichtungsentwurf. Entscheidungen, Aktionsergebnisse, Tagesüberblick und Betriebsprobleme
lassen sich unabhängig auf Telegram, Web-Push, beide oder keinen externen Kanal verteilen.
Die lokale Anzeige bleibt verfügbar. Technische Aktivierung und Geräteabonnement sind getrennt.
Telegram `neutral` übermittelt nur einen Hinweis; `summary` übermittelt auch Betreffzeilen
und den Tagesüberblick. Web-Push bleibt stets neutral.

Ruhezeiten verwenden die lokale Uhrzeit aus `timezone`, auch über Mitternacht und bei Zeitumstellung.
Aktive gleiche Start- und Endzeiten werden abgewiesen. Eine Betriebsproblem-Ausnahme ist standardmäßig aus.
Das Bündelungsfenster beginnt beim ersten Ereignis. Nach der Ruhezeit entsteht eine aktuelle
Zusammenfassung; erledigte oder ersetzte Entscheidungen entfallen.
Direkte Antworten im auslösenden Kanal, Anmeldung und bewusst angeforderte Tests bleiben sofort möglich.
Der Scheduler prüft spätestens alle fünf Sekunden; Netzwerkverzögerungen können die Zustellung verlängern.

`notification-queue.json` speichert schema-versionierte Referenzen und kanalbezogene Zustände:
`pending`, `deferred`, `sending`, `sent`, `failed`, `uncertain`, `cancelled`.
Vor dem Versand werden Profil, Relevanz und Push-Gerätesitzung/Abonnementrevision erneut geprüft.
Identische Einreihungen sind idempotent. Eindeutig abgelehnte Nachrichten bleiben fehlgeschlagen;
429 und nachweislich wiederholbare Fehler erhalten begrenzten Backoff.
Netzwerkabbrüche, uneindeutige Anbieterantworten und unterbrochene Sendeschritte bleiben unklar.
Telegram und Web-Push bieten keinen belastbaren Empfangsabgleich; diese Vorgänge werden nicht blind wiederholt.

`/benachrichtigungen` zeigt Zustellstatus, Versuche und sichere Fehlercodes.
Push `sent` bedeutet an den Dienst übergeben, nicht am Endgerät gelesen.
Ein Kanalfehler blockiert andere Kanäle nicht. Queue und Diagnose enthalten keine Mailtexte.
Ein voller Puffer verwirft keine Entscheidung: die Quelle bleibt vorhanden und wird später erneut aufgenommen.
Erledigte Telegram-Kommandos werden nur als abgeschlossene Ergebnisse erfasst und niemals zur erneuten
Ausführung eingereiht. Zusätzliche Kanalhinweise wiederholen keine direkte Telegram-Antwort.
Endgültige Fehler belegen keine ausstehenden Queue-Plätze und unterliegen der historischen Aufbewahrung.
Historie wird nach `history_days` bereinigt; noch relevante Referenzen bleiben zur Deduplizierung erhalten.

## Konfigurationsvertrag

Kanalnamen: `telegram`, `web_push`; Kategorien: `decisions`, `action_results`, `daily_briefing`, `system_errors`.
Ein Kategoriekanal darf nur einmal vorkommen. Telegram-Inhalte: `neutral` oder `summary`.
Uhrzeiten verwenden `HH:MM` (00:00–23:59). Bündelungsfenster: 1–86400 Sekunden.
Zustellversuche: 1–10; Backoff: 1–86400 Sekunden, Maximum mindestens Anfangswert.
Historie: 1–3650 Tage; maximal ausstehende Einträge: 1–100000.
Unbekannte Schlüssel und ungültige Typen werden abgewiesen. Beispiel: `config.example.yaml`.

## Upgrade und Rückkehr

Vor dem Upgrade Dienst stoppen, Konfiguration und alle Zustandsverzeichnisse sichern.
Ohne `notifications`-Abschnitt bleiben die bisherigen Kanalwahlen und Telegram-Inhaltsfreigaben erhalten;
Ruhezeit und Bündelung werden nicht automatisch aktiviert. Die Oberfläche zeigt diese Übernahme.
Der erste Start sichert Referenzen und alte Zustellmarker in `notifications-backup.json` und markiert die
Migration in `notifications-migration.json`. Alte Proposal-/Push-/Briefingmarker verhindern Wiederholungen.
Dieser Migrationssnapshot enthält keine alten Nachrichtentexte und ersetzt keine vollständige Sicherung.
Unklare alte Telegram-Zustellungen bleiben unklar. Die alte Telegram-Outbox übergibt neue
Hintergrundreferenzen an die gemeinsame Queue; direkte Dialogantworten bleiben fachlich verfügbar.
Die alten Push-/Briefing-Scheduler versenden im neuen Lauf nicht parallel.

Für ein vollständiges Rollback Dienst stoppen und die vorherige Paketversion samt vorab gesicherter
Konfiguration und Zustandsablage wiederherstellen. Nie beide Versionen gleichzeitig starten.
Ein bloßes Löschen der neuen Queue kann Wiederholungen verursachen und ist kein Rollback.
Schon übergebene Nachrichten lassen sich nicht zurückrufen. Nach dem Upgrade angelegte externe
Termine oder Aufgaben sind beim Rollback weiterhin vorhanden; vor Wiederanlage abgleichen.

Docker: Die Standard-Compose-Datei bindet `config.yaml` lesend ein. Für Webübernahme eine
beschreibbare Verzeichnisbindung verwenden, beispielsweise den dokumentierten Ablauf in
`compose.learn.yaml`; einzelne Dateibindungen erlauben keinen atomaren Dateiaustausch.
