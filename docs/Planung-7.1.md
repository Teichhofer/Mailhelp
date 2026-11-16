# Mailhelp 7.1 – Eigenständiger Demo-Modus mit vorbereiteten Beispieldaten

**Zielversion:** 7.1, Umsetzung in Patchversionen ab 7.1.1

**Stand:** 15. November 2026

**Status:** Umgesetzt in 7.1.1 bis 7.1.5 (16. November 2026); Abnahme und Abweichungen in
[Release 7.1](Release-7.1.md). Ergänzung des Auftraggebers vom
16. November 2026: zusätzlich 20 nicht relevante Mails, Bestand damit 30 Mails (siehe 5.1).
Der einmalige Erzeugungslauf über OpenRouter (D2) ist freigegeben.

**Ausgangsstand:** 7.0.3; bei Umsetzung gegen den dann aktuellen Stand prüfen.

**Grundlage:** [Entwicklungsregeln](../AGENTS.md),
[Projektspezifikation](../Mailhelp-Projektspezifikation.md)

## 1. Ziel und bestätigte Vorgaben

Mailhelp erhält einen ausdrücklich beim Programmstart ausgewählten Demo-Modus.
Besucher können die normale Weboberfläche ausprobieren, ohne ein E-Mail-Postfach,
Telegram, Google Kalender oder Todoist zu verbinden. Aufgaben und Termine werden
ausschließlich innerhalb der Demo simuliert.

Zehn synthetische Mails werden **während der Entwicklung** vom Entwicklungsagenten
verfasst und anschließend durch den echten Mailhelp-Verarbeitungspfad verarbeitet.
Die dabei entstandenen Mails, Zusammenfassungen, Aufgaben, Termine und Zustände
werden als geprüfter, vorbereiteter Datenbestand mitgeliefert. Beim späteren
Demo-Start wird dieser Bestand kopiert; es findet keine erneute Analyse statt.

Die ursprünglich genannte Versionsnummer 6.1 wurde vom Auftraggeber auf **7.1**
korrigiert. Die bestehende, abgeschlossene Planung 6.1 bleibt erhalten.

| Vorgabe | Festlegung |
| :--- | :--- |
| Aktivierung | `mailhelp --demo`; gleichwertiger Alias `mailhelp -demo` |
| Normaler Start | Ohne Demo-Parameter unveränderter Produktions-/Einrichtungsablauf |
| Anmeldung | Auf „Gerät koppeln“ ersetzt **„Demo starten“** die Telegram-Code-Anforderung |
| Bestand | Zehn vorbereitete Mails mit den daraus erkannten Vorschlägen und 20 nicht relevante Mails (30 Mails) |
| Erzeugung | Synthetische Originalmails → echter Verarbeitungspfad → geprüfter Export |
| Laufzeit | Vorbereitete Daten anzeigen und lokale Demo-Entscheidungen ermöglichen |
| Externe Dienste | Kein Postfach, kein Telegram, keine echten Kalender-/Aufgaben-Schreibzugriffe |
| KI im laufenden Demo-Modus | Keine Aufrufe; auch keine kostenpflichtige Hintergrundanalyse |

„Aufgaben“ und „Todos“ bezeichnen hier dieselbe Vorschlagsart. Vorgesehen sind zehn
Mails für die gezeigten Abläufe, nicht jeweils zehn Mails, zehn Termine und zehn Aufgaben, dazu
20 nicht relevante Mails (Ergänzung vom 16. November 2026).

## 2. Befund im vorhandenen Code

- `config/models.py` und `web/setting_help.py` kennen bereits `test_mode`. Dieser
  Trockenlauf simuliert Schreibaktionen, verhindert aber ausdrücklich nicht alle
  Netzwerkzugriffe, etwa Mailabruf oder KI. Er erfüllt den Demo-Modus allein nicht.
- `web/pages.py` rendert `login_page` mit „Gerät koppeln“ und „Code per Telegram
  senden“ beziehungsweise dem Konsolenweg.
- `web/auth.py` stellt Sitzungen und CSRF-Schutz bereit. `web/factory.py` verbindet
  diese mit Oberfläche und Befehlswarteschlange.
- `processing/orchestrator.py` und `processing/mail_pipeline.py` enthalten den
  echten Ablauf mit Aufbereitung, Relevanz, Zusammenfassung und Vorschlägen.
- Anwendungscode und Zustand sind inzwischen weiter aufgeteilt. Neue Bausteine
  sollen die vorhandenen Komponenten verwenden; keine zweite Fachlogik für eine
  gesonderte Demo-Oberfläche aufbauen.

## 3. Start und Betriebsgrenze

### 3.1 Expliziter Kommandozeilenparameter

```powershell
mailhelp --demo --config-directory .\demo-runtime
mailhelp -demo --config-directory .\demo-runtime
```

Beide Schreibweisen setzen denselben Startmodus. Der Modus bleibt für die gesamte
Prozesslaufzeit fest. Er wird nicht durch eine Subdomain, fehlende Zugangsdaten,
URL-Parameter, Cookies, Umgebungsvariablen oder eine Web-Einstellung aktiviert.

Der Demo-Start funktioniert mit einem leeren, eigenen Laufzeitverzeichnis und ohne
Einrichtung externer Dienste. Er überspringt die normale Postfach-/Telegram-/Ziel-
Einrichtung und startet unmittelbar den Demo-Webzugang. Ein interner Web-Schlüssel
wird lokal erzeugt und geschützt gespeichert; Besucher müssen keinen Schlüssel
angeben. Prompts, Modelle und LLM-Parameter verbleiben in `prompts.yaml`, Themen in
`topics.yaml`; normale Anwendungseinstellungen verbleiben in `config.yaml`.

Der Demo-Modus verwendet mitgelieferte synthetische Profile, Themen und Ziele.
Produktive Konfiguration, persönliche Informationen oder Zugangsdaten werden nicht
in die Demo übernommen. Bei einem Verzeichnis mit Produktionszustand bricht der
Demo-Start mit einer verständlichen Meldung ab. Umgekehrt darf der normale Modus
keinen Demo-Zustand als Produktionszustand öffnen.

### 3.2 Getrennte Instanz

Für einen öffentlichen Betrieb ist ein zweiter Docker-Container mit eigener
Subdomain vorgesehen. Dessen Startbefehl enthält ausdrücklich `--demo` oder `-demo`.
Die konkreten Compose-Argumente werden am vorhandenen Image-Einstiegspunkt geprüft.

Eigene Volumes, Daten- und Logverzeichnisse, eigener Web-Schlüssel und eigener
interner Port; keine Produktionsvolumes oder Produktionsgeheimnisse einbinden.
Cookies bleiben auf den jeweiligen Host beschränkt. HTTPS wird über den bestehenden
Reverse Proxy eingerichtet. Die konkrete Demo-Subdomain wird vor der Bereitstellung
festgelegt; das Schreiben dieses Plans verändert keine Serverkonfiguration.

## 4. Besucherablauf

1. Besucher öffnet die Demo-Subdomain und sieht die vertraute Anmeldeseite mit
   Überschrift **„Gerät koppeln“**, einem kurzen Demo-Hinweis und **„Demo starten“**.
2. Es gibt dort weder Telegram-Code-Anforderung noch Codeeingabe, Konsolenanleitung,
   Passwortpflicht oder Aufforderung, ein echtes Postfach zu verbinden.
3. Ein Klick sendet einen geschützten POST, erzeugt eine reguläre Demo-Websitzung
   und kopiert den geprüften Datenbestand in einen eigenen Besucherbereich.
4. Erst nach vollständig erfolgreicher Initialisierung öffnet sich **„Offen“**.
   In der Mailübersicht sind genau die 30 vorbereiteten Originalmails vorhanden.
5. Ein dauerhafter Hinweis lautet sinngemäß: **„Demo – Beispieldaten. Es werden
   keine echten Termine oder Aufgaben angelegt.“** Ergebnisse benennen Simulationen.
6. Eine bestehende Sitzung öffnet ihren bisherigen Demo-Bestand weiter. Doppelklick
   oder wiederholte Übertragung desselben Startauftrags erzeugen keine doppelten Mails.
7. **„Demo neu starten“** setzt nach Bestätigung nur den eigenen Besucherbereich
   zurück. Andere Besucher bleiben unberührt.

Vorbereitete JSON-Dateien und Originalmails sind eine unveränderliche Vorlage.
Sie werden nicht beim Containerstart als globaler, gemeinsam veränderbarer Bestand
angelegt. Der persönliche Bestand entsteht mit dem Klick auf „Demo starten“.

## 5. Erzeugung des mitgelieferten Bestands

### 5.1 Zehn synthetische Originalmails

Der Entwicklungsagent verfasst vollständige, synthetische `.eml`-Dateien mit
konsistenten Absendern, Empfängern, Betreffzeilen, Maildaten und Text-/HTML-Inhalten.
Adressen verwenden reservierte Beispieldomains; keine echten Personen, Postfächer,
Telefonnummern oder Dokumente verwenden.

| Nr. | Beispiel | Gezeigter Ablauf |
| :--- | :--- | :--- |
| 1 | Einladung zum Elternabend | Klarer Termin mit Datum, Uhrzeit und Ort |
| 2 | Formular für einen Ausflug zurücksenden | Aufgabe mit Frist |
| 3 | Material für einen Workshop besorgen | Aufgabe ohne feste Uhrzeit |
| 4 | Einladung mit Anmeldung und Veranstaltungstermin | Mehrere Vorschläge aus einer Mail |
| 5 | Verschobener Elternabend, Bezug auf Nr. 1 | Terminänderung und Zusammenhang |
| 6 | Erinnerung an das Formular aus Nr. 2 | Dubletten-/Zuordnungsprüfung |
| 7 | Terminmitteilung mit fehlender Uhrzeit | Rückfrage statt ungesicherter Anlage |
| 8 | Nachricht mit unklarer persönlicher Zuständigkeit | Offene Relevanzentscheidung |
| 9 | Nachricht zur Kenntnisnahme | Relevante Mail ohne Anlagebedarf |
| 10 | Unpassende Werbemail | Irrelevante Mail ohne Aufgabe oder Termin |

**Ergänzung (16. November 2026):** Dazu kommen 20 nicht relevante Mails (Werbung, Newsletter,
Automatikmeldungen, Rundschreiben ohne Bezug). Sie zeigen in der Demo, dass solche Mails
verarbeitet, als irrelevant erkannt und ohne Vorschlag abgelegt werden. Der Bestand umfasst damit
30 Mails; Manifest und Prüfungen verlangen genau 30 eindeutige Mail-Identitäten.

Die Tabelle ist das Abnahmeziel für den Beispielsatz. Entstehen diese Fälle im echten
Pfad nicht, werden die synthetischen Originalmails angepasst und neu verarbeitet.
Fertige Vorschläge werden nicht nachträglich passend von Hand geschrieben.

### 5.2 Echter Verarbeitungslauf während der Entwicklung

Ein Entwicklungswerkzeug speist die Originalmails an der bestehenden Eingangsgrenze
als `FetchedMail` ein. Nur der Postfachtransport wird durch einen lokalen Leser
ersetzt. MIME-Aufbereitung, Filter, Relevanz, Analyse, Vorschlagserzeugung,
Validierung, Dublettenprüfung und Persistenz verwenden den normalen Anwendungspfad.

Für die Erstellung werden die tatsächlichen Analysekomponenten mit den dafür
konfigurierten Modellen verwendet. Modellzugangsdaten bleiben außerhalb des Codes;
erforderliche KI-Aufrufe sind ein ausdrücklich gestarteter Entwicklungslauf und
kein Bestandteil automatisierter Tests oder des späteren Demo-Betriebs. Telegram
und echte Schreibanbieter werden auch bei diesem Lauf nicht verbunden. Synthetische
Kalender-/Aufgabenadapter liefern erforderlichen Vergleichsbestand.

Danach prüft der Agent die Ergebnisse fachlich: Belege passen zur Mail, Datumswerte
und Zuständigkeit stimmen, Änderungen sind zugeordnet, Fristen und Rückfragen sind
verständlich. Fehler werden an Eingangsdaten oder am normalen Verarbeitungspfad
behoben; Fehlerkorrekturen im Anwendungscode erhalten Regressionstests.

### 5.3 Export und Nachweis

Vorgeschlagener Paketpfad: `src/mailhelp/defaults/demo/standard-v1/` mit:

- 30 Originalmails und deren normal verarbeiteten, lesbaren JSON-Zuständen;
- den zugehörigen Zusammenfassungen, Vorschlägen, Historien und synthetischen Zielen;
- einem Manifest mit Datensatz-/Schema-Version, Referenzzeit und Zeitzone,
  Eingangs- und Dateiprüfsummen, Quellcommit sowie Prompt-/Themen-/Modellständen;
- vorbereiteten Antwortzweigen für die ausdrücklich unterstützten Rückfragen.

Der Export enthält keine Websitzungen, CSRF-Werte, Schlüssel, Tokens, echten
Anbieter-IDs, lokalen Benutzerpfade oder Produktionslogs. Ereignislogs bleiben
separate JSONL-Dateien; vollständige LLM-Inhalte werden nicht pauschal mitgeliefert.

Schema, Referenzen, Prüfsummen und genau 30 eindeutige Mail-Identitäten werden beim
Build und beim Laden geprüft. Fehlende oder beschädigte Daten führen zu einer
verständlichen Fehlermeldung; es gibt keinen Rückfall auf echte Verarbeitung.

## 6. Verhalten während der Demo

### 6.1 Vorbereitete Daten, normale Oberfläche

Mails, Zusammenfassungen und Vorschläge stammen ausschließlich aus dem geprüften
Paket. Ein Klick auf „Demo starten“ löst weder eine erneute Mailverarbeitung noch
Modellaufrufe aus. Auch zeitgesteuerte Hintergrundaufgaben dürfen das nicht tun.

Die normalen Seiten und Aktionswege werden wiederverwendet. Bestätigen, Verwerfen,
„Schon erledigt“ und angebotene Rücknahmen ändern nur den lokalen Besucherbestand.
Ein simuliertes Anlegen erscheint als **„In der Demo angelegt“** mit einem lokalen
Demo-Ziel. Es entstehen keine echten Termine oder Todoist-Aufgaben.

Auch Demo-Aktionen benötigen Sitzung, CSRF, genaue Vorschlagsversion und
Idempotenzschlüssel. Die Sitzung wird bei Ausführung erneut geprüft. Wiederholungen,
veraltete Versionen, Abmeldung und Neustarts bleiben abgesichert. Die normale
Bestätigungspflicht für echte Schreibzugriffe wird nicht verändert.

### 6.2 Rückfragen und weitere KI-Funktionen

Unterstützte Rückfragen bieten vorab definierte Beispielantworten. Deren Folgezustände
werden schon bei der Datensatzerstellung durch den echten Mailhelp-Antwort-/Analysepfad
erzeugt und geprüft. Zur Laufzeit wird nur der passende vorbereitete Folgezustand
in den aktuellen Besucherbestand übernommen; lokale Versionen, Historien und bereits
erfolgte Entscheidungen werden dabei nicht überschrieben.

Freie KI-Nachfragen, neue Mailanalysen und Regel-Lernläufe sind nicht ausführbar.
Die Oberfläche erklärt die Demo-Grenze, statt einen echten Aufruf zu versuchen oder
ein frei erfundenes Analyseergebnis anzuzeigen. Reine lokale Änderungen bleiben
möglich, soweit sie keine erneute Analyse oder externe Verbindung benötigen.

Einrichtungs-, OAuth-, Postfach-, Telegram-, Push-, SMTP- und Exportversand-Aktionen
sind serverseitig gesperrt. Verbindungs- und Zugangsdatenformulare werden in der Demo
nicht angeboten. Ein direkter API-Aufruf darf diese Sperre nicht umgehen.

### 6.3 Zeitdarstellung

Der Beispielsatz besitzt eine feste, sichtbar ausgewiesene Referenzzeit. Die fachliche
Demozeit beginnt dort und läuft mit der Besuchsdauer weiter. Dadurch bleiben
Termine und Fristen vorführbar, ohne vorbereitete Texte oder Datumswerte bei jedem
Start neu zu analysieren. Rücknahmefristen laufen tatsächlich ab.

Sitzungsablauf, Startlimits und Sicherheitsprotokolle verwenden die echte Serverzeit.
Die Demozeit darf keine Sicherheitsfrist verlängern. Zeitzone und Referenzzeit stehen
im Manifest; eine Umstellung verändert keine gemeinsam genutzte Vorlage.

## 7. Isolation und Lebensdauer

Jede Demo-Sitzung erhält einen eigenen zufälligen Besucherbereich. Diese Zuordnung
wird ausschließlich aus der serverseitig geprüften Sitzung ermittelt, niemals aus
einem frei wählbaren Pfad, Cookie-Inhalt oder Formularfeld. Lesen, Suche, Historie,
simulierte Ziele, Warteschlange und Hintergrundarbeit verwenden denselben Bereich.

Initialisierung ist atomar: entweder vollständig validierter Bestand und Sitzung
oder kein nutzbarer Besucherbereich. Ein Prozessabbruch hinterlässt keine halbe Demo.
Session-Fixation und parallele Startanfragen sind durch vorhandene Schutzmechanismen
beziehungsweise einen einmaligen Startauftrag mit Idempotenz abgesichert.

Geplante Vorgaben: zwei Stunden Sitzungsdauer, höchstens 50 aktive Besucherbereiche
und begrenzte Starts pro Client sowie insgesamt. Die konkreten Limits werden in
`config.yaml` dokumentiert. Abgelaufene Bereiche werden kontrolliert bereinigt;
Grenzerreichung liefert eine verständliche Meldung und löscht keine aktive fremde Demo.

## 8. Verbindliche Grenzen externer Zugriffe

Die Demo-Laufzeit erstellt keine IMAP-, Telegram-, Modell- oder echten Schreibclients
und startet deren Worker nicht. Eine zusätzliche Modusprüfung an den gemeinsamen
Ausführungsgrenzen lehnt versehentliche Aufrufe echter Anbieter ab. Vorhandene
Umgebungs-Zugangsdaten dürfen daran nichts ändern.

Der Demo-Container wird zusätzlich mit gesperrtem ausgehendem Internetzugriff
betrieben; eingehende HTTP-Verbindungen über den Reverse Proxy bleiben möglich.
Die Netzsperre ist eine zweite Schutzschicht. Das Programm muss bereits ohne sie
alle fachlich externen Aufrufe verhindern. Der Browser darf die eigene Webinstanz
nutzen, erhält aber keine Aufforderung zu externen Verbindungen oder Push-Aktivierung.

## 9. Umsetzung und Abnahme

| Schritt | Paket | Verbindlicher Nachweis |
| :--- | :--- | :--- |
| D1 | CLI `--demo` und `-demo`, feste Modusgrenze, isolierter Start | Beide Aliasse identisch; Start ohne Anbieter-Konfiguration; normaler Start unverändert; falsches Datenverzeichnis abgelehnt |
| D2 | Zehn Mails erstellen, echten Verarbeitungslauf und Exportwerkzeug bauen | Manifest und Pipeline-Nachweis; fachliche Prüfung der zehn Fälle; kein manuell erfundener Vorschlagsbestand |
| D3 | Geprüften Bestand paketieren und Besucherbereiche initialisieren | Genau 30 Mails; atomarer Start; Doppelklick/Retry erzeugt keine Dubletten; Neustart lädt den eigenen Bestand |
| D4 | Demo-Start auf „Gerät koppeln“, reguläre Sitzung und normaler Webzugang | Kein Code und keine Telegram-Verbindung; POST/CSRF/Idempotenz; Produktionsanmeldung unverändert |
| D5 | Lokale Anbieter, vorbereitete Rückfragen, Demo-Hinweise und Funktionsgrenzen | Bestätigen/Verwerfen/Rücknahme nur lokal; keine KI zur Laufzeit; gesperrte Wege auch per direktem POST nicht erreichbar |
| D6 | Besuchertrennung, Demozeit, Ablauf, Limits und Bereinigung | Zwei parallele Browser beeinflussen sich nicht; Sicherheitszeit echt; Reset nur eigener Bereich; abgelaufene Sitzung verhindert Befehlsausführung |
| D7 | Docker-Demobetrieb und vollständige Freigabe | Frischer Container ohne externe Secrets und ohne Internet-Egress funktioniert; normale Instanz unberührt; vollständige Tests und Dokumentation |

Patchgrenzen werden bei Umsetzung festgelegt; jeder Commit auf `main` oder `beta`
erhöht die Patchversion und aktualisiert `pyproject.toml`, `src/mailhelp/__init__.py`,
CHANGELOG und README gemäß den Entwicklungsregeln.

### Automatisierte Tests

- Echte externe Dienste werden in Tests ausschließlich simuliert; keine echten
  Modellaufrufe zur Generierung des Bestands während der Tests.
- Netzwerkfallen schlagen fehl, sobald die Demo einen externen Dienst aufzurufen
  versucht – einschließlich Hintergrundarbeit, Fehlerfall und manueller API-Aufrufe.
- Erfolg, Ablehnung, Wiederholung, Prozessabbruch, Neustart, veraltete Version,
  fehlende/abgelaufene Sitzung, falsches CSRF und fremde Besucher-ID prüfen.
- Beschädigtes Manifest, falsches Schema, fehlende Mail, doppelte Identität und
  unzulässige Pfade werden abgelehnt; Import und Bereinigung sind voneinander getrennt.
- Browserprüfung für Chromium und WebKit, Telefon und Desktop: Demo starten ohne
  Telegram, normal navigieren, wischen, simuliert bestätigen, Rückfrage beantworten,
  zurücksetzen und in zwei Browserkontexten voneinander getrennt arbeiten.
- Für Anwendungscode sind 100 % Zeilen- und 100 % Branch-Abdeckung verbindlich;
  unterschrittene Werte lassen die Prüfung scheitern. Neue Fehlerkorrekturen enthalten
  vor dem Fix scheiternde Regressionstests. JavaScript-Abdeckung bleibt vollständig.
- Vollständige Python- und Browsersuite gemäß vorhandenem Prüfablauf getrennt laufen
  lassen; Paket-/Containerprüfung einschließlich des mitgelieferten Demo-Bestands.

### Dokumentation bei Umsetzung

Projektspezifikation, README, CHANGELOG, Bedienung und Anmeldung, Ersteinrichtung,
Konfigurationsbeispiele, Docker-/Serveranleitung und Hilfeindex aktualisieren.
Ein Release-Bericht hält Datenherkunft, tatsächliche Pipeline-Verarbeitung,
Testresultate und die reale Geräteabnahme fest. Der Demo-Hinweis unterscheidet stets
eine Simulation von einer echten Anlage.

## 10. Nicht Teil dieses Auftrags

Diese Planung startet keine Container, ändert keine DNS-Einträge und verbindet keine
Dienste. Die Beispieldaten werden erst bei der Umsetzung erzeugt. Eine produktive
Telegram-freie Anmeldung, echte externe Anlagen aus der Demo und KI-Verarbeitung
während eines Demo-Besuchs sind nicht vorgesehen.
