# Tägliches Backup nach Dropbox

Stand: 28. November 2026. Ziel des Betreibers: Dropbox-Ordner
`Backup/Mailhelpserver`, einschließlich Zugangsdaten und ohne zusätzliche
Archivverschlüsselung. Die Verbindung verwendet HTTPS. Der Ordner darf nicht
öffentlich oder mit unberechtigten Personen geteilt werden.

## Komponenten und Ablage

| Datei/Komponente | Serverpfad |
| --- | --- |
| Getesteter Python-Ablauf `devtools/server_backup.py` | `/opt/mailhelp-backup/server_backup.py` |
| Konfiguration aus `backup-config.example.yaml` | `/etc/mailhelp-backup/config.yaml` |
| Private Dropbox-Autorisierung | `/etc/mailhelp-backup/rclone.conf` |
| Lokale Archive, Prüfsummen und Status | `/var/lib/mailhelp-backup/` |
| systemd-Service und Timer | `/etc/systemd/system/mailhelp-dropbox-backup.{service,timer}` |
| Fernziel | `mailhelp-dropbox:Backup/Mailhelpserver` |
| Kopie der Serveranleitungen und Vorlagen | `/opt/mailhelp/server-docs/` |

Private Verzeichnisse sind nur für root zugänglich (0700), Konfiguration, Tokens
und Archive haben Modus 0600. Keine dieser privaten Dateien gehört in Git.
Versionierbar sind das Python-Werkzeug, Tests, geheimnisfreie Konfiguration und Units.
Der tägliche Termin ist 03:30 Uhr in `Europe/Berlin`, einschließlich Sommerzeit.
`Persistent=true` holt einen während eines ausgeschalteten Servers verpassten Lauf nach.
Aktivierung erst nach erfolgreicher erster Sicherung und Wiederherstellungsprüfung.

**Verifiziert am 19.11.2026:** erster Upload von 298.662.689 Bytes erfolgreich;
Rückdownload mit identischer SHA-256, 17.731 gelesene Archiveinträge und private
Testwiederherstellung der benötigten Konfigurations-/Zugangsdaten erfolgreich.
Der Timer ist aktiviert und läuft täglich um 03:30 Uhr (`Europe/Berlin`).
Die vollständige Wiederherstellung des VPS wurde dadurch noch nicht geprüft.

## Umfang

Das Archiv enthält die in der Konfiguration ausdrücklich aufgeführten Verzeichnisse,
darunter Produktions-Runtime einschließlich `.env`, Postfach-/Google-/Todoist-/KI-
Zugangsdaten, JSON-Zustände, Schreibnachweise, Sitzungen und Logs; die Kundeninstanz
`/opt/mailhelp-kunde` (`mailhelp-kunde-mailhelp-1`, inkl. `operator.yaml` und Runtime);
den zentralen Auth-Dienst `/opt/inboxstride-auth` (`inboxstride-auth-auth-1`); aktive
Compose-Dateien, Releasequellen, Demo-Volume, Landingpage-Releases und Interessentendaten;
nginx, TLS-Zertifikate/private Schlüssel, systemd/cron, Firewall, SSH- und Benutzerkonfiguration.
Die private Dropbox-Verbindung selbst und das Backupwerkzeug werden mitgesichert.
Die aktuelle geheimnisfreie Dokumentationskopie unter `/opt/mailhelp/server-docs`
ist eine erforderliche Quelle: Fehlt sie, scheitert die Sicherung vor dem Anhalten
der Anwendungen. Sie enthält Betriebsanleitungen, Servervorlagen, Entwicklungsregeln
und einen Dateiprüfsummen-/Versionsnachweis. Sie ist nach bestätigten Serveränderungen
gemäß `AGENTS.md` zu aktualisieren und ersetzt nicht die Git-Versionierung.

Nicht enthalten sind Docker-Layer, das vollständige Betriebssystem, der alte lokale
Backupbestand `/opt/mailhelp/backups` und das Stagingverzeichnis selbst. Images
werden aus gesicherten Releasequellen/Locks neu gebaut; Betriebssystem/Pakete
werden entsprechend dem Serverhandbuch installiert. Lokale private Schlüssel auf
einem Windows-Rechner sind keine Serverdateien und brauchen eine eigene Sicherung.

## Konsistenz und Fehlerfälle

1. Vor dem Anhalten die Dropbox-Erreichbarkeit und erforderliche Quellen prüfen.
2. Nur tatsächlich laufende konfigurierte Container und Dienste erfassen und einen
   dauerhaften Wiederanlaufplan schreiben. Bereits angehaltene Dienste bleiben angehalten.
3. Diese Dienste kontrolliert stoppen und ein vollständiges gzip-komprimiertes
   TAR-Archiv mit relativ gespeicherten Serverpfaden und Inventarmanifest erstellen.
4. Ursprünglich laufende Dienste auch bei Archivierungsfehlern wieder starten.
   `ExecStopPost` führt nach Abbruch/Timeout zusätzlich die idempotente Wiederaufnahme aus.
   Ein nicht vollständig abgearbeiteter Plan bleibt zur Reparatur erhalten.
5. Nach Wiederanlauf Archiv und SHA-256-Datei mit Rclone hochladen und deren Inhalte
   mit `rclone check` prüfen. Fehlerausgaben werden nicht samt Zugangsdaten protokolliert.
6. Erst nach erfolgreichem Upload und Vergleich ältere eigene Backupdateien bereinigen.
   Keine fremden Dateien löschen und kein `rclone sync` auf den Dropbox-Ordner anwenden.

systemd und `flock` verhindern überlappende Backupläufe. Manuelle Sicherungen über
`systemctl start mailhelp-dropbox-backup.service` starten. Deployment/Änderungen
während der lokalen Archivierung vermeiden; vor Wartung den Timer anhalten und
einen gegebenenfalls laufenden Backupjob kontrolliert abschließen lassen.

Es werden nur Namen vom Muster `mailhelpserver-YYYYMMDDTHHMMSSZ.tar.gz` beziehungsweise
`.sha256` bereinigt. Im aktiven Dropbox-Ziel bleiben die letzten 14 Kalendertage
in `Europe/Berlin` einschließlich des heutigen Tages erhalten. Am 15. Tag werden
beim erfolgreichen täglichen Lauf sämtliche Backups des ersten Tages einschließlich
ihrer Prüfsummen entfernt, unabhängig von deren ursprünglicher Uhrzeit. Beispiel:
Am 03.12. werden Backups vom 19.11. entfernt; der 20.11. bis einschließlich 03.12.
bleibt erhalten. Auch Sommerzeitwechsel werden nach lokalen Kalendertagen behandelt.
Lokale Archive werden nach zwei Tagen beim nächsten erfolgreichen Lauf entfernt.
Das löscht weder fremde
Dateien noch automatisch die Dropbox-Versionshistorie oder dort wiederherstellbare
gelöschte Dateien. Diese Dropbox-Aufbewahrung muss für die vertragliche 14-Tage-
Löschregel gesondert geprüft und geregelt werden. Ein ausgefallener Sicherungslauf
ist keine erfolgreiche Löschkontrolle. Der Timer allein garantiert keine vollständige
fristgerechte Kundendatenlöschung auf allen Speicherebenen.

## Einrichtung und Betrieb

Rclone und Python mit PyYAML aus den gepflegten Systempaketen bereitstellen.
Dropbox einmal mit `rclone config` autorisieren. Bei headless Einrichtung kann
ein lokaler SSH-Tunnel Port 53682 zur Autorisierung bereitstellen; Details stehen
in der [Rclone-Anleitung](https://rclone.org/remote_setup/#configuring-using-ssh-tunnel).
Rclone-Konfiguration nie ins Terminal, in Chat, Logs oder Git kopieren. Der Zugriff
ist für den vorgesehenen Dropbox-Account erforderlich; erneute Autorisierung bei
Widerruf erfolgt ausdrücklich über den Betreiber.

```sh
systemd-analyze verify /etc/systemd/system/mailhelp-dropbox-backup.service /etc/systemd/system/mailhelp-dropbox-backup.timer
systemctl daemon-reload
systemctl start mailhelp-dropbox-backup.service
cat /var/lib/mailhelp-backup/status.json
systemctl enable --now mailhelp-dropbox-backup.timer
systemctl list-timers mailhelp-dropbox-backup.timer
```

`enable` erst nach erfolgreichem Probelauf und der unten beschriebenen Prüfung
ausführen. Status und JSONL-Ereignisse enthalten keine Mailtexte oder Tokenwerte.
Fehler erzeugen einen fehlgeschlagenen systemd-Dienst und `status: failed`; ein
erfolgreicher Taskstart allein bedeutet noch keinen erfolgreichen Upload.

```sh
systemctl status mailhelp-dropbox-backup.service
journalctl -u mailhelp-dropbox-backup.service --since today
cat /var/lib/mailhelp-backup/status.json
systemctl disable --now mailhelp-dropbox-backup.timer
```

Zum Deaktivieren den Timer stoppen, nicht ein laufendes Backup gewaltsam beenden.
Bei verbliebenem `/var/lib/mailhelp-backup/resume.json` keine weiteren Serveränderungen
beginnen; zuerst den Wiederanlauf über den dokumentierten Recovery-Aufruf unter
derselben `flock`-Sperre prüfen. Die Statusdatei ist lokal, kein externer Alarmdienst;
ein ausgebliebener Tageserfolg muss überwacht werden. Telegram-/E-Mail-Versand ist
hier nicht eingerichtet.

## Wiederherstellung und Rückkehr

Eine Sicherung gilt erst mit vorhandenem Archiv, zugehöriger SHA-256-Datei und
erfolgreichem Inhaltsvergleich als vollständig. Bei der Abnahme eine Sicherung aus
Dropbox in ein privates Testverzeichnis zurückladen, SHA-256 vergleichen, das Archiv
vollständig lesen und benötigte Konfigurationen/Secretdateien ohne Ausgabe ihrer
Inhalte an einem isolierten Ziel prüfen. Eine partielle Dateiwiederherstellung ist
keine bereits nachgewiesene vollständige Wiederherstellung des VPS.

Vollständiger Restore ausschließlich auf einem vorbereiteten Ersatzsystem oder nach
ausdrücklich geplanter Reparatur: Dienste vorher stoppen, Pfade/Versionsstand prüfen,
Eigentümer und Rechte erhalten, Symlinks und Releaseziele wiederherstellen und
Zugänge lesend prüfen. TAR-Archive enthalten private Daten und interne Symlinks;
nicht ungeprüft mit root über ein laufendes System entpacken. Neue externe
Schreibnachweise niemals durch eine alte Sicherung überschreiben. Ein bereits bei
Google widerrufener Refresh-Token wird durch Restore nicht wieder gültig.

Der Dropbox-Zugang und ein Wiederherstellungsweg zum Dropbox-Konto müssen zusätzlich
außerhalb des VPS verfügbar sein. Ein Zugang, der ausschließlich in der zu rettenden
Sicherung liegt, genügt bei vollständigem Verlust des Servers nicht.

## Prüfung des eigenen Codes

`tests/release/test_server_backup.py` prüft synthetische Geheimnisse, Inhalte,
Dienstwiederanlauf, fehlende Quellen, Platzmangel, Uploadfehler, wiederaufgenommene
Recovery-Pläne, sichere Bereinigung und inhaltsfreie Fehlermeldungen. Der neue
Python-Code erreicht 100 % Zeilen- und 100 % Branch-Abdeckung und wird als Teil
von `devtools` von der vollständigen Python-Prüfung erfasst.
