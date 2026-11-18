# Mailhelp 7.8 – Vollständige Lokalisierung und englische Demo

**Zielversion** 7.8 mit fortlaufenden Patchversionen ab 7.8.1.

**Stand** 17. November 2026. Überarbeitet anhand des lokalen Stands 7.7.1 und der laufenden 7.7-Arbeiten.

**Status** Umgesetzt in 7.8.1 und 7.8.2, siehe [Release 7.8](Release-7.8.md).

**Grundlagen** [Entwicklungsregeln](../AGENTS.md), [Spezifikation](../Mailhelp-Projektspezifikation.md), [Architektur](Architektur.md), [Planung 7.1](Planung-7.1.md), [Planung 7.5](Planung-7.5.md), [Release 7.5](Release-7.5.md), [Planung 7.6](Planung-7.6.md), [Release 7.6](Release-7.6.md), [Planung 7.7](Planung-7.7.md).

## 1. Ergebnis für die Nutzerinnen und Nutzer

Eine Besucherin öffnet die englische Landingpage, startet eine vollständig englische Demo und
entscheidet englische Beispielvorschläge. Anmeldung, Hinweise, Mailtexte, Karten, Gesten,
Tastaturhilfe, Ergebnisse und Zurücksetzen bilden einen durchgängigen Ablauf. Eine deutsche
Besucherin erhält denselben fachlichen Ablauf auf Deutsch.

Im normalen Betrieb erscheinen die von Mailhelp erzeugten Bedienoberflächen auf Deutsch oder
Englisch. Dazu gehören Web, PWA, Benachrichtigungen, Telegram, Hilfe und die menschlich lesbaren
CLI-Ausgaben. Eigene Mailinhalte und selbst vergebene Titel behalten ihren ursprünglichen Wortlaut.

Die Abnahme umfasst fünf nachweisbare Ergebnisse.

1. Die Sprachwahl funktioniert bereits vor dem Start einer Demo und bleibt über Navigation und
   Browserneustart erhalten.
2. Für jede Sprache existieren 30 vorverarbeitete synthetische Mails. Der englische Bestand enthält
   genau 10 relevante und 20 irrelevante Mails. Die deutsche Abnahme verwendet den bestehenden
   freigegebenen Bestand. Alle erzeugten Aufgaben und Termine sind sofort bestätigungsbereit.
3. Eine laufende Sitzung behält ihre Entscheidungen. Der Wechsel zu einem anderen Beispielsatz
   erfolgt über einen ausdrücklich bestätigten Neustart dieser Demo.
4. Jede erfasste Bedienoberfläche besitzt geprüfte deutsche und englische Texte. Die englische
   Hilfe enthält tatsächlich englische Inhalte.
5. Beide Sprachfassungen funktionieren im installierten Paket und im isolierten Docker-Demobetrieb.

## 2. Ausgangsstand und konkrete Lücken

| Bereich | Vorhandener Stand | Aufgabe in 7.8 |
| --- | --- | --- |
| Sprachkern | `i18n.Locale`, `tr()`, `stored()`, `use_locale()` und regionale Sprachkennungen | Vorhandene Mechanismen verwenden und Anfragegrenzen vollständig abdecken |
| Sprachauswahl | Cookie vor `Accept-Language` vor Standard. Qualitätsgewichte werden bisher nicht ausgewertet | Auswahl einschließlich `q`-Werten und ungültigen Eingaben verbindlich festlegen |
| Web und Telegram | Navigation, Formate, offene Entscheidungen und Telegram sind teilweise lokalisiert | Verbleibende Oberflächen anhand des Codes inventarisieren und schließen |
| Demo-Einstieg | `DemoSite.PUBLIC` enthält `/sprache` bisher nicht | Sprachwechsel vor der Anmeldung nativ ermöglichen |
| Demo-Rahmen | `demo_site.py` ergänzt deutsche Hinweise teilweise nach Rückkehr aus dem Sprachkontext des inneren `WebApp` | Sprachkontext auch für Hinweise, Fehler und Neustart erhalten |
| Demo-Inhalte | `standard-v1`, 30 deutsche Mails und der klärungsfreie Ablauf aus 7.6 | Vollwertigen englischen Bestand mit demselben Qualitätsniveau ergänzen |
| Datensatzprüfung | `DemoManifest`, `verify()` und `install()` prüfen einen festen Datensatz | Beide Bestände einschließlich Metadaten, Dateimengen und Kompatibilität prüfen |
| Besucherbereiche | `VisitorEntry` speichert Bereich und Erstellungszeit. `starts` bindet Schlüssel an Sitzungen | Datensatzsprache, Revision und Generation dauerhaft zuordnen |
| Neustart | `DemoVisitors.reset()` entfernt den bisherigen Bereich vor dem erneuten Start | Austausch einschließlich Fehler- und Konkurrenzfällen konsistent machen |
| Demo-Laufzeit | `DemoRuntimes` verwendet einen gemeinsamen Bestand, gemeinsame vorbereitete Antworten und `TIMEZONE` | Besucherspezifische Metadaten durchgängig an Anzeige und Wiederaufnahme geben |
| Hilfe | Ein deutscher Bestand mit versionsgebundenem Manifest und deutscher Wortstammsuche | Englische Dokumente, Suche, Antworten und sprachabhängige Caches ergänzen |
| Generierte Freitexte | Bestehende Zusammenfassungs-Prompts verlangen ausdrücklich Deutsch | Englische Generatorvariante für tatsächlich englische Zusammenfassungen, Titel und Beschreibungen definieren |
| Übersetzungsprüfung | AST-Prüfung findet literale `tr()`-/`de()`-Aufrufe und ausgewählte Beschriftungstabellen | Auch bislang unmarkierte Texte und dynamische Oberflächen erfassen |

Die tatsächliche Implementierung hat Vorrang vor älteren Patchzuordnungen in Planung 7.5.
Die inzwischen belegte Version 7.5.5 enthält den Datumsbereich-Nachtrag. Daraus lässt sich kein
Abschluss der damals für diese Nummer vorgesehenen Webseiten-Lokalisierung ableiten.

7.7 verändert gerade Relevanzprüfung, Vorfilter und Zustandsmodelle. Vor der Datensatzerzeugung
werden der verwendete Quellstand und die wirksame Konfiguration festgehalten. Nach fachlichen
Änderungen an dieser Pipeline wird der Paketnachweis erneut geprüft. Die Arbeiten am Sprachrahmen
können bereits auf den vorhandenen Schnittstellen aufbauen.

## 3. Verbindliche Sprach- und Inhaltsregeln

### 3.1 Auswahl der Oberflächensprache

| Situation | Ergebnis |
| --- | --- |
| Aufruf von `/de/` oder `/en/` | Gewählte Sprache merken und zum Demo-Einstieg führen |
| Gültiger Cookie `mailhelp_lang` | Gespeicherte Wahl verwenden |
| Gültiger Browserheader ohne gespeicherte Wahl | Höchsten unterstützten `q`-Wert verwenden. Bei Gleichstand gilt die Reihenfolge im Header |
| Regionale Kennung wie `en-GB`, `en-US` oder `de-AT` | Auf die unterstützte Grundsprache abbilden |
| Header mit `q=0` | Diesen Eintrag bei der Auswahl auslassen |
| Ungültiger Cookie oder unbrauchbarer Header | Mit der nächsten Auswahlstufe fortfahren |
| Normalbetrieb ohne passende Browserwahl | `config.yaml` → `language` verwenden |
| Demo ohne passende Browserwahl | Demo-Standard `de` verwenden. Ein expliziter CLI-Sprachparameter kann den Prozessstandard wählen |

Die Sprachwahl ist pro Anfrage gekapselt. Nach Ende einer Anfrage oder nach einer Ausnahme wird
der vorherige Kontext wiederhergestellt. Gleichzeitige deutsche und englische Anfragen erhalten
jeweils passende Inhalte und Cacheeinträge.

`GET /sprache?wert=de|en` bleibt die reguläre Umschaltung. Bei angemeldeten Besuchern führt sie
zur bisherigen internen Seite einschließlich unterstützter Filter zurück. Externe oder ungültige
Rücksprungziele führen zur Startseite. Ungültige explizite Sprachwerte erhalten eine verständliche
400-Antwort und erhalten die bisherige Wahl.

Die Einstiegspfade und der Sprachwechsel werden vor der Demo-Anmeldesperre behandelt. Der
Sprachcookie bleibt hostgebunden, gilt für `/`, verwendet `SameSite=Lax` und höchstens ein Jahr
Laufzeit. Über HTTPS erhält er `Secure`. Die vorhandenen Cookie-Helfer werden dafür zusammengeführt.

### 3.2 Oberflächensprache und Datensatzsprache

`ui_locale` bezeichnet die Sprache der aktuellen Anfrage. `dataset_locale` bezeichnet die Sprache
der dauerhaft angelegten Beispielinhalte eines Besucherbereichs. Beide Werte werden ausdrücklich
geführt.

| Auslöser | Oberfläche | Beispielinhalte und Entscheidungen |
| --- | --- | --- |
| Erster bestätigter Demo-Start auf Englisch | Englisch | Englischen Bestand installieren |
| Erster bestätigter Demo-Start auf Deutsch | Deutsch | Deutschen Bestand installieren |
| Sprache während einer laufenden Demo wechseln | Gewählte Sprache sofort anzeigen | Vorhandenen Bereich mit seinen Entscheidungen weiterverwenden |
| Datensatzsprache weicht von der Oberfläche ab | Verständlichen Hinweis und passenden Neustart anbieten | Austausch erst nach Bestätigung |
| Neustart bestätigen | Gewählte Sprache anzeigen | Bestätigten Sprachbestand als neue Generation einsetzen |
| Seite neu laden, Browser oder Server neu starten | Gespeicherte Auswahl beziehungsweise gültige Anfrageauswahl verwenden | Zugeordneten Bereich wieder öffnen |

Die Bestätigungsseite nennt die Zielsprache und den Verlust der bisherigen Demo-Entscheidungen.
Ein bloßer Sprachlink setzt den Bereich fort. Bei einem weiteren Sprachwechsel zwischen
Bestätigungsseite und POST gilt die auf der Bestätigungsseite gebundene Zielauswahl.

### 3.3 Welche Texte lokalisiert werden

| Inhalt | Behandlung |
| --- | --- |
| Überschriften, Navigation, Dialoge, Hinweise, ARIA-Texte und Bedienfehler | Beim Rendern übersetzen |
| Von Mailhelp gespeicherte Aktionsmeldungen | Kanonisch speichern und in der Lesersprache darstellen |
| Bestehende deutsche Rückfragen als Revisionsschlüssel | Identität erhalten und die sichtbare Beschriftung übersetzen |
| Statuswerte, JSON-Schlüssel, Themen-IDs, Befehle und Protokollereignisse | Als stabile technische Werte führen |
| Produktive Originalmails, Belege, eigene Titel und Beschreibungen | Originalinhalt anzeigen |
| Englische Demo-Mails, Persona und Vorschlagstexte | Aus dem echten englischen Vorverarbeitungslauf übernehmen |
| KI-Extraktionsschemas und fachliche Analyseprompts | Den bestehenden kanonischen Verarbeitungsvertrag verwenden |
| KI-Hilfeantworten | In der angefragten Hilfesprache erzeugen und prüfen |

Die Sprache einer Mail und die Sprache der Oberfläche sind getrennte Eingaben. Die Auswahl einer
englischen Oberfläche ändert den Bezug eines Datums, die Zuständigkeit oder eine bereits bestätigte
Vorschlagsversion ausschließlich durch die vorhandenen fachlichen Bearbeitungswege.
Die Tests belegen die Wiederverwendung bestehender Analysen und Vorschlagsversionen bei
Sprachwechseln. Anzeige- und Hilfecaches tragen ihren Sprachbezug ausdrücklich.

## 4. Demo-Oberflächen vollständig lokalisieren

Das Textinventar umfasst insbesondere Anmeldung, Startfehler, Limits, Sitzungsablauf, Demohinweis,
simulierte Ergebnisse, Tastenhilfe, Wischtexte, Rückgängig, leeren Stapel, Neustart und gesperrte
Funktionen. Dazu gehören Browserdialoge und die zugänglichen Namen ihrer Bedienelemente.

Der Einstieg trägt den Titel **„Demo starten“ / „Start demo“**. Der Knopf verwendet denselben
Handlungsbegriff. Der Hinweis beschreibt Beispieldaten und Simulation in der gewählten Sprache.
„Gerät koppeln“ bleibt dem tatsächlichen Koppelablauf des Normalbetriebs zugeordnet.

Alle sichtbaren Werte entstehen im aktiven Sprachkontext. Eine Übersetzung beim Modulimport würde
die erste Sprache festhalten. `DemoSite` muss den Kontext auch während `demo_response()`, der
Neustartbehandlung und eigener Fehlerantworten tragen.

Die vorhandenen Renderer erhalten eindeutige Demo-Beschriftungen und lokalisierte Ergebnistexte.
Die Umstellung der bisherigen `DEMO_TEXTS`-/`DEMO_LABELS`-Ersetzungen wird an Erzeugern und
Verbrauchern gemeinsam geprüft. Übersetzungen werden an den betreffenden Bedienelementen und
Meldungen angewandt. Mailtext, Belege und bereits escapte Nutzereingaben behalten ihren Inhalt.

Abnahmebeispiele umfassen englischen Erstaufruf, simuliertes Anlegen, Verwerfen, Rückgängig,
Tastenbedienung, abgeschlossenen Stapel, Neustartabbruch sowie ungültige und abgelaufene Formulare.
Eine deutsche Bestandsnachricht mit dem Wort „Simulieren“ dient als Regression gegen unbeabsichtigte
Änderungen am Mailinhalt.

## 5. Zwei geprüfte Demo-Bestände

### 5.1 Gemeinsamer fachlicher Vertrag

Beide Sprachbestände enthalten genau 30 eindeutige Originalmails. Die fachlichen Zahlen werden
anhand der gespeicherten Analyseergebnisse und Vorschläge geprüft. Quelllisten wie `RELEVANT`
dienen der Zusammenstellung. Die gespeicherte fachliche Entscheidung liefert die Relevanzzahl.

| Bestand | Relevante Mails | Irrelevante Mails | Bestätigungsbereite Termine | Bestätigungsbereite Aufgaben |
| --- | --- | --- | --- | --- |
| Deutsch, geprüfter 7.6-Bestand | 9 | 21 | 6 | 4 |
| Englisch, Zielbestand 7.8 | 10 | 20 | 6 | 5 |

Die deutsche Quellliste enthält bereits das negative Black-Week-Beispiel. Die deutsche Abnahme
übernimmt dessen fachliche Einordnung und die zehn freigegebenen Vorschläge. Der englische
Bestand ergänzt eine ausdrücklich relevante Bibliotheksaufgabe und erhält elf Vorschläge.
Zwei englische relevante Mails sind Informationen ohne Handlungsauftrag. Die übrigen acht
englischen Mails enthalten die Aufgaben und Termine aus Abschnitt 5.2.

Jeder ausführbare Vorschlag besitzt `pending_confirmation`, eine eindeutige Zuständigkeit,
vollständige Zeitangaben und eine leere Fragenliste. Die vorbereiteten Antworten sind im
klärungsfreien Paket leer. Der vorhandene Antwortmechanismus bleibt durch eigene synthetische
Klärungs-Fixtures abgesichert.

Der Beispielsatz besitzt eine explizite Referenzzeit. Planungsvorgabe für beide Bestände ist
`Europe/Berlin`, damit sich Sprachdarstellung und fachlicher Ablauf anhand derselben Zeitzone
vergleichen lassen. Die englischen Mails enthalten eindeutige ISO-Kalenderdaten mit Jahr sowie
24-Stunden-Uhrzeiten und die erforderlichen Zonenangaben. Der Eintrittsbeitrag lautet in beiden
Sprachen auf 12 EUR.

Die erzeugten Extraktionen werden gegen diese Daten geprüft. Falls ein englischer Datumausdruck
eine Erweiterung der Normalisierung erfordert, erfolgt diese deterministisch mit Regressionen für
Deutsch, Englisch, Wochentagswidersprüche, Zeitumstellung und Mehrdeutigkeit. Die tatsächlich
unterstützten Formen werden in der Spezifikation aufgeführt. Die Oberflächensprache dient dabei
als Anzeigeauswahl. Datumsentscheidungen stützen sich auf Mailinhalt und validierten Mailkontext.

Der sichtbare Beispielstand und zeitabhängige Anzeigen zu den Beispiel-Fristen verwenden die
Manifestreferenz über eine explizite Zeitquelle des Demo-Laufzeitkontexts. Aktionsprotokolle,
Sitzungsdauer, Startbegrenzung und Bereinigung verwenden Echtzeit. Das erhält eine nachvollziehbare
Vorführung auch bei späteren Aufrufen und ermöglicht eine wirksame Sitzungsablaufprüfung.

### 5.2 Englische Persona und positive Beispiele

Persona bleibt **Alex Miller**, Elternteil von Mia. Die vier Themen beschreiben **Maple Park
Elementary School**, **Oakville Youth Sports Club**, **Oakville Music Academy** und **Maple Park
PTA**. Namen und Adressen sind synthetisch. Mailadressen und Links verwenden Beispieldomains.
Die Themen tragen stabile fachliche IDs mit englischen Namen und Beschreibungen.

Die folgende Tabelle ist die unabhängige Sollvorgabe für den englischen Erzeugungslauf.

| Nr. | Englische Beispielmail | Erwartetes Ergebnis |
| --- | --- | --- |
| 01 | Grade 4 Parent-Teacher Meeting | Termin am 2026-11-26, 19:30–21:00, Raum 12. Alex nimmt ausdrücklich teil |
| 02 | Planetarium Field Trip – Chaperone Schedule & Consent Form | Begleitung am 2026-12-04, 08:30–13:00. Aufgabe zur Formularabgabe bis 2026-11-20 |
| 03 | Youth Craft Workshop – Schedule & Supplies | Termin am 2026-11-21, 10:00–12:30. Materialbeschaffung bis 2026-11-20 ausdrücklich Alex zugeordnet |
| 04 | Winter Holiday Fair – Thank You for Donating a Cake | Teilnahme am 2026-12-05, 14:00–17:00. Kuchenlieferung am selben Tag bis 13:30 als Aufgabe |
| 05 | Reading Mentors – Orientation Meeting | Termin am 2026-12-01, 18:00–19:00, Schulbibliothek |
| 06 | Planetarium Field Trip – Admission Fee Due | Aufgabe zur Überweisung von 12 EUR bis 2026-11-25 |
| 07 | Invitation to Violin Class Recital | Termin am 2026-12-09, 16:00–17:30 |
| 08 | New Youth Team Jerseys Arrived | Relevante Information. Ausgabe im ohnehin stattfindenden Training, ohne neuen Auftrag |
| 09 | December Cafeteria Menu Published | Relevante Information. Bestehende Bestellung läuft weiter |
| 10 | School Library – Return Borrowed Books | Aufgabe für Alex zur Rückgabe bis 2026-11-30 |

Die Werbemail „Black Week“ aus dem ersten Entwurf gehört zu den negativen Beispielen. Die neue
Bibliotheksmail vervollständigt die zehn relevanten Beispiele. Damit sind Mailzahl, Relevanzzahl
und Vorschlagszahl voneinander unabhängig überprüfbar.

### 5.3 Zwanzig negative Beispiele

| Nr. | Beispiel | Erwartung aus Sicht der Demo-Persona |
| --- | --- | --- |
| 11 | Black Week shop promotion | Unverwandte Werbung |
| 12 | Headphones special offer | Unverwandte Werbung |
| 13 | Fashion newsletter | Unverwandter Newsletter |
| 14 | Grocery recipes subscription | Unverwandter Newsletter |
| 15 | Winter travel deal | Unverwandte Werbung |
| 16 | Streaming catalogue update | Unterhaltung ohne Bezug zu den Themen |
| 17 | Furniture catalogue | Unverwandte Werbung |
| 18 | Gardening newsletter | Unverwandter Newsletter |
| 19 | Spa hotel package | Unverwandte Werbung |
| 20 | Insurance promotion | Unverwandte Werbung |
| 21 | Receipt for an already paid online order | Zahlungsbeleg mit ausdrücklich abgeschlossenem Vorgang |
| 22 | Parcel tracking notification | Versandinformation ohne Handlungspflicht |
| 23 | Delivery completed | Zustellinformation ohne Handlungspflicht |
| 24 | Receipt for an already paid subscription | Abgeschlossene Zahlung ohne Kündigungs- oder Verlängerungsauftrag |
| 25 | PhotoBook app update | Unverwandte Systeminformation |
| 26 | Social network notifications | Unverwandte Systeminformation |
| 27 | Completed service maintenance | Abgeschlossene technische Wartung eines themenfremden Dienstes |
| 28 | Optional customer survey | Freiwillige themenfremde Anfrage |
| 29 | Optional IT webinar | Themenfremde Einladung ohne Teilnahmezusage |
| 30 | General charity appeal | Spendenwerbung außerhalb des Schul-Fördervereins |

Die Einordnung folgt Persona und Themen. Der Generator verwendet eine dokumentierte
Vorfilterkonfiguration mit deaktivierten Kopfzeilenfiltern und ohne vorwegnehmende VIP- oder
Sperrregeln für diese Beispiele. Der Lauf zeichnet die tatsächliche Entscheidungsherkunft je Mail
auf. Dadurch bleibt die fachliche Prüfung auch nach den Pipelineänderungen aus 7.7 aussagekräftig.

### 5.4 Erzeugung, Herkunft und Paketierung

`devtools.demo.dataset` erhält `--locale {de,en}`. Der bisherige Aufruf ohne diesen Parameter
erzeugt weiterhin den deutschen Bestand. Persona, Themen, Mails, Referenzzeit und Zielverzeichnis
werden gemeinsam aus einer begrenzten Sprachdefinition gewählt.

Die englischen Originalmails stehen in `devtools/demo/mails_en.py`. Der vorhandene `DemoMail`-Typ
und die EML-Erzeugung werden gemeinsam verwendet. Die Laufzeitanwendung lädt die exportierten
Paketressourcen über `runtime/demo_dataset.py`. Die Erzeugung läuft im Entwicklungsverzeichnis.
Die Paketabnahme startet beide Sprachbestände mit dem installierten Wheel außerhalb des Checkouts.

Die englische Generatorvariante definiert die Sprache frei formulierter Modellantworten in
`prompts.yaml`. Das betrifft insbesondere Zusammenfassungen, Titel, Beschreibungen und sichtbare
fachliche Begründungen. Die vorhandenen deutschen Zusammenfassungsanweisungen werden dabei
gezielt durch die englische Variante ersetzt. Diese wirksame Promptkonfiguration einschließlich
Ausgabesprache geht in den Analyse-Fingerprint des Erzeugungslaufs ein. `ui_locale` bleibt die
Auswahl für die Darstellung. Der englische Bestand entsteht damit als Ergebnis der englisch
konfigurierten echten Verarbeitung.

Der Generator verwendet die bestehende Zusammenstellung über `build_application` und
`Orchestrator.process`. Die synthetischen Mails durchlaufen Vorbereitung, Relevanz, Extraktion,
Normalisierung, Abgleich und Persistenz. Die bestehenden Entwicklungszugänge, Modellparameter und
Budgeteinstellungen gelten. Externe Schreibziele und Telegram sind durch den Demo-Erzeugungspfad
abgekoppelt.

Nach dem Lauf erfolgt eine eigenständige Prüfung gegen die Solltabellen. Falsche Termine,
Zuständigkeiten oder Rückfragen führen zur Korrektur der Quelle beziehungsweise des nachgewiesenen
Verarbeitungsfehlers und zu einem neuen Lauf. Die exportierten Ergebnisse werden vollständig aus
dem erfolgreichen Pipeline-Lauf übernommen.

Das Manifest benennt Sprache, Datensatz-ID, Schema, Referenzzeit, Zeitzone, Quellstand,
Analyse-Fingerprint, verwendete Modelle und die SHA-256-Prüfsummen. Lokale Quellabweichungen werden
im Erzeugungsnachweis kenntlich gemacht. Dieser Nachweis nennt auch die fachlichen Ergebniszahlen
und die tatsächlich angefallenen Aufrufe.

Der Export verwendet eine Dateiauswahl für synthetische Mails und benötigte Zustände. Temporäre
Konfiguration, Zugangsdaten, Sitzungsschlüssel und produktive Daten verbleiben im Entwicklungs-
beziehungsweise Laufzeitverzeichnis. Vollständige LLM-Rohprotokolle folgen der vorhandenen
ausdrücklich zuschaltbaren Protokollierung.

Die freigegebenen Bestände werden eingecheckt und lokal zur Laufzeit verwendet. CI prüft sie mit
simulierten Diensten und aufgezeichneten synthetischen Analyseergebnissen. Modellaufrufe gehören
zum nachvollziehbaren Erzeugungslauf. Paketbau und wiederholte Prüfungen verwenden die freigegebenen
Artefakte.

## 6. Datensatz- und Besucherzustand

### 6.1 Registry und Integrität

| Sprache | Paket-ID | Paketverzeichnis |
| --- | --- | --- |
| `de` | `standard-v1` | `defaults/demo/standard-v1/` |
| `en` | `standard-en-v1` | `defaults/demo/standard-en-v1/` |

Eine feste Registry verbindet `Locale`, Paket-ID und Paketpfad. `packaged()` bleibt für bestehende
Aufrufer mit dem deutschen Standard verwendbar. Neue Aufrufer wählen die Sprache explizit.
`verify()` validiert ID und Sprache gemeinsam. Die alte deutsche Manifestversion wird als
deutscher Bestand weiter gelesen.

Der neue Manifestvertrag prüft zusätzlich die zeitlichen Metadaten, eindeutige IDs, vollständige
Dateimengen und den Bezug von Mail, Analyse und Vorschlag. Installiert werden ausschließlich die
freigegebenen Zustandsdateien. Dateinamen werden mit den bestehenden Speicherregeln abgeglichen.
Absolute Pfade, Traversierung, Backslashes, Symlinks und kollidierende Namen unter Windows werden
abgewiesen. Jede installierte Datei erhält eine Integritätsprüfung.

Fehlt der gewählte Bestand oder ist er beschädigt, bleibt eine bestehende Demo verwendbar. Ein
betroffener neuer Start erhält eine lokalisierte 503-Antwort. Die Sprache und der Fehler bleiben
für die Besucherin erkennbar. Die Diagnose enthält Datensatz-ID und Fehlerklasse.

### 6.2 Persistente Zuordnung und ältere Besucherbereiche

`VisitorEntry` wird um `dataset_locale`, `dataset_id`, `dataset_revision` und `generation`
ergänzt. Zeitzone und Referenzzeit stammen aus der geprüften Paketzuordnung und werden für die
Wiederaufnahme verfügbar gehalten. Eine unbekannte Revision älterer Bereiche bleibt als solche
gekennzeichnet.

Die zu einer Generation gehörenden Metadaten und vorbereiteten Antworten werden mit ihrer
Installation gesichert. Dadurch kann ein vorhandener Bereich auch nach einem Paketupdate mit
neuer Datensatzrevision seine zugehörige Referenzzeit und seine vorbereiteten Antworten verwenden.

`DemoHooks.start` und `reset` geben die gewählte Zielsprache ausdrücklich weiter. Die Auswahl des
Quellbestands gehört zum einzelnen Auftrag. Eine prozessweit veränderliche `dataset`-Auswahl würde
gleichzeitige Starts vermischen. `DemoRuntimes` baut Anzeige und vorbereitete Antworten aus den
Metadaten des jeweiligen Bereichs auf.

Der Besucherindex erhält eine dokumentierte Schema-Umstellung mit Sicherung und Upgrade-Fixture.
Bereits vorhandene Einträge werden als deutscher Bestand übernommen. Ihre Bereiche, Entscheidungen
und Ablaufzeiten bleiben erhalten. Die neue Implementierung kann alte Bereiche nach einem
Serverneustart wieder öffnen. Vorbereitete Antworten werden aus dem zugehörigen Datensatz geladen.

### 6.3 Idempotenz, Austausch und Konkurrenz

Ein Start- oder Neustartauftrag bindet Sitzung, Operation, Zielbestand und Idempotenzschlüssel.
Gleiche Wiederholungen liefern denselben Bereich. Die Wiederverwendung eines Schlüssels mit
anderem Inhalt erhält einen Konflikt. Die Besitzprüfung des bestehenden Systems bleibt bestehen.

Der Neustart bereitet die neue vollständige Kopie vor, prüft sie und aktiviert erst danach die
neue Zuordnung. Der vorherige Bereich wird bis zur erfolgreichen Aktivierung behalten. Ein
Kopierfehler oder Prozessabbruch lässt eine konsistente, wiederaufnehmbare Zuordnung zurück.

`DemoRuntimes` schließt die bisherigen Ressourcen koordiniert und verwirft ihre Anzeige-Caches.
Ein Formular und ein eingereihter Auftrag gehören zur jeweiligen Generation. Alte Formulare nach
einem Reset erhalten einen Konflikt mit Aufforderung zum Neuladen. Bereits laufende Worker und
Bereinigung werden in diese Übergänge einbezogen. Die Wiederaufnahme erkennt vorbereitete und
bereits aktivierte Generationen anhand dauerhafter Metadaten.

Die bestehenden Grenzen für Besucherzahl, Startfrequenz und zwei Stunden Sitzungsdauer werden
weiterverwendet. Echtzeitbegrenzung, signierte Sitzung, CSRF-Prüfung und Ausführungsprüfung gelten
für beide Sprachen. Die Demo bleibt im eigenen Verzeichnis und im isolierten Netz.

Die Tests überwachen die Konstruktion von Postfach-, Telegram-, KI- und echten Schreibadaptern.
Sie weisen nach, dass ein Demo-Start und Demo-Aktionen ausschließlich die lokalen Simulationswege
verwenden. Im Normalbetrieb bleibt vor externen Schreibzugriffen die ausdrückliche, bei Ausführung
erneut geprüfte Bestätigung der Vorschlagsversion maßgeblich.

## 7. Verbleibende Anwendungs-Lokalisierung

### 7.1 Inventar als Abnahmegrundlage

Zu Beginn entsteht eine überprüfbare Text- und Ablaufmatrix. Jede Zeile nennt Oberfläche,
Erzeuger, Textart, Übersetzungsschlüssel und zugehörigen Test. Erfasst werden mindestens
Mails und Details, Verlauf, Status, Abgleich, Auswertung, Berichte, Lernen, Einstellungen,
Konten, Ziele, Geräte, Einrichtung, Authentifizierung, Demo, Hilfe und CLI.

Die Matrix berücksichtigt leere Listen, Validierungsfehler, technische Fehler, abgelaufene
Sitzungen, Konflikte und erfolgreiche Quittungen. Bestehende Übersetzungen aus 7.5 werden
wiederverwendet. Die Abnahme weist jede erfasste Zeile mit deutscher und englischer Darstellung nach.

Die Katalogprüfung kontrolliert literale und dynamische Textquellen sowie die Übereinstimmung von
Platzhaltern und Beschriftungsfamilien. Erforderliche Schlüssel für ältere gespeicherte Meldungen
bleiben mit Beispielen abgesichert. Codeabdeckung und Vollständigkeit der Übersetzungen werden
gesondert ausgewiesen.

### 7.2 Web, JavaScript und PWA

JavaScript erhält seine UI-Meldungen über die vorhandenen Rendering- und Datenübergaben.
Platzhalterwerte werden an der Ausgabe sicher escapet. Gesten, Rückgängig, Ladezustände,
Fehlerhinweise, Dialoge und ARIA-Meldungen verwenden dieselben Begriffe wie die Karten.
HTML-Formwerte behalten die technischen Datums-, Versions- und Aktionsformate.

Offline-Seite, Installationshinweise und Service Worker werden sprachabhängig geprüft. Caches
unterscheiden sprachabhängige Inhalte. Eine Änderung der Sprache aktualisiert sichtbare Meldungen
und die Offline-Darstellung. Vorhandene Regeln für das Verwerfen offline gesendeter Schreibaufträge
werden in beiden Sprachen durchlaufen.

Die Matrix umfasst auch die Sprache neutraler System-Pushs. Bestehende Geräte- und
Konfigurationseinstellungen liefern die Zuordnung. Falls die Zuordnung pro Gerät ergänzt werden
muss, erhält sie eine optionale, kompatible Persistenz und dieselben Autorisierungsprüfungen wie
die bestehende Geräteverwaltung. Telegram folgt weiterhin der eingestellten Anwendungssprache.

### 7.3 Englische Hilfe

Die sieben freigegebenen Hilfequellen aus `devtools.help_index.SOURCES` erhalten fachlich geprüfte
englische Fassungen. Der Generator erstellt pro Sprache einen vollständigen Inhaltssatz samt
Manifest, Einstellungen-Metadaten und Suchbestand.

Abschnitts-IDs bleiben sprachübergreifend stabil. Übersetzte Überschriften und Dateinamen ändern
gespeicherte Quellenverweise und bestehende Links ausschließlich über eine dokumentierte Zuordnung.
Der Loader unterstützt den bisherigen deutschen Aufruf. Die englische Suche verwendet geeignete
englische Suchbegriffe und überprüfte typische Fragen. Die bisherige deutsche Wortstammsuche bleibt
mit ihren Fällen abgenommen.

Hilfecaches und gespeicherte Antworten erhalten einen Sprachbezug. Quellen in einer Antwort müssen
zum gewählten Bestand passen. Für die KI-Hilfe wird die Antwortsprache als kontrollierter Parameter
in `prompts.yaml` geführt. Die Gültigkeit von Quellen, vertraulichen Inhalten und Platzhaltern
bleibt geprüft. Der Versionswechsel aktualisiert sämtliche Hilfemanifeste vor dem Paketbau.

### 7.4 CLI und menschlich lesbare Diagnose

Die CLI erhält einen expliziten `--language {de,en}`-Parameter. Er gilt für den jeweiligen Aufruf.
`--help`, Argumentfehler und Konfigurationsfehler werden schon vor dem regulären Anwendungsstart
in der ausdrücklich gewählten Sprache ausgegeben. Ohne explizite Auswahl gilt im Hilfemodus
Deutsch. Nach erfolgreichem Konfigurationsladen greift die konfigurierte Sprache als Standard.

Unterbefehle und Optionsnamen bleiben stabile Aufrufschnittstellen. Exitcodes und maschinenlesbare
Ausgaben erhalten ihre bisherige Bedeutung. Menschliche Texte werden über den Sprachkern erzeugt.
Strukturierte Ereignisse, Stacktraces und technische Fehlerkennungen behalten ihre Diagnosefunktion.
Ein Hilfeaufruf benötigt den Parser und die Textressourcen. Die Tests prüfen zusätzlich, dass dabei
keine Anwendung mit Postfach- oder Telegramzugriff aufgebaut wird.

## 8. Umsetzungspakete und Abhängigkeiten

Jedes Paket liefert seine Tests und die zugehörige Dokumentation mit. Die Tabelle beschreibt
fachliche Pakete. Zusätzliche Commits erhalten gemäß AGENTS.md jeweils die nächste Patchnummer.
Die endgültigen Nummern werden im Release-Bericht dem tatsächlich gelieferten Umfang zugeordnet.

| Paket | Inhalt | Nachweis zum Abschluss |
| --- | --- | --- |
| A – Sprachvertrag und Einstieg | Inventar, Aushandlung, öffentlicher Sprachwechsel, native `/de/`- und `/en/`-Einstiege, Cookie | Browserwahl einschließlich `q=0`, Erstaufruf, interne Rückkehr, gleichzeitige Sprachen und Kontextbereinigung getestet |
| B – Demo-Rahmen | Einstieg, Hinweise, Ergebnisse, Tasten, leere Zustände, Fehler und Neustart | Vollständiger Demo-Rahmen DE/EN einschließlich Abbruch und Fehlerfälle. Originalinhalte bleiben durch Regressionen abgesichert |
| C – Bestandsvertrag | Registry, Manifest, Generatorparameter, Paketprüfung, bestehender deutscher Bestand | Deutscher bisheriger Aufruf und alte Manifeste funktionieren. Beschädigung, Dateimengen und Pfadgrenzen sind geprüft |
| D – Englische Inhalte | Persona, Themen, 30 Mails, realer Pipeline-Lauf und Freigabenachweis | Genau 10 relevante und 20 irrelevante Mails. Sechs Termine und fünf Aufgaben vollständig geklärt |
| E – Besucher-Lebenszyklus | Persistente Zuordnung, sprachbezogene Laufzeit, Referenzzeit, Migration, idempotenter Start und atomarer Reset | Wiederholungen, Neustarts, Fehler während des Kopierens, alte Formulare, Worker-Rennen und mehrere Besucher geprüft |
| F – Web, JS, PWA und Meldungen | Restliche Oberflächen aus der Matrix, Formate, ARIA, Offline- und Benachrichtigungstexte | Jede Matrixzeile DE/EN belegt. Bestehende Offline- und Bestätigungsregeln bleiben automatisiert geprüft |
| G – Hilfe | Englische Quellen, sprachabhängige Pakete, Suche, KI-Antworten und stabile Quellen-IDs | Fragenkorpus DE/EN, Versionsbindung, Quellenprüfung und Betrieb außerhalb des Checkouts bestehen |
| H – CLI | Frühe Sprachauswahl, Hilfe, Validierung und menschliche Statusausgaben | Beide Sprachen mit Erfolg, ungültigen Argumenten und fehlender Konfiguration. Exitcodes und JSON-Schnittstellen geprüft |
| I – Integration und Veröffentlichung | Installiertes Wheel, Docker, Browsermatrix, Upgrade, Landingpage und Proxy-Übergang | Gesamtabnahme und nachvollziehbarer Release-Bericht mit tatsächlichen Ergebnissen |

A legt den gemeinsamen Vertrag fest. C bereitet D vor. E integriert B, C und D. F bis H verwenden
das Inventar aus A. I führt alle freigegebenen Ergebnisse zusammen. Vor jedem Commit werden beide
Versionsdateien, README und CHANGELOG nach den Entwicklungsregeln aktualisiert.

## 9. Prüfmatrix und Abnahmekriterien

| Fall | Erwartetes Ergebnis |
| --- | --- |
| Englische Landingpage, deutscher Browser, vorhandener deutscher Sprachcookie | Englischer Einstieg und nach dem Start englische Mails und Karten |
| Deutscher Einstieg bei englischem Browser | Deutscher Einstieg und deutscher Bestand |
| Sprachwechsel vor Anmeldung | Auswahl wird vor jeder Kopplungs- oder Demo-Startabfrage wirksam |
| Sprachwechsel nach zwei Entscheidungen | Oberfläche wechselt. Entscheidungen und Datensatzzuordnung bleiben erhalten |
| Datensatzwechsel bestätigt beziehungsweise abgebrochen | Neue vollständig installierte Generation beziehungsweise bisheriger Bereich |
| Doppelter Start und doppelter Reset | Jeweils ein wirksamer Auftrag mit identischem Ergebnis |
| Gleicher Schlüssel mit anderer Zielsprache | Verständlicher Konflikt |
| Neustart zwischen Kopieren und Aktivieren | Konsistente Wiederaufnahme anhand der dauerhaften Zuordnung |
| Alte Formulare und wartende Aktionen nach Reset | Keine Aktion in der neuen Generation. Neuladen wird angeboten |
| Zwei Besucher und zwei Tabs mit unterschiedlichen Sprachen | Getrennte Bereiche und sprachlich passende Antworten ohne Cachevermischung |
| Alte deutsche Besuchereinträge nach Upgrade | Bestehende Entscheidungen und Ablaufzeiten bleiben lesbar |
| Englischer Bestand beschädigt oder unvollständig | Lokalisierter Fehler für den betroffenen Start und weiter nutzbare bestehende Bereiche |
| Manipulierte Sprache, Pfade, Mailinhalte und Übersetzungsplatzhalter | Begrenzte Werte, sichere Ausgabe und wirksame Autorisierung |
| Fenster mit anderer Serverzeitzone und Sommerzeitgrenze | Eindeutige fachliche Zeitpunkte aus Mail- und Datensatzkontext |
| Abgelaufene Sitzung, ungültiges CSRF und alte Vorschlagsversion | Ablehnung auch bei Ausführung eines eingereihten Auftrags |
| Installation als Wheel und Docker-Demo ohne ausgehendes Netz | Beide Bestände und beide Hilfesprachen lokal verfügbar |

Die Browserabnahme führt den vollständigen Weg für beide Sprachen durch. Sie umfasst Desktop,
mobile Ansicht und die vorhandenen Chromium-/WebKit-Szenarien. Touch, Tastenbedienung, Rückgängig,
Formularvalidierung, Darstellung bei 320 px, reine Tastaturnavigation und fehlendes JavaScript
werden mit den bestehenden geeigneten Prüffällen abgedeckt.

Für vollständig englische Fälle werden die in der Matrix erfassten UI-Texte geprüft. Eine pauschale
Suche nach deutschen Wörtern im gesamten HTML wäre wegen produktiver Originalmails ungeeignet.
Die Demo-Inhalte besitzen dafür eine eigene sprachliche und fachliche Inhaltsprüfung.

Für jede Anwendungscodeänderung gelten 100 % Zeilen- und 100 % Branch-Abdeckung. Bugfixes enthalten
eine vor dem Fix fehlgeschlagene Regression. Die bestehenden JavaScript-Abdeckungsprüfungen,
Ruff-, mypy-, Architektur-, Schema- und Paketprüfungen bleiben Bestandteil der Abnahme.

Die abschließenden Befehle laufen auf demselben festgehaltenen Quellstand nacheinander.

```powershell
python -m devtools.help_index --check
python -m devtools.check full --workers 12
python -m pytest ui_tests -n 6 --dist worksteal --no-cov
```

Python- und Browserprüfung erhalten ein exklusives Prüfzeitfenster. Die vorhandenen Lastgrenzen
werden weiter gemessen. Bei einem schon im Ausgangsstand auftretenden Befund werden Baseline,
Kandidat, Umgebung und Wiederholung getrennt im Release-Bericht erfasst. Geänderte Quellen während
eines Laufs erfordern einen zu diesem Quellstand passenden neuen Nachweis.

## 10. Veröffentlichung, Kompatibilität und Abschluss

Vor der Veröffentlichung werden README, Spezifikation, Bedienung, passende Konfigurationsbeispiele
und `docs/Release-7.8.md` aktualisiert. Der Dokumentationsindex verlinkt Plan und Release-Bericht.
Der Bericht nennt Inventarabschluss, Datensatzzahlen, Quellenstand, Modelle, Prüfergebnisse,
Übersetzungsprüfung und verbleibende Befunde.

Die vorhandenen Landingpage-Links `/de/` und `/en/` bilden den öffentlichen Vertrag. Die Demo
implementiert diese Wege zuerst nativ. Nach Prüfung über HTTPS wird die derzeitige
Sprachweiterleitung im nginx-Proxy auf die native Umsetzung umgestellt. Beide Adressen und die
seitenbezogene Umschaltung werden nach der Umstellung erneut geprüft. Die Landingpage wird auf
den freigegebenen Stand abgeglichen. Cookie-Hinweise folgen der tatsächlich verwendeten Laufzeit.

Das Deployment sichert Images, Compose-Konfiguration und die Demo-Zustände vor einer
Schema-Umstellung. Ein Neustart mit der neuen Version muss bestehende Besucher wieder öffnen.
Für einen Rückwechsel werden Image und kompatibler Demo-Zustand gemeinsam behandelt. Für die
Produktivinstanz gilt der bestehende Schutz später bestätigter Schreibresultate.

Paketgröße, Erststart und Speicherverbrauch werden mit beiden Sprachen und mehreren Besuchern
gegen die Ausgangswerte gemessen. Das bestehende Demo-Deploymentprofil dient als Ressourcenbudget.
Statische Ressourcen und geprüfte Paketmetadaten werden pro Prozess gemeinsam verwendet.
Besucherspezifische Zustände und Aktionen bleiben getrennt. Der Release-Bericht dokumentiert die
Messwerte und die beim Test tatsächlich verwendeten Containergrenzen.

7.8 ist abgeschlossen, wenn alle fünf Ergebnisse aus Abschnitt 1 und sämtliche Fälle der
Prüfmatrix nachgewiesen sind, beide Bestände im installierten Paket vorliegen und der öffentliche
englische Demo-Durchlauf einschließlich englischer Inhalte erfolgreich geprüft wurde.
