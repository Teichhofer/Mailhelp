# Verifizierte Servervorlagen

Stand: 19. November 2026. Produktion und Demo: Mailhelp 7.9.8, Quellcommit
`51adae6`, Image `mailhelp-production:7.9.8-51adae6`; zentraler Anmeldedienst
`inboxstride-auth:7.9.5-2073ef0` (unverändert).

| Vorlage | Installationsort | Compose-Projekt |
| --- | --- | --- |
| `production.compose.example.yaml` | `/opt/mailhelp/compose.setup.yaml` | `mailhelp-update` |
| `demo.compose.example.yaml` | `/opt/mailhelp-demo/compose.yaml` | `mailhelp-demo` |

Vorlagen beschreiben den erfolgreich geprüften aktuellen Stand, kein vollständiges
Serverhandbuch. DNS, nginx/TLS, Host-Firewall und Secret-/Backupbereitstellung werden
im Serverhandbuch der Planung 8.0 vervollständigt.
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

Eingerichtet und geprüft mit 7.9.5; die Pilotanmeldung eines Google-Kontos steht noch aus.
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
