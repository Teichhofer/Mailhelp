# Mailhelp 5.1 – Zuverlässigere Erkennung und nachvollziehbare Entscheidungen

**Zielversion:** 5.1.0, Umsetzungsschritte als Patchversionen 5.1.0 bis 5.1.9
**Stand:** 9. November 2026
**Status:** In Umsetzung (R1 in 5.1.0, R2 in 5.1.1, R3 in 5.1.2, R4 in 5.1.3, R5 in 5.1.4)
**Grundlage:** [Entwicklungsregeln](../AGENTS.md), [Projektspezifikation](../Mailhelp-Projektspezifikation.md), [Qualitätsprüfung 4.1](Qualitaet-4.1.md)
**Vorgänger:** [Planung 5.0](Planung-5.0.md) – Oberfläche und Bedienung
**Nachfolger:** [Planung 5.2](Planung-5.2.md) – Eintragungen beim Anbieter überprüfen
**Technischer Ausgangsstand:** 5.0.3. Vor der Umsetzung ist der abgeschlossene Stand von 5.0 erneut abzugleichen.

## 1. Ziel

Mailhelp soll Aufgaben und Termine nachvollziehbar erkennen und Hinweise auf mögliche
Auslassungen zeigen. Die Frage **„Warum wurde aus dieser Mail keine Aufgabe?“** soll sich
direkt in der Mailansicht beantworten lassen. Bei einem vermuteten Fehler kann die Person
die Mail gezielt erneut analysieren lassen und die Unterschiede prüfen.

Die vier Schwerpunkte sind:

1. Verständlicher Prüfverlauf pro Mail aus gespeicherten Verarbeitungsergebnissen.
2. Gezielte Nachanalyse auch für relevante Mails ohne passende Vorschläge.
3. Prüfhinweise bei widersprüchlichen oder möglicherweise unvollständigen Ergebnissen.
4. Messbare Erkennungsqualität mit reproduzierbaren Fällen und ehrlicher Trennung zwischen
   technischen Tests und tatsächlicher Modellbewertung.

5.1 behandelt die Erkennung **vor** einer externen Eintragung. Die in 5.2 geplante
Kontrolle bereits geschriebener Aufgaben und Termine bleibt ein eigener Arbeitsschritt.

## 2. Ausgangslage und vorhandene Bausteine

| Bereits vorhanden | Erweiterung für 5.1 |
| --- | --- |
| Relevanz, Zusammenfassung, Fristen und erkannte Vorschläge in der [Mailansicht](../src/mailhelp/web/archive_pages.py) | Einheitliche Erklärung des tatsächlichen Verarbeitungspfads einschließlich Gründen für fehlende Vorschläge |
| Aktionsrouter mit `action_state`, Aufgaben-/Terminzählern und Begründung in [ActionRoute](../src/mailhelp/domain/extraction.py) | Gespeicherte Routerentscheidung und Grenzen verständlich anzeigen; Modellbegründungen als solche kennzeichnen |
| Zählkonflikte zwischen Router und Extraktion in der [Pipeline](../src/mailhelp/processing/mail_pipeline.py) | Vorhandene Konflikte zusammenführen und gezielte weitere Konsistenzhinweise ergänzen |
| [Erneute Prüfung irrelevanter Mails](../src/mailhelp/processing/mail_recheck.py) | Nachanalyse relevanter Mails ohne passende Aktionen ermöglichen und vorhandene Entscheidungen sicher erhalten |
| [Analyseschnappschüsse und Verlauf](../src/mailhelp/review/archive.py) | Analyseversionen, Hinweise und Vorher-/Nachher-Vergleich nachvollziehbar speichern |
| [Prompt-Fingerprint-Schutz](../devtools/prompt_guard.py) und synthetische Qualitätsfälle | Erkennung, Fehlalarme und Feldkorrektheit getrennt messen; keine Modellqualität aus simulierten Antworten ableiten |

Die bestehende Nachprüfung irrelevanter Mails setzt den Analysezustand zurück. Dieses
Verfahren darf nicht unverändert auf Mails mit vorhandenen Vorschlägen, Freigaben oder
Schreibbelegen ausgeweitet werden: Deren Identitäten und Entscheidungen müssen erhalten bleiben.

## 3. Prüfverlauf und Erklärung

Die Mailansicht erhält einen Bereich **„So wurde diese Mail verarbeitet“**. Jeder Schritt
zeigt seinen gespeicherten Ausgang, einen verständlichen Grund und die zugehörige Analyserunde.

| Schritt | Beispiel für eine nachvollziehbare Aussage |
| --- | --- |
| Eingang und Vorfilter | „Absender durch deine Ausschlussregel gefiltert“ oder „Eigener automatisch erzeugter Inhalt erkannt“ |
| Relevanz | „Als relevant für Schule eingestuft“ oder „Als irrelevant eingeordnet; Aktionsanalyse wurde ausgelassen“ |
| Aktionsentscheidung | „Router erkannte eine mögliche Aufgabe und keinen Termin“ oder „Modell bewertete die Mail als Information ohne Handlungsbedarf“ |
| Extraktion | „Eine Aufgabe extrahiert“ oder „Router erwartete zwei Aufgaben; eine wurde extrahiert“ |
| Bewertung und Abgleich | „Vorschlag benötigt Klärung“, „Bereits vorhanden“ oder „Mit einem bestehenden Vorschlag zusammengeführt“ |
| Ergebnis | „Ein Vorschlag wartet auf deine Bestätigung“, „Keine Aktion erkannt“ oder „Auswertung wegen eines Fehlers unvollständig“ |

Verbindliche Regeln:

- Die Erklärung verwendet tatsächlich gespeicherte Zustände und feste Erklärungstexte.
  Ein zusätzliches Modell erfindet keine nachträgliche Begründung für frühere Entscheidungen.
- Eine gespeicherte LLM-Begründung wird ausdrücklich als Modellbewertung angezeigt,
  nicht als bewiesene Tatsache über den Mailinhalt.
- „Keine Aufgabe erkannt“, „nicht geprüft“, „fehlgeschlagen“ und „Ergebnis nicht mehr
  aufbewahrt“ sind unterschiedliche Ausgänge. Eine leere Liste allein bedeutet keinen Erfolg.
- Belege zeigen kurze, vorhandene Originalausschnitte mit Quellenbezug, soweit die
  Aufbewahrung dies erlaubt. Fehlende oder entfernte Belege werden nicht rekonstruiert.
- Eine reine Terminankündigung kann einen Termin enthalten, ohne einen eigenen Arbeitsauftrag
  zu enthalten. Mailhelp erklärt diese Unterscheidung, statt für jede Besprechung eine Aufgabe zu fordern.
- Die Ansicht funktioniert ohne JavaScript und bleibt auf Mobilgeräten lesbar.

## 4. Gezielte Nachanalyse

### 4.1 Auslösen und Umfang

Die Mailansicht bietet **„Aufgabe oder Termin übersehen?“** an. Vor dem Start zeigt sie,
welche Mail und Analyserunde betroffen sind, welche Einstellungen verwendet werden und
welche Kosten beziehungsweise welches Budget für die Nachanalyse gelten.
Optional kann die Person einen kurzen Hinweis ergänzen, etwa „Bitte die Rückmeldefrist prüfen“.
Der Hinweis ist Eingabe für eine Analyse, keine Schreibfreigabe.

Geeignete Fälle sind relevante Mails ohne Aktionen, vermutete Auslassungen in vorhandenen
Vorschlägen und abgeschlossene Analysen mit nachvollziehbarem Fehler. Bereits laufende
Analysen werden nicht parallel gestartet. Der bisherige Weg für irrelevante Mails bleibt erhalten.

### 4.2 Eigenständiger, dauerhafter Analyseauftrag

Die Nachanalyse bekommt eine eigene Kennung und einen lesbaren JSON-Zustand mit Mailidentität,
Ausgangsrunde, Konfigurations-/Prompt-Fingerabdruck, Fortschritt, Budget, Ergebnissen und Fehlercodes.
LLM-Aufrufe, erwartete und tatsächlich verbrauchte Kosten werden dem Auftrag zugeordnet.
Vorhandene Mailergebnisse bleiben bis zur geprüften Übernahme des neuen Ergebnisses lesbar.

Nach einem Neustart wird ein unterbrochener Auftrag sicher fortgesetzt oder mit einem
verständlichen Grund beendet. Bereits abgeschlossene kostenpflichtige Schritte werden
nicht unnötig wiederholt. Unklare Aufrufresultate folgen der bestehenden begrenzten
Wiederholungs- und Budgetpolitik; sie dürfen keine unkontrollierte Kostenschleife erzeugen.

Falls der Originalinhalt entfernt wurde, darf er nur über die gebundene ursprüngliche
Postfach-/Nachrichtenidentität erneut gelesen werden. Geänderte UIDVALIDITY, fehlende Mail,
unzugängliches Postfach oder fehlende Inhalte führen zu einem erklärten Abbruch.
Eine andere Mail mit gleichem Betreff ist kein Ersatz. Relative Datumsangaben beziehen
sich auf den ursprünglichen Mailkontext, nicht auf das Datum der Nachanalyse.

### 4.3 Ergebnisse vergleichen und sicher übernehmen

| Ergebnis | Verhalten |
| --- | --- |
| Inhaltlich unveränderter Vorschlag | Bestehende Identität und Version erhalten; keine doppelte Karte |
| Zusätzliche belegte Aktion | Als neuer, unbestätigter Vorschlag anzeigen |
| Änderung eines offenen Vorschlags | Unterschied anzeigen; Übernahme versionsgeprüft und ohne Übertragung einer alten Schreibfreigabe |
| Bezug zu bereits angelegtem oder unklar geschriebenem Eintrag | Externe ID, Zielbindung, Idempotenzschlüssel und Schreibbeleg erhalten; keine neue Anlage auslösen |
| Früher bewusst verworfener Vorschlag | Nicht automatisch wieder aktivieren; frühere Entscheidung sichtbar halten |
| Früherer Vorschlag wird nicht mehr erkannt | Bestehenden Vorschlag nicht stillschweigend löschen; Unterschied zur Prüfung anzeigen |
| Nachanalyse fehlgeschlagen | Bisherige Ergebnisse erhalten; verständlichen Fehler und gegebenenfalls Wiederholungsmöglichkeit zeigen |

Der vorhandene Vorschlagsabgleich und das Aktionsledger werden genutzt. Ein vollständiges
Zurücksetzen vorhandener Entscheidungen ist nicht vorgesehen. Nachanalyse startet keine
Kalender-/Aufgabenschreibzugriffe, keine automatische Antwortentwurfsablage und keinen
erneuten Versand alter Zusammenfassungen. Benachrichtigungen über neue Prüfergebnisse
werden idempotent und mit dem bestehenden Benachrichtigungsprofil erzeugt.

## 5. Konsistenz- und Vollständigkeitshinweise

Vorhandene Informationen werden deterministisch gegeneinander geprüft. Ein Hinweis beschreibt
einen möglichen Widerspruch und verweist auf die Belege; er behauptet keine vollständig
übersehene Aktion, solange diese nicht belastbar erkannt wurde.

Vorgesehene Regeln:

1. **Zählkonflikt:** Router und Extraktion nennen unterschiedliche Kandidatenzahlen.
2. **Mögliche Auslassung:** Zusammenfassung oder extrahierter Beleg nennt einen konkreten
   eigenen Handlungsauftrag mit Frist, dem kein Vorschlag oder erklärter Abgleich zugeordnet ist.
3. **Unklare Zuordnung:** Ein Termin wurde erkannt, aber die zugehörige Anmelde-/Rückmeldepflicht
   ist nur teilweise erfasst. Termin und organisatorische Aufgabe werden getrennt bewertet.
4. **Widersprüchliche Angaben:** Fälligkeit, Datum oder Zuständigkeit widersprechen gespeicherten Belegen.
5. **Unvollständige Verarbeitung:** Fehler, Größen-/Extraktionsgrenzen oder nicht gelesene Anhänge
   verhindern eine vollständige Auswertung.

Eine Datumsangabe oder Frist allein erzeugt keine Aufgabe. Veranstaltungsdatum,
Werbeangebot, freiwillige Handlung und verpflichtender Arbeitsauftrag müssen getrennt bleiben.
Eine vage Zusammenfassung ist kein ausreichender Originalbeleg. Jeder Hinweis erhält eine
stabile Regelkennung, eine Schwere, einen Belegbezug und die Analyserunde; identische Hinweise
werden nicht mehrfach angelegt. Hinweise lösen keine kostenpflichtige Nachanalyse automatisch aus.

## 6. Erkennungsqualität und Evaluierung

### 6.1 Reproduzierbarer Korpus

Ein versionierter Korpus mit ausschließlich synthetischen Mails hält erwartete Entscheidungen,
Aktionen und Felder fest. Er umfasst mindestens:

- Besprechung mit explizitem Vorbereitungsauftrag sowie reine Besprechungsinformation ohne Arbeitsauftrag.
- Anmeldung, Rückmeldung und Unterlagenversand mit Frist, einschließlich mehrerer Aktionen in einer Mail.
- Freiwillige Buchung, Newsletter und fremde Zuständigkeit als Gegenbeispiele für falsche Aufgaben.
- Eigene Notiz, versandte Mail und Weiterleitung mit eigener Handlungsanweisung.
- Relative Daten, Datum ohne Uhrzeit, Zeitzonenwechsel, widersprüchliche Termine und Absagen.
- Mehrere Mails zum selben Vorgang, bewusste Ablehnung und bereits angelegte oder unklar geschriebene Einträge.
- Fehlerhafte Modellantwort, fehlender Anhangstext und unvollständige Auswertung.
- Manipulative Mail-/Modellinhalte, die Schreibfreigaben oder Systemanweisungen vortäuschen.

Jeder Fall enthält seinen Zweck und konkrete Sollfelder. Repräsentative bekannte Fehler
werden als synthetische Regressionen nachgebildet. Für einen Bugfix muss der zugehörige
Test vor dem Fix fehlschlagen und nach dem Fix bestehen.

### 6.2 Getrennte Nachweise

| Nachweis | Aussage und Grenze |
| --- | --- |
| Automatisierte Unit-/Integrations-/Browser-Tests mit simulierten Diensten | Belegen Verarbeitung, Zustandsübergänge, Sicherheit und Darstellung; erreichen 100 % Zeilen- und Branch-Abdeckung des eigenen Anwendungscodes |
| Auswertung aufgezeichneter synthetischer Antworten | Belegt reproduzierbaren Vergleich und zeigt bekannte Fehlerfälle; beweist keine Qualität eines neu geänderten Prompts |
| Vergleich mit einem tatsächlichen Modell | Misst Erkennung und Fehlalarme auf demselben eingefrorenen synthetischen Korpus; benötigt vorher ausdrückliche Freigabe für Modell, Datenübertragung, Umfang und Kostenbudget |

Gemessen werden getrennt nach Aufgaben und Terminen: korrekt erkannte Aktionen,
übersehene Aktionen, fälschlich vorgeschlagene Aktionen und Feldkorrektheit
(Datum, Frist, Zuständigkeit, Beleg und Zuordnung). Technische Ausfälle und nicht
auswertbare Antworten werden separat gezählt und nicht aus den Ergebnissen entfernt.

Vor Modell-/Promptanpassungen werden Korpus, Baseline und Abnahmeschwellen festgelegt.
Schwellen werden nicht nachträglich abgesenkt oder Fälle entfernt, um eine Änderung freizugeben.
Kritische Sicherheitsfälle dürfen keine unberechtigte Anlage oder automatische Freigabe erzeugen.
Der bestehende Fingerprint-Schutz bleibt aktiv; eine neue Baseline benötigt einen begründeten Nachweis.

Eine Aussage „bessere Modellerkennung“ setzt einen vergleichbaren Vorher-/Nachher-Lauf
mit tatsächlichen Modellausgaben voraus. Ohne dessen Freigabe dokumentiert der Release-Bericht
die Modellqualität als nicht nachgewiesen. Simulierte Tests werden nicht als Ersatz ausgegeben.

## 7. Sicherheit, Datenschutz und Einstellungen

- Webaktionen prüfen bei Annahme und Ausführung Sitzung, CSRF-Schutz, Analyserunde,
  betroffene Vorschlagsversionen und Idempotenzschlüssel. Doppelte oder parallele Starts
  führen höchstens zu einem aktiven Auftrag je Mail und Ausgangsrunde.
- Mailinhalt, Benutzerhinweis und LLM-Ergebnisse bleiben nicht vertrauenswürdig. Sie können
  weder Berechtigungen erweitern noch eine ausdrückliche Schreibbestätigung ersetzen.
- Jeder neue externe Schreibzugriff benötigt weiterhin die ausdrückliche Freigabe genau
  der aktuellen Vorschlagsversion. Die Übernahme einer Analyse ist keine solche Freigabe.
- Modelle, Prompts und LLM-Parameter bleiben in `prompts.yaml`, Themen in `topics.yaml`,
  Anwendungslimits und Prüfregeln in `config.yaml`; Geheimnisse bleiben außerhalb des Codes.
  Die genauen neuen Einstellungsnamen werden vor Implementierung der Aufträge festgelegt.
- Kein automatisches Umschreiben von Prompts oder Themen anhand von Rückmeldungen.
  Eine spätere Anpassung bleibt ein eigenständiger prüfbarer Vorgang.
- Aufbewahrung und Löschung gelten auch für neue Belege, Vergleichsergebnisse und Analyseaufträge.
  Gelöschte Inhalte werden nicht durch zusätzliche Erklärungsschnappschüsse dauerhaft erhalten.
- Zustände stehen in lesbaren JSON-Dateien; JSONL-Logs enthalten Kennungen und Fehlercodes,
  keine Zugangsdaten oder vollständigen Mail-/LLM-Inhalte im regulären Betrieb.
- Der Testmodus führt keine echten externen Schreibzugriffe aus. Automatisierte Tests
  verwenden für Postfach, LLM und Zielanbieter ausschließlich simulierte Dienste.

## 8. Umsetzungsschritte

Jeder Schritt ist für die spätere Umsetzung vorgesehen und erhält eigene Tests sowie
einen versionsgepflegten Commit. S bedeutet höchstens einen Entwicklungstag, M höchstens
zwei; größere Pakete werden vor Beginn geteilt. Keine der folgenden Versionen wird durch
diesen Plan bereits veröffentlicht.

| Schritt | Geplante Patchversion | Inhalt / fertig, wenn … | Umfang | Voraussetzung |
| --- | --- | --- | :---: | --- |
| R1 | 5.1.0 | Erklärungsmodell und Statusinventar: tatsächliche Pipelineausgänge, Gründe, Quellen und fehlende Daten eindeutig abbilden; bestehende gespeicherte Zustände ohne erfundene Informationen lesen. | M | Stand nach 5.0 abgleichen |
| R2 | 5.1.1 | Prüfverlauf in der Mailansicht: fehlende Aufgabe, ausgelassene Prüfung, Fehler und Dublette verständlich unterscheiden; mobil und ohne JavaScript nutzbar. | S | R1 |
| R3 | 5.1.2 | Dauerhafte Nachanalyseaufträge: Analyserunde, Fingerabdrücke, Budget, Grenzen, Abbruch, Neustart und sichere Bindung an die Originalmail. | M | R1 |
| R4 | 5.1.3 | Ergebnisvergleich und Übernahme: bestehende Vorschläge, Ablehnungen, externe IDs, Zielbindungen und Schreibbelege erhalten; neue Ergebnisse nur als unbestätigte Vorschläge. | M | R3 |
| R5 | 5.1.4 | Konsistenzhinweise: vorhandene Zählkonflikte zusammenführen, belegte Widersprüche und Grenzen erkennen; stabile Regelkennungen, keine Datums-/Frist-Automatik ohne Handlungsbeleg. | M | R1, R4 |
| R6 | 5.1.5 | Bedienung der Nachanalyse: „Aufgabe oder Termin übersehen?“, Kosten-/Budgethinweis, Fortschritt, Vorher-/Nachher-Vergleich und geprüfte Übernahme; Authentifizierung und Replay getestet. | M | R2–R5 |
| R7 | 5.1.6 | Qualitätskorpus und Bericht: synthetische Positiv-/Negativfälle, Erkennung, Auslassungen, Fehlalarme und Feldkorrektheit getrennt auswerten; bestehende Gates erhalten. | M | R1, R5 |
| R8 | 5.1.7 | Gezielte Erkennungsverbesserungen: konkrete Fehler reproduzieren und beheben; Prompt-/Modelländerungen nur mit eingefrorener Baseline und dokumentierter Vergleichsmethode. Tatsächlicher Modelllauf ausschließlich nach gesonderter Freigabe. | M | R7 |
| R9 | 5.1.8 | Migration, Retention und Gesamtsicherheit: alte und beschädigte Zustände, fehlende Originale, Versionskonflikte, parallele Bedienung und Neustarts prüfen; Spezifikation und Konfigurationsbeispiele aktualisieren. | M | R4–R8 |
| R10 | 5.1.9 | Abnahme und Release: vollständige Prüfungen unter Windows 11 und Linux/Docker, 100 % Zeilen-/Branch-Abdeckung, Browser-/Paketprüfung; README, Changelog und `docs/Release-5.1.md` mit Nachweisen und Grenzen. | M | R9 |

Bei jedem Implementierungscommit in `main` oder `beta` werden die Versionen in
`pyproject.toml` und `src/mailhelp/__init__.py`, Changelog und README gemäß Entwicklungsregeln gepflegt.
Während der Erstellung dieses Plans werden Anwendungscode, Konfiguration und Versionsnummer nicht geändert.

## 9. Verbindliche Abnahmefälle

| Fall | Erwartetes Ergebnis |
| --- | --- |
| Mail ohne Aufgabe | Gespeicherter tatsächlicher Grund und Analyserunde sichtbar; kein zusätzlicher LLM-Aufruf allein zum Erklären |
| Relevante Mail mit übersehenem Auftrag | Gezielte Nachanalyse möglich; belegter neuer Vorschlag bleibt unbestätigt |
| Besprechungsinformation ohne eigenen Arbeitsauftrag | Kein erzwungener Aufgabenvorschlag aufgrund von Betreff oder Datum |
| Router-/Extraktionskonflikt | Konkreter Hinweis statt stillschweigender vollständiger Erfolgsmeldung |
| Frist in einer Zusammenfassung ohne belastbaren Handlungsbeleg | Allenfalls Prüfhinweis; keine automatische Aufgabe oder Freigabe |
| Bereits angelegter oder unklar geschriebener Vorschlag | Schreibbeleg und Idempotenz erhalten; keine doppelte externe Anlage |
| Verworfener oder manuell bearbeiteter Vorschlag | Entscheidung erhalten; keine automatische Reaktivierung oder Überschreibung |
| Wiederholter Start oder Prozessabbruch | Höchstens ein Auftrag, sichere Fortsetzung, erhaltenes Budget und keine doppelten Vorschläge/Benachrichtigungen |
| Neue Analyserunde oder Vorschlagsversion während laufender Nachanalyse | Veraltete Übernahme wird abgelehnt; bestehender Stand bleibt erhalten |
| Ungültige Sitzung, CSRF oder manipulierter Hinweis | Keine unberechtigte Wirkung; Inhalte können keine Schreibbestätigung ersetzen |
| Originalmail fehlt oder UIDVALIDITY ändert sich | Verständlicher Abbruch; keine Analyse einer anderen Mail mit gleichem Betreff |
| Inhalt nach Aufbewahrungsregel entfernt | Erklärung zeigt fehlende Daten; keine Rekonstruktion oder Umgehung der Löschung |
| Modell-/Extraktionsfehler und zu großer Anhang | Als unvollständige Analyse ausweisen; alte Ergebnisse bleiben nutzbar |
| Testmodus und Nachanalyse bei aktivierten Antwortentwürfen | Keine echten Schreibzugriffe und keine automatische zusätzliche IMAP-Entwurfsablage |
| Qualitätsbericht mit simulierten Antworten | Technische Ergebnisse ausweisen, keine unbewiesene Behauptung über die aktuelle Modellqualität |

**Releasefreigabe:** Alle technischen Abnahmefälle bestehen auf beiden Zielplattformen.
Sämtlicher eigener Anwendungscode erreicht 100 % Zeilen- und 100 % Branch-Abdeckung;
jede Unterschreitung lässt die automatische Prüfung scheitern. Keine neuen Coverage-Ausschlüsse
oder wirkungslosen Tests. Ruff und mypy sind ohne Befunde. Browserprüfungen decken die neuen
Ansichten, mobilen Abläufe und Bedienung ohne JavaScript ab. Der Release-Bericht trennt
Funktionsnachweis und tatsächliche Modellbewertung ausdrücklich.
