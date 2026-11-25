# Verifizierte Servervorlagen

Stand: 24. November 2026. Produktion und Demo: Mailhelp 8.5.4, Quellcommit
`1ea1c98`, Image `mailhelp-production:8.5.4-1ea1c98`; zentraler Anmeldedienst
`inboxstride-auth:7.9.5-2073ef0` (unverändert).

| Vorlage | Installationsort | Compose-Projekt |
| --- | --- | --- |
| `production.compose.example.yaml` | `/opt/mailhelp/compose.setup.yaml` | `mailhelp-update` |
| `demo.compose.example.yaml` | `/opt/mailhelp-demo/compose.yaml` | `mailhelp-demo` |
| `kunde.compose.example.yaml` | `/opt/mailhelp-kunde/compose.yaml` (8.7, geplant, siehe [Planung](../../docs/Planung-8.7-Lernen.md)) | `mailhelp-kunde` |

Vorlagen beschreiben den erfolgreich geprüften aktuellen Stand, kein vollständiges
Serverhandbuch. DNS, nginx/TLS, Host-Firewall und Secret-/Backupbereitstellung werden
im [Serverhandbuch](../../docs/Serverhandbuch.md) zusammengeführt. Ergänzende
Neuaufbauvorlagen sind noch keine automatisch übernommenen Serveränderungen:

| Vorlage | Ziel / Parameter | Validierung und Übernahme | Rückkehr |
| --- | --- | --- | --- |
| `nginx-mailhelp.example.conf` | Nutzer-Site; `DOMAIN` ersetzen, Zertifikat bereitstellen | `nginx -t`, danach reload; Site vorher sichern | Gesicherte Site prüfen/reload |
| `nginx-demo.example.conf` | Demo-Site; `DOMAIN`, Compose-IP abgleichen | `nginx -t`, danach reload, Host/Limits prüfen | Gesicherte Demo-Site |
| `nginx-auth-mailboxes.location.example.conf` | 8.1-Location im Auth-HTTPS-Server | Erst Anbieterregistrierung, dann prüfen/reload | Zusätzliche Location entfernen |
| `mailhelp-cert-renew@.service`, `@.timer` | `/etc/systemd/system/`; Instanz = Zertifikatname | `systemd-analyze verify`, daemon-reload, Timer aktivieren | Timer aus, bisherigen Cron wiederherstellen |
| `firewall.example.txt` | Geprüfter SSH-Port statt `SSH_PORT` | Zuerst `--dry-run` und zweiter SSH-Zugang | Nur geänderte Regeln zurücknehmen |
| `permissions.example.txt` | Konkrete Pfade, UID/GID des Images | `stat`, einzelne Installationsschritte | Vorher notierte Eigentümer/Modi |

TLS-Units sind eine Alternative zum vorhandenen Cron, niemals parallel aktivieren.
Landingpage-/Formulardienstvorlagen liegen unter `landing/ops/`. Private Werte folgen
`.env.example` und `config.example.yaml` und werden getrennt bereitgestellt.
Postfach-OAuth: [Einrichtung und Freigaben](OAuth-Postfaecher.md).
Produktions-Konfiguration und Kundendaten sind nicht enthalten.

Seit 19.11.2026 ist zusätzlich das [tägliche Dropbox-Backup](Dropbox-Backup.md)
eingerichtet und per Rückdownload/Prüfsumme getestet. Vorlagen:
`backup-config.example.yaml`, `mailhelp-dropbox-backup.service` und
`mailhelp-dropbox-backup.timer`; Python-Werkzeug `devtools/server_backup.py`.
Ziel: `Backup/Mailhelpserver`, täglich 03:30 Uhr Europe/Berlin, ausdrücklich
einschließlich Zugangsdaten und ohne zusätzliche Archivverschlüsselung.
Dropbox-Wiederherstellungsfristen müssen zusätzlich zur Bereinigung aktiver
Backup-Dateien berücksichtigt werden.

Die aktuelle Anleitungs-/Vorlagenkopie liegt zusätzlich auf dem Server unter
`/opt/mailhelp/server-docs/`. Dieser Pfad ist im täglichen Backup verpflichtend.
`INDEX.md` nennt Einstieg und bekannte Grenzen; `manifest.json` enthält Quellcommit,
Snapshot-Zeitpunkt und Dateiprüfsummen. Bei bestätigten Serveränderungen nachführen.

Vor jeder Übernahme die tatsächliche Installation und Abweichungen prüfen. Die relative
Produktionsablage `./runtime` ist bezogen auf `/opt/mailhelp/compose.setup.yaml`.
Das Demo-Volume und sein Netz sind eigene Ressourcen und dürfen nicht durch
Produktions-Mounts oder produktive Umgebungsvariablen ersetzt werden.

Vorlagen vor der Übernahme mit `docker compose --env-file /dev/null -p <Projekt>
-f <Vorlagenpfad> config --quiet` prüfen. Danach die konfigurierte Zieldatei mit
demselben Befehl prüfen. Ein `config`-Erfolg ersetzt keine Health-/Funktionsprüfung.
Images zuerst bauen, erst danach Dienste kontrolliert anhalten und konsistent sichern.
Keine Geheimnisse in Buildkontext, Image oder Git aufnehmen.

## Zentraler Anmeldedienst (eingerichtet 19.11.2026)

Eingerichtet und geprüft mit 7.9.5. Der Betreiber meldet einen erfolgreichen Pilot;
am 20.11.2026 ist zentral ein Zugang aktiv, lokal aber noch keine Kalenderreferenz
gespeichert. Der konsistente Abschluss bleibt zu prüfen; keine automatische Zuordnung.
Einzelheiten, Prüfungen und Rückkehr: [Betrieb](../../docs/Betrieb.md).

| Vorlage | Installationsort | Compose-Projekt |
| --- | --- | --- |
| `auth.compose.example.yaml` | `/opt/inboxstride-auth/compose.yaml` | `inboxstride-auth` |
| `nginx-auth.inboxstride.de.example.conf` | `/etc/nginx/sites-available/auth.inboxstride.de` | – |

Das Image entsteht aus dem Release-Verzeichnis mit `ops/auth/Dockerfile`; es enthält nur
das Paket `inboxstride_auth` und die gepinnte Teilmenge `ops/auth/requirements.lock`.
Benötigte private Dateien auf dem Host, jeweils Eigentümer 65532 und Modus 0600
(Verzeichnisse 0700): Fernet-Schlüsseldatei `secrets/key` (`create-key`), TLS-Material
`secrets/tls/` (`ca-init`, `issue auth-intern --server`) und der Google-Client als
JSON-Datei, die nur einmalig mit `set-client` eingelesen und danach entfernt wird. Die
private CA bleibt außerhalb des Containers und wird getrennt gesichert. Nutzerinstanzen
treten dem Netz `inboxstride-auth` bei und erhalten ihr Client-Zertifikat
(`issue <instanz>`) sowie `hosted_auth` in `config.yaml` (bei einer neuen Ersteinrichtung
`MAILHELP_HOSTED_AUTH_URL=https://auth-intern:8443` mit `_INSTANCE`, `_CERT`, `_KEY` und
`_CA`); die Demo nie.

Update, Sicherung, Prüfergebnisse und Rückkehrgrenzen stehen in
[Betrieb und Update](../../docs/Betrieb.md). Änderungen erst nach überprüftem Erfolg
als gültigen Istzustand übernehmen; Betriebsdokumentation und Vorlagen zusammen pflegen.
