# Mailhelp

<p align="center">
  <img src="src/mailhelp/assets/logo.png" alt="Mailhelp" width="280">
</p>

Mailhelp analysiert E-Mails und erstellt überprüfbare Vorschläge für Aufgaben und
Termine. Die Freigabe erfolgt über Telegram oder die authentifizierte Weboberfläche.
Erst eine ausdrückliche Bestätigung der jeweiligen Vorschlagsversion erlaubt das
Schreiben in den Kalender oder die Aufgabenliste.

Die Anwendung läuft lokal unter Windows 11 oder als Docker-Dienst unter Linux.
Für die KI-Auswertung verwendet sie OpenRouter; ein experimenteller Betrieb mit
einem lokalen Ollama-Server ist ebenfalls verfügbar.

**Version:** 8.7.16 · **Python:** 3.12.x · **Lizenz:** MIT

Version 8.7.16: 8.7.15 läuft auf der Betreiber-Testinstanz `kunde` (weiter im Ersteinrichtungsmodus); Produktion und Demo bleiben bei 8.5.4.

Version 8.7.15: Kunden übernehmen eigene Postfach-, Benachrichtigungs- und Zielentwürfe selbst („Entwurf übernehmen“ auf der Postfachseite). Fehlt eine Prüfung einer Verbindung, startet die Vorschau sie direkt und nur lesend. Reine Postfachregeln wie Ruhezeiten oder Signatur brauchen keine Diagnose mehr. Damit ist der Plan 8.7 abgeschlossen; manuelle Schritte auf `kunde` entfallen, eine Kundenfreischaltung gibt es weiterhin nicht.

Version 8.7.14: Der Lasttest mit gehaltener Speichersperre hat auf GitHub-Runnern eine eigene Grenze (Median unter
1000 ms, höchstens 2000 ms). Lokal gilt weiter Median unter 100 ms und höchstens 300 ms.

Version 8.7.13: Die Linux-Browsersuite hängt nicht mehr – das Aufräumen nach einem Test wartet nie unbegrenzt
auf einen stummen Browser, asynchrone Wartebedingungen warten wirklich, und der CI-Schritt endet nach höchstens
45 Minuten. Keine Änderung an der Anwendung selbst.

Version 8.7.12: CI auf Linux – statische Web-Dateien haben auf jedem System dieselben Bytes und damit
dieselben Cache-Schlüssel; die Browsertests laufen unabhängig von der Systemsprache auf Deutsch, und die
Linux-Browsersuite rechnet mit Roboto wie Android-Geräte.

Version 8.7.11: Prüfstabilität – Zustandsdateien, Prüfberichte, Demo-Start und Demo-Export überstehen
unter Windows kurz gesperrte Dateien; die Live-Suche misst ihre Antwortzeit im Browser, und CI meldet
fehlgeschlagene Tests als öffentlich lesbare Annotationen. Der Rest von AP6 ist auf Wunsch des Betreibers zurückgestellt.

Version 8.7.10: Die Kundeninstanz `kunde` läuft mit 8.7.9; die Abnahmepunkte 15, 17, 19 und 20 sind
automatisiert bestanden. Die übrige Abnahme folgt nach der Ersteinrichtung durch den Betreiber.

Version 8.7.9: `mailhelp --check-instance` zeigt dem Betreiber am Host, welche Einrichtungsschritte einer
Kundeninstanz noch fehlen; zwei Instanzen bleiben nachweislich getrennt.

Version 8.7.8: In einer Kundeninstanz zeigen Hilfe und Hilfschat nur die für Kunden bestimmten
Abschnitte; Betriebs-, Server- und Kostenkapitel bleiben dem Betreiber vorbehalten.

Version 8.7.7: In einer Kundeninstanz stehen Tätigkeitsberichte zur Verfügung, ihre Schätzung und die
Nachanalyse sprechen nur von Punkten; Notion-Datenquelle und -Zuordnung sind für Kunden freigegeben.

Version 8.7.6: In einer Kundeninstanz zeigen Navigation und Seiten nur noch, was Kunden nutzen
dürfen; „Einstellungen“ führt Kunden zu einer Übersicht ihrer Bereiche. Die Eingabetaste im Lernformular
zeigt die Schätzung.

Version 8.7.5: Betrieb – die Kundeninstanz `kunde` läuft mit 8.7.4 und einer aus den
Produktionslogs hergeleiteten Preisannahme für Lernläufe (1,2 USD je Million Tokens); die nächsten
Arbeitspakete bis zur Abnahme stehen in [Lernen in Punkten](docs/Planung-8.7-Lernen.md) §8.

Version 8.7.4: Lernen in Punkten. In einer Kundeninstanz wählt man für „Aus dem Postfach lernen“
eine Punktegrenze statt eines USD-Budgets und sieht Schätzung, Reservierung und Verbrauch nur in
Punkten; die Preisannahme legt der Betreiber in `operator.yaml` fest (`learning_usd_per_million_tokens`).
Die Lernseiten sind damit für Kundensitzungen freigegeben. Selbst betriebene Instanzen bleiben unverändert.
Noch keine Kundenfreischaltung.

Version 8.7.3: Betrieb – eigene Kundeninstanz `kunde.inboxstride.de` für die Abnahme des
Kundenmodus eingerichtet (Testinstanz, keine Kundenfreischaltung).

Version 8.7.2: `mailhelp --set-valuation` funktioniert schon vor der Ersteinrichtung. Neuer Plan für
Lernen in Punkten und die Kundeninstanz `kunde` ([Planung](docs/Planung-8.7-Lernen.md)).

Version 8.7.1: Grundlagen für den Kundenmodus. Der KI-Verbrauch wird in Punkten erfasst und unter
„Verbrauch“ angezeigt (Bewertungsstand am Host mit `mailhelp --set-valuation`). Websitzungen können
Rollen tragen; Betreiberzugang gibt es nur über `mailhelp --pair --operator`. Noch keine Kundenfreischaltung.

Version 8.6.3: Die Vollprüfung besteht auch in GitHub Actions unter Linux und Windows wieder.

Version 8.6.2: Die Projektwebsite wird mit den aktuellen GitHub-Pages-Actions veröffentlicht.

Version 8.6.1: Die GitHub-Workflows laufen wieder auf Ubuntu 26.04 und folgen dem Python-3.12-Kanal;
die Container bauen auf Python 3.12.16.

Version 8.5.4: Nach einer Konfigurationsänderung wird eine aufgegebene Mail genau einmal neu versucht
statt bei jeder Wiederaufnahme erneut geholt.

Version 8.5.3: Eine aufgegebene Mail wird nicht mehr bei jedem Abruf erneut geholt und abgebrochen;
„Erneut versuchen“ in der Fehlerliste nimmt sie weiterhin auf.

Version 8.5.2 dokumentiert das Serverupdate auf 8.5.1.

Version 8.5.1: Die Einstellungen sind nach Aufgaben in sechs Bereiche gegliedert. Mehrere Werte eines
Abschnitts lassen sich gemeinsam prüfen und übernehmen; jedes Feld zeigt seine Wirkung und ob es vom
Standard abweicht. Selten benötigte Werte stehen unter „Erweitert“.

Version 8.4.3: Die Einrichtung nennt vor dem Übernehmen, wenn eine geänderte Verbindung noch geprüft
werden muss, und bietet „Verbindungen prüfen“ direkt an. Planung 8.5 beschreibt die Überarbeitung der
Einstellungen.

Version 8.4.2: Bugfix für die Bilderkennung – Smartphone-JPEGs im MPO-Format (z. B.
iPhone-/Android-HDR-Fotos mit Gain-Map) werden nicht mehr als unlesbar übersprungen,
sondern sauber dekodiert und per Vision-OCR ausgelesen.

Version 8.4.1: Automatische Erinnerungen für neue zeitgebundene Kalendereinträge je
Zielprofil (Standard: 5 Minuten vor Beginn, 0–1440 Minuten, optional deaktivierbar;
Google Kalender, Outlook/Microsoft 365 und CalDAV/iCloud), gemeinsame Vorschau in Web
und Telegram (DE/EN) sowie Nachleseprüfung beim Kalenderanbieter.

Version 8.3.3: Serverhandbuch, Betriebsnachweis und Entwicklungsregeln dokumentieren das
verbindliche Aktualisieren aller installierten Host-Programme und Systempakete bei jedem
Server-Deployment sowie den verifizierten Stand `8.3.2-86dcfc5` und das Host-Update auf
Kernel `7.0.0-44-generic`.

Version 8.3.2: In konfigurierten Instanzen hat die eingestellte Sprache (`language` in
`config.yaml`) Vorrang vor dem `Accept-Language`-Header des Browsers; beim Speichern von
`language` in den Web-Einstellungen wird das Browser-Cookie `mailhelp_lang` direkt mit
aktualisiert. In der öffentlichen Demo bleibt die automatische Browser-Spracherkennung aktiv.

Version 8.3.1: Vollständige Bereinigung der englischen und deutschen Sprachausgabe nach
Live-Prüfung auf Produktiv- und Demo-Server: Seitentitel, Web-Passwort, Einrichtung,
Zugangsdaten, Status-Dienstnamen, Konsistenzhinweise, Entscheidungsbegründungen,
Vorschlagsabgleich, Auswertungslabels, mobile Tabellen-Labels und englische Dokumentation
sind konsistent übersetzt; auf `/mail/<id>` erscheint statt `pending_confirmation` das
lesbare Statuslabel ([Planung 8.3](docs/Planung-8.3.md)).

Arbeitsstand 8.2.1: Geführtes 3-Schritte-Self-Service-Onboarding (`/onboarding`) mit
Anbietererkennung, Zielauswahl, kuratierten Starter-Themenprofilen und risikofreiem
Probelauf im Testmodus vor der ausdrücklichen Aktivierung. Gehostete Inboxstride-Instanzen
können neben Google Kalender (8.0) und Postfach-OAuth2 (8.1) auch Microsoft-Ziele
(Outlook-Kalender und Microsoft To Do) sowie Notion über den zentralen Anmeldedienst
verbinden (`targets.microsoft_connection`, `targets.notion_connection`).

Arbeitsstand 8.1.1: Anbietervorlagen vereinfachen die Postfacheinrichtung; Gmail- und
Microsoft-Postfachzugänge verwenden getrenntes OAuth2 mit lesender Ordnerprüfung.
Die Anbieterregistrierungen sind vor Produktivfreigabe noch einzurichten.
Terminantworten dürfen ein fehlendes Datum zu einer bekannten Uhrzeit ergänzen;
pausierte Rückfragen lassen sich gezielt vorprüfen und wieder aufnehmen.
Die Vorlagen berücksichtigen das iCloud-Benutzernamensformat. Postfachwarnungen
führen direkt zur passenden Wiederverbindung; wiederholte Übernahmen prüfen auch
nach lokalem Speichern den Konfigurationsstand. UTC-Zeitangaben werden beim
Schutz bekannter Termindaten in der eingestellten Zeitzone verglichen.
Der Stand aus 8.0 mit zentralem Google-Kalenderzugang ist enthalten. Prüfungen und
Freigabegrenzen: [8.0](docs/Release-8.0.md), [8.1](docs/Release-8.1.md), [8.2](docs/Release-8.2.md).

7.9.9 behebt, dass „Verbindung übernehmen“ nach der Google-Anmeldung scheiterte, und aktiviert eine neue Verbindung erst, wenn das Zielprofil gespeichert ist. 7.9.8 behebt, dass „Weiter zu Google“ beim Verbinden über Inboxstride ohne Wirkung blieb. 7.9.7 nimmt die Quellen der Landingpage `inboxstride.de` unter `landing/` ins Repository auf; ein Test baut die ausgelieferte Seite daraus Byte für Byte nach. 7.9.6 nimmt den zentralen Anmeldedienst unter `auth.inboxstride.de` in Betrieb und bindet die Produktion an; bis zur Pilotanmeldung nutzt sie weiter ihren eigenen Google-Zugang. Der Server wird täglich nach Dropbox gesichert. 7.9.5 ergänzt die Verwaltung gehosteter Google-Verbindungen: **Anderen Kalender wählen** wechselt den Kalender mit dem vorhandenen Zugang ohne neue Google-Anmeldung, und **Verbindung trennen** beendet die Tokenausgabe sofort, ohne Termine zu löschen oder die Google-Freigabe zu widerrufen. Der zentrale Anmeldedienst erhält ein eigenes schlankes Docker-Image. 7.9.4 führt die Vorbereitung von 8.0 fort: Gehostete Instanzen können den Google Kalender mit „Mit Google verbinden“ über den zentralen Inboxstride-Anmeldedienst verbinden, ohne Client-Daten oder Tokens einzutragen; der Dienst hat dafür einen öffentlichen Callback und eine interne mTLS-Schnittstelle mit eigener CA. Im eigenen Betrieb bleibt alles wie bisher. 7.9.3 bereitet Planung 8.0 vor: Die neue Komponente `inboxstride_auth` enthält Zustandsmodell, verschlüsselten Geheimnisspeicher und den geprüften Anmeldeablauf eines zentralen Google-Anmeldedienstes. Sie ist noch nicht in Betrieb; die Mailhelp-Anwendung verhält sich unverändert.

7.9 ist mit 7.9.2 abgeschlossen: Lehnt ein verbundener Dienst die Anmeldung ab, etwa bei einer abgelaufenen Google-Freigabe, steht über Offen und Mails ein dauerhafter Hinweis „Verbindungsprobleme“ mit Auswirkung und Link „Verbindung prüfen“, bis der Dienst wieder erreichbar ist. Mailhelp prüft die Verbindungen dazu alle 15 Minuten rein lesend. 7.9.1 ergänzt den Einwahllink eines bereits eingetragenen Online-Termins: Liefert eine spätere Mail den Konferenzlink, bietet Mailhelp „Bestehenden Termin aktualisieren: Videolink ergänzen“ an statt den Vorschlag als Duplikat abzuschließen. Erst die Bestätigung schreibt den Link genau einmal in den vorhandenen Termin; Titel, Zeiten und eigene Notizen bleiben erhalten. Ein anderer vorhandener Konferenzlink wird nur nach ausdrücklicher Auswahl ersetzt, und ältere Duplikate mit Link lassen sich mit **Mit Kalender erneut abgleichen** neu bewerten.

7.8 ist mit 7.8.2 abgeschlossen: Die öffentliche Demo nutzt die nativen Einstiege `/de/` und `/en/` und wurde auf Englisch vollständig über HTTPS geprüft. 7.8.1 ergänzt native deutsche und englische Einstiege (`/de/`, `/en/`), einen vollständig englisch vorverarbeiteten Demo-Bestand, eine generationsgebundene Demo-Zuordnung und sprachabhängige Hilfe, PWA- und CLI-Texte. Die Oberfläche lässt sich mit `--language en` auch beim frühen CLI-Aufruf auf Englisch wählen. Ein Sprachwechsel behält laufende Demo-Entscheidungen; ein bestätigter Neustart lädt den gewünschten Beispielsatz.

7.7 ist mit 7.7.6 abgeschlossen; die Bedienung beschreibt Absender-Regeln und Vorfilter im Abschnitt „Absender-Regeln und Vorfilter“. 7.7.1 legt die Grundlage für Vorfilter-Regeln und VIP-Absender (Planung 7.7): Regeln für Adressen, Domains, Muster wie `no-reply@*` und Betreffe sowie Verteiler-Kopfzeilen, ausgewertet ohne Sprachmodell. Seit 7.7.2 wirken sie in der Verarbeitung: VIP-Absender sparen den Relevanz-Aufruf, Sperrregeln sortieren ohne jeden KI-Aufruf aus; Seit 7.7.3 verwaltet die Seite „Absender-Regeln“ alle Regeln mit Trefferzahlen und Vorschau; an der Mailseite lassen sich Domains ignorieren und Absender als VIP einstufen, und in Telegram ignoriert „🚫 Absender immer ignorieren“ einen Absender direkt aus der Relevanzrückfrage – mit „Rückgängig“. Seit 7.7.4 lassen sich Newsletter und automatische Systemmails anhand ihrer Kopfzeilen vorfiltern; ein Probelauf zeigt vorher, was aussortiert würde, und Verteiler wie der Elternbrief der Schule lassen sich ausnehmen. Seit 7.7.5 schlägt Lernen → Vorschläge neue Regeln aus deinen Entscheidungen vor, und die Auswertung zeigt, wie viele Relevanzprüfungen der Vorfilter gespart hat.

7.6.1 macht die Demo klärungsfrei: Alle zehn Vorschläge der Beispielmails sind sofort bestätigbar, keine Karte stellt eine Rückfrage. So lässt sich der ganze Stapel in einem Zug entscheiden. Seit 7.6.2 bestätigt `1` und verwirft `2` den ausgewählten Vorgang, danach ist die nächste Karte ausgewählt; die Demo nennt die Tasten und bietet nach der letzten Karte einen Neustart an.

7.5.5 integriert den vollständigen Nachtrag zu 7.4. Datumsbereiche ohne Jahr folgen derselben Mailkontext-Regel wie Einzeltage, einschließlich Jahreswechsel. Bei fehlender Enduhrzeit bleibt der letzte Kalendertag auch über Klärung und Neustart erhalten. Widersprüchliche Angaben führen zu Rückfragen.

7.5.1 beginnt die englische Oberfläche: Navigation und Statusbezeichnungen lassen sich über einen Link in der Navigation oder die Einstellung `language` auf Englisch umstellen; weitere Bereiche folgen in den nächsten Patches. Seit 7.5.4 sind die offenen Entscheidungen mit allen Aktionen sowie die Telegram-Quittungen und -Meldungen zweisprachig.

7.4.1 erkennt mehrtägige Termine: Datumsbereiche wie „Donnerstag 07. bis Freitag 08. Januar 2027“ oder `07./08.01.2027` werden mit Beginn- und Endzeit über alle Tage eingetragen, ohne Rückfrage nach dem Datum.

7.3 macht fehlgeschlagene Mails direkt bedienbar: Die Fehlerliste nennt Ursache, Stufe und Versuche, „Erneut versuchen“ und „Ignorieren“ wirken ohne Umweg, und ein kopierbarer Fehlerbericht steht oben auf der Mailseite und als Dialog in der Liste; „Alle erneut versuchen“ und „Alle ignorieren“ wirken nach einer Bestätigung auf die ganze Liste.

7.2.3 bis 7.2.5 bringen Notion als Aufgabenziel, mit festem Token oder Anmeldung über „Notion verbinden“: Bestätigte Aufgaben werden als Seiten in einer Notion-Datenquelle angelegt (Datenquelle und Eigenschaften seit 7.2.4 unter Zielprofile auswählbar). 7.2.2 ergänzte die Auswahl der Google-Tasks-Liste in der Einrichtung und je Zielprofil. Vorschau und Telegram zeigen vor der Freigabe, dass Google Tasks das Datum übernimmt und die genaue Frist im Text steht.

Der Demo-Modus (`mailhelp --demo`) zeigt Mailhelp mit 30 vorbereiteten Beispielmails: „Demo starten“ öffnet für zwei Stunden eine eigene Kopie in der normalen Oberfläche. Bestätigungen werden nur in der Demo angelegt, alle Vorschläge sind ohne Rückfrage entscheidbar, und „Demo neu starten“ setzt die eigene Kopie zurück. Einrichtung, Konten und KI-Funktionen sind gesperrt.

Alle Änderungen früherer Versionen stehen im [CHANGELOG](CHANGELOG.md).

## Funktionen

- **Mehrere Postfächer:** IMAP-Abruf mit getrennten Kontoidentitäten und Wiederaufnahme
  gespeicherter Verarbeitungsschritte nach einem Neustart. Neue Postfächer werden mit Server,
  Ordnern und Zugangsdaten gemeinsam geprüft und ohne Dienstneustart aktiviert.
- **Gezielte Analyse:** Themen, ausgeschlossene Themen und Absenderfilter bestimmen, welche
  Nachrichten verarbeitet werden. Dokumente und Bildanhänge können einbezogen werden.
- **Aufgaben und Termine:** Vorschläge enthalten Belege und Rückfragen bei fehlenden oder
  widersprüchlichen Angaben. Der Abgleich berücksichtigt vorhandene Einträge und offene
  Entscheidungen, um doppelte Aktionen zu vermeiden. Angelegte Einträge werden durch einen
  frischen Abruf beim Anbieter nachgeprüft.
- **Einstellungen je Postfach:** Eigene Zielprofile, Themen, Signaturen, Ruhezeiten,
  Benachrichtigungen, Termindauern und Aufbewahrungsregeln mit globaler Vererbung.
- **Telegram und Web-App:** Vorschläge prüfen, klären, bearbeiten, bestätigen oder verwerfen,
  auf dem Telefon auch per Wischgeste. Die installierbare Web-App funktioniert auch ohne Telegram
  und bietet Verlauf, Auswertung, Lernen, Einstellungssuche und einen Hilfschat.
- **IServ-Elternbriefe:** Briefe aus dem IServ-Elternbriefmodul werden wie Mails verarbeitet,
  einschließlich Anhängen, und gelten immer als relevant.
- **Optional:** Antwortentwürfe im Ursprungspostfach, Postfach-Briefings, Web-Push und
  Tätigkeitsberichte mit XLSX-Export.

Antwortentwürfe werden nur im IMAP-Entwurfsordner abgelegt. Mailhelp versendet keine E-Mails.

### Unterstützte Dienste

| Bereich | Dienste |
| --- | --- |
| E-Mail | IMAP-Postfächer |
| Schule | IServ-Elternbriefe (Lesezugriff über die Weboberfläche, keine offizielle API) |
| Kalender | Google Kalender, Outlook / Microsoft 365, CalDAV |
| Aufgaben | Todoist, Microsoft To Do, Google Tasks, Notion, CalDAV-Aufgabenlisten, Apple Erinnerungen über iCloud-CalDAV |
| KI-Auswertung | OpenRouter; experimentell Ollama |
| Bedienung | Telegram, lokale Weboberfläche und PWA |

## Schnellstart

Voraussetzungen: Python **3.12.x** oder Docker mit Compose, ein IMAP-Postfach und Zugangsdaten
für die verwendeten Dienste.

### Windows 11

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.lock
.venv\Scripts\python -m pip install --no-deps -e .
.venv\Scripts\mailhelp
```

### Linux

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/mailhelp
```

Ohne `config.yaml` startet ein geschützter Einrichtungsassistent. Das Terminal zeigt einen
Code; damit koppelt der Browser unter **http://127.0.0.1:8765** und führt durch Web-Zugang,
Postfach, KI-Anbieter, Kalender und Aufgaben. Schritt für Schritt beschreibt das die
[Ersteinrichtung](docs/Ersteinrichtung.md).

Für eine manuelle Konfiguration stattdessen `config.example.yaml` nach `config.yaml`,
`.env.example` nach `.env` und `irrelevant-senders.example.json` nach
`irrelevant-senders.json` kopieren und anpassen.

### Docker

```sh
docker compose -f compose.setup.yaml up --build
```

Den ausgegebenen Einmalcode unter `http://localhost:8765/anmelden` eingeben. Konfiguration,
Zugangsdaten, Zustände und Logs bleiben im benannten Volume `mailhelp-config`. Die
`compose.yaml` verwendet eine manuell angelegte Konfiguration; Einzelheiten stehen in
[Betrieb und Update](docs/Betrieb.md). Eine getrennte Demo-Instanz ohne Internetzugang startet
`compose.demo.yaml` (siehe dort, Abschnitt Demo-Instanz).

### Prüfen und starten

```sh
mailhelp --check --config-directory .
mailhelp --check-access --config-directory .
mailhelp --max-mails 10 --config-directory .
mailhelp --config-directory .
```

`--check` prüft die Konfiguration ohne Netzwerkzugriff, `--check-access` die Zugänge (ohne
Aufgaben oder Termine anzulegen). `--max-mails 10` begrenzt einen einzelnen Durchlauf; ohne
diese Optionen läuft Mailhelp als Dienst. Pro Datenverzeichnis läuft nur eine Instanz.

## Konfiguration

| Datei | Inhalt |
| --- | --- |
| `config.yaml` | Postfächer, Ziele, Betriebsart, Zeitzone, Limits, Benachrichtigungen und Aufbewahrung |
| `prompts.yaml` | Prompts, Modelle und LLM-Parameter für die Analyseschritte |
| `decisions_prompts.yaml` | Konfiguration der Standard-Relevanzprüfung |
| `topics.yaml` | Relevante Themen, optional auf einzelne Postfächer begrenzt |
| `irrelevant_topics.yaml` | Ausgeschlossene Themen |
| `irrelevant-senders.json` | Globale und postfachbezogene Absenderfilter |
| `.env` | Zugangsdaten, Tokens und Sitzungsschlüssel; alternativ Prozessumgebung |

[config.example.yaml](config.example.yaml) und [.env.example](.env.example) zeigen alle
Einstellungen und Geheimnisnamen. Prozessvariablen haben Vorrang vor `.env`. Fast alles lässt
sich auch in der Weboberfläche unter **Einstellungen** ändern; jede Einstellung erklärt die
[Einstellungsreferenz](docs/Web-Einstellungen.md). Mit `test_mode: true` werden Kalender- und
Aufgabenaktionen nur simuliert.

## Datenschutz und Sicherheit

Die Mailanalyse liest das Postfach, ohne Nachrichten oder Lesestatus zu ändern. Bei externen
KI-Diensten werden ausgewählte Mailinhalte an die konfigurierten Anbieter übertragen; lokale
Ausführung bedeutet daher nicht automatisch ausschließlich lokale Verarbeitung.

Zustände werden als lesbare JSON-Dateien, Ereignisse als getrennte JSONL-Logs gespeichert.
Mailzustände (Schema 9) und offene Entscheidungen bleiben über Neustarts erhalten.
Zugangsdaten werden nicht protokolliert. Die ausgelieferte `config.example.yaml` schaltet
vollständige KI-Anfrage- und Antwortlogs ausdrücklich ein; für einen Betrieb ohne diese
Inhalte `logging.llm.include_requests` und `logging.llm.include_responses` auf `false` setzen.

Externe Schreibaktionen sind an Vorschlagsversion, Ziel und ausdrückliche Freigabe gebunden;
unklare Schreibresultate werden vor einer Wiederholung abgeglichen. Webaktionen prüfen
Sitzung, CSRF-Schutz, Version und Idempotenz. Hinweise für betriebene Instanzen stehen in der
[Datenschutzerklärung](DATENSCHUTZ.md) und den [Nutzungsbedingungen](NUTZUNGSBEDINGUNGEN.md);
beide Vorlagen müssen an den jeweiligen Betrieb angepasst werden.

## Entwicklung

Automatisierte Tests verwenden synthetische Daten und simulierte externe Dienste. Die
vollständige Prüfung baut die Pakete und erzwingt **100 % Zeilen- und Branch-Abdeckung**
des eigenen Codes einschließlich der Entwicklungswerkzeuge:

```sh
python -m devtools.check full --workers 12
python -m devtools.check fast
python -m devtools.check tdd tests/unit/test_core.py
python -m pytest ui_tests -n 6 --dist worksteal --no-cov
```

`--workers` an die Zahl der Rechenkerne anpassen; ohne Angabe läuft die vollständige Prüfung
seriell. Python- und Browserprüfung nicht gleichzeitig starten, weil die Zeitmessungen sonst
unzuverlässig werden. Lint und Typprüfung:

```sh
python -m pip install -r requirements-lint.lock
python -m ruff check src tests ui_tests devtools
python -m mypy
```

mypy verlangt für jede Funktion vollständige Typangaben; Schichten, Funktionslänge und
Parameterzahl prüfen `tests/unit/test_layers.py` und `tests/unit/test_limits.py`. Die
Browsertests decken Desktop-, Mobil- und schmale Telefonansichten, große Bildschirme,
Barrierefreiheit und 100 % der JavaScript-Blöcke ab.

Entwicklungsregeln stehen in [AGENTS.md](AGENTS.md), der Aufbau in der
[Architektur](docs/Architektur.md), technische Verträge in der
[Projektspezifikation](Mailhelp-Projektspezifikation.md).

## Dokumentation

Das [Inhaltsverzeichnis](docs/README.md) führt alle aktuellen Anleitungen auf:
[Ersteinrichtung](docs/Ersteinrichtung.md) · [Konten verwalten](docs/Konten-verwalten.md) ·
[Kalender und Aufgaben verbinden](docs/Ziele-einrichten.md) · [Bedienung](docs/Bedienung.md) ·
[Fehler beheben](docs/Fehlerbehebung.md) · [Betrieb und Update](docs/Betrieb.md) ·
[Einstellungen](docs/Web-Einstellungen.md). Abgeschlossene Pläne und Release-Berichte liegen
im [Archiv](docs/archiv/). Die statische Projektwebsite liegt unter [website/](website/).

Serveränderungen müssen nach erfolgreicher Prüfung vor Abschluss der Arbeit in der
Betriebsdokumentation und den betroffenen Vorlagen nachgeführt werden; siehe
[Entwicklungsregeln](AGENTS.md). Das vollständige Serverhandbuch mit Neuaufbau,
Reparatur, Wiederherstellung und geheimnisfreien Konfigurationsvorlagen steht im
[Serverhandbuch](docs/Serverhandbuch.md) mit [Vorlagen](ops/server/README.md).

[Planung 8.1](docs/Planung-8.1.md) beschreibt die vereinfachte Postfacheinrichtung
mit Anbieterauswahl, automatischen IMAP-Einstellungen und OAuth2 für Gmail und
Microsoft-Postfächer. Zusätzlich enthält sie den Fix für blockierte Terminrückfragen
beim Ergänzen eines Datums zu einer bekannten Uhrzeit sowie die gezielte Wiederaufnahme
betroffener Vorgänge. Den aktuellen Umsetzungs- und Prüfstand dokumentiert
[Release 8.1](docs/Release-8.1.md).

## Lizenz

Mailhelp wird unter der [MIT-Lizenz](LICENSE) bereitgestellt.
