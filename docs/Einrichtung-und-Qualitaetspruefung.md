# Einrichtung und Qualitätsprüfung

## Aktualisierung einer bestehenden Installation

Nach Übernahme der Änderungen die Installation mit `python -m pip install -e ".[test]"`
aktualisieren, damit auch `mailhelp-evaluate` als neuer Befehl eingerichtet wird.
Die geänderten Extraktionsprompts verändern den Konfigurationsfingerprint.
Noch unvollständige Mailzustände mit altem Fingerprint werden deshalb weiterhin
sichtbar gesperrt. Solche Vorgänge mit der ursprünglichen Konfiguration abschließen
oder nach dem dokumentierten Verfahren bewusst neu verarbeiten; den gespeicherten
Fingerprint nicht manuell überschreiben. Bereits abgeschlossene Zustände und
versionsbezogene Schreibreferenzen erhalten.

## Google OAuth erstmals einrichten

Stand der verlinkten Google-Dokumentation: geprüft am 7. Oktober 2026.

1. In der [Google Cloud Console](https://console.cloud.google.com/) ein eigenes
   Projekt auswählen und die Google Calendar API aktivieren. Den OAuth-
   Zustimmungsbildschirm mit passender Zielgruppe konfigurieren. Bei externem
   Testbetrieb das eigene Google-Konto als Testnutzer hinzufügen.
2. Einen OAuth-Client vom Typ Webanwendung anlegen. Als autorisierte Redirect-URI
   exakt `https://developers.google.com/oauthplayground` eintragen.
3. Im [Google OAuth Playground](https://developers.google.com/oauthplayground/)
   die Einstellungen öffnen: eigene OAuth-Zugangsdaten aktivieren, Client-ID und
   Client-Secret eintragen, Google-Endpunkte, Server-side, Offline und Consent
   Screen auswählen. Eigene Zugangsdaten vermeiden den besonderen automatischen
   24-Stunden-Widerruf der Playground-Standardtokens. Der Playground vermittelt
   die Autorisierungsanfragen über Google; keine Freigabelinks mit Tokens erstellen.
4. Diese beiden Scopes autorisieren:

   - `https://www.googleapis.com/auth/calendar.events` für Termine und Duplikatabgleich.
   - `https://www.googleapis.com/auth/calendar.calendars.readonly` für die Prüfung
     der Kalender-Metadaten durch `--check-access`.

   Der zweite Scope ist erforderlich, weil ein reiner Event-Scope nicht den
   verwendeten Aufruf `calendars.get` erlaubt. Siehe
   [Calendar-Scopes](https://developers.google.com/workspace/calendar/api/auth) und
   [calendars.get](https://developers.google.com/workspace/calendar/api/v3/reference/calendars/get).
5. Mit dem Konto zustimmen, das Schreibrechte im Zielkalender besitzt. Im
   Playground den Autorisierungscode gegen Tokens tauschen. Den **Refresh-Token**
   verwenden, nicht den kurzlebigen Access-Token.
6. Client-ID, Client-Secret und Refresh-Token ausschließlich in `.env` unter
   `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET` und
   `GOOGLE_OAUTH_REFRESH_TOKEN` speichern. Die Werte nicht in Befehlszeilen,
   Screenshots, Git oder Berichte übernehmen. Vorhandene Prozessvariablen haben
   Vorrang vor `.env` und müssen gegebenenfalls ebenfalls aktualisiert werden.
7. `targets.google_calendar` auf die Kalender-ID setzen (`primary` für den
   Hauptkalender des autorisierten Kontos). Dann `mailhelp --check-access`
   ausführen. Dieser Test legt keine Aufgaben oder Termine an, sendet jedoch die
   dokumentierte Telegram-Testnachricht.

Der zugrunde liegende Austausch und Offline-Zugriff sind in Googles
[OAuth-Webserverablauf](https://developers.google.com/identity/protocols/oauth2/web-server)
beschrieben. Externe Apps im Veröffentlichungsstatus „Testing“ erhalten für diese
Scopes normalerweise nur sieben Tage gültige Refresh-Tokens. Vor dauerhaftem
Betrieb den passenden Veröffentlichungsstatus und gegebenenfalls notwendige
Verifizierung klären; Workspace-Richtlinien können zusätzlich gelten.
[Token-Lebensdauer und Widerrufsgründe](https://developers.google.com/identity/protocols/oauth2#expiration)

Bei `invalid_grant`, widerrufener Zustimmung oder abgelaufenem Refresh-Token:
Mailhelp stoppen, denselben Autorisierungsablauf mit den eigenen Clientdaten
wiederholen, die Geheimnisse ersetzen und `--check-access` erneut ausführen.
Erst nach erfolgreicher Prüfung neu starten. Den Zustand erhalten: Schreibzustände
`writing` und `uncertain` werden abgeglichen, nicht zur erneuten Anlage freigegeben.

## Docker: Filter und Lernmodus

Vor dem ersten Normalstart eine fehlende `irrelevant-senders.json` aus
`irrelevant-senders.example.json` kopieren. Eine vorhandene Filterdatei behalten.
Compose bindet die Datei ausdrücklich schreibgeschützt ein; fehlt sie, meldet der
Bind-Mount einen Fehler statt unbemerkt einen leeren Filter zu verwenden.

Für Lernen gibt es die **eigenständige** Datei `compose.learn.yaml`. Sie bindet
das ganze Verzeichnis `learning-config` ein, damit atomarer Dateiaustausch möglich
ist. Die Datei nicht als Overlay mit `compose.yaml` kombinieren.

Bei gestopptem Dienst unter Linux einrichten:

```sh
mkdir -p learning-config data logs
cp config.yaml prompts.yaml topics.yaml irrelevant_topics.yaml irrelevant-senders.json learning-config/
sudo chown -R 65532:65532 learning-config data logs
docker compose -f compose.learn.yaml run --rm mailhelp --learn 20
```

Unter Windows die Verzeichnisse und Kopien entsprechend in PowerShell anlegen;
`chown` entfällt bei den üblichen Docker-Desktop-Bind-Mounts. Lernen wird interaktiv
im Terminal bestätigt. Vor dem ersten Kopieren sicherstellen, dass im Lernverzeichnis
keine neueren Änderungen liegen. Nach dem Lauf die geänderten Dateien prüfen und
`config.yaml`, `topics.yaml`, `irrelevant_topics.yaml` und `irrelevant-senders.json`
aus `learning-config` zurück ins normale Konfigurationsverzeichnis übernehmen.
Danach den Normalbetrieb starten. Geheimnisse bleiben im bestehenden `.env`.
Nicht gleichzeitig lernen und den Dienst mit denselben Zustandsverzeichnissen betreiben.

## Reale Erkennungsqualität ausdrücklich prüfen

Die Standardtests bleiben offline und messen Vertrauensgrenzen, Persistenz und
Verarbeitung. Für echte Modellausgaben gibt es nach Installation den separaten
Befehl `mailhelp-evaluate`. Er verwendet keine IMAP-, Telegram-, Todoist- oder
Kalenderadapter. Den API-Key ausdrücklich als `OPENROUTER_API_KEY` in der
Prozessumgebung bereitstellen; der Befehl liest keine persönliche `.env` automatisch.

```sh
mailhelp-evaluate --allow-network --max-calls 100 --corpus tests/fixtures/mail_corpus_v1/corpus.json --prompts prompts.yaml --output evaluation-report.json
```

Der Aufruf ist kostenpflichtige OpenRouter-Nutzung. Ohne `--allow-network`,
positives `--max-calls` und Key startet er nicht. Jede tatsächlich angeforderte
Providerroute verbraucht einen Budgetplatz, auch Fallbacks. HTTP-Retries und
Schema-/JSON-Reparaturen sind in diesem Diagnosepfad deaktiviert. Jede Route muss
in `prompts.yaml` ein `max_tokens` von 1 bis 16.000 haben. Das begrenzt Aufrufe und
Ausgabetokens, garantiert aber keinen Eurobetrag: Eingabetokens und Modellpreise
kommen hinzu. Das Aufrufbudget vor dem Start passend wählen.

Das JSON-Ergebnis enthält Zeit, Prompt-/Korpus-Fingerprints, Modelle und
Routingparameter, verbrauchte Aufrufe sowie erwartete und tatsächliche semantische
Ergebnisse pro Stufe. Keine Erwartungsantwort wird an das Modell gesendet.
Relevanz/Themen, Kandidatenzahlen, Klassifikation, Zuständigkeit, Sicherheit und
extrahierte Zeit-/Ortsdaten werden gegen den synthetischen Korpus verglichen.
Abweichungen in Textformen können bewusst als Fehler sichtbar bleiben und müssen
fachlich bewertet werden. Zusammenfassungen werden auf Fristen und Satzanzahl
geprüft; ihre Faktentreue sowie Titel, Beschreibung und Evidenz erfordern eine
zusätzliche manuelle Qualitätsprüfung. Dies ist keine automatische Gesamtfreigabe.

Exit-Code 0 bedeutet vollständigen Lauf mit bestandenen automatischen Kriterien;
Exit-Code 1 umfasst Abweichungen, Providerfehler und ausgeschöpftes Budget. Ein
Teilergebnis ist ausdrücklich `complete: false`. Die automatisierte CI testet
auch diesen Befehl ausschließlich mit simuliertem Provider und einem synthetischen
Key. Ein realer Modelllauf ist bei der Implementierung nicht automatisch enthalten.
