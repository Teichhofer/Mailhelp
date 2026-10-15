# Dokumentationsprüfung

Stand: 14. Oktober 2026. Ausgangspunkt: `beta`, Commit `b1193fb`, Version 3.3.1.
Das Facelift aus `b30395a` ist enthalten; der Folgecommit korrigierte dessen zunächst
verwendete Versionsnummer 3.3.2 auf 3.3.1.

## Ergebnis

Die Dokumentation war nicht vollständig aktuell. Die folgenden Abweichungen wurden
in den lokalen Dateien korrigiert:

| Bereich | Korrektur |
| --- | --- |
| README und Changelog | Facelift wieder beschrieben; Navigation, Einstellungsbereiche und tatsächlich aktivierte Beispiel-Inhaltslogs dokumentiert. |
| Aktuelle Release-Anleitung | [Release 3.3](Release-3.3.md) ergänzt und in das Quellarchiv aufgenommen. Refactoring, UI, Upgrade und verbleibende Architekturarbeiten beschrieben. |
| Einrichtung | Lockdatei bei Installation und Update; lokale Webkopplung ohne Telegram; Google-Desktop-OAuth mit `--google-auth` und Profilnummer; aktueller Korpus v3 statt v2 für neue Qualitätsläufe. |
| Technische Instanzvorlagen | Mehrere Postfächer, Zielprofile, Anhangsauswertung, Microsoft-/CalDAV-Ziele, optionale Telegram-Nutzung, Web-Push, Berichte und ausdrücklich gespeicherte IMAP-Entwürfe berücksichtigt. |
| Datenminimierung | Konfigurierbare Fristen, Berichtsvolltexte, Benachrichtigungshistorie, explizite Inhaltslogs und deren aktivierter Zustand im Beispiel klargestellt. |
| Projektwebsite | Telegram oder Web statt Telegrampflicht, vollständige Erstinstallationsschritte mit Filterdatei, Zielprofile und aktuelle Datenflüsse; Schreibfehler in den Nutzungsbedingungen behoben. |
| Historische Dokumente | 35 ältere Pläne, Konzepte, Architektur- und Release-Dokumente als historisch gekennzeichnet. Veraltete „In Planung“-Statusangaben für 1.3, 1.4 und 2.1 berichtigt. Ursprüngliche Messwerte und Detailziele bleiben nachvollziehbar. |
| Planung 3.3/4.0 | Umgesetzte Phasen von weiter offenen Architekturarbeiten getrennt; 4.0 ausdrücklich als zukünftiger Browser-Erststart und Web-Lernmodus gekennzeichnet. |
| Verweise | Gelöschtes `telegram/temporal.py` durch den heutigen Modulverweis ersetzt. Website-Vorschau verwendet Port 8000, um den laufenden Dienst auf 8765 nicht zu blockieren. |

Grundlage waren die versionierten Markdown- und HTML-Dateien einschließlich
Korpusbeschreibungen und datierter Qualitätsberichte sowie CLI, Konfigurationsmodelle,
Beispiele, OAuth-Code, Web-Routen, Persistenzschemas und Veröffentlichungsworkflows.
Externe OAuth-Angaben wurden mit Googles [Desktop-Ablauf](https://developers.google.com/identity/protocols/oauth2/native-app),
[Kalender-Scopes](https://developers.google.com/workspace/calendar/api/auth) und
[Token-Lebensdauer](https://developers.google.com/identity/protocols/oauth2#expiration)
abgeglichen. Die Tailscale-Optionen wurden gegen die
[Serve-Referenz](https://tailscale.com/docs/reference/tailscale-cli/serve) geprüft.

## Verifikation und Grenzen

Die Prüfung der lokalen Linkziele und Abschnittsanker ist ohne fehlende Ziele
abgeschlossen. Die 24 bestehenden Tests für Dokumentationsschemas, Konfigurationsbeispiele,
Spezifikationsverträge und die vollständige Einstellungsreferenz bestehen. Wheel und
Quellarchiv wurden gebaut; zwei Paketprüfungen bestehen. `git diff --check` ist sauber.
Die archivierten vollständigen Test- und Modellmesswerte wurden für diese Textänderungen
nicht neu erhoben und werden als historische Abnahmen dargestellt.

Betreiberplatzhalter in `DATENSCHUTZ.md` und `NUTZUNGSBEDINGUNGEN.md` bleiben bewusst
erhalten. Dienste, Rechtsgrundlagen und Fristen müssen für die jeweilige Instanz
eingetragen werden; die öffentlichen Website-Texte beschreiben einen anderen Betrieb.
Die Website wurde lokal überarbeitet, nicht veröffentlicht. Release-Tags und entfernte
Deployments wurden nicht als neue Veröffentlichungsnachweise bewertet.

Während der Prüfung entstanden unabhängig Änderungen an `application.py`, `cli.py`
und `metrics.py` für eine Hintergrund-Zugangsprüfung. Diese Änderungen wurden nicht
bearbeitet und sind kein Bestandteil der hier dokumentierten Release-Abnahme.
