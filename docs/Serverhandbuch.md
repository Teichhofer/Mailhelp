# Serverhandbuch Inboxstride

Geprüft für Mailhelp 8.5.3

Stand: 23. November 2026. Diese Anleitung verbindet den bestätigten Serverbestand
mit den [Konfigurationsvorlagen](../ops/server/README.md). Detaillierte Änderungsnachweise
und ältere Rückkehrpunkte stehen in [Betrieb](Betrieb.md). Private Dateien werden
aus der getrennten Sicherung bereitgestellt, niemals aus Git.

## Bestätigter Bestand und Grenzen

Centron, Deutschland; Ubuntu 26.04.1 LTS. Zuletzt ermittelt: Docker 29.1.3,
Compose 2.40.3, nginx 1.28.3. Update und Kontrolle am 22.11.2026: nginx und Formulardienst
aktiv, drei Container aktiv, Produktion, Demo und Auth gesund.
Produktion und Demo verwenden nach dem Update vom 24.11.2026 tatsächlich
`mailhelp-production:8.5.3-241e23e` (Commit `241e23e`), der Auth-Dienst unverändert
`inboxstride-auth:7.9.5-2073ef0`. Änderungen im lokalen Checkout sind damit
nicht automatisch produktiv. Der Betreiber bestätigt am 20.11.2026 den erfolgreichen
Google-Pilotabschluss einschließlich Übernehmen der Verbindung. Der anschließende
Serverabgleich findet jedoch nur eine zentrale aktive Verbindung und keine lokale
Kalenderreferenz. Der produktive Profilwechsel ist noch nicht nachgewiesen.

| Dienst | Quelle / veränderliche Daten | Zugang |
| --- | --- | --- |
| Produktion | `/opt/mailhelp/releases/`, `/opt/mailhelp/runtime` | nginx → `127.0.0.1:8765`, `stefan.inboxstride.de` |
| Demo | `/opt/mailhelp-demo/compose.yaml`, Volume `mailhelp-demo-runtime` | nginx → `172.30.86.2:8765`, `demo.inboxstride.de` |
| Landingpage | Git `landing/`; `/opt/inboxstride/current` → Release | `inboxstride.de`, `www.inboxstride.de` |
| Formulardienst | systemd `inboxstride`, `/var/lib/inboxstride/leads` | Loopback-Port 8877, nginx |
| OAuth | `/opt/inboxstride-auth/`, Compose `inboxstride-auth` | nginx → `127.0.0.1:8780`; intern mTLS `auth-intern:8443` |
| Sicherung | `/etc/mailhelp-backup`, `/opt/mailhelp-backup` | systemd-Timer, Dropbox |

Die ursprünglich geplante isolierte Neuaufbau-/Reparaturprobe wurde laut
[Planung 8.0](Planung-8.0.md) am 19.11.2026 vom Betreiber abgewählt. Die nachfolgende
Neuaufbauanleitung ist deshalb kein Nachweis eines vollständig getesteten VPS-Restores.
Dateirückdownload und Archivprüfsummen wurden dagegen geprüft, siehe Backup-Anleitung.

## Neuaufbau: Voraussetzungen und Reihenfolge

1. Linux-VPS mit ausreichend Speicher für aktive Daten, Images und ein zusätzliches
   konsistentes Backup bereitstellen. Administrationszugang mit SSH-Schlüssel
   unabhängig von Mailhelp testen. Aktuelle Paketquellen und Sicherheitsupdates verwenden.
2. Docker Engine mit Compose-Plugin, nginx, Python 3, PyYAML und rclone installieren.
   Die verwendeten Versionen und Paketquellen im Betriebsnachweis festhalten.
   Git-Checkout und passende private Sicherung derselben Installation bereitstellen.
3. Verzeichnisse gemäß Tabelle anlegen. Produktion/Demo laufen mit der UID aus dem
   jeweiligen Dockerfile; Runtime-Rechte daran ausrichten. Der Auth-Container nutzt
   UID 65532; dessen Daten-/Secretverzeichnisse benötigen Eigentümer 65532 und Modus
   0700, Geheimdateien 0600. Die private Auth-CA bleibt außerhalb der Container.
4. Versionierte Quellen nach `/opt/mailhelp/releases/<Version>-<Commit>` übertragen.
   Keine `.env`, Zustandsdateien oder privaten Schlüssel in den Buildkontext aufnehmen.
   Mailhelp-Image mit dem Repository-Dockerfile und Auth-Image mit
   `ops/auth/Dockerfile` bauen; unverwechselbare Versions-/Commit-Tags verwenden.
5. Auth-Compose gemäß Vorlage einrichten und starten; das Netz `inboxstride-auth`
   entsteht dadurch. Auth-Geheimnisse und mTLS gemäß folgendem Abschnitt bereitstellen.
6. Produktions-Compose aus Vorlage nach `/opt/mailhelp/compose.setup.yaml` übernehmen,
   Releasepfad/Image einstellen und Runtime wiederherstellen beziehungsweise eine
   frische Ersteinrichtung vorbereiten. Vorlagen niemals über private Konfiguration kopieren.
7. Demo aus der eigenen Vorlage mit eigenem Volume und isoliertem Netz einrichten.
   Sie erhält weder Produktions-Mounts noch Auth-Netz oder produktive Zugangsdaten.
8. Landingpage aus `landing/` bauen; Quell-README und `devtools/landing_install.py`
   für die Installation verwenden. Formulardaten außerhalb der Releases wiederherstellen.
9. DNS, nginx und TLS wie unten einrichten. Erst nach internen Gesundheitsprüfungen
   öffentlich freigeben. Anschließend Backup-Dienst installieren und Probesicherung prüfen.

## DNS, nginx, TLS und Netzwerk

Die DNS-A-/gegebenenfalls AAAA-Einträge von Hauptdomain, www, Demo, Auth und jeder
freigeschalteten Nutzerinstanz müssen auf den vorgesehenen Host zeigen. AAAA nur
setzen, wenn die komplette Erreichbarkeit über IPv6 geprüft ist. Subdomains allein
registrieren noch keine berechtigte Instanz beim Anmeldedienst.

nginx-Sites liegen überwiegend unter `/etc/nginx/sites-available`, aktivierte Links unter
`sites-enabled`. Ausnahme: `sites-enabled/mailhelp-domain` ist im bestätigten Bestand
eine reguläre Datei, kein Link. Die Auth-Vorlage ist
`ops/server/nginx-auth.inboxstride.de.example.conf`; die übrigen bestehenden Sites
werden aus der privaten Serverkonfigurationssicherung wiederhergestellt und an DNS
und Pfade angepasst. Bestehende Site-Namen: `inboxstride-http`, `inboxstride-https`,
`mailhelp-demo-http`, `mailhelp-demo-https`, `mailhelp-domain`, `mailhelp-http`,
`mailhelp-ip`, `auth.inboxstride.de`. Vor jedem Reload `nginx -t` ausführen.

Öffentlich erforderlich: HTTP 80 für ACME/Weiterleitung, HTTPS 443 sowie der bewusst
konfigurierte SSH-Administrationsport. Interne Anwendungsports nicht öffentlich öffnen.
Die zuletzt ermittelte ufw-Konfiguration war inaktiv; dies ist eine Bestandsangabe,
keine Empfehlung zum Abschalten einer Firewall. Neue Regeln erst mit getestetem
zweitem Administrationszugang aktivieren; Docker-Portfreigaben separat prüfen.
Die Produktionsvorlage `ops/server/nginx-mailhelp.example.conf` schaltet Zugriffslogs
aus, damit lokale OAuth-Abschlussbelege nicht in nginx-Querystrings landen. Gegenüber
der am 20.11.2026 gelesenen Produktions-Site ist dies eine noch zu übernehmende Härtung.

Let's Encrypt wird per certbot-Container v5.10.0 und Webroot erneuert. Schlüssel
und Konfiguration liegen unter `/etc/letsencrypt`. Die tatsächlich vorhandenen
Erneuerungsskripte unter `/usr/local/sbin` heißen `renew-inboxstride`,
`renew-inboxstride-auth`, `renew-mailhelp-demo`, `renew-mailhelp-domain` und
`renew-mailhelp-ip`; zugehörige Zeitpläne liegen unter `/etc/cron.d`. Sie sind im
Backup enthalten. Bei Neuaufbau Webroot, Zertifikatnamen, DNS und nginx-Pfade zuerst
abgleichen, dann die wiederhergestellten Skripte prüfen. Testausstellung gegen
ACME-Staging verwenden; Produktionslimits nicht durch wiederholte Versuche belasten.

## Zentraler Google-Zugang und Instanzen

Öffentlicher Callback: `https://auth.inboxstride.de/auth/google/callback`.
Google-Webclient und Kalender-Scopes gemäß Planung 8.0 konfigurieren. Der Kalender-
Client erhält dadurch keinen Gmail-Zugriff. Private Clientdatei nur kurzfristig
geschützt bereitstellen und mit `python -m inboxstride_auth set-client` importieren.
Exakte CLI-Parameter vor Verwendung mit `python -m inboxstride_auth --help` prüfen.

`create-key` erstellt den Speicherschlüssel. `ca-init` erstellt die private CA,
`issue auth-intern --server` das Dienstzertifikat; `issue <Instanz>` erstellt das
Clientzertifikat. Die CLI-Kommandos laufen mit den in der Auth-Compose-Vorlage
genannten `INBOXSTRIDE_AUTH_*`-Pfaden. CA, Schlüssel und verschlüsselten Zustand
zusammen und getrennt vom Code sichern. Den privaten CA-Schlüssel nie in den
laufenden Auth-Container mounten.

Mit `register` werden Instanz-ID, erlaubter Host und Zertifikatsfingerabdruck gebunden.

Betreiberkommandos mit Zustands-/Secretänderungen (`register`, `disable`, `set-client`,
`set-mail-client`, `sweep`, Schlüsselrotation) im Wartungsfenster bei gestopptem
Auth-Dienst ausführen. Es gibt genau einen zustandsschreibenden Dienstprozess;
die Sperren koordinieren seine Threads, nicht unabhängig gestartete Container.
Vorher Zustand und Schlüssel getrennt sichern, danach Dienst wieder starten und
Healthcheck sowie mTLS-Zugriff prüfen. Kein zweiter Auth-Dienst auf denselben Dateien.

Die Nutzerinstanz erhält ihre Dateien unter `runtime/hosted-auth/` und `hosted_auth`
in `config.yaml`. Frische Instanzen können stattdessen mit den
`MAILHELP_HOSTED_AUTH_URL`, `_INSTANCE`, `_CERT`, `_KEY`, `_CA`-Variablen vorbereitet
werden. Beispiele und Dateizuordnung stehen in `ops/server/README.md`.
Keine Tokens oder Schlüssel als CLI-Werte in Shell-Historien schreiben.

nginx veröffentlicht ausschließlich den Callback; interne Tokenausgabe erfolgt über
mTLS im Docker-Netz. Falsches/fehlendes Zertifikat muss scheitern. Auth-Querystrings
nicht protokollieren. Healthchecks geben keine Verbindungen oder Geheimnisse aus.
Die lokale Übernahme braucht eine gültige Sitzung, CSRF, passende Entwurfsversion
und Idempotenzschlüssel. Eine neue Kalenderverbindung ist keine Schreibfreigabe.

## Sicherung und Wiederherstellung

Verbindliche Detailanleitung: [Dropbox-Backup](../ops/server/Dropbox-Backup.md).
Täglich 03:30 Europe/Berlin sichert der Timer `mailhelp-dropbox-backup.timer` nach
`mailhelp-dropbox:Backup/Mailhelpserver`, ausdrücklich einschließlich Zugangsdaten
und ohne zusätzliche Archivverschlüsselung auf Wunsch des Betreibers. Die aktive
Ablage enthält heute plus 13 vorangehende Berliner Kalendertage. Erst nach erfolgreichem
Upload und Prüfung werden ältere eigene Archive samt Prüfsumme gelöscht. Dropbox-
Papierkorb/Versionshistorie können darüber hinaus bestehen.

Backup-Konfiguration `/etc/mailhelp-backup/config.yaml`, rclone-Zugang
`/etc/mailhelp-backup/rclone.conf`, Werkzeug `/opt/mailhelp-backup/server_backup.py`;
Private Rechte 0700/0600. Zeitplan, Unit und Konfigurationsvorlage stehen in Git.
Der Sicherungspunkt stoppt nur zuvor laufende Dienste und nimmt sie anschließend
wieder auf. Fehlgeschlagene Wiederaufnahme über Recovery-Zustand untersuchen,
nicht blind zusätzliche Container starten. Status und sichere Ereignisse liegen
unter `/var/lib/mailhelp-backup`. Kein Backup rekursiv in seine Quellen aufnehmen.

Bei Serververlust zuerst Archiv und SHA256-Datei herunterladen und Hash abgleichen.
Archivinhalt vor Extraktion prüfen; auf einem isolierten Ersatzsystem mit passenden
Pfaden, Eigentümern und Codeversion wiederherstellen. Keine zweite aktive Instanz
auf denselben Mail-/Kalenderzugängen starten. Auth-Zustand braucht den passenden
Speicherschlüssel, Konfiguration die privaten Zugangsdaten und mTLS-Zertifikate.
Fehlende Schlüssel oder defekte Archive verhindern die Freigabe. Neue Produktions-
Schreibnachweise niemals mit einem älteren Gesamtbackup überschreiben.

Vor Wiederfreigabe Lösch-/Sperrnachweise seit dem Sicherungszeitpunkt abgleichen:
gelöschte Konten nicht reaktivieren. Bei unklarer Lage Instanz deaktiviert lassen
und neu autorisieren. Google-seitig widerrufene Tokens werden durch Restore nicht
wieder gültig. Vertragsende: Daten binnen 14 Tagen löschen, soweit keine gesetzlichen
Aufbewahrungspflichten bestehen; Dropbox-Historie und zentrale Geheimnisse einbeziehen.

## Update, Prüfung und Rückkehr

Bei jedem Deployment einer neuen Mailhelp-Version auf dem Server ist verpflichtend
auch ein Update aller installierten Host-Programme und Systempakete durchzuführen:
1. Paketlisten aktualisieren und ausstehende Paket- und Sicherheitsupdates einspielen
   (`apt-get update && apt-get upgrade -y`, einschließlich `nginx`, `openssl`, `systemd`,
   `docker`, `rclone`, `python3` sowie Kernel-/Bibliothekspaketen); zusätzlich aktuelle
   Container-Hilfsimages (z. B. `certbot/certbot`) auf Aktualität prüfen.
2. Nach `nginx`-Updates `nginx -t`, `systemctl status nginx` und das tatsächlich laufende
   Binary (`/proc/$(cat /run/nginx.pid)/exe`, kein `(deleted)`) prüfen.
3. `/var/run/reboot-required` prüfen: Falls ein Neustart (z. B. nach Kernel- oder
   `libc6`-Updates) erforderlich ist, diesen kontrolliert nach Abschluss der Sicherung
   einplanen/ausführen und danach alle Container, `nginx` und HTTPS-Endpunkte verifizieren.

Quellen und Images zunächst separat bauen. Mit `docker compose -p <Projekt>
-f <Datei> config --quiet` prüfen; Aufruf gegebenenfalls mit privater Env-Datei,
deren Werte nicht ausgeben. Danach konsistenten Sicherungspunkt und vorherige
Compose-/Image-Zuordnung festhalten. Auth, Produktion und Demo sind getrennte
Projekte; Images und Konfiguration jeweils ausdrücklich auswählen.

Nach Wechsel Containerzustand, HTTPS mit richtigem Host, Anmeldeseite und lesende
Verbindungsprüfungen kontrollieren. Demo mit `Host: demo.inboxstride.de` testen,
sonst ist HTTP 421 erwartbar. Google-Pilot prüft Anmeldung und Kalenderliste,
erst eine gesonderte bestätigte Vorschlagsversion erlaubt Kalender-/Todoist-Schreiben.
Bei fehlerhafter neuer Anwendung zunächst den vorherigen Image-/Compose-Stand
verwenden; Daten nur nach gesondertem Kompatibilitätsabgleich zurückspielen.

## Fehlerdiagnose

| Symptom | Lesende Prüfung | Begrenzte Abhilfe |
| --- | --- | --- |
| HTTPS nicht erreichbar | DNS, Zertifikatablauf, `nginx -t`, `systemctl status nginx` | DNS/Webroot/Pfade korrigieren, Konfiguration prüfen, dann reload |
| HTTP 502 | `docker ps`, `docker inspect`, erwartete Loopbackports | Gestoppten richtigen Dienst starten oder fehlerhaften Upstream reparieren |
| Demo HTTP 421 | Hostheader und erlaubte Hosts | Vorgesehenen Host verwenden; keinen Produktionszugang eintragen |
| Auth-mTLS scheitert | Zertifikatlaufzeit, Name `auth-intern`, CA, Instanzregister | Passende Identität/Dateirechte wiederherstellen; interne Schnittstelle nicht veröffentlichen |
| Google abgelehnt | Sicheren Fehlercode, aktuelle Verbindung und Clientrevision prüfen | Betroffene Verbindung erneut autorisieren, keine Tokenwerte protokollieren |
| Schreibrechte fehlen | Mountpfade, UID 65532 und Modi prüfen | Nur betroffene Pfade korrigieren; kein pauschales chmod 777 |
| Speicher voll | `df -h`, `docker system df`, Backupstatus | Nach Inventur unbenötigte Images/Cache entfernen; keine aktiven Daten löschen |
| Backup überfällig | `systemctl list-timers`, Unitstatus, status.json | Dropbox/Platz/Quellen prüfen, Recovery beachten, begrenzt erneut ausführen |
| Formular defekt | `systemctl status inboxstride`, Loopback 8877 | Richtigen Releasepfad und Dateneigentümer wiederherstellen |

## Pflegepflicht

Nach erfolgreich verifizierter Serveränderung dieses Handbuch, passende Vorlagen
und [Betriebsnachweis](Betrieb.md) aktualisieren. Danach geheimnisfreie Kopie unter
`/opt/mailhelp/server-docs` samt Manifest synchronisieren und Backupaufnahme prüfen.
Abgebrochene Versuche als solche dokumentieren; lokale Änderungen sind ohne Commit
noch keine Git-Sicherung. Konkrete Geheimwerte gehören ausschließlich in private
Konfiguration und die ausdrücklich dafür vorgesehene Sicherung.
