# Mailhelp 3.7 – Ersteinrichtung und OAuth im Browser

Arbeitsstand 3.7.19, 4. November 2026. Alle 20 Planschritte sind umgesetzt;
die Zuordnung 3.7.0–3.7.19 bezeichnet keine hier veröffentlichten Zwischenreleases.

## Erster Start

Unter Windows Mailhelp mit dem gewünschten Konfigurationsverzeichnis starten.
Fehlt `config.yaml`, startet ausschließlich der Einrichtungsserver. Es werden
noch keine Postfächer abgerufen oder Kalender-/Aufgabenadapter aufgebaut.
Im Terminal erscheint ein zehn Minuten gültiger Einmalcode. Diesen unter
`http://localhost:8765/anmelden` eingeben; erst danach sind die Einrichtungsrouten
zugänglich. Browserzugriffe erzeugen keine Terminal-Codes.

Für Docker steht `docker compose -f compose.setup.yaml up --build` bereit.
Das benannte Volume `mailhelp-config` enthält Konfiguration, `.env`, Zustände und
Logs dauerhaft. Es benötigt keine vorbereiteten Dateien. Die vorhandene
`compose.yaml` bleibt für bereits konfigurierte Installationen erhalten.
Den Code der sichtbaren Dienstausgabe entnehmen. Nach Ablauf kann am Host
`mailhelp --pair` beziehungsweise im Container
`docker compose -f compose.setup.yaml exec mailhelp mailhelp --pair --config-directory /config`
einen neuen Code anfordern. Ein Neustart des Einrichtungsdienstes gibt ebenfalls
einen neuen Code aus; die persistierten Fehlversuchs- und Anfragelimits bleiben wirksam.

Der Einrichtungsserver lauscht standardmäßig auf `0.0.0.0:8765`; lokale und private
Netzwerkadressen benötigen weiterhin den Code. `MAILHELP_SETUP_HOST`,
`MAILHELP_SETUP_PORT` und `MAILHELP_SETUP_ALLOWED_HOSTS` steuern den Erststart.
Die zusätzliche Hostliste ist kommasepariert und enthält genaue Hostnamen mit
gegebenenfalls Port. Nach Abschluss gelten die gespeicherten Web-Einstellungen.
Die neue Docker-Vorlage veröffentlicht den Port ausschließlich auf dem Host-Loopback.

## Die fünf Schritte

1. Web-Passwort (mindestens zwölf Zeichen) und IANA-Zeitzone festlegen.
   JavaScript schlägt die Browserzeitzone vor; die manuelle Auswahl funktioniert
   auch ohne JavaScript. Der Sitzungsschlüssel wird bereits vor der Codeausgabe
   automatisch erzeugt, damit auch der Erstzugang geschützt ist.
2. IMAP-Server, Port, Verschlüsselung und Zugangsdaten eingeben. Die lesende
   Verbindungsprüfung liefert Ordner und deren Special-Use-Rollen; Posteingang
   und Entwurfsordner lassen sich daraus auswählen.
3. OpenRouter oder Ollama wählen. OpenRouter prüft den Schlüssel und den
   Modellkatalog. Kontoguthaben wird angezeigt, soweit der Schlüssel dessen
   Abfrage erlaubt; sonst wird das verfügbare Schlüssellimit angezeigt. Die
   Katalogprüfung garantiert keine spätere Erreichbarkeit jedes Modellanbieters.
   Ollama liefert die installierten Modelle. Die Adresse steht in `config.yaml`,
   das Modell weiter in `prompts.yaml`; die Auswahl bleibt nach Neustart aktiv.
4. Kalender- und Aufgabendienst konfigurieren und lesend prüfen. Google,
   Microsoft, Todoist und CalDAV sind verfügbar. Für Todoist genügt der
   persönliche API-Token. Für Google steht die vollständige
   [Playground-Anleitung](Google-OAuth-Playground.md) direkt an den Feldern bereit.
5. Das Speichern und den Start ausdrücklich bestätigen. Alle Verbindungen werden
   erneut geprüft. Danach aktiviert ein kontrollierter Neustart den Normalbetrieb.
   Der Web-Lernmodus folgt in 4.0.

## Anmelden und Konten verbinden

Terminal-Codes über `--pair`, Telegram-Codes und Web-Passwort erzeugen gleichberechtigte
widerrufbare Sitzungen. Passwort-Hashes verwenden scrypt und einen eigenen Zufallssalt;
der Klartext wird nicht gespeichert. Unter `/einstellungen/web-passwort` kann eine
angemeldete Sitzung das Passwort versionsgebunden ändern. Zur Wiederherstellung den
Dienst beenden und am Host `mailhelp --reset-web-password --config-directory …`
ausführen: Das löscht den Passwort-Hash und widerruft sämtliche Websitzungen.
Anschließend den Dienst starten und einen neuen Terminal-Code anfordern.

Für die direkte Google-Anmeldung wird ein Webanwendungs-Client verwendet.
`web.google_redirect_uri` muss exakt bei Google registriert sein. Erlaubt sind
HTTPS oder HTTP auf Loopback, jeweils mit `/auth/google/callback`; für Docker auf
einem entfernten Rechner eine öffentlich für den Browser erreichbare HTTPS-Adresse
und einen zugelassenen Host konfigurieren. Der Playground-Weg benötigt keine
Rückleitung auf Mailhelp und bleibt eine unabhängige Alternative.

Die Google-Zustimmung nutzt State und PKCE und ist an die ursprüngliche Sitzung
gebunden. Wegen der absichtlich strikten SameSite-Cookies kann nach der Rückleitung
ein zusätzlicher Klick auf „Google-Anmeldung abschließen“ nötig sein. Ohne gültige
ursprüngliche Sitzung erfolgt kein Tokenaustausch. Bereits verbrauchte oder durch
Absturz unterbrochene Codeaustausche werden nicht blind wiederholt.

Microsoft fordert den Gerätecode im Hintergrund an. Code, Kopierknopf und
Anmeldelink erscheinen im Browser; ohne JavaScript zeigt Neuladen den Status.
Der Server fragt auch bei geschlossenem Browser weiter und beachtet Ablaufzeit,
`authorization_pending` und `slow_down`. Wartende Vorgänge werden nach einem Neustart
fortgesetzt, sofern Sitzung und Clientdaten noch gültig sind. Refresh-Tokens werden
im passenden Profil und bei Microsoft zusätzlich in der bestehenden Token-Datei gespeichert.

Die Kalenderauswahl lädt ausschließlich Kalender mit Schreibrecht, unterstützt
Pagination und speichert die Auswahl zunächst als versionsgebundenen Entwurf.
Eine neue Verbindung, ein gespeichertes Ziel oder OAuth-Zustimmung ist keine Freigabe
einer externen Kalender- oder Aufgabenanlage.

## Persistenz und Wiederherstellung

- `initial-setup.json`: nicht geheime, versionierte Einstellungen und HMAC-Belege.
- `web-password.json`: gesalzener Passwort-Hash und Versionsnummer.
- `web-oauth.json`: sitzungsgebundene Anmeldevorgänge; wegen PKCE- und Device-Secrets
  wird diese JSON-Datei von Beginn an mit Eigentümerrechten atomar geschrieben.
- `.env`: Clientdaten, Refresh-Tokens und Sitzungsschlüssel; keine Klartextwerte in
  HTML-Antworten, Diagnosemeldungen oder Anwendungslogs. Der vorgesehene Einmalcode
  wird ausdrücklich nur zur Authentifizierung im Terminal beziehungsweise Telegram ausgegeben.

Nach langsamen Prüfungen werden Sitzung und Entwurfsstand erneut kontrolliert.
Idempotenzschlüssel verhindern doppelte Formularübernahmen. Zugangsdaten werden
vorbereitet, zusätzliche Dateien angelegt und `config.yaml` als letzter atomarer
Aktivierungsmarker geschrieben. Ein Abbruch davor lässt den Assistenten fortsetzbar;
ein Abbruch danach startet mit der bereits vollständigen Konfiguration.
Prozessvariablen überschreiben weiterhin `.env`; beim Zugangsdatenwechsel müssen
gegebenenfalls auch diese angepasst werden. Für normale Abrufadapter wirken neue
Zugangsdaten nach einem kontrollierten Neustart.

Vor dem Upgrade Datenverzeichnis, Konfiguration und Zugangsdaten sichern. Bei einem
Downgrade auf ältere strikte Konfigurationsmodelle auch die passende Sicherung der
Konfiguration wiederherstellen: Die neuen Felder `llm` und `web.google_redirect_uri`
sind älteren Versionen nicht bekannt. Default-OpenRouter behält seine Analyse-Hashes;
ein bewusster Wechsel auf den lokalen Anbieter ändert sie.

## Abnahme

Die automatisierten Prüfungen verwenden ausschließlich simulierte Dienste und
synthetische Daten; sie legen keine echten Termine oder Aufgaben an.

| Prüfung | Ergebnis |
| :--- | :--- |
| Windows 11, Python 3.12.14: vollständige Python-Suite | 2.966 bestanden; 100 % Zeilen- und 100 % Branch-Abdeckung |
| Linux, Python 3.12.3: vollständige Python-Suite | 2.966 bestanden; 100 % Zeilen- und 100 % Branch-Abdeckung |
| Browser: Desktop, Mobilgeräte und Bedienung ohne JavaScript | 215 bestanden; 100 % JavaScript-Blockabdeckung für `app.js`, `sw.js` und `setup.js` |
| Tatsächlich installiertes Wheel: Ressourcen, CLI, Einrichtung, OAuth und erster Abruf | 78 bestanden |
| Tatsächlich installiertes Wheel: Browser-Ersteinrichtung | 10 bestanden |
| Statische Prüfungen | `ruff` ohne Befund; `mypy` ohne Befund in 221 Quelldateien |

Die Abdeckung umfasst auf beiden Plattformen 23.123 ausgeführte Anweisungen und
6.656 ausgeführte Branches, jeweils ohne fehlende Abdeckung. Die Linux-Prüfung lief
in einem eigenen nativen Ubuntu-Verzeichnis unter dem unprivilegierten Benutzer `nobody`.
Zusätzlich bestehen dort vorab 128 gezielte CLI-, Laufzeit- und Modellvertragstests.

Die vollständige Suite wird mit `python -m pytest --cov=mailhelp --cov-branch
--cov-fail-under=100` ausgeführt, die Browser-Suite mit
`python -m pytest ui_tests --no-cov`. Wheel und Quellarchiv werden mit
`python -m hatchling build` erzeugt und auf enthaltene Ressourcen und ausgeschlossene
private Laufzeitdateien geprüft. Die lokalen XML- und Coverage-Berichte liegen unter
`.test-tmp-37/` (`windows-results.xml`, `linux-results.xml`, `ui-results.xml`,
`wheel-results.xml`, `ui-wheel-results.xml` und die jeweiligen Coverage-JSON-Dateien).

Docker ist auf dem Entwicklungsrechner nicht installiert. Deshalb wurde hier kein
Container-Image gebaut oder gestartet. Die neue Compose-Vorlage wurde strukturell
geprüft; Linux-Laufzeit und Paketbau wurden separat unter Ubuntu geprüft. Echte
OAuth-Zustimmungen und externe Verbindungen gehören nicht zu dieser automatisierten Abnahme.
