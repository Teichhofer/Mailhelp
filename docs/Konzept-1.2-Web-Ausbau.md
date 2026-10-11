# Mailhelp 1.2 – Konzept und detaillierter Umsetzungsplan

**Stand:** 11. Oktober 2026  
**Zielversion:** 1.2.0  
**Status:** Plan, noch nicht implementiert. Grundlage ist der aktuelle Arbeitsstand von 1.1 im Branch `beta`, einschließlich bereits begonnener Änderungen an Betriebsdaten und Webansichten.

## 1. Ziel und vollständiger Umfang

Die Weboberfläche soll nicht nur offene Vorschläge bearbeiten, sondern den gesamten gespeicherten Mailverarbeitungsprozess nachvollziehbar machen. Telegram bleibt für Benachrichtigungen und bestehende Dialoge erhalten. Windows 11, Docker/Linux und die installierbare PWA bleiben unterstützt.

| Funktion | Ergebnis in 1.2 |
| --- | --- |
| Mailübersicht | Suche, Filter, Sortierung und Seitennavigation über alle noch gespeicherten Mails |
| Entscheidungsverlauf | Vollständiger noch aufbewahrter Verlauf mit Vorschlagsversionen und Ergebnissen |
| Analyseansicht | Zusammenfassung, Fristen, Relevanz, Themen und Begründungen auch ohne Vorschlag |
| Betriebsstatus | Laufender Verarbeitungsschritt, Wartezustände, Fehler und Wiederholungszeitpunkte |
| Kosten und Zeiten | Auswertung nach Zeitraum, Modell, Anbieter und Verarbeitungsschritt |
| Strukturierte Bearbeitung | Aufgaben und Termine in Formularfeldern ändern, neue Version erneut bestätigen |
| Themenverwaltung | Themen anlegen, ändern und deaktivieren, Änderungen kontrolliert übernehmen |
| Modelle und Einstellungen | Aktiven Modus und wirksame Konfiguration anzeigen; wichtige Anwendungseinstellungen validiert ändern, ohne Geheimnisse |
| Programm beenden | Mailhelp aus dem Web kontrolliert stoppen, mit ausdrücklicher Bestätigung und sicherem Wiederanlauf |

Nicht Teil dieser Version: Mehrbenutzerbetrieb, Web-Push, Offlineaktionen, Anhangsauswertung, automatisches Beantworten oder Verschieben von Mails sowie nachträgliches Ändern/Löschen bereits angelegter Kalender- oder Todoist-Einträge. Eine freie Promptbearbeitung und ein beliebiger YAML-/Geheimniseditor gehören nicht zum Umfang. Wichtige Anwendungseinstellungen werden über begrenzte, validierte Formulare bearbeitet; Modelle und Prompttexte bleiben in dieser Version lesend.

## 2. Ausgangslage und technische Ansatzpunkte

- `review/views.py` liefert offene Vorschläge und acht zuletzt erledigte Einträge. `proposal()` sucht derzeit in diesen beiden Listen. Dadurch muss die Detailauflösung für ältere Vorschläge vom Übersichtsfenster entkoppelt werden.
- `domain/mail.py:MailState` speichert bereits `relevance`, `summary`, Extraktionsergebnisse, Verarbeitungsschritte, Fehler und LLM-Aufrufreferenzen. `Relevance` enthält Themen-IDs und eine Begründung; `Summary` enthält ein bis zwei Sätze und Fristen.
- `web/site.py` und `web/review_pages.py` bieten Übersicht, Mail-/Vorschlagsdetails, Status, Aktionen und Geräteverwaltung. Die neuen Seiten erweitern den vorhandenen Router und das serverseitige HTML, ohne Frontend-Framework.
- `ReviewViews.system()` und die bereits begonnene Erweiterung der Statusansicht sind vor Umsetzung erneut abzugleichen. Vorhandene Arbeit wird integriert, nicht parallel neu aufgebaut.
- `review/commands.py`, `review/service.py` und `review/inbox.py` bieten typisierte, versionsgebundene Befehle und Wiederanlauf. Strukturierte Revisionen sollen diese Grenzen verwenden.
- `domain/proposal.py` enthält Feld- und Zeitinvarianten sowie `ProposalRevisionChanges`. Ein Webformular darf diese Regeln nicht durch direkte Feldzuweisungen umgehen.
- `openrouter.py`, `decisions.py` und `orchestrator.py` protokollieren Laufzeiten; OpenRouter meldet teilweise Tokenzahlen und Kosten. Ollama liefert Tokenzahlen, hat aber keine gleichwertige Abrechnung.
- `config.py` validiert `Topic`, `TopicsConfig` und `IrrelevantTopicsConfig`. `learning.py:save_topics()` schreibt YAML bereits atomar; Themen werden beim Anwendungsaufbau in Dienste eingebunden.
- `retention.py` entfernt nach Abschluss nicht nur den Mailtext, sondern je nach `debug_llm_days` auch Relevanz, Zusammenfassung und Aufrufreferenzen. Eine langlebige Analyseansicht funktioniert daher nicht allein durch zusätzliche HTML-Ausgabe.

## 3. Verbindliche Architektur und Sicherheitsregeln

1. JSON bleibt maßgeblicher Zustand, JSONL bleibt separates Protokoll. Kein Datenbankwechsel in 1.2.
2. Webthreads lesen konsistente, begrenzte Lesemodelle. Fachliche Änderungen laufen ausschließlich über den Hauptthread und persistierte Befehle.
3. Authentifizierung, Sitzungswiderruf, CSRF, Hostprüfung, Größenlimits, Escaping und Sicherheitsheader gelten für alle neuen Routen. Kein Zugriff auf beliebige Dateipfade durch URL-Parameter.
4. Änderungen eines Vorschlags tragen dessen erwartete Version. Wiederholungen verwenden denselben Idempotenzschlüssel. Unklare externe Schreibresultate werden vor weiteren Schreibversuchen abgeglichen.
5. Bearbeiten und Speichern erzeugt niemals unmittelbar einen Kalender- oder Todoist-Schreibzugriff. Die neue Vorschlagsversion benötigt eine ausdrückliche Bestätigung.
6. **Bestätigungsregel (vom Auftraggeber am 11. Oktober 2026 ausdrücklich freigegeben):** Bearbeitung und versionsbezogene Bestätigung sind über Telegram oder die authentifizierte Weboberfläche zulässig. Speichern einer Bearbeitung erzeugt keine externe Anlage; jede neue Vorschlagsversion benötigt eine separate ausdrückliche Bestätigung. Webaktionen verlangen CSRF-Schutz, Idempotenzschlüssel und erneute Sitzungs-, Versions- und Zustandsprüfung bei Ausführung. `AGENTS.md` enthält dieselbe Regel.
7. Mit deaktiviertem Web müssen die bisherigen Verarbeitungswege weiter funktionieren. Neue Telemetrie erzeugt weder LLM-Aufrufe noch Änderungen an Relevanzentscheidungen.
8. PWA und Browser speichern keine Maildaten, Formularentwürfe oder Antworten dauerhaft. Kein Hintergrundversand und kein Daten-Cache im Service Worker.
9. Für sämtlichen eigenen Anwendungscode bleiben 100 % Zeilen- und 100 % Branch-Abdeckung verbindlich. Jeder Bugfix erhält einen vor dem Fix scheiternden Regressionstest.

## 4. Informationsarchitektur und Bedienung

Die Navigation erhält: **Offen**, **Mails**, **Verlauf**, **Status**, **Auswertung**, **Einstellungen**. Geräteverwaltung und Themenverwaltung werden aus Einstellungen erreichbar. Auf Mobilgeräten darf die Navigation umbrechen; kein horizontales Scrollen der gesamten Seite.

Neue GET-Routen, jeweils mit Anmeldung:

| Route | Inhalt |
| --- | --- |
| `/mails` | Suche und Filter über gespeicherte Mails |
| `/mail/<mail_id>` | Erweiterte Maildetailseite einschließlich Analyse und Vorschlägen |
| `/verlauf` | Filterbarer Entscheidungsverlauf |
| `/vorschlag/<mail_id>/<proposal_id>` | Aktuelle Version unabhängig von Listenbegrenzungen |
| `/vorschlag/<mail_id>/<proposal_id>/version/<version>` | Aufbewahrte historische Version, ausschließlich lesend |
| `/vorschlag/<mail_id>/<proposal_id>/bearbeiten` | Typabhängiges Formular für einen offenen Vorschlag |
| `/status` | Betrieb, letzter Lauf, Fortschritt und Fehler |
| `/auswertung` | Kosten und Zeiten mit Zeitraum und Modellfiltern |
| `/einstellungen` | Wirksame Konfiguration, bearbeitbare wichtige Settings und ausstehende Änderungen |
| `/einstellungen/beenden` | Bestätigungsseite für den kontrollierten Programmstopp |
| `/themen` | Themenlisten und Revision |
| `/themen/<topic_id>/bearbeiten` | Themenformular |

Neue POST-Routen sind schmale Adapter für typisierte Befehle, keine direkten Dateischreiber. Vorgesehen sind `/vorschlag/.../bearbeiten`, `/themen/anlegen`, `/themen/.../bearbeiten`, `/themen/.../aktivierung`, `/einstellungen/speichern` und `/einstellungen/beenden`. Ergebnisanzeige, 202/303 und Statusadresse folgen dem bestehenden Webablauf. Veraltete Versionen ergeben 409, ungültige Formulardaten 422 mit erhaltenen Eingaben, ausgelastete Warteschlangen 503.

Alle Grundfunktionen funktionieren ohne JavaScript. JS ergänzt Aktualisierungen und Verbindungshinweise. Ungesendete Formulare dürfen durch Aktualisierung oder Sitzungsablauf nicht still überschrieben werden; nach erneutem Anmelden muss eine Versionsprüfung erfolgen.

## 5. Feature A – Mailübersicht, Suche und Filter

### Daten und Abfragen

- Neues Lesemodell `MailListItem`: ID, Absender, Betreff, Empfangszeit soweit vorhanden, letztes Update, Analysezustand, Relevanz, Themen-IDs, Vorschlagszahlen und Hinweis auf gelöschte Inhalte.
- Relevanz, Analysezustand und Vorschlagsstatus sind getrennte Filter: Eine relevante Mail kann ohne Vorschlag abgeschlossen sein; eine Mail kann mehrere Vorschläge in unterschiedlichen Zuständen haben.
- Suchfelder: Absender und Betreff standardmäßig, optional noch vorhandene Zusammenfassungen. Keine implizite Volltextsuche durch Rohlogs oder erneutes Abrufen vom IMAP-Server.
- Filter: relevant/irrelevant/unklar/nicht mehr verfügbar, Themen-ID, Zeitraum, Fehler, wartet auf Nutzer, ohne Aktion und Vorschlagsstatus. Unbekannte Filterwerte werden nachvollziehbar abgewiesen.
- Sortierung: neueste Empfangszeit zuerst, alternativ letzte Bearbeitung; stabile ID als zweites Sortierkriterium. Fehlende Empfangszeit ist ausdrücklich gekennzeichnet.
- Seite standardmäßig 25, maximal 100 Einträge. Begrenzte Suchlänge, validierte Datumsgrenzen und erlaubte Sortierfelder; keine frei interpretierte Querysprache.

### Umsetzung

`ReviewViews` um eine Mailabfrage ergänzen oder in ein eigenes Lesemodul aufteilen. Zunächst ein konsistenter Scan der vorhandenen JSON-Dateien. Für große Bestände ein in-memory Index über ausschließlich zulässige Metadaten; Hauptthread invalidiert ihn bei Zustandsschreibzugriffen und Bereinigung. Kein zweiter persistierter Mailinhalt. Navigation bleibt auch bei Änderungen des Bestands definiert; bei Bedarf wird ein neuer Stand angezeigt.

Die Übersicht umfasst nur gespeicherte Vorgänge, keinen vollständigen IMAP-Posteingang. Automatisch als irrelevant bewertete Mails werden sichtbar, aber in 1.2 nicht still neu analysiert oder durch eine neue Schaltfläche umklassifiziert. Bestehende offene Relevanzfragen behalten ihre Aktionen.

**Abnahme:** Gemischter synthetischer Bestand mit allen Zuständen, mehreren Vorschlägen je Mail, fehlenden Daten und beschädigten Dateien; Suche, Filterkombinationen, Grenzzeiten, Pagination und sichere HTML-Ausgabe. 10.000 synthetische Vorgänge als Performanceprüfung: nach Indexaufbau Listenanfragen ohne unbeschränkte Dateiscans; gemessene Zeiten dokumentieren, keine hardwareunabhängigen Versprechen.

## 6. Feature B – Vollständiger Entscheidungs- und Versionsverlauf

### Datenmodell

- Aktuelle Vorschläge direkt über `ProposalRepository` auflösen, nicht über die letzten acht erledigten Einträge. Gespeicherte Identitäten und Zugehörigkeit zur Mail prüfen.
- Vorhandene Versionsdateien, Aktionsbuch und Zustände lesen; Unterschiede zwischen Versionen als Feldänderungen anzeigen. Historische Versionen haben keine Aktionsformulare.
- Neue lokale Ereignisse erhalten ID, Mail-/Vorschlags-ID, Version, Zeitpunkt, Quelle, Ereignisart, Ergebnis und Referenz auf den fachlichen Vorgang. Beispiele: Vorschlag erzeugt, Antwort angenommen, Revision gespeichert, verworfen, bestätigt, Anlage erfolgreich/fehlgeschlagen/unklar.
- Keine Sitzungs-Token, keine Rohantworten, keine Kopplungscodes. Quelle wird als Telegram/Web/System angezeigt; keine unnötigen Gerätekennungen.
- Vorschlagstext bleibt in den bereits vorhandenen Versionsdaten; Ereignisse duplizieren keine kompletten Beschreibungen oder Mailtexte.

### Konsistenz und Wiederanlauf

Lesbarer Zustand pro Vorgang, etwa `history-<mail_id>.json`, mit Schemaversion und begrenzter Aufbewahrung. Ereignisschlüssel aus fachlichem Vorgang und Ereignisart ableiten. Fachlicher Zustand und Ereignis werden über eine wiederaufnehmbare Operation verbunden: Nach Absturz fehlendes Ereignis aus gespeicherter Operationsreferenz ergänzen, niemals eine externe Wirkung wiederholen. Ein JSONL-Debuglog ist nicht die einzige Quelle des sichtbaren Verlaufs.

Für Altbestände nur belegte Zustands- und Versionsdaten anzeigen, mit Kennzeichnung „historischer Ablauf nicht vollständig erfasst“. Keine erfundenen Zeitpunkte oder Benutzerentscheidungen. Filter nach Zeitraum, Ereignis, Zustand und Vorschlagsart; Detailzugriff unabhängig von Pagination.

**Abnahme:** Regressionstest für einen Vorschlag außerhalb der letzten acht Einträge; lückenhafte Altbestände, Revisionen, Absturz zwischen Zustand/Ereignis, doppelte Befehle, kanalübergreifende Entscheidungen und Aufbewahrungsbereinigung.

## 7. Feature C – Zusammenfassungen und Analyseansicht

Maildetails erhalten Abschnitte **Zusammenfassung**, **Relevanz und Themen**, **Erkannte Aktionen**, **Verlauf** und **Originalmail**. Zusammenfassung und Fristen auch anzeigen, wenn keine Aufgabe oder kein Termin erkannt wurde. Relevanzbegründung ist eine Modellbewertung, keine verifizierte Tatsache.

- Modellentscheidung und gegebenenfalls menschliche Entscheidung getrennt darstellen. Themen anhand stabiler IDs und, für neue Analysen, des Namens zum Analysezeitpunkt auflösen. Deaktivierte oder inzwischen umbenannte Themen bleiben nachvollziehbar.
- Entscheidungsquelle für neue Verarbeitung speichern: Vorfilter, JEV, Standard-LLM-Fallback, Ollama oder Mensch; fehlende historische Quelle als unbekannt anzeigen.
- Keine Zusammenfassungen für irrelevante Mails nachträglich erzeugen. Unterschiedliche Leerzustände: nicht erforderlich, noch nicht erstellt, fehlgeschlagen, nie gespeichert oder nach Aufbewahrung entfernt.
- Keine LLM-Abfrage beim Öffnen einer Seite. Keine Rohprompts oder internen Reasoning-Inhalte im Web.

### Aufbewahrung als notwendige Voraussetzung

Vor der Migration einen eigenen kompakten, versionierten Analysezustand definieren, etwa `MailAnalysisRecord` mit Entscheidungsquelle, Endergebnis, Themenbezug, Zusammenfassung und Erfassungszeit. Bestehende `MailState`-Schemaversion 9 nur mit registrierter, getesteter Migration erweitern; bereits entfernte Daten lassen sich nicht rekonstruieren.

Zielkonfiguration in `config.yaml`: `retention.analysis_days: 30` für kompakte Analyseinhalte und `retention.history_days: 90` für den Anzeigeverlauf. Bestehende Installationen erhalten bei fehlendem `analysis_days` zunächst das bisherige Bereinigungsverhalten; das neue Beispiel erklärt die bewusste Aktivierung von 30 Tagen. Offene Vorgänge bleiben geschützt. Die GUI nennt Verfügbarkeit und Frist; eine erfolgreiche Ansicht darf die Frist nicht verlängern.

Bei Analysebereinigung auch Zusammenfassungs-Suchindex und personenbezogene Ereignisdetails entfernen. Minimal nötige Dubletten-, Bestätigungs- und Wiederanlaufreferenzen bleiben nach bestehender Fachregel erhalten. Fristen für diese Sicherheitsreferenzen dürfen nicht unbesehen an den Anzeigeverlauf gekoppelt werden.

**Abnahme:** Relevante Mail ohne Aktion, irrelevante Mail, offene Klärung, gelöschte Inhalte, geänderte Themennamen und Migration sämtlicher unterstützter Altzustände. Retentiontests belegen, dass Web und Index keine gelöschten Daten weiter zeigen.

## 8. Feature D – Erweiterter Betriebsstatus

`ReviewViews.system()` und laufende Statusarbeiten integrieren. Zusätzlich ein rein lesbarer Laufzeitschnappschuss mit Lauf-ID, Mail-ID, Schritt, Beginn des Schritts, letzter Aktivität und nächstem geplanten Poll. Laufzeit über monotone Uhr messen, Zeitpunkte in UTC speichern und in konfigurierter Zeitzone anzeigen.

Anzeige:

- Aktuelle Analysephase und bisherige Dauer, wartende Nutzerentscheidung oder Leerlauf.
- Analysierter Anteil des aktuellen Maildurchlaufs; offene Entscheidungen separat. Kein scheinbarer Gesamtfortschritt, der Analyseabschluss mit externer Anlage verwechselt.
- Letzte erfolgreiche Mailverarbeitung und letzter bekannter erfolgreicher Dienstkontakt.
- Fehlerliste mit betroffenem Vorgang, Schritt, verständlicher Ursache, Zeitpunkt, Wiederholbarkeit und `deferred_until`.
- Wartende Webaktionen, Telegram-Rückstau und lokale Aufrufbegrenzung.
- Aktiver Trockenlaufmodus und tatsächlich aktivierter LLM-Pfad.

Kein automatischer Zugriffstest beim Laden der Seite. Dienstzustände heißen „zuletzt erfolgreich“ bzw. „unbekannt“, nicht unbelegt „verbunden“. Keine Stacktraces, Geheimnisse oder ungefilterten Anbieterantworten. Manuelles „Erneut versuchen“ ist in 1.2 nicht nötig; automatische fachliche Retryregeln bleiben maßgeblich.

Runtime-Zustand liegt unter einer kleinen Thread-Sperre, ohne den gesamten Zustand während eines HTTP-Aufrufs zu halten. Neustart zeigt zunächst „kein aktiver Schritt“; historische Dauer zählt nicht als laufende Verarbeitung weiter. JS-Aktualisierung berücksichtigt Änderungen auf der Statusseite selbst, nicht nur den Fingerprint offener Vorschläge.

**Abnahme:** Alle Schritte, lange LLM-Antwort, Retry-Wartezeit, fehlgeschlagener Dienst, Neustart, PC nicht erreichbar und getrennte Analyse-/Reviewfortschritte; kein externer Aufruf durch Anzeige.

## 9. Feature E – Kosten- und Zeitübersicht

### Erfassung statt Rohlog-Abhängigkeit

Gemeinsame typisierte Telemetrie an den Adaptergrenzen für OpenRouter, JEV und Ollama vorsehen. Jeder tatsächliche Versuch erhält lokale eindeutige Attempt-ID, übergeordnete logische Call-ID, optional Anbieter-ID, Mail-/Laufbezug, Modus (`standard`, `local`, `decision_test`), Schritt, Modell, Anbieter, Start, Dauer, Status, Tokenzahlen und gemeldete Kosten/Währung.

Fehlgeschlagene, verworfene und wiederholte Antworten gehören zur realen Belastung. Cachetreffer ohne externen Aufruf sind gesondert und dürfen nicht als neue Rechnung zählen. JEV plus Fallback sind zwei tatsächliche Aufrufe. Anbieter-IDs allein sind insbesondere bei Ollama kein verlässlicher Deduplizierungsschlüssel.

Contentfreie Metriken als separates `logs/metrics/llm.jsonl`; begrenzte, atomar geschriebene Tagesaggregate im JSON-Zustand für schnelle Auswertungen. Hauptthread übernimmt Adapterergebnisse oder drainbare Metrikereignisse; keine parallelen fachlichen Zustandsänderungen. Aggregate führen verarbeitete Quellpositionen/Attempt-IDs zur sicheren Wiederaufnahme. Logrotation und Abstürze dürfen keine Doppelzählung erzeugen. Lücken werden als unvollständige Erfassung gekennzeichnet.

Bestehende Logs optional einmalig lokal importieren, nur bekannte Metadatenfelder lesen. Keine vollständigen Prompts in den Index übernehmen. Unvollständige Altlogs nicht als vollständige Abrechnung ausgeben. Anzeige funktioniert unabhängig vom Schalter für vollständige LLM-Inhalte.

### Berechnung und Darstellung

- Zeitraum: heute, 7/30 Tage und frei gewählt. Filter nach Modell, Anbieter, Schritt und Modus. Produktions- und Decision-Test-Aufrufe standardmäßig getrennt.
- Kennzahlen: Versuchszahl, Erfolgs-/Fehlerrate, bekannte Kosten, Anteil mit unbekannten Kosten, Tokenzahlen soweit vorhanden, Median, Mittelwert und p95 der Dauer. p95 über tatsächlich verfügbare Einzeldauern innerhalb der Metrikfrist, nicht durch Mittelung von Tagesperzentilen.
- Cloudkosten primär aus Anbieterangaben; fehlend bedeutet unbekannt, nicht null. Geschätzte Tokenkosten nur mit versionierter Preisquelle und Kennzeichnung als Schätzung. Keine automatisch aus dem Internet geholten Preise nötig.
- USD und EUR getrennt anzeigen, solange kein expliziter Wechselkurs mit Datum hinterlegt ist. Keine implizite Gleichsetzung. Geldrechnung mit Dezimalarithmetik.
- Ollama-Stromschätzung: `Leistung_W / 1000 × Dauer_s / 3600 × Preis_EUR_kWh`. Ausgangswert aus dem bisherigen Versuch: **300 W und 0,30 EUR/kWh**, also **0,09 EUR/h** und **0,000025 EUR/s**. Als konfigurierbare Annahme kennzeichnen, nicht als aktuelle Messung.
- Leistung gilt für den ganzen Server. Bei parallelen Aufrufen belegte Zeitintervalle zusammenführen, damit dieselbe Sekunde nicht mehrfach berechnet wird. Aufrufanteile gegebenenfalls nach Laufzeit aufteilen und als Zuordnungsschätzung kennzeichnen. Andere Serverlast, Leerlauf, Hardwarekosten und Messungenauigkeit sind nicht enthalten.
- Summierte Aufrufdauer, verstrichene Durchlaufzeit und Wartezeit auf Menschen getrennt darstellen. Daraus keine ungeprüfte Zeitersparnis oder Qualitätsgleichheit ableiten.

Zielkonfiguration: `metrics.enabled`, `metrics.retention_days`, `metrics.ollama_power_watts`, `metrics.electricity_eur_per_kwh`, optional Wechselkurs samt Datum in `config.yaml`. Vorschlag: Erfassung aktiviert, Einzeldaten 90 Tage; ältere Tagesaggregate ohne Mailbezug. Nutzer müssen die Annahmen vor wirtschaftlichen Schlussfolgerungen prüfen können.

**Abnahme:** Mit synthetischen Zahlen verifizierte Formeln, fehlende Usage/Kosten, Nullkosten, Retries, gleiche Anbieter-ID, Parallelität, zwei Währungen, Rotation, Neustart, beschädigte Logzeile und getrennte Test-/Produktionssummen. Rundung erst in der Darstellung.

## 10. Feature F – Strukturierte Vorschlagsbearbeitung

Formularfelder nach Typ:

- Gemeinsam: Titel, Beschreibung, zulässiges Ziel aus konfigurierter Auswahl.
- Aufgabe: Frist ohne Uhrzeit oder mit Uhrzeit und Zeitzone.
- Termin: Beginn, Ende, Ganztägigkeit, Ort und geprüfter Videolink.

Sicherheitsfelder wie Autorisierung, Version, Aktionsbuch, externe IDs, Beleg, Zuständigkeit und Sonderbestätigungen sind keine frei editierbaren Hidden-Felder. Unbekannte Felder zurückweisen. Optionales Leeren muss typisiert von „unverändert“ unterscheidbar sein.

### Fachlicher Ablauf

1. Aktuelle offene Version laden, Formular mit CSRF und Idempotenzschlüssel anzeigen.
2. Eingaben serverseitig mit einem eigenen geschlossenen `ProposalEditPatch` validieren. Keine freie Übernahme von `Proposal.model_dump()` aus dem Browser.
3. Hauptthread prüft Sitzung, erwartete Version und erlaubten Zustand erneut.
4. Bounded Patch über eine gemeinsame Revisionsfunktion anwenden; vorhandene Normalisierung, Invarianten, Ziel- und Dublettenprüfung wiederverwenden. Eindeutige strukturierte Eingaben benötigen keinen LLM-Aufruf.
5. Zeiten in der konfigurierten IANA-Zeitzone interpretieren. Mehrdeutige Sommer-/Winterzeit verlangt Offsetauswahl, nicht existierende Uhrzeit wird abgewiesen; Ende muss nach Beginn liegen.
6. Bei echter Änderung neue Version erzeugen, alte Bestätigungen verwerfen, offene Fragen aus den Fachregeln neu bestimmen und Versionsereignis speichern. Keine Änderung: keine neue Version.
7. Neue Version mit Vorher/Nachher anzeigen; Telegram erhält den aktuellen Vorschlag über die bestehende Outbox. Veraltete Schaltflächen bleiben wirkungslos.
8. Erst die separate zulässige Bestätigung der neuen Version kann extern schreiben. Keine Bearbeitung für `WRITING`, `UNCERTAIN` oder bereits angelegte Vorschläge; diese bleiben lesend.

Freitext „Ändern“ und Rückfragen bleiben zusätzlich erhalten. Eingaben dürfen fehlende Zustimmung, widersprüchliche Verantwortlichkeit oder Sonderbestätigungen nicht automatisch auflösen. Falls Fachregeln noch Fragen erfordern, bleibt der Vorschlag in Klärung.

**Abnahme:** Beide Typen, leere Felder, ungültige Ziele/Links, Sommerzeit, Ganztägigkeit, parallel eingehende Telegramantwort, doppelte Übermittlung, alte Version, Neustart und erneute Bestätigung. Kein externer Schreibaufruf durch Speichern.

## 11. Feature G – Themenverwaltung mit sicherer Übernahme

Themen aus `topics.yaml` und ausgeschlossene Kategorien aus `irrelevant_topics.yaml` getrennt anzeigen und bearbeiten. Eingabefelder: Name, Beschreibung, Beispiele, Ausschlüsse, aktiviert. IDs stabil; IDänderung und endgültiges Löschen bestehender Themen sind nicht vorgesehen. Deaktivieren erhält historische Zuordnungen. Mindestens ein relevantes Thema bleibt aktiv.

### Schreib- und Aktivierungsmodell

- Typisierter Konfigurationsbefehl mit Sessionautor, Idempotenzschlüssel und erwarteten Datei-/Konfigurationshashes. Vom Client gelieferte Pfade niemals verwenden.
- Vor dem Schreiben den aktuellen Dateiinhalt erneut prüfen. Bei manueller Bearbeitung, parallelem Lernlauf oder anderem Webgerät 409 mit Diff statt Überschreiben.
- Gemeinsamen atomaren YAML-Schreibdienst aus `learning.py` herauslösen und für Web und Lernmodus verwenden. Vollständiges Kandidatenmodell vor dem Schreiben validieren, Sonderzeichen nicht als YAML-Code interpretieren.
- Kandidatenkonfiguration einschließlich betroffener Fingerprints und Dienstdaten zunächst vollständig aufbauen. Fehlende Berechtigungen, schreibgeschützte Docker-Mounts und ungültige Dateien führen zu einem verständlichen Ergebnis ohne Teilübernahme.
- Änderungen als wiederaufnehmbare Operation journalisieren. Pro Befehl eine Themendatei ersetzen; dateiübergreifende Umordnung ist nicht Teil des Formulars. Nach Absturz entscheidet Dateihash/Kandidatenrevision über den Abschluss, kein blindes Überschreiben.
- Hauptthread übernimmt Themen und neue Fingerprints an der Grenze zwischen zwei Mailanalysen. Die laufende Mail behält ihren konsistenten Konfigurationsschnappschuss.
- Bereits begonnene Vorgänge behalten ihre alte Revision; neue Mails nutzen die neue. Bestehende Vorschläge und ihre Bestätigungen werden nicht automatisch geändert. Die heutige Fingerprintbehandlung in `application.py` muss dafür explizit angepasst und getestet werden.
- Oberfläche zeigt gespeicherte und aktive Themenrevision sowie noch ausstehende Übernahme. Neustart baut dieselbe gespeicherte Revision auf. YAML-Dateien bleiben die maßgebliche Konfiguration; das Journal ist kein alternativer Themenbestand.
- Die Absender-Vorfilter in `IrrelevantSenders` dürfen durch Deaktivierung einer Kategorie nicht still unverändert als themenabhängig gelten. Herkunft vorhandener Einträge prüfen: ohne Zuordnungsbeleg auf unabhängige Vorfilter hinweisen; gezielte Bearbeitung dieser Listen ist außerhalb von 1.2. Keine automatische Löschung.

Neue Themen wirken nicht rückwirkend auf alle Mails. Es gibt keinen automatisch gestarteten Lernlauf und keine dadurch ausgelösten LLM-Kosten. Das Formular erklärt diese Wirkung vor dem Speichern.

**Abnahme:** Erstellen, Ändern, Deaktivieren beider Listen, doppelte IDs, letztes aktives Thema, paralleler Lernlauf, manuelle Dateiänderung, Schreibfehler, Absturz vor/nach atomarem Austausch, laufende Analyse, Neustart und unveränderte alte Vorschläge.

## 12. Feature H – Einstellungsseite mit sicheren Änderungen

Eigenes `EffectiveSettingsView` ausschließlich aus einer Positivliste zulässiger Felder erzeugen. Keine automatische Serialisierung von `Secrets`, `.env`, Rohkonfiguration oder Clientobjekten.

Anzeige: Anwendungs-/Schemaversion, Standard-/Ollama-Modus, Relevanzmodell und Fallback, Modelle pro weiterem Schritt, erlaubte LLM-Parameter, Timeout/Retry/Limits, Zeitzone, Pollintervall, Trockenlauf, Aufbewahrung, Webbindung und aktiver Themenstand. Anbieter-/Serveradressen nur sanitisiert, ohne URL-Benutzerinfo oder Queryparameter. Kontonamen, Chat-IDs und Ziel-IDs nur wenn für die Bedienung nötig und geeignet maskiert.

Quelle je Feld nennen: `config.yaml`, `prompts.yaml` oder tatsächlich verwendete separate Decision-/Laya-Promptdatei sowie Startparameter. Gestartete effektive Konfiguration von seitdem auf Datenträger geänderten Dateien unterscheiden; externe Änderungen ohne Übernahme heißen „Neustart/Übernahme erforderlich“.

Prompttexte, Secrets und Authentifizierungszustände nicht ausgeben. Modelle/Parameter bleiben in Promptdateien, Anwendungseinstellungen in `config.yaml`, Themen in Themendateien. Es gibt in 1.2 keine Schaltflächen zum freien Modellwechsel, Dienstzugriffstest oder Geheimnisbearbeiten. Die folgenden Anwendungseinstellungen sind dagegen bearbeitbar.

### Bearbeitbare Settings und Übernahmezeitpunkt

| Bereich | Felder der Einstellungsseite | Wirkung |
| --- | --- | --- |
| Mailabruf | `poll_interval_seconds` | Nächste Leerlauf-/Pollplanung; keine zweite parallel gestartete Abfrage |
| Darstellung | `timezone` | Neue Anzeigen und neue Verarbeitung nach sicherer Übernahme; vorhandene Zeitpunkte werden nicht umgeschrieben |
| Aufrufbudget und Mailgrenzen | `limits.llm_calls_per_minute`, `limits.max_mail_bytes`, `limits.max_llm_payload_bytes` | Nächster sicherer Verarbeitungspunkt; Budgethistorie nicht zurücksetzen |
| Timeouts und Wiederholungen | `timeouts` der Dienste einschließlich Ollama: Timeout, Retries und Backoff; ausgewählte `retries` für Interpretation/Revision | Speichern für nächsten Start; in 1.2 keine Clients während laufender Requests austauschen |
| Aufbewahrung | `retention.full_mail_days`, `debug_llm_days`, `analysis_days`, `history_days` | Nächster Bereinigungslauf; Verkürzung mit gesondertem Hinweis auf irreversible Entfernung |
| Protokollierung | Konsolen-/Dateilevel und Opt-in für vollständige LLM-Anfragen/-Antworten | Nächster Start; aktivierte Inhaltsprotokollierung ausdrücklich bestätigen |
| Wirtschaftlichkeit | Metrikfrist, Ollama-Leistung und Strompreis; optionaler Wechselkurs mit Datum | Neue Messungen/Schätzungen; historische Annahmen erhalten und Änderung datieren |
| Trockenlauf | `test_mode` | Nächster Start; Wechsel in echten Schreibbetrieb deutlich bestätigen, vorhandene Vorschläge nicht automatisch bestätigen |
| Ziele | Konfigurierte Todoist-/Kalenderziele aus einer begrenzten Auswahl bekannter zulässiger Ziele | Nächster Start; vorhandene Vorschläge behalten ihren Zielbezug und benötigen bei Änderung eine neue Version |

Grenzen stammen aus den Pydantic-Konfigurationsmodellen, nicht aus abweichenden HTML-Konstanten. Zeitzonen gegen IANA validieren; Retention unterstützt die bestehenden Werte für Tage, `disabled` und `unlimited`, soweit die jeweilige neue Frist das zulässt. Nicht angebotene Einstellungen bleiben lesend. Web-Host, Port, erlaubte Hosts, Datenverzeichnis, IMAP-Konten, Tokens und Sitzungsgeheimnisse werden nicht über das Formular geändert; dadurch sperrt der Nutzer sich nicht versehentlich aus.

### Speicherung, Konflikte und Aktivierung

1. Formular zeigt wirksamen und gespeicherten Wert sowie Kennzeichnung „sofort/sicherer Verarbeitungspunkt“ oder „nächster Start“. Startparameter haben sichtbaren Vorrang; übersteuerte Werte lassen sich nicht scheinbar aktiv ändern.
2. `SettingsPatch` ist ein geschlossenes, typisiertes Modell. Der Server ergänzt Autor, CSRF, Idempotenzschlüssel und erwarteten Dateihash; weder Dateipfad noch Geheimnisse kommen aus dem Browser.
3. Vor dem Speichern vollständige Kandidatenkonfiguration validieren, Differenz und Folgen anzeigen. Eine Bestätigung bindet sich an genau diese Kandidatenrevision. Fremde/manuelle Dateiänderung ergibt 409 statt Überschreiben.
4. Über den gemeinsamen Konfigurationsdienst im Hauptthread `config.yaml` atomar ersetzen. Unbekannte/nicht angebotene Werte erhalten; keine Geheimnisse aufnehmen. Dateimodus und Schreibrechte beachten. YAML-Kommentarverlust vermeiden oder vor Umsetzung einen verlustarmen Weg festlegen und dokumentieren.
5. Anwendung separat aktivieren: sofort freigegebene Felder an sicherer Grenze übernehmen, restartpflichtige Felder nur vormerken. Journal und Hashes ermöglichen eindeutige Wiederaufnahme bei Absturz; ein Ladefehler lässt die aktive Konfiguration unverändert.
6. Ein verkürzter Aufrufgrenzwert nutzt das gemeinsame bestehende Budget; bereits gezählte Aufrufe bleiben gezählt. Änderungen starten keine erneute Mailanalyse und führen keine alten Aktionen automatisch aus.
7. Verkürzte Retention und Inhaltslogging brauchen eine konkrete Folgenbestätigung. Ausgeschaltetes Inhaltslogging löscht nicht automatisch bereits bestehende Logs. Historische Stromkosten werden nicht still mit einer neuen Leistungsannahme neu berechnet; eine bewusste Szenariorechnung ist gesondert gekennzeichnet.
8. „Gespeichert – Neustart erforderlich“ ist ein gültiges Ergebnis, aber nicht „bereits aktiv“. Ein kontrollierter Stopp kann anschließend über Feature I ausgelöst werden; automatischer Neustart ist nicht vorgesehen.

**Abnahme:** Beide LLM-Modi, Fallback, Startparameter, geänderte Dateien und maskierte sensible Angaben. Zusätzlich jede Settinggruppe mit gültigen/ungültigen Werten, Konflikt, Schreibfehler, Doppelübermittlung, Neustart, aktiver Analyse und korrektem Übernahmezeitpunkt testen. Regressionen gegen Budgetreset, unbeabsichtigte Retentionlöschung, Logging ohne Opt-in und automatische externe Anlage. Synthetische Geheimnisse dürfen in HTML, JSON, Fehlern und Logs nicht vorkommen.

## 13. Feature I – Mailhelp kontrolliert aus der Weboberfläche beenden

### Bedienung und Autorisierung

Unter Einstellungen steht „Mailhelp beenden“. Ein erster Aufruf öffnet eine Bestätigungsseite mit aktivem Vorgang, Warteschlangen und dem Hinweis: Danach ist auch die Weboberfläche nicht erreichbar; erneut starten muss man Mailhelp am PC oder über den Betreiber des Containers/Dienstes. Der Vorgang fährt weder Windows noch den Docker-Host herunter.

Erst ein ausdrücklich bestätigter POST mit Sitzung, CSRF, Idempotenzschlüssel und aktueller Prozess-/Startkennung fordert den Stopp an. GET, Prefetching und Linkvorschau beenden nichts. Der Browser zeigt zunächst „Beenden angefordert“ und die letzte bekannte Phase. Verbindungsabbruch allein beweist keinen erfolgreichen Shutdown; entsprechend „Verbindung beendet – Abschluss nicht mehr überprüfbar“ anzeigen, falls keine abschließende Rückmeldung vorliegt.

### Technischer Ablauf

- Bestehende `Application.stop()`, `stop_event` und den `finally`-Aufräumweg in `Application.run()` wiederverwenden. Keine `os._exit`, Prozesskills oder Shellbefehle aus einer Webroute. Webserver-Shutdown nicht aus seinem Serving-Thread aufrufen.
- Stopanforderung als eigener typisierter Steuerbefehl behandeln, nicht als normale Vorschlagsaktion. Sitzung bei Annahme und Übergabe erneut prüfen. Eingang idempotent quittieren und Antwort ausliefern, bevor der Server geschlossen werden darf.
- Ein kleiner Lifecycle-Koordinator reicht nach der Antwort das Stoppsignal unmittelbar weiter und weckt den Hauptthread. Dieses Signal darf auch während eines blockierenden LLM-Aufrufs gesetzt werden; persistente fachliche Abschlussänderungen verbleiben im Hauptthread. Ein bloßes Einreihen hinter einer langen Analyse reicht nicht.
- Zustand `running → stop_requested → stopping → stopped` mit Prozesskennung und Zeitpunkten sichtbar machen. Ab `stop_requested` keine neuen Analysen und keine neuen fachlichen Änderungs-/Bestätigungsbefehle annehmen; GET-Status bis zum tatsächlichen Serverstopp verfügbar halten. Wiederholter Stopp liefert dasselbe Ergebnis.
- Laufenden synchronen Request nicht gewaltsam abbrechen: Er darf bis zu seinem konfigurierten Timeout auslaufen; Retry-/Backoff-Warten muss das Stoppsignal beachten. Die Oberfläche nennt diese mögliche Wartezeit, insbesondere bei Ollama. Keine weiteren LLM-Schritte nach dem sicheren Abbruchpunkt starten.
- Bereits begonnene externe Schreiboperation normal abschließen oder bei unklarem Ausgang als abzugleichen persistieren. Shutdown ist weder Erfolg noch Autorisierung für eine Wiederholung. Kein neuer externer Schreibversuch wird zum Aufräumen ausgelöst.
- Noch nicht ausgeführte Befehle bleiben nachvollziehbar gespeichert. Beim Neustart erneut Sitzung, erwartete Version und ursprüngliche Autorisierung prüfen; `running` wie bisher abgleichen. Eine neue externe Aktion benötigt die geltende Bestätigung; Shutdown erzeugt keine Ersatzbestätigung.
- Aktuelle Analyse, Konfigurationsoperationen und Verlauf an sicheren Punkten sichern, Logs flushen, Receiver/Webserver stoppen und Ressourcen nach bestehendem Contextmanager freigeben. Shutdown mit SIGINT/SIGTERM muss denselben Pfad nutzen.
- Eine Stopanforderung ist an diese Prozessinstanz gebunden. Beim nächsten Start als abgeschlossen/überholt behandeln; niemals automatisch erneut ausführen und die neue Instanz sofort beenden. Für einen Neustart ausschließlich eine neue explizite Anforderung erlauben.
- Docker-/Dienst-Restartpolitik prüfen: Ein Supervisor kann den regulär beendeten Prozess automatisch neu starten. Dies wird in der Releaseanleitung erklärt und in der Oberfläche benannt, sofern bekannt; kein uneingeschränktes Versprechen, dass der Dienst dauerhaft ausgeschaltet bleibt. Host-/Supervisor-Konfiguration nicht heimlich ändern.

**Abnahme:** Stoppen im Leerlauf, während Relevanzfrage, LLM-Request, Retry-Wartezeit, Konfigurationsübernahme und externer Anlage; sichere Persistenz bei Timeout/unklarem Schreibresultat. CSRF, abgelaufene/widerrufene Sitzung, GET, Doppelclick, alte Prozesskennung, Antwort vor Serverstopp, Deadlockfreiheit, paralleles SIGTERM und Neustart ohne wiederholten Stop testen. Kein Kalender-/Todoist-Schreibzugriff durch Stoppen; keine fremden Prozesse oder Hostfunktionen werden beendet.

## 14. Geplante Modulstruktur

Bestehende Dienste erweitern, nicht duplizieren. Die folgenden neuen Modulnamen sind Vorschläge und werden beim Implementierungsstart mit dem aktuellen Arbeitsstand abgeglichen:

```text
src/mailhelp/
  review/
    queries.py             # Mail-/Verlaufsabfragen, Pagination und Suchindex
    history.py             # Versionierte Ereignisse und Wiederanlauf
    editing.py             # Typisierte Formularänderung und gemeinsame Revision
  metrics/
    models.py              # Inhaltfreie Aufruf-/Versuchsdaten
    recorder.py            # Erfassung und Rotation
    aggregation.py         # Tagesaggregate, Deduplizierung und Abfragen
    costs.py               # Dezimalrechnung und Stromannahmen
  configuration/
    topics.py              # Gemeinsame YAML-Persistenz und Themenbefehle
    effective.py           # Sichere Ansicht wirksamer Einstellungen
    settings.py            # SettingsPatch, atomare Speicherung und Aktivierung
  lifecycle.py             # Autorisierter Stop und geordneter Shutdown
  web/
    mail_pages.py          # Übersicht und Analyse
    history_pages.py       # Verlauf und historische Versionen
    settings_pages.py      # Themen, Settingformulare und Stopbestätigung
    metrics_pages.py       # Kosten und Zeiten
```

Vor einer Aufteilung Import- und Migrationspfade prüfen. Ein Konfigurationsbefehlsmodell erhält keine künstliche Mail-ID, nur um in `ReviewCommand` zu passen; stattdessen eine geschlossene Befehlsunion in der bestehenden Inbox mit kompatibler Schemamigration.

## 15. Umsetzung in überprüfbaren Phasen

| Phase | Arbeiten | Abnahme und Ergebnis |
| --- | --- | --- |
| 0 – Bestandsaufnahme | Aktuellen 1.1-Stand, laufende Statusarbeiten, Testbasis, Retention, Bestätigungsregel und Migrationsregister prüfen | Dokumentierte Ausgangslage; keine fremden Änderungen überschrieben; Freigabegrenze für externe Webaktionen geklärt |
| 1 – Datenbasis | Analyse-/Verlaufsschemas, Migration, Retention und direkte historische Detailauflösung | Altbestand ladbar; Regression für ältere Details; Bereinigung entfernt Inhalte einschließlich Index |
| 2 – Mailansichten | Mailqueries, Suchindex, Filter/Pagination und Analyseansicht | Features A und C mit Desktop-/Mobilansichten und Leer-/Fehlerzuständen vollständig |
| 3 – Verlauf | Ereigniserfassung, Idempotenz, Wiederanlauf, Versionsdiff und Verlaufsseite | Feature B, keine erfundenen Altinformationen und keine doppelte externe Wirkung |
| 4 – Betrieb | Systemlesemodelle integrieren, Laufzeitschnappschuss, Retry- und Fehlersichten | Feature D; Status ohne externe Aufrufe und mit eigenem Aktualisierungssignal |
| 5 – Wirtschaftlichkeit | Adaptermetriken, Import, Aggregate, Stromschätzung und Auswertungsseite | Feature E mit prüfbaren Formeln und unbekannten Kosten statt Scheingenauigkeit |
| 6 – Formulare | Gemeinsame Revision, Editbefehle, Zeitvalidierung und typabhängige Formulare | Feature F; neue Version, erneute Bestätigung, unveränderte Schreibgrenze |
| 7 – Konfiguration | Einstellungsformulare, Themenbefehle, atomare Speicherung und Übernahme | Features G und H; Konflikte, Budget, Retention, Restartpflicht und Geheimnisschutz geprüft |
| 8 – Programmstopp | Lifecycle-Koordinator, Bestätigung und geordneter Shutdown | Feature I; laufende Requests, externe Schreibresultate, wiederholte Stopps und Neustart sicher |
| 9 – Gesamtabnahme | Ende-zu-Ende, Migration, Performance, Retention, Plattformen und Dokumentation | Sämtliche Kriterien aus Abschnitt 16 erfüllt, Release 1.2.0 vorbereitet |

Jede Phase enthält ihre Tests und Dokumentationsänderungen. Keine spätere Testphase als Ersatz für die Abdeckung während der Implementierung. Phasen 4/5 können nach der Datenbasis unabhängig vorbereitet werden; Änderungen an gemeinsamem Zustand werden abgestimmt integriert.

## 16. Test- und Releasekriterien

- Gesamtsuite mit 100 % Zeilen- und 100 % Branch-Abdeckung für eigenen Pythoncode; kein Ausschluss neuer Module. JavaScript ebenfalls nach bestehender CI-Regel vollständig prüfen.
- Tests simulieren IMAP, OpenRouter/JEV/Ollama, Telegram, Kalender und Todoist mit synthetischen Daten. Keine produktiven Decision-Tests als automatisierte Abnahme.
- Jede schreibende Funktion: Erfolg, Validierung, fehlende Autorisierung, CSRF, Widerruf vor Ausführung, Versionskonflikt, doppelte Übermittlung und Neustart. Externe Schreibgrenzen separat testen.
- Windows-11- und Linux-/Docker-Prüfungen, atomare Dateioperationen und schreibgeschützte Mounts. Upgrade vom ältesten unterstützten Zustand und von 1.1 mit offenen Fragen/Befehlen.
- Browsertests für alle neuen Seiten in Desktop-, iPhone- und schmalem Mobilformat: keine Seitenüberläufe, Labels, Tastaturbedienung, Fokusführung, Kontrast, ausreichend große Tippflächen und unverlorene Formulartexte.
- Ohne JS funktionieren Suche, Filter, Formulare und Navigation. Offline keine personenbezogenen Daten im Cache, keine verzögert ausgeführten Aktionen. Abmelden entfernt Zugriff auch auf neue Seiten.
- Sicherheitsfälle: XSS in Betreff, Zusammenfassung, Themenname und Versionsdiff; Pfadmanipulation; bösartige Queryparameter; übergroße Formulare; Geheimnisse in Fehlermeldungen; Fremdhosts und gefälschte Proxyheader.
- Performance und Begrenzungen mit synthetischem Großbestand dokumentieren. Logauswertung nie unbeschränkt im HTTP-Thread; lange Locks dürfen Befehle und Mailanalyse nicht blockieren.
- Ende-zu-Ende: relevante Mail ohne Aktion finden; irrelevante Mail nachvollziehen; Vorschlag strukturiert ändern und die neue Version separat bestätigen; alten Vorgang wiederfinden; Themen speichern und Wirkung nur bei neuen Mails zeigen; Kosten korrekt zuordnen.
- README, Spezifikation, Konfigurationsbeispiele, Datenschutzunterlagen und Websitebeschreibung aktualisieren. Neue Dateien, Fristen und sichtbare Daten erklären; `docs/Release-1.2.md` mit Upgrade-/Rollbackhinweisen erstellen.
- Einstellungs- und Stop-Ende-zu-Ende: Pollintervall speichern und aktive Wirkung prüfen, restartpflichtigen Timeout speichern und als ausstehend anzeigen, Stopp bestätigen, neu starten und gespeicherte Konfiguration übernehmen; kein wiederholter Stop oder doppelter externer Effekt. Docker-Recoverypolitik gesondert prüfen.
- Rollback: Sicherung vor Migration dokumentieren, neue YAML-Schlüssel und Schemas benennen. Keine Behauptung, 1.1 könne neue Zustände ungeprüft lesen. Wiederherstellung offener Aktionen muss mit externem Aktionsbuch abgestimmt sein, um Doppelanlagen zu verhindern.
- Releaseversion in `pyproject.toml` und `src/mailhelp/__init__.py` konsistent setzen, CHANGELOG ergänzen. Bei Commits nach `main` zusätzlich die verbindliche Patchversionsregel aus `AGENTS.md` beachten.

## 17. Festgelegte Planungsentscheidungen und verbleibende Voraussetzungen

Festgelegt sind serverseitiges HTML, JSON/JSONL, kein neuer Cloudservice, bearbeitbare wichtige Anwendungseinstellungen, lesende Modelle/Prompts, kontrollierter Programmstopp, bearbeitbare Themen, deaktivieren statt löschen, explizite neue Vorschlagsversionen, getrennte Produktions-/Testmetriken und begrenzte Aufbewahrung.

Vor Implementierung konkret zu prüfen sind die inzwischen integrierten 1.1-Änderungen, der Umfang vorhandener historischer Versionsdateien und die genaue Migration der bisherigen Fingerprintbehandlung. Fehlende Altinformationen werden sichtbar als unbekannt behandelt.

Die Freigabe für externe Webschreibaktionen wurde am 11. Oktober 2026 ausdrücklich erteilt; die Sicherheitsbedingungen aus Abschnitt 3 bleiben verbindlich. Die angenommene Ollama-Leistung von 300 W ist ein konfigurierbarer Rechenwert, keine zugesicherte Messung. Für die Planerstellung werden weder laufende Mailtests gestartet noch Anwendungseinstellungen geändert.
