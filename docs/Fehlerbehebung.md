# Fehler beheben

Stand: Mailhelp 5.4. Sichere nächste Schritte für häufige Probleme. Keine dieser Maßnahmen legt
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

## Web-Passwort zurücksetzen

1. Den laufenden Dienst kontrolliert beenden; der Rücksetzbefehl benötigt alleinigen Zugriff
   auf das Datenverzeichnis.
2. Am Host im Konfigurationsverzeichnis `mailhelp --reset-web-password --config-directory .`
   ausführen. Das löscht den bisherigen Passworthash und meldet alle Websitzungen ab;
   es erzeugt kein neues Passwort.
3. Bei beendetem Dienst `mailhelp --pair --config-directory .` ausführen und den einmaligen
   Terminal-Code bereithalten. Den Dienst wieder starten und mit diesem Code anmelden.
4. Nach gültiger Anmeldung kann unter `/einstellungen/web-passwort` ausdrücklich ein neues
   Web-Passwort gesetzt werden. Den Code und das Passwort nicht in den Hilfschat eingeben.

## Diagnose

**Einstellungen → Verbindungen prüfen** prüft jede Verbindung nur lesend und nennt je Dienst Ergebnis und
Handlungsempfehlung; **Alles auf einmal prüfen (Selbsttest)** auf derselben Seite prüft alle Komponenten. Der Diagnosebericht
enthält keine Zugangsdaten. Protokolle stehen im Protokollverzeichnis (`logging.directory`);
Inhalte von KI-Anfragen nur, wenn sie ausdrücklich eingeschaltet sind.

## Hilfschat im Einstellungsfenster

Das Fenster bleibt bei Suche und Speichern geöffnet. Ist es im Weg, den Kopf ziehen oder den
Titel fokussieren und die Pfeiltasten verwenden. Nur **Hilfschat schließen** blendet es aus;
**Chat leeren** entfernt den Verlauf. Erscheint eine Antwort nicht, die Seite neu laden.
Keine Frage wegen eines Seitenwechsels erneut senden: Mailhelp zeigt den vorhandenen Auftrag.

Ist Browserspeicher gesperrt, sichert Mailhelp den Fensterstand vor Navigation auf dem lokalen
Server. Bei einem Fehler bleibt die Seite mit dem Entwurf erhalten; Verbindung prüfen und
erneut versuchen. Ohne JavaScript bleibt eine ungesendete Frage beim Seitenwechsel nicht erhalten.
Erscheint „crypto.randomUUID is not a function“ (Mailhelp über `http://` im Heimnetz vor 5.5),
auf 5.5 aktualisieren; seither erzeugt Mailhelp die Schlüssel auch ohne sicheren Kontext.
Nach Abmeldung oder Sitzungsablauf erneut anmelden; alte private Chatdaten werden nicht aus
dem Browserzustand einer neuen Sitzung übernommen.
