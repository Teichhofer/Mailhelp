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
