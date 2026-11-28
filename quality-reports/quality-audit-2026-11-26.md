# Bewertungsartefakte und Extraktionsbefunde getrennt – 26.11.2026

Die Auffälligkeiten des letzten vollständigen 46-Fälle-Laufs wurden gegen die
synthetischen Quellen, Sollwerte, bereits erlaubten Alternativen und tatsächlichen
Modellantworten geprüft. **Die niedrige rohe Aufgabenquote ist kein belastbarer
Nachweis, dass das Modell so viele Aufgaben übersieht.** Der Prüfer zählt mehrere
korrekt erkannte Handlungen wegen ihrer Benennung doppelt als fehlend und als
Fehlalarm. Gleichzeitig übersieht seine Freigabelogik wichtige Faktenfehler.

Das ist ein fachlicher Diagnosebericht, keine neue Qualitätsfreigabe. Scorer,
Schwellen, Prompts und eingefrorene Korpora wurden in dieser Arbeitsphase nicht
verändert. Die bisherigen Messberichte bleiben unverändert. Keine neuen
Modellaufrufe, keine Serveränderung, kein Commit oder Push.

## 1. Die Fehlermengen sind vollständig bilanziert

| Roher Messwert | Ergebnis der beleggestützten Zuordnungsprüfung |
| --- | --- |
| 9 fehlende Aufgaben | 6 Titel-Zuordnungsfehler, 2 bereits erlaubte leere Alternativen, 1 ungeklärte Kalenderregel |
| 6 Aufgaben-Fehlalarme | Dieselben 6 Titel-Zuordnungsfehler; keine sechs zusätzlichen Handlungen |
| 3 fehlende Termine und 3 Termin-Fehlalarme | Dieselben 3 korrekt identifizierten Termine mit abweichender Benennung |
| 1 technischer Ausfall | Tagesplan mit `LlmTokenLimitExceeded`; bleibt ein eigenständiger technischer Befund |

Diese Bilanz betrifft **Identität und Anzahl** der Aktionen. Sie bedeutet nicht,
dass alle identifizierten Termine sachlich richtig sind. Insbesondere dürfen
Zuständigkeit, Sicherheit oder Zeitdaten nicht durch eine bessere Titelzuordnung
automatisch als richtig gelten. Es wird bewusst keine neue globale Erfolgsquote
aus den manuellen Zuordnungen berechnet.

### Bestätigte Titel-Zuordnungsfehler

`quality_metrics._similar` verlangt mindestens 50 % gemeinsame Titelwörter.
Füllwörter, deutsche Zusammensetzungen und `ae`/`ä` verändern diese Quote stark.
Die folgenden neun Zuordnungen wurden inhaltlich anhand der Quelle und Belege
geprüft; die bisherigen semantischen Stufenvergleiche bestehen ebenfalls:

| Fall | Gleiche belegte Handlung trotz anderem Titel |
| --- | --- |
| 02 | Reisekostenbelege einreichen / Belege für Reisekostenabrechnung einreichen |
| 04 | Protokoll senden / Protokoll der letzten Sitzung senden |
| 14 und 28 | Zum Fachtag anmelden / Für Fachtag Digitalisierung anmelden |
| 15 | Verfügbarkeit für ein Grußwort rückmelden / Rückmeldung zu Grußwort geben |
| 21 | Hofführungsanfrage beantworten / Jimdo-Anfrage zu Hofführung beantworten |
| 20, Termin | Projektgespraech / Projektgespräch verschoben |
| 23 | Stellplatzbuchung Familie Weber / Stellplatz 3 Buchung Familie Weber |
| 32 | Landesversammlung / Landesversammlung des Landesverbands |

Die normalisierten tatsächlichen Belegzitate kommen in Mail oder mitgeliefertem
synthetischem Bildtext vor. Die JSON-Datei enthält Titel, Belege, Indizes,
Wortüberschneidung und die jeweilige fachliche Begründung.

### Bereits erlaubte Alternativen werden ignoriert

In `05_unclear_action` und `16_invitation_feedback_other` ist eine leere Aufgabenliste
bereits unter `accept.task_extraction` des eingefrorenen Korpus erlaubt. Das Modell
liefert diese erlaubte Alternative. Der Stufenvergleich akzeptiert sie; die zweite
Aktionsbewertung liest ausschließlich `expected` und zählt trotzdem je eine
fehlende Aufgabe. Hier liegt ein belegter Widerspruch zwischen den beiden Prüfern
vor, keine nachträgliche Lockerung der Erwartungen.

### Der Matcher kann auch falsche Gleichheit behaupten

Die Prüfung akzeptiert im synthetischen Gegenbeispiel „Rechnung für Lieferant Müller
prüfen“ und „Rechnung für Lieferant Müller bezahlen“ als ähnlich. Die Handlungen
sind verschieden. Nur den Titelvergleich zu lockern, gleiche Anzahlen zu akzeptieren
oder nachträglich alle Titel zu erlauben wäre daher keine verlässliche Reparatur.

Eine weitere Diagnose zeigt Reihenfolgeabhängigkeit: Bei unveränderten zwei
Ausgaben erkennt der gierige Matcher in einer Reihenfolge eine, in umgekehrter
Reihenfolge zwei Aktionen. Das ist ein technischer Zuordnungsfehler; aus diesem
synthetischen Gegenbeispiel wird keine semantische Qualitätsaussage abgeleitet.

## 2. Vorgaben müssen vor weiterem Prompt-Tuning geklärt werden

| Befund | Einordnung |
| --- | --- |
| Kalenderänderung, Fall 20 | Der Aufgabenprompt fordert administrative Folgeaufgaben als `change`, schließt das Eintragen im Kalender aber zugleich als zusätzliche Aufgabe aus. Der Router folgt der zweiten Regel. Das ist zuerst ein Regelkonflikt, kein eindeutig fehlender Modellauftrag. |
| Zusammenfassungen, sechs Fälle | Die aktuelle Anweisung verlangt belegte Zeitangaben auch bei Fremdfristen und ohne eigene Handlung. Die Referenzen erwarten teils keine solche Angabe; der Vergleicher reduziert Monate und Uhrzeiten auf `<ohne Datum>`. Diese Abweichungen sind keine belegten erfundenen Fristen. |
| Themenzuordnung, sieben Fälle | In sechs Fällen ist das erwartete Thema enthalten, aber ein zusätzliches plausibles Thema wird abgelehnt. Die Konfiguration erlaubt Mehrfachzuordnung. Ein weiterer Fall betrifft die Überlappung von Kommune und Arbeit. Das braucht eine vollständige Themenreferenz, keine Optimierung auf genau ein Stichwort. |
| Antwortbedarf, Fall 41 | Unterlagen zusenden ist belegt, „per Mail“ nicht ausdrücklich. Die Modellbegründung ergänzt diesen Kanal. Die strenge Kanalregel und der Umgang mit impliziten Erwartungen müssen konsistent festgelegt werden. |
| Sitzungsliste, Fall 30 | Elf Termine erhalten `user/certain`, obwohl die Quelle keine eigene Einladung oder Einteilung belegt. Der Prompt setzt Termine an den Empfänger jedoch grundsätzlich als eigene voraus, während die Referenz `unclear/uncertain` verlangt. Das Ergebnis ist zu bestimmt; der Auftrag selbst ist hier ebenfalls widersprüchlich. |

Diese Kategorien werden nicht als sicher richtige Modellantworten umetikettiert.
Sie sind offene Referenz-/Regelentscheidungen. Eine spätere Korrektur gehört in
eine nachvollziehbar neue Referenzversion; der eingefrorene v4-Korpus wird nicht
nach Kenntnis der Ergebnisse passend gemacht.

## 3. Belegbare Probleme, die bessere Titelzuordnung nicht löst

**Priorität 1: Termininformationen werden vor der Extraktion verworfen.**
`37_change_new_room` und `38_cancellation_without_replacement` liefern
`irrelevant`, obwohl eine gezielte Raumänderung beziehungsweise Absage eines
bestehenden Termins gemeint ist. Der Evaluator prüft spätere Stufen trotzdem.
Im tatsächlichen Produktivpfad beendet `mail_pipeline` bei `irrelevant` dagegen
die weitere Analyse. Richtige nachgelagerte Antworten im Test retten diese
Mails im Produktivpfad deshalb nicht.

**Priorität 1: Wochentagsinformation geht vor der Datumsprüfung verloren.**
In Fall 45 steht „Dienstag, den 19.11.2026“; der 19.11.2026 ist ein Donnerstag.
Das Modell gibt nur `19.11.2026` und `certainty: certain` zurück. Die direkte
Normalisierung dieser tatsächlichen Ausgabe meldet lediglich `missing_end_time`
und speichert den 19.11. als bekanntes Datum. Sie erkennt nicht den Widerspruch.
Auch die Referenz lässt den Wochentag im Datumsfeld weg und erwartet stattdessen,
dass das Modell `contradictory` meldet. Das ist keine robuste Trennung zwischen
Extraktion und deterministischer Validierung.

Die reproduzierten Gegenproben stehen in der JSON-Datei: Mit der vollständigen
Formulierung einschließlich „den“ fragt der Parser wegen `unsupported_date_format`
nach dem Datum; mit der unterstützten Form „Dienstag, 19.11.2026“ erkennt er
`invalid_date` und den Wochentagswiderspruch. Erhalt und Prüfung der Quellenangabe
sind hier wichtiger als weitere Sprachvarianten im Prompt. Die fehlende Endzeit
ist kein Nachweis, dass der Datumswiderspruch bereits sicher abgefangen wird.

**Weitere konkrete Extraktionsbefunde:**

- Fall 11: „jeden Montag“ steht in der Quelle, das Datumsfeld bleibt jedoch leer.
- Fall 37: Bei unverändertem Tag und Raumänderung verlangt die aktuelle Anweisung
  das Bezugsdatum auch in `original_date_text`; das Modell liefert dort `null`.
- Fall 26: Der vollständige Lauf überschreitet das Ausgabelimit. Die getrennte
  Einzelwiederholung läuft ohne technischen Fehler, ordnet aber beide Einsätze
  „Hr. Muster“ als `other` ein, obwohl der Empfänger Alex Muster heißt. Namensbezug
  und zulässige Unsicherheit brauchen eine eigene Prüfung; die Wiederholung
  ersetzt den ursprünglichen Ausfall nicht.

Alle sieben bestehenden kritischen Keine-Aktion-Fälle bleiben im vollständigen
letzten Lauf ohne vorgeschlagene Aktion. Das ist ein eigener positiver Befund,
keine Entwarnung für die oben beschriebenen Feld- und Relevanzprobleme.

## 4. Die Freigabe prüft Fakten noch nicht ausreichend

Der alte Aktionsprüfer erfasst nur Frist beziehungsweise erstes Datum und
Beginnuhrzeit, Zuständigkeit, nichtleeren Beleg und Klassifikation. Beispielsweise
Sicherheit, Endzeit, Zeitart und Bezugsdatum fehlen dort. Noch wichtiger:
`gate()` bewertet die Feldfehler überhaupt nicht, sondern nur Erkennungsrate,
Anzahl, technische Fehler und die sieben Keine-Aktion-Fälle. Gute Erkennungszahlen
allein könnten deshalb eine sachlich falsche Ausgabe nicht zuverlässig sperren.

Der vorhandene semantische Stufenvergleich erkennt mehr dieser Unterschiede.
Auch er ignoriert aber Titel und den eigentlichen Handlungsgegenstand. Gleiche
Anzahl, Frist und Zuständigkeit beweisen nicht, dass beispielsweise „prüfen“
statt „bezahlen“ korrekt extrahiert wurde. Beide Verfahren müssen daher
zusammengeführt werden, ohne einem der beiden blind zu vertrauen.

## Konkrete Reihenfolge für die Reparatur

1. **Bewertungsvertrag definieren:** Aktionsidentität, sachliche Felder und reine
   Formulierung getrennt ausweisen. Vorab erlaubte Alternativen einheitlich
   berücksichtigen. Unklare Zuordnungen erfordern belegte Prüfung statt automatische
   Gleichsetzung oder automatische Fehlalarmzählung. Der Gegenstand der Handlung
   muss dabei erhalten bleiben.
2. **Prüfer absichern:** Reihenfolgeunabhängige eindeutige Zuordnung, positive und
   negative semantische Gegenbeispiele und verbindliche Prüfung sicherheitsrelevanter
   Felder. Zusätzlich die tatsächliche Ende-zu-Ende-Wirkung eines Relevanzstopps
   bewerten; unabhängige spätere Stufenergebnisse dürfen ihn nicht verdecken.
   Kein abgesenkter Grenzwert und kein Überschreiben der alten Ergebnisse.
3. **Fachliche Regeln konsistent machen:** Kalenderbehandlung versus Zusatzaufgabe,
   Teilnahmesicherheit, Mehrfachthemen und Zusammenfassungsumfang festlegen. Erst
   anschließend eine neue Referenzversion einfrieren.
4. **Gezielt die echten Befunde beheben:** Relevanz für Änderungen/Absagen,
   Quellen-Wochentag und dessen Validierung, Bezugstage, Wiederholungsangaben,
   Namenszuordnung und den umfangreichen Tagesplan. Danach neue unverbrauchte
   Kontrollfälle und einen vollständigen Vorher-/Nachher-Lauf verwenden.

## Nachvollziehbarkeit und Grenzen

`quality-audit-2026-11-26.json` enthält Hashes der Quellen und des Prüfers,
alle 46 Fallbilanzen, die neun fachlich geprüften Paarungen, die zwei ignorierten
Alternativen sowie die reproduzierten Diagnosefälle. Die Zuordnungen sind eine
beleggestützte Prüfung durch Codex, keine unabhängige neue Modellmessung oder
vom Nutzer erteilte Qualitätsfreigabe. Freie Beschreibungstexte wurden nicht
vollständig neu abgenommen. Die arithmetische Bilanz jeder alten Fehlermenge
und die Belege der neun Paarungen wurden zusätzlich lokal geprüft.

Die vorhandenen Tests für Qualitätsbewertung und Baseline bestehen unverändert
mit **13/13**. Sie bestätigen das bisherige Verhalten, nicht dessen fachliche
Eignung. Keine Änderung an Anwendungscode oder Prompts, deshalb keine erneute
vollständige Python-/Browserprüfung für diese reine Auswertung. Die offenen
Browserbefunde aus dem [Restprüfbericht](remaining-tests-2026-11-26.md) bleiben
unabhängig davon bestehen. Baselines und Server sind unverändert; dieser Audit
erteilt keine Freigabe und hat **keine weiteren API-Kosten** verursacht.
