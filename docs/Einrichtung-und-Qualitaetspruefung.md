# Einrichtung und Qualitätsprüfung

Stand: 15. Oktober 2026, Anwendungsversion 3.4.1. Die Einrichtungshinweise gelten
für den aktuellen Stand. Datierte Qualitätsberichte weiter unten dokumentieren
jeweils den damaligen Code und die damals geprüften Modelle.

<p align="center">
  <img src="../src/mailhelp/assets/logo.png" alt="Mailhelp" width="200">
</p>

## Anwendungslogo und Telegram-Profilbild

Das offizielle Logo liegt unter
[`src/mailhelp/assets/logo.png`](../src/mailhelp/assets/logo.png).
Die bereitgestellte PNG-Datei bleibt unverändert und wird mit dem Python-Paket
und Docker-Image ausgeliefert. Auch bei einer installierten Version ist sie als
Paketressource `mailhelp/assets/logo.png` verfügbar.

Als sichtbares Anwendungsicon dient das Profilbild des Telegram-Bots. Für einen
neu eingerichteten Bot lässt es sich in BotFather über `/setuserpic` setzen:
den zugehörigen Mailhelp-Bot auswählen und die Logo-Datei als Bild hochladen.
Telegram speichert das Profilbild; ein erneuter Upload bei jedem Programmstart
ist nicht erforderlich. Die Kommandozeilenoberfläche benötigt kein Bildbanner.

## Aktualisierung einer bestehenden Installation

Den Dienst stoppen und Konfiguration, Geheimnisse, Token-Dateien und den vollständigen
Zustandsordner sichern. Bei einer Repository-Installation zunächst die Abhängigkeiten
mit `python -m pip install -r requirements.lock` und dann die Anwendung mit
`python -m pip install --no-deps -e .` aktualisieren. Eine Entwicklungsinstallation
verwendet stattdessen `python -m pip install --no-deps -e ".[test]"`.
Für Paketinstallation und Docker gelten die Schritte in der [README](../README.md).

`mailhelp --check` vor dem Start ausführen. Die Konsolidierung und das Facelift
benötigen keine Promptänderung. Tatsächliche Änderungen an Prompts oder wirksamen
Analysethemen können unvollständige Mails zurückhalten; Fingerprints niemals manuell
überschreiben. Reine Zieländerungen verändern seit 3.2 den Analyse-Fingerprint nicht.
Bei einem Upgrade von älteren Versionen zunächst die bisherigen Ziele beibehalten,
damit Alt-Fingerprints registriert werden. Details zu Migration und Rückkehr:
[Release 3.2](Release-3.2.md), [Release 3.3](Release-3.3.md) und [Release 3.4](Release-3.4.md).

## Weboberfläche und Tailscale (ab 1.1)

Einrichtung der optionalen Weboberfläche, Tailscale Serve für das iPhone,
Installation als App und Verhalten bei Schlaf oder Neustart des PCs beschreibt
[Release-1.1.md](Release-1.1.md). Kurzfassung: `web.enabled: true` und
`MAILHELP_WEB_SECRET` setzen und am PC `http://127.0.0.1:8765` öffnen. Einen Code mit
`mailhelp --pair` am lokalen Host oder über Telegram anfordern und damit koppeln.
Für das iPhone `tailscale serve --bg --https=443
http://127.0.0.1:8765` ausführen und den Tailnet-Namen in `web.allowed_hosts`
eintragen.

Für den Betrieb ohne Telegram `telegram.enabled: false` setzen. Die Erstkopplung
benötigt einen laufenden Dienst und den lokalen `--pair`-Aufruf; Codes erscheinen
ausschließlich im aufrufenden Terminal. Nach der Anmeldung bietet `/einrichtung`
versionsbezogene Konfigurationsentwürfe und `/diagnose` sichere Einzelprüfungen.
Passwörter und Tokens liegen in `.env` oder der Prozessumgebung; seit 3.3.11 lassen sie sich unter
**Einstellungen → Zugangsdaten** nur schreibend eintragen. Postfächer und IServ-Konten werden unter
**Einstellungen → Postfächer** bzw. **→ IServ-Konten** als Entwurf angelegt. Ein vollständig
browserbasierter Erststart, OAuth-Anmeldung im Browser und ein Web-Lernmodus sind noch nicht
implementiert.

## IServ-Elternbriefe einrichten (ab 3.3.7)

Elternbriefe aus dem IServ-Elternbriefmodul werden wie Mails verarbeitet und gelten immer als
relevant. Benötigt werden die HTTPS-Adresse der Schule (z. B. `https://schule.example`) und die
Anmeldedaten des Elternkontos.

1. **Einstellungen → IServ-Konten**: Adresse, Anzeigename und das Postfach eintragen, dessen
   Zielprofil gelten soll; „IServ-Konto als Entwurf hinzufügen“.
2. **Einstellungen → Zugangsdaten**: `ISERV_<n>_USERNAME` und `ISERV_<n>_PASSWORD` eintragen.
3. **Diagnose → iserv** starten. „bereit“ bestätigt Anmeldung und Briefübersicht; ein
   Zugangsdatenproblem bedeutet falsche Anmeldedaten oder einen zweiten Anmeldeschritt, den
   Mailhelp noch nicht unterstützt.
4. Den Entwurf übernehmen und Mailhelp neu starten.

Ohne Weboberfläche: in `config.yaml` unter `iserv.accounts` ein Konto mit `id`, `server` und
`mailbox` eintragen, in `.env` `ISERV_<id>_USERNAME` und `ISERV_<id>_PASSWORD` setzen und
`mailhelp --check-access` ausführen. Briefe vor der Startgrenze (ohne Angabe: die des Postfachs)
bleiben unberührt. Mailhelp verändert in IServ nichts. Details: [Release 3.4](Release-3.4.md).

## Google OAuth erstmals einrichten

Stand: 14. Oktober 2026. Mailhelp unterstützt eine lokale Browseranmeldung.
Der verwendete OAuth-Client ist eine **Desktop-App** mit lokalem Rückruf und PKCE,
entsprechend Googles [Desktop-OAuth-Ablauf](https://developers.google.com/identity/protocols/oauth2/native-app).

1. In der [Google Cloud Console](https://console.cloud.google.com/) ein eigenes
   Projekt wählen, Google Calendar API aktivieren und den Zustimmungsbildschirm
   einrichten. Bei externem Testbetrieb das eigene Konto als Testnutzer hinzufügen.
2. Einen OAuth-Client vom Typ **Desktop-App** anlegen. Client-ID und Client-Secret
   ausschließlich in `.env` oder der Prozessumgebung als `GOOGLE_OAUTH_CLIENT_ID`
   und `GOOGLE_OAUTH_CLIENT_SECRET` hinterlegen. Für zusätzliche Profile gelten
   die nummerierten Geheimnisnamen aus [Release 3.2](Release-3.2.md).
3. Am Host `mailhelp --google-auth --config-directory .` ausführen; für Profil 2
   zusätzlich `--profile 2` angeben. Mailhelp öffnet den Browser und nimmt den
   State-/PKCE-geschützten Rückruf an `127.0.0.1` auf einem freien Port entgegen.
   Die Anmeldung läuft nach fünf Minuten ab. Der Refresh-Token wird atomar im
   passenden Eintrag der lokalen `.env` gespeichert, nicht im Terminal ausgegeben.
4. Mit einem Konto zustimmen, das Schreibrechte im Zielkalender besitzt. Mailhelp
   fordert `calendar.events` für Termine sowie `calendar.calendars.readonly` für
   Kalendermetadaten an. Die [Calendar-Scope-Referenz](https://developers.google.com/workspace/calendar/api/auth)
   erläutert diese Berechtigungen. Eine Zustimmung zur OAuth-Anmeldung bestätigt
   keine Aufgaben- oder Terminanlage.
5. `targets.google_calendar` beziehungsweise den Kalender des Zielprofils auf die
   gewünschte ID setzen; `primary` bezeichnet den Hauptkalender. Danach
   `mailhelp --check-access` ausführen. Die Prüfung erstellt keine Termine oder
   Aufgaben; bei aktiviertem Telegram sendet sie eine Testnachricht.

Für Docker die Erstanmeldung auf dem Host durchführen und die geschützte `.env`
einbinden. Ein Container ohne Hostbrowser ist kein geeigneter Ort für diesen
Loopback-Ablauf. Vorhandene Prozessvariablen haben Vorrang vor `.env`; einen alten
Refresh-Token dort ebenfalls ersetzen oder entfernen.

Externe OAuth-Apps im Veröffentlichungsstatus „Testing“ erhalten für diese Scopes
normalerweise nur sieben Tage gültige Refresh-Tokens. Vor dauerhaftem Betrieb den
passenden Veröffentlichungsstatus und gegebenenfalls Verifizierung klären;
Workspace-Richtlinien können zusätzlich gelten. Siehe Googles
[Token-Lebensdauer und Widerrufsgründe](https://developers.google.com/identity/protocols/oauth2#expiration).

Bei `invalid_grant` oder widerrufener Zustimmung die lokale Anmeldung für das
betroffene Profil wiederholen und den Zugriff erneut prüfen. Gespeicherte
Schreibreferenzen erhalten: `writing` und `uncertain` werden abgeglichen, nicht
zur ungeprüften erneuten Anlage freigegeben. Andere Zielprofile bleiben unabhängig.
Ein früher manuell beschaffter Refresh-Token kann weiter verwendet werden, solange
er gültig ist und zu seinen OAuth-Clientdaten passt. Für die integrierte Anmeldung
muss der Client den Desktop-Ablauf unterstützen.

## Docker: Filter und Lernmodus

Die Quellordner und `imap.drafts_folder` benötigen die exakten Namen des jeweiligen
IMAP-Servers. Unter `/einrichtung` die lesende Ordnerliste prüfen. Bezeichnungen
wie `Drafts`, `Sent`, `Spam` und `Trash` sind keine universellen IMAP-Namen; bei
WEB.DE können die Ordner `Entwurf`, `Gesendet`, `Unerwünscht` und `Papierkorb` heißen.
Das Beispiel muss daher vor dem Start an das eigene Postfach angepasst werden.
Ein zusätzlicher Ordner mit Lesefehler verhindert den Abruf von INBOX nicht, wird
aber ausgelassen. Die Statusseite zeigt solche Abruffehler getrennt von Fehlern
bereits gespeicherter Mails. Ein erfolgreicher Abruf des betroffenen Ordners hebt
den Fehlerhinweis auf; ein erfolgreicher Abruf eines anderen Postfachs tut das nicht.

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

Ab Version 1.0 prüft der folgende Befehl standardmäßig den produktiven
Jev-Relevanzpfad einschließlich des generativen Rückfalls bei `unclear`.
`--decisions-prompts` wählt eine andere Jev-Konfiguration; ansonsten wird sie
neben `prompts.yaml` oder aus der Paketvorlage geladen. `--legacy-relevance`
prüft ausdrücklich nur den früheren Pfad und zählt nicht als Standardpfad-Abnahme.
Jev und generative Aufrufe teilen sich `--max-calls`; Berichte in Schema 3 enthalten
zusätzlich den geprüften Modus und einen Fingerprint der Jev-Konfiguration.
Für die Release-Abnahme `tests/fixtures/mail_corpus_v3/corpus.json` verwenden.
Gleichbedeutende Uhrzeitangaben werden auch bei unvollständigen Terminen normalisiert.

Die folgenden historischen Ergebnisse beschreiben frühere Stände. Maßgeblich für
eine Release-Freigabe sind die aktuellen Berichte unter `quality-reports/`.

Die Standardtests bleiben offline und messen Vertrauensgrenzen, Persistenz und
Verarbeitung. Für echte Modellausgaben gibt es nach Installation den separaten
Befehl `mailhelp-evaluate`. Er verwendet keine IMAP-, Telegram-, Todoist- oder
Kalenderadapter. Den API-Key ausdrücklich als `OPENROUTER_API_KEY` in der
Prozessumgebung bereitstellen; der Befehl liest keine persönliche `.env` automatisch.

```sh
mailhelp-evaluate --allow-network --max-calls 100 --corpus tests/fixtures/mail_corpus_v3/corpus.json --prompts prompts.yaml --output evaluation-report.json
```

Der Aufruf ist kostenpflichtige OpenRouter-Nutzung. Ohne `--allow-network`,
positives `--max-calls` und Key startet er nicht. Jede tatsächlich angeforderte
Providerroute verbraucht einen Budgetplatz, auch Fallbacks. HTTP-Retries und
Schema-/JSON-Reparaturen sind in diesem Diagnosepfad deaktiviert. Jede Route muss
in `prompts.yaml` ein `max_tokens` von 1 bis 16.000 haben. Das begrenzt Aufrufe und
Ausgabetokens, garantiert aber keinen Eurobetrag: Eingabetokens und Modellpreise
kommen hinzu. Das Aufrufbudget vor dem Start passend wählen.

Für aktuelle reale Modellläufe ist `mail_corpus_v3` vorgesehen: realistische Mails mit
Empfangszeitpunkt, aussagekräftige Themenbeschreibungen und für fachliche
Grenzfälle ausdrücklich erlaubte Alternativen (`accept`). `mail_corpus_v1` bleibt
unverändert die Grundlage der simulierten Standardtests. `mail_corpus_v2` bleibt
für die Wiederholung der historischen Läufe vom 7. und 8. Oktober erhalten.

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

In beiden damaligen Läufen gleiche Abweichungen (keine vollständige Spec-Abnahme):

- `17_optional_booking`: Der Router stuft das freiwillige Buchungsangebot als
  `unclear` ohne Aufgabe ein, sodass kein Vorschlag entsteht. Dies widerspricht
  der Spec für persönliche, direkt ausführbare Buchungsangebote. Die verbindliche
  Korpuserwartung bleibt `task`; eine Zusammenfassung ersetzt den Vorschlag nicht.
- `03_council_event`: Zuständigkeit oder Sicherheit schwanken zwischen `unclear`
  und `uncertain`; beide Varianten führen zur gleichen Rückfrage.
- `14_invitation_registration`: Die Zusammenfassung nennt die Anmeldefrist, aber
  nicht den Termin des Fachtags. Auch dies ist eine Spec-Abweichung: `deadlines`
  muss sowohl Anmeldefrist als auch Veranstaltungstermin enthalten.

Zum damaligen Prüfdatum stand die manuelle Bewertung von Zusammenfassung, Titel,
Beschreibung und Evidenz noch aus. Spätere Befunde stehen im
[manuellen Prüfbericht für Release 1.0](../quality-reports/manuelle-llm-qualitaetspruefung-release-1.0.md).

### Nachbesserung und Prüfstand (8. Oktober 2026)

Die Prompts enthalten jetzt konkrete Gegenbeispiele für die beiden fachlichen
Abweichungen: Ein persönliches freiwilliges Buchungsangebot erzeugt eine Aufgabe,
keinen schon vereinbarten Kalendertermin; Anmeldefrist und Veranstaltungstermin
müssen beide in `deadlines` erscheinen. Die bisherigen Korpuserwartungen bleiben
unverändert. Automatische Tests prüfen Schema und Vollständigkeit der neuen
Promptbeispiele; das ersetzt keine Prüfung tatsächlicher Modellantworten.

Ein neuer Evaluationsversuch mit maximal 100 Aufrufen wurde durchgeführt.
Der [Rohbericht](../quality-reports/evaluation-2026-10-08.json) enthält
17 versuchte Fälle mit jeweils `LlmProviderResponseInvalid` und keine
verwertbaren Modellantworten. Ein separater schreibfreier Zugriffstest ergab
`RetryableError` mit Ursache `ConnectError`, ohne HTTP-Status. Der Versuch belegt
somit keine Modellqualität und keine Ablehnung des API-Schlüssels durch den Dienst.
`complete: true` bedeutet nur, dass alle Korpusfälle versucht wurden;
`passed: false` bleibt die maßgebliche Abnahmebewertung. Nullwerte bei Tokens
und Kosten sind fehlende Verbrauchsmeldungen, keine Abrechnungsbestätigung.

Nach wiederhergestelltem OpenRouter-Zugang denselben Korpus erneut ausführen und
Zusammenfassungen, Titel, Beschreibungen und Evidenz anhand der Rohantworten
manuell prüfen. Ohne solche Antworten bleibt diese manuelle Abnahme offen.

Die damalige lokale Windows-Prüfung bestand mit **892 Tests**, **6.565/6.565 Statements**
und **2.034/2.034 Branches**, Exit-Code 0. Ausgeführt mit Python 3.12.14 und
vorhandenen Projektpaketen; die alte virtuelle Umgebung wurde nicht verändert.
Docker war für diesen damaligen Lauf nicht verfügbar; die GitHub-CLI war nicht angemeldet. Die
damals vorhandenen Linux-/Container-CI-Prüfungen mussten noch für den endgültigen Commit
erfolgreich ausgeführt werden. Kalender und Todoist wurden nicht beschrieben.

Dieser Bericht vom 8. Oktober beschreibt nicht die heutige Plattformverfügbarkeit
oder Abnahme. Die spätere lokale Facelift-Prüfung unter Windows, WSL und Docker
steht in [Release 3.3](Release-3.3.md); reale Modellqualität bleibt separat zu prüfen.

Die Telegram-Korrekturen bewahren Rückfragesperren bei unklarem Versand und nach
Neustart. Zurückgehaltene Relevanzfragen pausieren nur ihre eigene Mail. Diese
Mails bleiben unvollständig und werden nicht vorschnell als abgeschlossene UIDs
verbucht; bei späteren Abrufen verbrauchen sie kein Verarbeitungskontingent.
Gesperrte Restverzeichnisse der Testbereinigung verhindern keinen erfolgreichen
Testabschluss mehr.

**Deployment:** Geänderte Prompts ändern den Konfigurationsfingerprint. Bereits
angefangene Mails mit altem Fingerprint benötigen die ursprüngliche Konfiguration
zur Fortsetzung oder eine ausdrücklich gewählte Neuverarbeitung.
Der Sicherheitsmechanismus wird durch dieses Update nicht abgeschwächt.
