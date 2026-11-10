# Fehler beheben

Stand: Mailhelp 5.3. Sichere nächste Schritte für häufige Probleme. Keine dieser Maßnahmen legt
Einträge doppelt an: Mailhelp wiederholt nie eine Anlage, deren Ergebnis unklar ist, sondern
gleicht sie zuerst mit dem Anbieter ab.

| Lage | Ursache | Nächster Schritt |
| --- | --- | --- |
| Anmeldung am Postfach fehlgeschlagen | Benutzername, Passwort oder Verbindungsart falsch | **Einstellungen → Zugangsdaten** prüfen; bei Zwei-Faktor-Schutz App-Passwort; **Zugriffe prüfen** |
| Ordner fehlt | Ordnername anders als auf dem Server | auf der Postfachseite die gefundene Ordnerliste übernehmen |
| Google: Anmeldung abgelaufen (`token_refresh_denied` im Protokoll) | Refresh-Token widerrufen oder abgelaufen | **Google verbinden** erneut ausführen |
| Microsoft: Anmeldung abgelehnt | Token abgelaufen | **Microsoft verbinden** oder `mailhelp --microsoft-login` |
| Anbieter nicht erreichbar | Netzwerk oder Störung beim Anbieter | abwarten; Mailhelp versucht es erneut. **Status** zeigt den letzten Kontakt |
| KI-Budget erschöpft | `limits.llm_calls_per_minute` erreicht | nichts tun: die Mail wird automatisch später ausgewertet |
| „Die Nachricht überschreitet ein Sicherheitslimit“ | Mail zu groß oder zu verschachtelt | Grenzen unter `limits` nur für vertrauenswürdige Mails erhöhen |
| Einstellung „gespeichert – wirkt erst nach einem Neustart“ | noch nicht aktiv | **Einstellungen → Mailhelp neu starten** |
| Eintragung noch nicht bestätigt | Eintrag beim Anbieter nicht sichtbar oder Abruf verweigert | Eintrag beim Anbieter ansehen; danach **Erneut prüfen** |
| Unklarer Schreiberfolg | Antwort des Anbieters ging verloren | nichts tun: Mailhelp gleicht ab und legt nicht erneut an |
| Ziel geändert, Anlage gesperrt | Vorschlag für ein anderes Ziel bestätigt | ursprüngliches Ziel wiederherstellen oder den neuen Vorschlag bestätigen |
| „Beenden nicht ausgeführt“ oder „Neustart nicht ausgeführt“ | Bestätigung von einem früheren Start oder unvollständig | auf derselben Seite erneut bestätigen; hilft das nicht, Mailhelp im Terminal mit Strg+C beenden |
| „Mailhelp läuft bereits …“ | zweiter Start auf demselben Datenverzeichnis | laufende Instanz beenden |
| Web-Passwort vergessen | – | am Rechner `mailhelp --reset-web-password --config-directory .` |

## Diagnose

**Einstellungen → Diagnose** prüft jede Verbindung nur lesend und nennt je Dienst Ergebnis und
Handlungsempfehlung; die Kachel **Lesender Selbsttest** unter Einstellungen prüft alle Komponenten. Der Diagnosebericht
enthält keine Zugangsdaten. Protokolle stehen im Protokollverzeichnis (`logging.directory`);
Inhalte von KI-Anfragen nur, wenn sie ausdrücklich eingeschaltet sind.
