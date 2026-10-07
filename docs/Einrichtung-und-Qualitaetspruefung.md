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
mailhelp-evaluate --allow-network --max-calls 100 --corpus tests/fixtures/mail_corpus_v2/corpus.json --prompts prompts.yaml --output evaluation-report.json
```

Der Aufruf ist kostenpflichtige OpenRouter-Nutzung. Ohne `--allow-network`,
positives `--max-calls` und Key startet er nicht. Jede tatsächlich angeforderte
Providerroute verbraucht einen Budgetplatz, auch Fallbacks. HTTP-Retries und
Schema-/JSON-Reparaturen sind in diesem Diagnosepfad deaktiviert. Jede Route muss
in `prompts.yaml` ein `max_tokens` von 1 bis 16.000 haben. Das begrenzt Aufrufe und
Ausgabetokens, garantiert aber keinen Eurobetrag: Eingabetokens und Modellpreise
kommen hinzu. Das Aufrufbudget vor dem Start passend wählen.

Für reale Modellläufe ist `mail_corpus_v2` vorgesehen: realistische Mails mit
Empfangszeitpunkt, aussagekräftige Themenbeschreibungen und für fachliche
Grenzfälle ausdrücklich erlaubte Alternativen (`accept`). `mail_corpus_v1` bleibt
unverändert die Grundlage der simulierten Standardtests.

Der Zielpfad des Berichts wird vor dem ersten kostenpflichtigen Aufruf geprüft.
Nach jedem Fall schreibt der Befehl den Zwischenstand atomar in die Ausgabedatei
(`complete: false`) und meldet den Fortschritt auf stderr, etwa
`[3/17] 03_council_event: bestanden (Aufrufe 12/100)`.

Das JSON-Ergebnis enthält Zeit, Prompt-/Korpus-Fingerprints, Modelle und
Routingparameter, verbrauchte Aufrufe, vom Provider gemeldete Tokens und Kosten
(`usage`), bestandene Fälle je Stufe (`stage_pass_counts`) sowie erwartete,
erlaubte und tatsächliche semantische Ergebnisse pro Stufe. Keine
Erwartungsantwort wird an das Modell gesendet. Die Mail wird wie im Betrieb mit
Empfangszeitpunkt und Nutzerzeitzone aufbereitet. Relevanz/Themen,
Kandidatenzahlen, Klassifikation, Zuständigkeit, Sicherheit und Zeitangaben werden
verglichen; Fristen und Termine nach derselben deterministischen Normalisierung wie
in der Anwendung, sodass „bis 01.10.2026“ und „01.10.2026“ gleich sind. Freitext
wird ohne Groß-/Kleinschreibung und Leerraumunterschiede verglichen, beim Ort nur
dessen Vorhandensein. Zusammenfassungen werden auf die genannten Fristen (als
Datum, sonst als Text) und die Satzanzahl geprüft; ihre Faktentreue sowie Titel, Beschreibung und Evidenz erfordern eine
zusätzliche manuelle Qualitätsprüfung. Dies ist keine automatische Gesamtfreigabe.

Exit-Code 0 bedeutet vollständigen Lauf mit bestandenen automatischen Kriterien;
Exit-Code 1 umfasst Abweichungen, Providerfehler und ausgeschöpftes Budget. Ein
Teilergebnis ist ausdrücklich `complete: false`. Die automatisierte CI testet
auch diesen Befehl ausschließlich mit simuliertem Provider und einem synthetischen
Key. Ein realer Modelllauf ist bei der Implementierung nicht automatisch enthalten.

### Stand der realen Qualitätsprüfung (7. Oktober 2026)

Modell `z-ai/glm-5.3-flash`, Korpus `mail_corpus_v2`, `reasoning: {effort: low}`
global und `medium` für `action_router`. Zwei identische Läufe ergaben jeweils
**14 von 17** vollständig bestandenen Fällen bei rund 0,013 USD und 140–200
Sekunden je Lauf, ohne Provider-, Schema- oder Tokenlimitfehler. Relevanz 17/17,
Router, Aufgaben und Termine je 16/17, Zusammenfassung 16/17.

Bewusst akzeptierte, in beiden Läufen gleiche Abweichungen:

- `17_optional_booking`: Der Router stuft das freiwillige Buchungsangebot als
  `unclear` ohne Aufgabe ein, sodass kein Vorschlag entsteht. Akzeptiert, weil es
  sich um ein freiwilliges Angebot handelt und die Mail weiterhin als
  Zusammenfassung erscheint. Die Korpuserwartung bleibt `task`, damit eine
  Verbesserung oder Verschlechterung sichtbar bleibt.
- `03_council_event`: Zuständigkeit oder Sicherheit schwanken zwischen `unclear`
  und `uncertain`; beide Varianten führen zur gleichen Rückfrage.
- `14_invitation_registration`: Die Zusammenfassung nennt die Anmeldefrist, aber
  nicht den Termin des Fachtags (nur Anzeige).

Die manuelle Bewertung von Zusammenfassung, Titel, Beschreibung und Evidenz steht
weiterhin aus.
