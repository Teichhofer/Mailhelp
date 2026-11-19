# Verifizierte Servervorlagen

Stand: 19. November 2026. Produktion und Demo: Mailhelp 7.9.3, Quellcommit
`70f671b04b84b91c2ddaab4b2a63b4a567aabbb7`, Image `mailhelp-production:7.9.3-70f671b`.

| Vorlage | Installationsort | Compose-Projekt |
| --- | --- | --- |
| `production.compose.example.yaml` | `/opt/mailhelp/compose.setup.yaml` | `mailhelp-update` |
| `demo.compose.example.yaml` | `/opt/mailhelp-demo/compose.yaml` | `mailhelp-demo` |

Vorlagen beschreiben den erfolgreich geprüften aktuellen Stand, kein vollständiges
Serverhandbuch. DNS, nginx/TLS, Host-Firewall, Secret-/Backupbereitstellung und das
zukünftige zentrale OAuth-System werden im Rahmen der Planung 8.0 vervollständigt.
Produktions-Konfiguration und Kundendaten sind nicht enthalten.

Vor jeder Übernahme die tatsächliche Installation und Abweichungen prüfen. Die relative
Produktionsablage `./runtime` ist bezogen auf `/opt/mailhelp/compose.setup.yaml`.
Das Demo-Volume und sein Netz sind eigene Ressourcen und dürfen nicht durch
Produktions-Mounts oder produktive Umgebungsvariablen ersetzt werden.

Vorlagen vor der Übernahme mit `docker compose --env-file /dev/null -p <Projekt>
-f <Vorlagenpfad> config --quiet` prüfen. Danach die konfigurierte Zieldatei mit
demselben Befehl prüfen. Ein `config`-Erfolg ersetzt keine Health-/Funktionsprüfung.
Images zuerst bauen, erst danach Dienste kontrolliert anhalten und konsistent sichern.
Keine Geheimnisse in Buildkontext, Image oder Git aufnehmen.

Update, Sicherung, Prüfergebnisse und Rückkehrgrenzen stehen in
[Betrieb und Update](../../docs/Betrieb.md). Änderungen erst nach überprüftem Erfolg
als gültigen Istzustand übernehmen; Betriebsdokumentation und Vorlagen zusammen pflegen.
