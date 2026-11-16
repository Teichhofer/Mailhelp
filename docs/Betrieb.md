# Betrieb und Update

Stand: Mailhelp 5.4.1.

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
Die Nachmessung am echten Bestand erfolgt nach einer Woche Betrieb.

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

## Sicherung

Für eine konsistente Sicherung zuerst den Dienst kontrolliert beenden. Erst nach dem
vollständigen Ende die Dateien kopieren; anschließend Mailhelp wieder starten.

Zu sichern sind `config.yaml`, `.env`, `prompts.yaml`, die Themen-Dateien, das Datenverzeichnis
(`data_directory`, Zustände als lesbare JSON-Dateien) und bei Bedarf das Protokollverzeichnis.
`.env` enthält Zugangsdaten und gehört nicht in fremde Hände.

## Update

Nach dem Installieren einer neuen Version den Dienst neu starten. Stylesheet und Skript werden
beim Start eingelesen. Ab 6.3.2 verweist jede Seite mit einem Inhaltskürzel auf den passenden
Stand beider Dateien, auch wenn ein älterer Service Worker den ersten Aufruf übernimmt.

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
