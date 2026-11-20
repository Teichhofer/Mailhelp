# Betrieb und Update

Geprüft für Mailhelp 7.0.

Für Serveränderungen gilt zusätzlich die Dokumentationspflicht aus [AGENTS.md](../AGENTS.md):
Nach nachgewiesen erfolgreicher Einrichtung, Änderung oder Reparatur den bestätigten
Istzustand, reproduzierbare Schritte, betroffene Versionen, Prüfungen und das
Rückkehrverfahren vor Abschluss der Arbeit nachführen. Das gilt auch für DNS, nginx,
TLS, Container, systemd, Firewall, Dateirechte, Sicherung und OAuth-Konfiguration.
Fehlversuche und zurückgenommene Änderungen als solche kennzeichnen, nicht als
gültige Einrichtung übernehmen. Geheimnisse bleiben außerhalb von Git.

[Planung 8.0](Planung-8.0.md) sieht dafür ein versioniertes Serverhandbuch unter
docs/Serverhandbuch.md (geplant) und geheimnisfreie Vorlagen unter `ops/server/` vor.
Diese vollständige Neuaufbau-/Wiederherstellungsanleitung ist noch zu erstellen;
bis dahin hier den verifizierten Betriebsstand ergänzen. Lokale Notizen oder nur
auf dem Server gespeicherte Konfigurationen ersetzen keine Git-Sicherung.

## Wiederkehrende Verarbeitungsfehler

Mailhelp versucht dasselbe Fehlerbild je Mail höchstens fünfmal. Die Pausen zwischen
den Versuchen betragen 1 Minute, 5 Minuten, 30 Minuten und 2 Stunden. Danach bleibt die
Mail gespeichert und wird nicht weiter automatisch aufgenommen. Dauerhafte Fehler
werden sofort aufgegeben. Anbieterlimits setzen nur ihre eigene Wartezeit.
Der Status nennt Schritt, Beginn, Versuchszahl und nächsten Versuch. Telegram meldet
das Aufgeben einmal, mit dem Link zur Mail bei aktivierter Weboberfläche.

`logging.verbose: false` reduziert Routinezeilen: unveränderte Ordnerzahlen stündlich,
ein Abschluss je Telegram-Abfrage, Webanfragen nur bei Fehler oder über einer Sekunde.
Der erste Stacktrace bleibt vollständig, Wiederholungen erscheinen alle 15 Minuten
mit Zähler. „Ausführliches Protokoll“ aktiviert Einzelmeldungen nach dem Neustart;
vollständige LLM-Inhalte benötigen weiterhin ihre eigenen Schalter.
Das synthetische Tageslimit beträgt 2 MB bei unveränderten Rotationsgrenzen.

Neue Zustände enthalten optionale Wiederholungsfelder. Beim Rückwechsel auf eine
ältere Version müssen diese im aktuellen Zustand kompatibel entfernt werden.
Eine alte Sicherung ersetzt niemals unbesehen später bestätigte Schreibresultate.

## Starten, prüfen, beenden

| Befehl oder Seite | Wirkung |
| --- | --- |
| `mailhelp --check --config-directory .` | prüft die Konfiguration ohne Netzwerkzugriff |
| `mailhelp --check-access --config-directory .` | prüft alle Zugänge lesend |
| `mailhelp --config-directory .` | startet den Dienst |
| **Einstellungen → Mailhelp neu starten** | kontrollierter Neustart; gespeicherte Änderungen werden wirksam |
| **Einstellungen → Mailhelp beenden** | Dienst anhalten |

Pro Datenverzeichnis läuft nur eine Instanz. **Konfiguration neu laden** wechselt Verbindungen
ohne Prozessneustart.

## Speichern, Aktivieren, Neuladen und Neustart

| Schritt | Was geschieht | Wann wirkt es |
| --- | --- | --- |
| Speichern | Eine geänderte Einstellung wird nach der Vorschau („Prüfen“) in `config.yaml` geschrieben. Die Seite zeigt „gespeichert“, bis sie wirkt. | – |
| Im laufenden Betrieb übernehmen | Einstellungen wie Abrufintervall, Aufbewahrung, Messung, persönliche Angaben, Benachrichtigungen, Termindauern, Vorschlagsabgleich, Entwürfe und Briefings übernimmt Mailhelp selbst. | an der nächsten sicheren Stelle, ohne Neustart |
| Aktivieren | Postfächer, IServ-Konten und Zielprofile werden auf ihren Seiten als Entwurf gespeichert und erst nach erneuter ausdrücklicher Bestätigung aktiviert (**Entwurf übernehmen**, **Verbindung prüfen und Postfach aktivieren**). | zwischen zwei Mailzyklen |
| Konfiguration neu laden | **Konfiguration ausdrücklich neu laden** übernimmt Themen, Prompts, Postfächer, Zugangsdaten und Zielprofile, nachdem unfertige Analysen abgeschlossen sind. | am nächsten sicheren Zeitpunkt, ohne Prozessneustart |
| Neustart | **Mailhelp neu starten** beendet den Dienst kontrolliert und startet ihn neu; alle übrigen gespeicherten Einstellungen sowie Web-Zugang und Datenverzeichnis werden wirksam. | sofort nach dem Neustart |

Speichern oder Aktivieren legt nie Aufgaben oder Termine an; dafür ist immer die ausdrückliche
Bestätigung eines Vorschlags nötig.

## Demo-Instanz

`mailhelp --demo --config-directory <leeres Verzeichnis>` startet eine Demo mit 30 vorbereiteten
Beispielmails, ohne Postfach, Telegram, KI oder echte Ziele. Jede Besucherin und jeder Besucher
erhält über „Demo starten“ eine eigene Kopie für zwei Stunden; Bestätigungen werden nur simuliert.
Port und Hostnamen: `MAILHELP_DEMO_PORT`, `MAILHELP_DEMO_HOST`, `MAILHELP_DEMO_ALLOWED_HOSTS`.
Ein Verzeichnis einer normalen Installation lehnt die Demo ab und umgekehrt.

Starts sind auf 5 je Client und 60 insgesamt pro Stunde begrenzt. Hinter dem eigenen Reverse Proxy
`MAILHELP_DEMO_TRUST_PROXY=1` setzen, damit der Client aus `X-Forwarded-For` stammt (letzter Eintrag;
der Proxy muss seine Gegenstelle anhängen, wie nginx, Caddy und Traefik es tun); ohne Proxy die
Variable nicht setzen, sonst kann ein Besucher die Grenze mit einem erfundenen Kopf umgehen.
Besucher beantworten Rückfragen nur mit den vorbereiteten Beispielantworten und setzen über
„Demo neu starten“ ihre eigene Kopie zurück. Abgelaufene Kopien entfernt die Demo selbst.

### Demo im Docker-Container

```sh
MAILHELP_DEMO_ALLOWED_HOSTS=demo.example.org docker compose -f compose.demo.yaml up -d --build
```

`compose.demo.yaml` startet denselben Image-Einstiegspunkt mit `--demo` und dem eigenen Volume
`demo-daten`; `.env`, `config.yaml`, Daten und Logs der normalen Instanz werden nicht eingebunden.
Beide Instanzen laufen unabhängig, auch gleichzeitig. Das Netz `mailhelp-demo` ist intern, der
Container erreicht also kein Internet. Das ist die zweite Schutzschicht: Die Demo erzeugt ohnehin
keine Clients für Postfach, Telegram, KI oder Ziele.

Der HTTPS-Proxy für die Demo-Subdomain tritt dem Netz `mailhelp-demo` bei und leitet an
`mailhelp-demo:8765` weiter. Ein internes Netz kann keinen Port auf dem Host veröffentlichen. Läuft
der Proxy auf dem Host (etwa Tailscale Serve), braucht der Dienst ein normales Netz mit
`127.0.0.1:<Port>:8765`; die Sperre des ausgehenden Verkehrs übernimmt dann eine Firewallregel für
das Demo-Netz (unter Linux in der Kette `DOCKER-USER`). `MAILHELP_DEMO_TRUST_PROXY` bleibt nur
gesetzt, solange ausschließlich der Proxy den Container erreicht.

Zurücksetzen der ganzen Demo: Container stoppen und das Volume `demo-daten` löschen; beim nächsten
Start ist das Verzeichnis leer und wird neu markiert.

### Sprach-Einstiege hinter dem Proxy (verifiziert am 18.11.2026 mit 7.8.1)

Seit 7.8.1 bedient Mailhelp `/de/`, `/en/` und `/sprache?wert=de|en` selbst. Die Antwort ist eine
Weiterleitung (303) zur Startseite mit dem Cookie `mailhelp_lang` (`Secure`, `SameSite=Lax`,
ein Jahr); ein ungültiger Wert ergibt 400. Der Proxy leitet diese Pfade deshalb unverändert weiter
und setzt weder Sprachcookie noch eigene Weiterleitung.

Umstellung einer bestehenden Proxy-Konfiguration:

1. Am Container ohne Proxy prüfen, dass `/en/` mit 303 und `Set-Cookie: mailhelp_lang=en` antwortet.
2. Die Konfigurationsdatei der Demo-Subdomain sichern.
3. Daraus die Zuordnungen für Sprachcookie und Cache-Header, die beiden `add_header`-Zeilen dafür
   und die Blöcke `location = /de/` und `location = /en/` entfernen.
4. `nginx -t` ausführen und nur bei Erfolg `systemctl reload nginx`; sonst die Sicherung zurückspielen.
5. Über HTTPS prüfen: `/en/` mit deutschem Browser zeigt die englische Startseite, `/de/` mit
   englischem Browser die deutsche; ein Demo-Start zeigt den passenden Beispielbestand.

Rückweg: die gesicherte Datei zurückkopieren, `nginx -t`, `systemctl reload nginx`. Ältere Versionen
vor 7.8.1 brauchen die Proxy-Weiterleitung, weil sie `/de/` und `/en/` nicht kennen.

### Server-Update mit Image (verifiziert am 18.11.2026, 7.7.6 → 7.8.1)

Produktive Instanz und Demo laufen als Compose-Projekte desselben Images. Das Update lief so:

1. Quellarchiv eines Commits erzeugen: `git archive <commit> Dockerfile README.md pyproject.toml
   requirements.lock src`; auf dem Server in ein eigenes Release-Verzeichnis `<version>-<commit>`
   entpacken und daraus das Image `mailhelp-production:<version>-<commit>` bauen.
2. Version im Image ohne Netz prüfen: `docker run --rm --network none --entrypoint python <image>
   -c "import mailhelp; print(mailhelp.__version__)"`.
3. Beide Compose-Dateien sichern, Image und Build-Pfad darin ersetzen und mit
   `docker compose config --quiet` prüfen.
4. Beide Container stoppen (Produktion mit 45 s Wartezeit), erst dann die Laufzeitverzeichnisse
   beider Instanzen als Archiv sichern; das ergibt einen konsistenten Stand.
5. Beide Container ohne Neubau starten, die Healthchecks abwarten und die Version im laufenden
   Container prüfen. Schlägt ein Schritt fehl, werden die gesicherten Compose-Dateien
   zurückgeschrieben und die vorherigen Container wieder gestartet.

Ergebnis am 18.11.2026: beide Healthchecks bestanden, Version 7.8.1 in beiden Containern, bestehende
Demo-Besucher wurden ohne Fehler übernommen. Rückweg: gesicherte Compose-Dateien zurückkopieren, die
gesicherten Laufzeitarchive bei gestoppten Containern zurückspielen und die Container mit dem
vorherigen, weiter vorhandenen Image starten. Zugangsdaten bleiben in der `.env` der Instanz und
werden weder ins Archiv des Quellstands noch ins Image übernommen.

Beobachtung nach dem Neustart: Google lehnte die Erneuerung des Kalenderzugangs ab (HTTP 400), weil
der Refresh-Token einer OAuth-App im Google-Status `Testing` nach sieben Tagen verfällt. Abhilfe ist
eine erneute Google-Anmeldung über die Weboberfläche; dauerhaft hilft die Umstellung der App auf den
Google-Status `In production`.

## Sicherung

Für eine konsistente Sicherung zuerst den Dienst kontrolliert beenden. Erst nach dem
vollständigen Ende die Dateien kopieren; anschließend Mailhelp wieder starten.

Zu sichern sind `config.yaml`, `.env`, `prompts.yaml`, die Themen-Dateien, das Datenverzeichnis
(`data_directory`, Zustände als lesbare JSON-Dateien) und bei Bedarf das Protokollverzeichnis.
`.env` enthält Zugangsdaten und gehört nicht in fremde Hände.

## Update

Nach dem Installieren einer neuen Version den Dienst neu starten. Stylesheet und Skripte werden
beim Start eingelesen. Jede Seite verweist mit einem Inhaltskürzel auf den passenden Stand jeder
Datei, auch wenn ein älterer Service Worker den ersten Aufruf übernimmt.

1. Mailhelp beenden. Unter Windows ist das Pflicht, sonst sperrt Windows die Programmdatei.
2. Konfiguration, `.env`, Prompts, Themen und Datenverzeichnis sichern (siehe Sicherung).
3. Neuen Stand holen und in derselben virtuellen Umgebung installieren:
   `python -m pip install -r requirements.lock` und `python -m pip install --no-deps -e .`.
4. `mailhelp --check --config-directory .` und danach starten.

Neue Einstellungen gelten mit ihrem Standard, ohne die eigene `config.yaml` umzuschreiben. Neue
Prompt-Schritte werden nicht still in eine eigene `prompts.yaml` eingefügt; der jeweilige
Release-Bericht beschreibt die Übernahme.

## Aufbewahrung

Mailinhalte, Verlauf, Diagnosedaten, Prüfnachweise und Lernprotokolle folgen den Fristen unter
`retention`; offene Vorgänge bleiben geschützt. Die Originalmails im Postfach werden nie gelöscht.

## Rückkehr zur Vorversion

Vor der Rückkehr zu einer Version vor 5.2.0 bei beendetem Dienst
`mailhelp --prepare-rollback --config-directory .` ausführen. Einzelheiten stehen im
Release-Bericht der jeweiligen Version.


## Web-Push ab 6.8.1

Die Einstellungen zeigen neun Prüfstufen für das angemeldete Gerät. Unter iOS
Mailhelp vom Home-Bildschirm als installierte Web-App über HTTPS öffnen.
Server-Push unter Einrichtung einschalten, gültigen VAPID-Kontakt eintragen und
neu starten. Anschließend das Gerät aktivieren. Fehlende Postfachkanäle lassen
sich nach einer ausdrücklichen, versionsgeprüften Vorschau ergänzen.

Ein Test-Push überträgt ausschließlich einen festen neutralen Typ. Anbieterannahme
und Geräterückmeldung sind getrennte Zustände; die sichtbare Systemmeldung muss
am Gerät geprüft werden. Nach Schlüsselwechsel oder 401/403 neu aktivieren.
429, 5xx und Netzwerkfehler bleiben wiederholbar. Eigene Änderungen und vor der
Aktivierung offene Vorschläge erzeugen keinen neuen Push. Abonnements, VAPID,
Aktivierungszeiten und Versionsherkunft im dauerhaften Datenverzeichnis sichern.
Einzelheiten: [Release 6.8](archiv/Release-6.8.md).

## Verifizierter Inboxstride-Serverstand vom 19. November 2026

Produktion und öffentliche Demo wurden um etwa 07:00 Uhr MEZ von 7.8.1 auf 7.9.3
aktualisiert. Quelle ist ausschließlich der committed Stand
`70f671b04b84b91c2ddaab4b2a63b4a567aabbb7`; Image
`mailhelp-production:7.9.3-70f671b`, Buildkontext
`/opt/mailhelp/releases/7.9.3-70f671b`. Das Image wurde auf dem Server gebaut und
vor Nutzung isoliert ohne Netzwerk auf die installierte Version geprüft.
Die vollständigen Python-/Browserprüfungen dieses Quellstands sind im
[Releasebericht 8.0, Zwischenstand 7.9.3](Release-8.0.md) nachgewiesen.

| Komponente | Aktiver Stand |
| --- | --- |
| Produktion | `mailhelp-update-mailhelp-1`, Compose-Projekt `mailhelp-update`, Datei `/opt/mailhelp/compose.setup.yaml`, nur Hostport `127.0.0.1:8765` |
| Produktionsdaten | `/opt/mailhelp/runtime` als Bind-Mount nach `/config`; eigene Konfiguration/Secrets bleiben erhalten |
| Demo | `mailhelp-demo-mailhelp-demo-1`, Projekt `mailhelp-demo`, Datei `/opt/mailhelp-demo/compose.yaml` |
| Demo-Daten | Eigenes Volume `mailhelp-demo-runtime`, keine Produktionsdateien oder Zugangsdaten |
| Demo-Netz | Internes `mailhelp-demo-isolated`, `172.30.86.0/28`, Container `172.30.86.2`; keine veröffentlichten Ports |
| Demo-Schutz | Schreibgeschütztes Root-Dateisystem, temporäres `/tmp`, keine Capabilities, `no-new-privileges`; 384 MiB RAM, 0,5 CPU, 128 Prozesse |
| Öffentlich | `https://stefan.inboxstride.de/` und `https://demo.inboxstride.de/` über bestehenden Host-nginx |

Geheimnisfreie, mit der tatsächlichen Compose-Konfiguration abgeglichene Vorlagen:
[Produktion](../ops/server/production.compose.example.yaml),
[Demo](../ops/server/demo.compose.example.yaml),
[Hinweise](../ops/server/README.md). Der zentrale OAuth-Dienst aus 8.0 ist weiterhin
nicht in Betrieb; 7.9.3 enthält nur dessen noch nicht angebundene Grundlage.

### Sicherung und Updateablauf dieses Releases

Die erfolgreiche Übernahme ist unter
`/opt/mailhelp/backups/upgrade-7.9.3-20261119T055857Z` gesichert und dokumentiert:

- `production-compose.yaml` und `demo-compose.yaml`: vorherige Compose-Dateien.
- `production-runtime.tar.gz`: konsistente Sicherung des angehaltenen Produktionsdienstes,
  Archivwurzel `production-runtime` einschließlich privater Konfiguration, Daten und Logs.
- `demo-runtime.tar.gz`: konsistente Sicherung des angehaltenen Demo-Volumes,
  Archivwurzel `demo-runtime`.
- `deployment.json` und `verification.json`: Übernahme- und Prüfnachweis ohne Tokenwerte.
  Der private Sicherungsordner hat Modus 0700 und liegt nicht im Webverzeichnis.

Reihenfolge: neues Image bauen; Demo anhalten und sichern; Konfiguration im neuen
Image ohne Netzwerk validieren; Demo umstellen und prüfen; Produktion anhalten und
sichern; Produktions-Compose auf das neue Image und den neuen Buildkontext umstellen;
Start, Version, Datenbindung und HTTPS prüfen. Die bestehenden Images bleiben erhalten.
Sicherung auf demselben VPS ersetzt keine verschlüsselte externe Katastrophensicherung.

Für die isolierte Konfigurationsprüfung benötigt auch `--check` einen beschreibbaren
Logpfad. Das Runtime-Verzeichnis bleibt schreibgeschützt; temporäres `/tmp` bereitstellen:

```sh
docker run --rm --network none --read-only \
  --tmpfs /tmp:size=16777216,mode=1777 \
  --mount type=bind,src=/opt/mailhelp/runtime,dst=/config,readonly \
  mailhelp-production:7.9.3-70f671b \
  --check --config-directory /config --log-directory /tmp/check-logs
```

Aufrufe auf internen IPs brauchen den richtigen Host-Kopf; eine Anfrage ohne ihn
kann korrekt mit HTTP 421 abgewiesen werden und ist kein Beleg eines Dienstfehlers:

```sh
curl --fail -H 'Host: demo.inboxstride.de' http://172.30.86.2:8765/health
curl --fail -H 'Host: stefan.inboxstride.de' http://127.0.0.1:8765/health
```

Zwei Vorversuche wurden vor der Produktionsumstellung kontrolliert zurückgenommen:
zunächst scheiterte die Prüfung am schreibgeschützten Logpfad, dann am fehlenden
Host-Kopf der Demo-Anfrage. Die vorherigen Container wurden jeweils wieder gestartet;
Runtime-Sicherungen wurden nicht über neuere Daten zurückgespielt. Diese Versuche
sind unter `upgrade-7.9.3-20261119T055527Z` und `upgrade-7.9.3-20261119T055636Z`
als zurückgenommen dokumentiert, nicht als aktiver Stand.

### Abnahme und Rückkehrgrenzen

Nachgewiesen: beide Container liefern 7.9.3, keine automatischen Neustarts; Demo-Health
ist `healthy`; öffentliche Health-/Anmeldeseiten liefern HTTPS 200. Die Demo-Einstiege
`/de/` und `/en/` liefern die richtige Sprache. Ein Socketversuch aus der Demo zu
einer externen Adresse scheitert; internes Netz und getrenntes Volume sind erhalten.
Produktionskonfiguration und Zugangsdaten stimmen per Prüfsumme mit dem Stand vor
dem Wechsel überein, bestehende Sitzungen und Ledger-Schreibnachweise sind erhalten.
Google Kalender, Todoist, Telegram, LLM und IServ meldeten beim Start bestätigten
Zugriff; bis zur Abnahme trat kein Anwendungsfehler auf. Landingpage, Datenschutz
und Nutzungsbedingungen blieben über HTTPS erreichbar. Keine Testtermine oder
Testaufgaben wurden angelegt; Produktiv-Neubewertungen wurden nicht ausgelöst.

Vor Umschaltung der Produktion kann auf die gesicherten Compose-Dateien und das
vorherige Image `mailhelp-production:7.8.1-ae4dcb9` zurückgekehrt werden. Nach Start
der neuen Produktion zuerst kontrolliert stoppen und Schema-/Schreibnachweise prüfen:
neue Felder oder inzwischen bestätigte Aktionen können eine blinde Rückkehr unsicher
machen. Eine alte Runtime-Sicherung niemals ungeprüft über den aktuellen Bestand
spielen; unklare externe Resultate vor jeder Wiederholung abgleichen. Eine eventuelle
Datenrückmigration gesondert prüfen. Der Stand 7.9.3 ist bei erfolgreicher Abnahme
die aktive Installation; die Altversion ist nur eine Rückkehrmöglichkeit.

## Tägliches Dropbox-Backup seit 19. November 2026

Erfolgreich eingerichtet: `mailhelp-dropbox-backup.timer` startet täglich um 03:30
Uhr in `Europe/Berlin` den zugehörigen systemd-Dienst. Nächster Termin bei Abnahme:
20.11.2026, 03:30 Uhr MEZ. Ziel ist der vom Betreiber freigegebene Dropbox-Ordner
`Backup/Mailhelpserver`; die Archive enthalten ausdrücklich auch Zugangsdaten und
haben auf Wunsch des Betreibers keine zusätzliche Backup-Verschlüsselung. Die
Übertragung erfolgt per HTTPS. Dropbox wurde einmalig vom Betreiber autorisiert.

Werkzeug: Rclone aus den Ubuntu-Paketquellen (installiert `1.60.1+dfsg-4ubuntu3.2`)
und das eigenständige Python-Werkzeug `devtools/server_backup.py`. Konfiguration und
private Dropbox-Verbindung liegen unter `/etc/mailhelp-backup/`, nur für root lesbar.
Einzelheiten, Umfang, Vorlagen, Kontrolle und Wiederherstellungsgrenzen stehen in
der [Dropbox-Backup-Anleitung](../ops/server/Dropbox-Backup.md).

Erste Sicherung: `mailhelpserver-20261119T130646Z.tar.gz`, 298.662.689 Bytes, mit
separater SHA-256-Datei. Dropbox-Upload und Inhaltsvergleich erfolgreich. Anschließend
wurde das Archiv aus Dropbox in ein privates Testverzeichnis zurückgeladen; Prüfsumme,
17.731 Archiveinträge und die testweise Dateiwiederherstellung von Konfiguration und
Zugangsdaten wurden geprüft. Das ist keine bereits durchgeführte vollständige
VPS-Wiederherstellung. Die Dienste wurden nur zur lokalen Archivierung angehalten
und vor dem Upload wieder gestartet. Produktion und Demo laufen weiterhin auf 7.9.3;
die Demo ist gesund, der Website-Formulardienst ist aktiv.

Eigene aktive Backupdateien im Dropbox-Ziel werden nach 14 Tagen, lokale nach zwei
Tagen beim nächsten erfolgreichen Lauf bereinigt. Dropbox-Versionshistorie und
wiederherstellbare gelöschte Dateien werden damit nicht endgültig gelöscht; die
vertragliche Kundendatenlöschung muss diese zusätzliche Ebene gesondert berücksichtigen.
Die Sicherung selbst schreibt keine Kalendertermine oder Aufgaben und versendet
keine Telegram-/E-Mail-Nachrichten.

Der neue Python-Code wurde mit synthetischen Diensten geprüft: neun Tests, 100 %
Zeilen- und Branch-Abdeckung; Ruff besteht. Die allgemeine Anwendungsversion und
die sonstigen laufenden 8.0-Arbeiten wurden für diese Servereinrichtung nicht deployed.
Vorlagen, Werkzeug und dieses Protokoll sind lokal zur Git-Erfassung vorbereitet;
Commit und Push erfordern einen eigenen Auftrag. Die private Rclone-Datei bleibt außerhalb von Git.

### Anleitungen zusätzlich auf dem Server

Seit 19.11.2026 liegt eine geheimnisfreie Kopie der aktuellen Dokumentation und
Servervorlagen unter `/opt/mailhelp/server-docs/`. Einstieg ist `INDEX.md`, gefolgt
von `docs/Betrieb.md` und `ops/server/Dropbox-Backup.md`. `manifest.json` enthält
Snapshot-Zeitpunkt, Quellcommit und SHA-256 der einzelnen Dateien; der Snapshot
kann noch nicht committeden Arbeitsstand enthalten und weist dies ausdrücklich aus.
Die erste Übertragung wurde mit 188 Dateiprüfsummen verifiziert.

Der Ordner ist eine verpflichtende Quelle in `/etc/mailhelp-backup/config.yaml`
und wird im TAR-Archiv unter `opt/mailhelp/server-docs/` gespeichert. Fehlt die
Dokumentkopie, scheitert der Backup-Vorlauf vor dem Anhalten der Dienste.
Nach erfolgreich geprüften Serveränderungen sind Git-Arbeitsstand und Serverkopie
gemeinsam zu aktualisieren; siehe `AGENTS.md`. Das vollständige Serverhandbuch ist
weiterhin ein Lieferumfang von 8.0; geplante Komponenten bleiben als geplant markiert.
Private Konfiguration, Tokens und Schlüssel liegen außerhalb der Dokumentkopie und
werden über die jeweiligen privaten Backupquellen gesichert.

### Präzisierung der 14-Tage-Backupbereinigung am 19.11.2026

Die aktive Regel zählt jetzt 14 Kalendertage in `Europe/Berlin`, einschließlich
des heutigen Tages. Beim erfolgreichen Lauf am 15. Tag werden alle eigenen Archive
und Prüfsummen des ersten Tages entfernt, auch wenn sie nachmittags statt zur
regulären Sicherungszeit entstanden sind. Beispiel: Am 03.12. entfallen Sicherungen
vom 19.11.; der 20.11. bis 03.12. bleibt erhalten. Sommerzeitwechsel werden korrekt
berücksichtigt. Es bleiben damit die Backups der letzten 14 Kalendertage, nicht
zwangsläufig exakt 14 Dateien bei zusätzlichen manuellen Sicherungen.

Die frühere Berechnung nach verstrichenen 24-Stunden-Perioden konnte die Löschung
eines späten Backups bis zum folgenden Lauf verzögern. Drei neue Regressionstests
reproduzierten dies vor der Korrektur (3 fehlgeschlagen); danach bestehen alle
13 Backup-Tests mit 100 % Zeilen- und Branch-Abdeckung. Die korrigierte Datei wurde
auf dem Server übernommen, der Tag-15-Fall dort ohne echten Löschzugriff geprüft.
Der vorherige Skriptstand bleibt unter `/opt/mailhelp-backup/server_backup-before-calendar-*.py`
erhalten. Zeitplan und Zugangsdaten wurden nicht verändert.

Die Bereinigung betrifft weiterhin nur den aktiven Dropbox-Zielordner nach einem
erfolgreichen Backup. Dropbox-Papierkorb/Versionshistorie und ein aufgrund von
Verbindungsfehlern ausgefallener Bereinigungslauf sind davon zu unterscheiden.

### Speicherbereinigung und IP-Zertifikat (19.11.2026)

Lesende Inventur vorab: Ubuntu 26.04.1 LTS, Kernel 7.0.0-34, Docker 29.1.3, Compose 2.40.3,
nginx 1.28.3, ufw installiert, aber inaktiv. Zertifikate stellt der Container
`certbot/certbot:v5.10.0` per Webroot `/var/www/mailhelp-acme` aus; je Domain erneuert ein
Skript unter `/usr/local/sbin/` aus `/etc/cron.d/` alle sechs Stunden und lädt nginx neu.

Speicher (mit Freigabe): Das Wurzeldateisystem war zu 92 % belegt (1,6 GB frei). Entfernt
wurden die Images `mailhelp-release:*` und `mailhelp-rollback:*`, `mailhelp-update-mailhelp:latest`,
`mailhelp-production` 7.0.16, 7.1.5 und 7.5.5, der gesamte Build-Cache (3,3 GB) sowie die
Sicherung `pre-6.2.5-20261114T080227Z` (4,5 GB). Danach 44 % belegt, 11 GB frei. Erhalten blieben
`mailhelp-production` 7.7.6, 7.8.1 und 7.9.3, das Image des gestoppten Altprojekts `mailhelp` mit
Volume, certbot und alle übrigen Sicherungen. Produktion und Demo liefen unverändert weiter.
Gelöschte Images lassen sich nur aus den Releasequellen neu bauen.

Das IP-Zertifikat für den direkten HTTPS-Zugang über die Serveradresse: Es war mit dem
Standalone-Verfahren und dem Kurzzeitprofil (sechs Tage) ausgestellt worden, hatte keine Erneuerung
und wäre am 20.11.2026 abgelaufen. Nach einem erfolgreichen Probelauf wurde es per Webroot neu
ausgestellt (gültig bis 26.11.2026); die Renewal-Konfiguration nutzt jetzt Webroot. Neu:
`/usr/local/sbin/renew-mailhelp-ip` und `/etc/cron.d/mailhelp-ip-cert-renew` (alle sechs
Stunden, Log `/var/log/mailhelp-ip-cert-renew.log`). Geprüft: `nginx -t`, ausgeliefertes
Zertifikat, Erneuerungs-Probelauf und HTTPS aller vier Sites. Rückkehr: die alte
Renewal-Datei liegt als Sicherung unter `/root/`; Skript und Cron-Datei lassen sich entfernen.

## Update auf 7.9.5 und zentraler Anmeldedienst (19.11.2026)

Quelle ist ausschließlich Commit `2073ef0` (`git archive` mit `ops/`), Release-Verzeichnis
`/opt/mailhelp/releases/7.9.5-2073ef0`. Auf dem Server gebaut: `mailhelp-production:7.9.5-2073ef0`
und aus `ops/auth/Dockerfile` `inboxstride-auth:7.9.5-2073ef0`. Prüfungen des Quellstands:
[Releasebericht 8.0, Abschnitt 7.9.5](Release-8.0.md).

### Anmeldedienst und auth.inboxstride.de

| Komponente | Stand |
| --- | --- |
| Container | `inboxstride-auth-auth-1`, Projekt `inboxstride-auth`, Datei `/opt/inboxstride-auth/compose.yaml`, Image-Tag in `/opt/inboxstride-auth/.env` |
| Schutz | Benutzer 65532, schreibgeschütztes Root-Dateisystem, keine Capabilities, `no-new-privileges`, Healthcheck `healthy` |
| Öffentlich | nur `127.0.0.1:8780`; nginx-Site `/etc/nginx/sites-available/auth.inboxstride.de` leitet ausschließlich `/auth/google/callback` und `/health` weiter |
| Intern | mTLS-Port 8443 nur im Docker-Netz `inboxstride-auth` (Alias `auth-intern`), nicht am Host veröffentlicht |
| Zustand | `/opt/inboxstride-auth/state` (Fernet-verschlüsselte Geheimnisse), Log `/opt/inboxstride-auth/logs/events.jsonl` |
| Geheimnisse | Schlüsseldatei und TLS-Material unter `/opt/inboxstride-auth/secrets` (65532, 0600); private CA in `/opt/inboxstride-auth/ca` (root, 0700), nicht im Container |
| TLS | Let's-Encrypt-Zertifikat `auth.inboxstride.de` per Webroot; `/usr/local/sbin/renew-inboxstride-auth` aus `/etc/cron.d/inboxstride-auth-cert-renew` |

Schritte: Verzeichnisse mit Eigentümer und Modus angelegt; `create-key`, `ca-init`,
`issue auth-intern --server` und `issue stefan` jeweils in einem Container ohne Netz; Instanz
`stefan` mit Host `stefan.inboxstride.de` registriert. Die Google-Clientdatei (Webanwendung,
Weiterleitung nur `https://auth.inboxstride.de/auth/google/callback`) wurde einmalig mit
`set-client` eingelesen und danach mit `shred` entfernt; im Zustand stehen Client-ID und Secret
nur verschlüsselt. Danach Compose-Start, Zertifikat, nginx-Site und Erneuerung.

Geprüft: `/health` liefert 200 über HTTPS mit passendem Zertifikat; `/intern/token` und `/`
liefern 404, ein POST auf den Callback 403, ein Callback ohne gültigen State 400 (Log:
`callback_refused` mit sicherem Grund, keine Parameterwerte). Erneuerungs-Probelauf erfolgreich.

### Update von Produktion und Demo, Anbindung der Produktion

Update mit Freigabe nach isolierter Konfigurationsprüfung ohne Netz: beide Container
angehalten, Laufzeitdaten konsistent gesichert unter
`/opt/mailhelp/backups/upgrade-7.9.5-20261119T141834Z`, umgestellt, Health und Version 7.9.5
beider Container geprüft.

Anbindung: `config.yaml` der Produktion erhielt `hosted_auth` (Dienst `https://auth-intern:8443`,
Instanz `stefan`, Zertifikat, Schlüssel und CA unter `/config/hosted-auth/`), die Compose-Datei
das externe Netz `inboxstride-auth`. Vorher gesichert unter
`/opt/mailhelp/backups/hosted-auth-20261119T141908Z`. Eine Probe aus dem Produktionscontainer
erhält über mTLS `unknown_connection` für eine nicht existierende Verbindung; damit sind
Zertifikat, CA und Instanzregister bestätigt. Die Demo ist nicht im Netz des Dienstes.

Der bisherige eigene Google-Zugang der Produktion ist unverändert aktiv
(`token_credentials_accepted`, Kalender, Todoist, Telegram, LLM und IServ mit
`access_confirmed`). Erst „Mit Google verbinden“ mit ausdrücklicher Übernahme stellt ein
Zielprofil auf den zentralen Dienst um; diese Pilotanmeldung ist noch nicht erfolgt.

Update auf 7.9.8 (19.11.2026, mit Freigabe): Bugfix für „Weiter zu Google“ (die
Sicherheitsrichtlinie verwarf die Weiterleitung zu Google). Commit `51adae6`, Image
`mailhelp-production:7.9.8-51adae6` nach Offline-Konfigurationsprüfung; Sicherung
`/opt/mailhelp/backups/upgrade-7.9.8-20261119T202944Z`; Health und Version 7.9.8 beider
Container geprüft. Netz `inboxstride-auth` und `hosted_auth` blieben erhalten; der Anmeldedienst
wurde nicht verändert. Rückkehr auf `mailhelp-production:7.9.5-2073ef0` mit den Compose-Dateien
dieser Sicherung.

Update auf 7.9.10 (20.11.2026, mit Freigabe): enthält die Bugfixes aus 7.9.9 („Verbindung
übernehmen“) und 7.9.10 (angenommenes Terminende). Commit `fd4d1e7`, Image
`mailhelp-production:7.9.10-fd4d1e7` nach Offline-Konfigurationsprüfung; Sicherung
`/opt/mailhelp/backups/upgrade-7.9.10-20261120T165909Z`; Health und Version 7.9.10 beider
Container geprüft; Netz `inboxstride-auth` und `hosted_auth` erhalten. Rückkehr auf
`mailhelp-production:7.9.8-51adae6` mit den Compose-Dateien dieser Sicherung.

Rückkehr: Anbindung durch Zurückspielen von `config.yaml` und Compose-Datei aus der Sicherung
`hosted-auth-…` und Neuerstellen des Containers; Update mit den Compose-Dateien aus
`upgrade-7.9.5-…` und Image `mailhelp-production:7.9.3-70f671b`. Der Dienst lässt sich mit
`docker compose -p inboxstride-auth down` anhalten und die nginx-Site entfernen; Zustand,
Schlüssel und CA dann nicht löschen, solange Verbindungen bestehen könnten.
