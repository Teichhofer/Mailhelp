# Mailhelp 8.9 – Extraktionsqualität und belastbare Abnahme

**Stand:** 28.11.2026. **Status:** Abgeschlossen mit 8.9.5 ([Release 8.9](Release-8.9.md)); Auftrag des Betreibers vom 28.11.2026. Umgesetzt: AP1 mit
8.9.1 ([Bewertungsvertrag v5](Bewertungsvertrag-v5.md), Korpus v5, `quality-reports/baseline-8.9.json`), AP2 mit
8.9.2 (Prüfer, Evaluation und Prompt-Gate nach Vertrag v5), AP3 mit 8.9.3 (Wochentag der Quelle), AP5 mit 8.9.4 (Latenzphasen; Messung ab dem Eingabeereignis laut Betreiberentscheidung vom 28.11.2026), AP4 und AP6 mit 8.9.5 (Promptregeln, Abnahme, aktive Baseline). Vorhandene
lokale Promptentwürfe und Audits bilden die Ausgangsbasis, keine erfolgreiche Abnahme von Version 8.9.

**Zielversion:** 8.9, erste Auslieferung 8.9.1. Weitere Commits in `main` und
`beta` erhöhen die Patchversion gemäß den Entwicklungsregeln.

Der Plan übernimmt den Reparaturplan zur Extraktionsqualität vollständig als
Versionsumfang von 8.9. Die [Planung 8.8](Planung-8.8.md) für Kundenmodus und OAuth
bleibt davon unverändert.

**Grundlagen:** [Audit](../quality-reports/quality-audit-2026-11-26.md),
[Restprüfungen](../quality-reports/remaining-tests-2026-11-26.md),
[Entwicklungsregeln](../AGENTS.md),
[Qualitätsanleitung](Einrichtung-und-Qualitaetspruefung.md).

## Ziel

Ein anders formulierter richtiger Titel darf nicht als verlorene Aufgabe gelten.
Eine falsche Handlung, Zuständigkeit oder Uhrzeit darf durch einen ähnlichen Titel
aber auch nicht als richtig bestehen. Relevante Terminänderungen müssen den
Verarbeitungsweg erreichen, und Widersprüche in der Quelle müssen bis zur Klärung
erhalten bleiben. Die frühere Ankunftszeit bleibt berücksichtigt.

Die Umsetzung behält versionsbezogene Freigabe, Sitzung, CSRF-Prüfung,
Idempotenz und Abgleich unklarer Schreibresultate bei. Alle Tests verwenden
synthetische Daten und simulierte Schreibdienste. Bestehende externe Einträge
werden durch diese Reparatur nicht nachträglich automatisch geändert.

## Ausgangslage

- Sechs Aufgaben- und drei Terminpaare sind belegte Titel-Zuordnungsartefakte.
- Zwei vermeintlich fehlende Aufgaben sind bereits als leere Alternative erlaubt.
- Kalenderbehandlung, Teilnahmeannahmen und einige Referenzerwartungen widersprechen
  den aktuellen Anweisungen teilweise.
- Die Relevanzstufe verwirft eine konkrete Raumänderung und eine Absage.
- Wochentag, Wiederholungsangabe oder Bezugsdatum gehen teilweise verloren.
- Ein Tagesplan überschreitet das Ausgabelimit; im separaten Wiederholungslauf
  stimmt die Zuordnung zur Person nicht.
- Der letzte Python-Lauf erreicht 100 % Zeilen- und Branch-Abdeckung. Offen sind
  die Modellabnahme, Suchlatenz unter paralleler Browserlast und zwei
  JavaScript-Abdeckungslücken.

Die alten Messberichte und der eingefrorene v4-Korpus bleiben als historische
Nachweise erhalten. Aus dem Audit wird keine nachträglich grüne Baseline gemacht.

## Reihenfolge und Abhängigkeiten

| Paket | Inhalt | Abhängigkeit | Fertig, wenn … |
| --- | --- | --- | --- |
| AP1 | Bewertungs- und Fachvertrag festlegen | Audit | Widersprüche entschieden und neue Referenzen vor Modellläufen eingefroren sind |
| AP2 | Aktionszuordnung und Qualitätsgate reparieren | AP1 | Paraphrasen, falsche Verben, Alternativen, Feldfehler und Ausgabereihenfolgen korrekt geprüft werden |
| AP3 | Quellenbezug und Datumsvalidierung sichern | AP1 | Der bekannte Wochentagswiderspruch auch nach verkürzter Extraktion als Datumsproblem zur Klärung führt |
| AP4 | Relevanz und Extraktionsregeln gezielt korrigieren | AP1, AP3 | Die echten Auditfälle und ihre Gegenbeispiele im tatsächlichen Verarbeitungsweg bestehen |
| AP5 | Suchlatenz und JavaScript-Abdeckung | unabhängig von AP2–AP4 | Die unveränderte 300-ms-Grenze im Parallelbetrieb und vollständige JS-Abdeckung erreicht werden |
| AP6 | Unabhängige Kontrollfälle und endgültige Abnahme | AP2–AP5 | Modellvergleich, Gate, vollständige Python- und Browserprüfung erfolgreich sind |

AP2 und AP3 können in getrennten Änderungen umgesetzt werden. Für die Bewertung
weiterer Promptänderungen muss AP2 jedoch zuerst belastbar sein. Python-Gesamtprüfung
und Browsersuite laufen weiterhin niemals gleichzeitig.

## AP1 – Eindeutigen Vertrag und neue Referenzversion festlegen

**Vorgeschlagene Zielregeln:**

1. **Kalenderbehandlung:** „Termin vormerken“, „Kalendereintrag ändern“ und eine
   reine Raum-/Zeitänderung ergeben die entsprechende Kalenderaktion. Keine
   zweite Aufgabe für dieselbe Kalenderhandlung. Eine zusätzliche Anmeldung,
   Rückmeldung, Vorbereitung oder Benachrichtigung bleibt eine eigene Aufgabe.
   Die widersprechende Regel über administrative Kalender-Folgeaufgaben wird
   damit ausdrücklich ersetzt, nicht durch ein weiteres Beispiel überlagert.
2. **Teilnahme:** Eine eigene Einladung oder belegte Einteilung rechtfertigt
   `user`. Eine allgemeine Terminliste allein rechtfertigt keine sichere eigene
   Teilnahme. Mehrdeutige Teilnahme oder Namenszuordnung bleibt `unclear` und
   klärungsbedürftig; `other` verlangt eine belegte andere Person.
3. **Mehrere Themen:** Für jeden Referenzfall werden erforderliche, zulässige und
   ausgeschlossene Themen vorab festgelegt. Zusätzliche Themen sind weder pauschal
   richtig noch pauschal falsch. Die bloße Relevanzentscheidung wird getrennt
   von der Vollständigkeit und Genauigkeit der Themenzuordnung bewertet.
4. **Zusammenfassung:** Belegte Datums- und Zeitangaben bleiben sichtbar, auch
   ohne eigene Handlungspflicht. Monate, relative Fristen und reine Uhrzeiten
   behalten ihre Genauigkeit. Sie werden nicht zu einem erfundenen Tag oder
   einem einzigen austauschbaren `<ohne Datum>`-Wert umgedeutet. Eine solche
   Zeitangabe begründet für sich allein keine Aufgabe oder Einladung.
5. **Antwortbedarf:** Eine Bitte um Unterlagen ist eine Aufgabe. `reply_needed`
   wird nur gesetzt, wenn die Rückmeldung per Mail belegt ist; ein nicht
   genannter Übermittlungskanal wird nicht ergänzt. Diese Regel und ihre
   Gegenbeispiele werden explizit in die neue Referenz aufgenommen.
6. **Ankunft und Belegung:** Frühere ausdrücklich zugehörige Anwesenheit bestimmt
   den Beginn; freiwilliges Vorprogramm und Zeiten anderer Rollen nicht.
   Eigene bestätigte Ressourcenbelegungen behalten ihren Kalenderbezug und ihre
   datumsbezogene Zeitart. Ein bloßes Veranstaltungsdatum bleibt ohne weitere
   Evidenz kein Ganztagstermin.

**Ergebnis:** Ein neuer, versionierter Bewertungsvertrag und Referenzkorpus v5.
Die 46 v4-Fälle werden mit nachvollziehbarer Migrationsbegründung übernommen;
alte Sollwerte bleiben unverändert in v4. Die neun nachträglich begutachteten
Paarungen dienen als Diagnosefälle, nicht als unabhängiger Erfolgsnachweis.
Mindestens 20 zusätzliche Fälle mit anderen Namen, Daten und Formulierungen
werden als bislang nicht verwendete Kontrolle eingefroren.

## AP2 – Prüfer korrigieren, ohne die Abnahme zu erleichtern

**Betroffene Stellen:** `src/mailhelp/llm/quality_metrics.py`,
`src/mailhelp/llm/evaluation.py`, `devtools/prompt_guard.py` und
`tests/evaluation/`.

- Aktionsidentität, Faktenrichtigkeit und Formulierungsqualität getrennt ausweisen.
- Bereits vorab definierte `accept`-Alternativen in beiden Verfahren einheitlich
  berücksichtigen. Eine Alternative gilt vollständig, nicht als beliebige Mischung
  einzelner günstiger Felder. Zusätzliche unerlaubte Aktionen bleiben Fehler.
- Kandidaten anhand verifizierbarer Quellenbezüge zuordnen. Eine gleiche Anzahl,
  Frist oder Zuständigkeit allein beweist keine gleiche Handlung.
- Sichere sprachliche Normalisierung und vorab definierte Paraphrasen von echter
  Bedeutungsänderung trennen. „Prüfen“ darf nicht wegen ähnlicher Wörter als
  „bezahlen“ bestehen. Nicht eindeutig belegbare Paarungen erhalten einen eigenen
  Reviewstatus, der eine automatische Freigabe verhindert.
- Eindeutige Zuordnungen reihenfolgeunabhängig berechnen. Mehrdeutigkeit nicht
  durch das erste gefundene Paar oder einen zufälligen Gleichstand auflösen.
- Bereits erkannte Aktionen vollständig prüfen: Beginn und Ende, Tagesbereich,
  Zeitart, Zuständigkeit, Sicherheit, Klassifikation, Bezugsdatum, Ort, Link,
  Frist und Quellenbeleg. Fehlende Angaben bleiben zulässig, wenn genau dies
  der vorab festgelegte Vertrag verlangt; bekannte Fakten dürfen nicht fehlen.
- Die tatsächliche Ende-zu-Ende-Verarbeitung zusätzlich prüfen: Ein vorgelagertes
  `irrelevant` darf nicht durch separat korrekte nachgelagerte Testantworten
  verdeckt werden.
- Das Gate muss unerlaubte Faktenabweichungen, unaufgelöste Reviews und die
  Ende-zu-Ende-Verluste sperren. Die bisherigen Mindestgrenzen werden nicht
  abgesenkt: mindestens 90 % Erkennung, höchstens zwei Fehlalarme je Aktionsart,
  keine technischen/unlesbaren Ausfälle und keine Aktionen in den kritischen
  Keine-Aktion-Fällen. Sicherheitsrelevante Fakten dürfen nicht falsch sein.

**Regressionen vor dem Fix:** Neun Titelartefakte, zwei erlaubte Leerfälle,
„Rechnung prüfen“ gegen „Rechnung bezahlen“, gleiche Daten bei verschiedener
Handlung, zwei unterschiedliche Personen, vertauschte Ausgabe-Reihenfolge,
doppelte Aktionen, falsche Endzeit und falsche Sicherheit trotz richtigem Titel.
Jeder Fall muss vor dem zugehörigen Fix scheitern und danach bestehen.

Historische Baselines behalten ihre alten Fingerabdrücke. Eine neue Baseline und
ihre aktive Auswahl werden ausdrücklich versioniert; reine Hashaktualisierung
oder Codex-Audit allein autorisieren keinen Wechsel. Alte und neue Messungen
werden mit dem jeweiligen Bewertungsvertrag beschriftet und nicht vermischt.

## AP3 – Quelleninformation vor Zeitnormalisierung sichern

**Betroffene Bereiche:** Vorbereitung/Analyse, Quellennachweise, Proposal-Aufbau,
`src/mailhelp/proposals/action_normalization.py` und zeitliche Rückfragen.

- Datum und Wochentag aus der passenden aktuellen Quellenstelle erhalten.
  Verifizierte Belegstellen werden durch Anwendungscode ermittelt; Modellzitate
  oder Modell-Offsets gelten nicht ungeprüft als gültige Quellenbeweise.
- Bei verkürzter Modellausgabe widersprechende Quellenangaben nicht verlieren.
  Ein Wochentag aus einem Mail-Header, einer anderen Tabellenzeile oder einer
  überholten zitierten Einladung darf jedoch keinen falschen Widerspruch erzeugen.
- Gängige Formen wie „Dienstag, den 19.11.2026“ und ausgeschriebene Monatsnamen
  deterministisch verarbeiten. Kalenderrechnung bleibt Anwendungscode.
- Wochentags-/Datumswiderspruch vor der Frage nach einer fehlenden Endzeit klären.
  Ein neues Ende darf den ungelösten Datumswiderspruch nicht versehentlich beseitigen.
- Rohangaben, Konflikt und verifizierter Quellenbezug müssen Neustart, Rückfrage
  und erneute Verarbeitung überstehen. Alte JSON-Zustände kompatibel laden;
  fehlender Quellenbezug ist kein Anlass für stilles Raten oder rückwirkende
  Änderung vorhandener externer Termine.

**Pflichtfälle:** Auditfall 45; richtiger Wochentag; fehlender Wochentag im
Modellfeld; mehrere Termine mit verschiedenen Wochentagen; Altzitat und Header;
Datumsbereiche, Monats-/Jahreswechsel; „den“-Schreibweisen; Neustart; Antwort nur
auf die Endzeit; ausdrücklich korrigiertes Datum; veraltete Vorschlagsversion.

## AP4 – Echte Relevanz- und Extraktionsbefunde gezielt reparieren

**Konfiguration:** `prompts.yaml`, `decisions_prompts.yaml`, `topics.yaml` bei
begründetem Bedarf und jeweils die zugehörigen Paketvorlagen. Keine Modelle oder
Parameter beiläufig wechseln; jede solche Änderung erhält einen getrennten Vergleich.

- Raumänderung und Absage eines eigenen bestehenden Termins dürfen nicht als
  allgemeine Veranstaltungswerbung verworfen werden. Klarer eigener Bezug:
  relevant; mehrdeutiger Bezug: Rückfrage statt unbegründetem Verwerfen oder
  sicherem Zuordnen. Werbung und reine Fremdberichte bleiben Gegenbeispiele.
- Kalenderhandling und Zusatzaufgabe anhand der beschlossenen AP1-Regel trennen.
- Wiederholungsangaben wie „jeden Montag“ vollständig erhalten.
- Bei gleichbleibendem Tag und geändertem Raum/Uhrzeit das Bezugsdatum erhalten.
- „Hr. Muster“ in einem Einsatzplan mit dem Empfänger- und Nutzerkontext
  abgleichen. Mehrdeutigkeit wird nicht in sichere fremde Zuständigkeit umgedeutet.
- Eigener Absender, echte eigene Notiz und ausgehende Bitte an andere getrennt
  behandeln. Die beiden bereits reparierten Sicherheitsfälle bleiben negativ.
- Den großen Tagesplan nach Zahl der belegten Einsätze und Länge der Ausgabe
  untersuchen. Erst dann Redundanz/Reasoning, Ausgabeaufteilung oder ein begrenztes
  Tokenbudget ändern. Aufteilung darf keine fehlenden oder doppelten Termine
  erzeugen und kein unbeschränktes Wiederholen ermöglichen.

**Pflichtfälle:** 11, 20, 26, 30, 37, 38, 41 und 45, alle sieben kritischen Fälle,
die Ankunfts-/Check-in-Fälle sowie neue unabhängige Gegenbeispiele. Jede Änderung
erst mit einer kleinen gezielten Fallgruppe prüfen, bevor ein weiterer voller
kostenpflichtiger Vergleich gestartet wird.

## AP5 – Offene Browserabnahme unabhängig abschließen

**Betroffene Bereiche:** `src/mailhelp/web/static/settings.js`, Suchendpunkt,
`ui_tests/test_ui_settings_live_search.py` und Abschnittsformular-Tests.

1. Die Suchlatenz in Debounce, Anfrage, Serverarbeit und Darstellung aufteilen.
   Nach dem gemessenen Engpass optimieren, etwa unnötige Neuberechnung vermeiden.
   Caches müssen Sprache, Rolle und Einstellungsrevision beachten; Kundensitzungen
   dürfen dadurch keine Betreiberinformationen erhalten.
2. Die Messgrenze bleibt unverändert: mindestens 95 von 100 Suchläufen innerhalb
   300 ms im vollständigen Browserlauf mit sechs Workern. Keine spätere Startmarke,
   längere Frist oder isolierte Ersatzabnahme. Isolierte Läufe dienen nur der Diagnose.
3. Die beiden Abdeckungslücken in der Speicherleiste fachlich untersuchen:
   verborgene Formularelemente und Änderungszähler. Reale Zustandswechsel einschließlich
   Rücknahme von Eingaben prüfen. Benötigte Schutzfälle realistisch testen;
   nachweislich unerreichbare Logik nur begründet vereinfachen. Keine künstlichen
   DOM-Manipulationen ausschließlich zur Erhöhung des Zählers.
4. JavaScript-Daten aller Worker prüfen, auch wenn ein anderer Test scheitert;
   fehlende Berichte und ungeladene Skripte bleiben Abnahmefehler.

## AP6 – Verbindliche Abschlussabnahme

1. Neue Referenz und Aliase zuerst einfrieren. Vorher- und Nachher-Promptstand,
   Modelle, Parameter und Quelldateien mit Fingerabdrücken sichern. Die neuen
   Kontrollfälle nicht nach ersten Ausgaben passend ändern.
2. Beide Stände mit demselben neuen Bewertungsvertrag und Korpus messen. Alte
   v4-Messungen werden nicht als Vorher-Lauf eines erweiterten v5-Korpus ausgegeben.
3. Erst bei erfüllten Grenzen, korrekten Pflichtfeldern und ohne offene Reviews
   eine neue aktive Prompt-/Qualitätsbaseline freigeben.
4. `python -m devtools.check full --workers 12`: Paketbau, vollständige Python-Tests,
   100 % Zeilen- und 100 % Branch-Abdeckung, anschließend getrennte Lasttests.
5. Danach `python -m pytest ui_tests -n 6 --dist worksteal --no-cov`: vollständige
   Browsersuite, ursprüngliche Latenzgrenze, vollständige JavaScript-Abdeckung.
   Übersprungene Fälle nachvollziehbar ausweisen, fehlende Browser-Abhängigkeiten
   vor dem Lauf bereitstellen.
6. README, Spezifikation, Beispiele und CHANGELOG aktualisieren. Änderungen bleiben
   ohne konkrete Commit-/Push-Anweisung lokal. Bei einem später beauftragten Commit
   die Patchversion in beiden Versionsdateien erhöhen. Ein späteres Deployment ist
   ein eigener Schritt mit den vorgeschriebenen Serverprüfungen, Handbuchpflege,
   Dokumentationskopie und Rückkehrverfahren.

## Netzwerk- und Kostenrahmen

Dieser Plan führt keine Modellaufrufe aus. Vor den neuen kostenpflichtigen
Vergleichen werden Modelle, konkrete Fallzahl und gemeinsames Aufrufbudget
ausdrücklich festgelegt. Die letzte zusätzliche Freigabe war 300 Aufrufe; davon
wurden 178 verbraucht. Der Rest reicht nicht für einen vollständigen neuen
Vorher-/Nachher-Vergleich und wird nicht als neue unbegrenzte Freigabe behandelt.

Planungsobergrenze beim bisherigen Evaluator: bis zu sechs Aufrufe pro Mail
(einschließlich Relevanz-Fallback). Für zwei Läufe mit jeweils N Fällen daher
höchstens 12 × N Aufrufe, vor zusätzlichen Wiederholungen. Bei 66 Fällen wären
das 792. Zunächst reduzieren kostenlose Regressionen und kleine gezielte
Modellgruppen die Fehlersuche; vollständige Modellläufe erfolgen erst mit einem
stabilen Kandidaten. Wiederholungen bleiben separat sichtbar und im genehmigten
Budget. Keine produktiven Mails ohne eigene Datenfreigabe übertragen.

## Abnahme von Version 8.9

Alle Arbeitspakete und Regressionen bestehen; Quellenbezug und Datumswidersprüche
bleiben bis zur gültigen Klärung erhalten; echte Terminänderungen gehen nicht im
Relevanzfilter verloren; neue Bedeutungen werden nicht als bloße Paraphrase
akzeptiert; alle Qualitäts-, Coverage-, Latenz- und Sicherheitsgrenzen sind
erfüllt. Keine offene Review wird als Erfolg gezählt. Ein vollständiger Prüfbericht
enthält auch Fehler, Wiederholungen, Budget, Fingerabdrücke und die tatsächlichen
Ergebnisse. Erst dann ist die lokale Reparatur zur Veröffentlichung abgenommen.
