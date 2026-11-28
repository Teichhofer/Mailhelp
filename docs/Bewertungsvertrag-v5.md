# Bewertungsvertrag v5 für die Extraktionsqualität

**Stand:** 28.11.2026, festgelegt mit Mailhelp 8.9.1 ([Planung 8.9](Planung-8.9.md) AP1).
**Referenzkorpus:** `tests/fixtures/mail_corpus_v5/corpus.json` (eingefroren, Prüfsumme in
`quality-reports/baseline-8.9.json`). Der Vertrag v4 und sein Korpus
`tests/fixtures/mail_corpus_v4/` bleiben unverändert als historische Grundlage der Messungen bis 8.8.

Der Vertrag legt fest, was eine Modellantwort als richtig ausweist. Er wird **vor** jedem Modelllauf
eingefroren. Nach ersten Ausgaben werden weder Sollwerte noch Alternativen oder Schwellen passend
gemacht; eine nötige Korrektur ergibt eine neue Vertragsversion.

## Fachregeln

1. **Kalenderbehandlung.** „Termin vormerken“, „Kalendereintrag ändern“ und eine reine Raum- oder
   Zeitänderung ergeben die passende Kalenderaktion (neuer Termin, Änderung oder Absage). Für dieselbe
   Kalenderhandlung entsteht keine zweite Aufgabe. Eine zusätzliche Anmeldung, Rückmeldung,
   Vorbereitung oder Benachrichtigung bleibt eine eigene Aufgabe. Diese Regel ersetzt die frühere Regel
   über administrative Kalender-Folgeaufgaben.
2. **Teilnahme.** Eine eigene Einladung oder eine belegte Einteilung rechtfertigt `user`. Eine
   allgemeine Terminliste allein belegt keine sichere eigene Teilnahme. Mehrdeutige Teilnahme oder
   Namenszuordnung bleibt `unclear` und klärungsbedürftig; `other` verlangt eine belegte andere Person.
3. **Mehrere Themen.** Jeder Fall nennt erforderliche, zulässige und ausgeschlossene Themen. Ein
   zusätzliches zulässiges Thema ist kein Fehler, ein ausgeschlossenes oder ein fehlendes
   erforderliches Thema schon. Die Relevanzentscheidung wird getrennt von der Themenzuordnung bewertet.
4. **Zusammenfassung.** Belegte Datums- und Zeitangaben bleiben sichtbar, auch ohne eigene
   Handlungspflicht. Monate, relative Fristen und reine Uhrzeiten behalten ihre Genauigkeit; sie werden
   weder zu einem erfundenen Tag noch zu einem austauschbaren Platzhalter. Eine solche Angabe begründet
   für sich allein keine Aufgabe und keine Einladung.
5. **Antwortbedarf.** Eine Bitte um Unterlagen ist eine Aufgabe. `reply_needed` gilt nur, wenn die
   Rückmeldung per Mail belegt ist; ein nicht genannter Übermittlungskanal wird nicht ergänzt.
6. **Ankunft und Belegung.** Eine frühere, ausdrücklich zugehörige Anwesenheit (Ankommen, Einlass,
   Check-in) bestimmt den Beginn; freiwilliges Vorprogramm und Zeiten anderer Rollen nicht. Eigene
   bestätigte Ressourcenbelegungen behalten ihren Kalenderbezug und ihre datumsbezogene Zeitart. Ein
   bloßes Veranstaltungsdatum bleibt ohne weitere Evidenz kein Ganztagstermin.

## Bewertung einer Aktion

Die Bewertung trennt drei Fragen und weist sie getrennt aus:

| Frage | Prüfung | Wirkung |
| --- | --- | --- |
| **Identität** – dieselbe Handlung? | Handlungsverb, Gegenstand, vorab festgelegte Aliase und ein verifizierter Quellenbezug | Erkannt, übersehen, Fehlalarm oder **Review** |
| **Fakten** – stimmen die Felder? | Beginn, Ende, Tagesbereich, Zeitart, Frist, Zuständigkeit, Sicherheit, Klassifikation, Bezugsdatum, Ort, Link, Beleg | Feldfehler sperren die Freigabe |
| **Formulierung** | Titel und Beschreibung | nur Bericht, keine Freigabewirkung |

- **Verben.** Zwei Titel mit verschiedenen bekannten Handlungsverben („prüfen“, „bezahlen“) sind
  verschiedene Handlungen, auch bei gleichen übrigen Wörtern. Gleichbedeutende Verben („senden“,
  „schicken“, „übermitteln“) stehen in einer festen Liste.
- **Gegenstand.** Umlaute (`ae`/`ä`), Groß-/Kleinschreibung, Füllwörter und Zusammensetzungen
  („Reisekostenbelege“ ~ „Belege für Reisekostenabrechnung“) werden vor dem Vergleich vereinheitlicht.
  Vorab im Korpus genannte Aliase gelten als gleiche Handlung; ihre Verben zählen wie die des Solltitels.
- **Quellenbezug.** Der Beleg einer Antwort zählt nur, wenn er nach Vereinheitlichung der Leerzeichen
  wörtlich in Mail, Anhangstext oder Bildtext steht. Er stützt die Zuordnung, wenn er sich mit dem
  Sollbeleg überschneidet. Gleiche Anzahl, Frist oder Zuständigkeit allein beweist keine gleiche Handlung.
- **Zuordnung.** Die Paare werden als beste Gesamtzuordnung unabhängig von der Ausgabereihenfolge
  bestimmt. Gibt es mehrere gleich gute Zuordnungen mit verschiedenen Paaren, erhalten die betroffenen
  Aktionen den Status **Review**; ein offenes Review verhindert die automatische Freigabe.
- **Alternativen.** Eine Antwort wird gegen den Sollwert und jede vorab genannte vollständige
  Alternative einer Stufe bewertet; es zählt die Alternative mit den wenigsten Fehlern. Felder
  verschiedener Alternativen werden nicht gemischt. Zusätzliche unerlaubte Aktionen bleiben Fehler.
- **Fehlende Angaben.** Ein leeres Feld ist richtig, wenn der Sollwert es leer verlangt; eine bekannte
  Angabe darf nicht fehlen.

## Bewertung der übrigen Stufen

- **Relevanz:** Die Entscheidung muss dem Sollwert oder einer Alternative entsprechen; die Themen
  erfüllen den Themenvertrag des Falls (Regel 3).
- **Zusammenfassung:** Jede Zeitangabe wird auf ihre Bestandteile zurückgeführt: Kalendertag, Uhrzeit
  und sonst der Wortlaut ohne Signalwörter („im Oktober“ → „oktober“, „bis Freitag“ → „freitag“). Alle
  Bestandteile des Sollwerts müssen vorkommen; jeder zusätzliche Bestandteil muss in der Quelle belegt
  sein. Ein aus „nächsten Freitag“ errechneter Kalendertag ist daher ein Fehler (Regel 4). Die
  Satzanzahl bleibt bei ein bis zwei Sätzen.
- **Aktionsrouter:** Zustand, Anzahlen und Antwortbedarf wie bisher.

## Ende-zu-Ende

Neben den getrennten Stufen wird der tatsächliche Verarbeitungsweg bewertet: Liefert die Relevanzstufe
`irrelevant`, endet die Verarbeitung wie im Produktivpfad, und alle erwarteten Aktionen des Falls zählen
als **verloren**. Richtige nachgelagerte Antworten derselben Mail verdecken diesen Verlust nicht.

## Freigabe

Eine neue aktive Baseline setzt voraus:

- mindestens 90 % erkannte Aufgaben und Termine, höchstens zwei Fehlalarme je Art;
- keine technischen oder unlesbaren Ausfälle, keine Aktion in den kritischen Keine-Aktion-Fällen;
- keine Feldfehler bei Zuständigkeit, Sicherheit, Klassifikation, Zeit- und Fristangaben und Beleg;
- keine offenen Reviews und keine Ende-zu-Ende-Verluste;
- tatsächliche Modellausgaben für den unveränderten und den geänderten Stand mit demselben Vertrag und
  Korpus. Alte v4-Messungen gelten nicht als Vorher-Lauf des v5-Korpus.

Die bisherigen Mindestgrenzen werden nicht abgesenkt.

## Korpus v5

`tests/fixtures/mail_corpus_v5/corpus.json` (`schema_version` 5, `contract_version` 5) enthält 68 Fälle:

- **46 übernommene Fälle** aus v4 mit unveränderten Mails. Jede Änderung der Sollwerte steht im Fall
  unter `migration.changes` mit Regel und Begründung; unveränderte Fälle tragen eine leere Liste.
  Geändert sind: Fall 20 (Regel 1, keine zweite Aufgabe für die Kalenderanpassung), die Themen der Fälle
  08, 20, 21, 26, 39, 44 und 45 (Regel 3), die Zusammenfassungen der Fälle 21, 22, 25, 27, 36 und 42
  (Regel 4), eine Alternative mit `certain` in Fall 45 (AP3) und eine Alternative `unclear/uncertain` in
  Fall 26 (Regel 2).
- **Diagnosefälle.** Die neun im Audit vom 26.11.2026 begutachteten Titelpaare stehen als Aliase unter
  `aliases` (je Art nach Solltitel) und die Fälle tragen `diagnostic: true`. Sie belegen den Prüfer,
  nicht die Modellqualität.
- **22 Kontrollfälle** (`K01` bis `K22`, `control: true`) mit anderen Namen, Daten und Formulierungen,
  vor dem ersten Modelllauf eingefroren: Kalendervormerkung, Verschiebung mit Rückmeldung, Orts- und
  Absageänderungen eigener Termine, allgemeine Terminliste, Einsatzplan mit fremdem Namen, Antwortkanal,
  Einlass und freiwilliges Vorprogramm, Belegung, Datum ohne Uhrzeit, Wochentagswiderspruch, „Freitag,
  den …“, Wiederholung, Werbefrist, Fremdbericht, „prüfen“ statt „bezahlen“, zwei Handlungen, Wochentag
  nur im Zitat, Monatsangaben und eine Anweisung an das Modell.

Je Fall legt `topics` die erforderlichen (`required`), alternativ erforderlichen (`any_of`, mindestens
eines) und zusätzlich zulässigen (`allowed`) Themen fest; jedes andere Thema ist ausgeschlossen.

Die Prüfsumme des Korpus, die Grenzen und die kritischen Keine-Aktion-Fälle (die sieben aus v4 sowie
K16, K17 und K22) stehen in `quality-reports/baseline-8.9.json`. Eine aktive Prompt-Baseline nach diesem
Vertrag gibt es erst nach dem Vorher-/Nachher-Vergleich aus AP6.
