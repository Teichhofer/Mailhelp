# Mailhelp 2.4 – Offene Vorschläge zusammenführen und Termindauern vorbelegen

**Zielversion:** 2.4.0

**Stand:** 14. Oktober 2026

**Status:** Auf `beta` umgesetzt; Implementierung in 2.3.2, Abschlussdokumentation in
2.3.3. Die Zielversion 2.4.0 ist noch nicht als Release veröffentlicht.
Die folgenden Abschnitte erhalten die ursprünglichen Planungsentscheidungen.
Den realisierten Ablauf beschreiben die [Architektur](Architektur-2.4.md) und
die [Betriebs- und Upgrade-Anleitung](Release-2.4.md).

**Grundlage:** [Entwicklungsregeln](../AGENTS.md), [Projektspezifikation](../Mailhelp-Projektspezifikation.md),
[Planung 2.3](Planung-2.3.md), [Web-Einstellungen](Web-Einstellungen.md).

## 1. Ziel und verbindliche Entscheidungen

Version 2.4 erweitert den Abgleich jedes erkannten Termins und jeder erkannten Aufgabe
um die **offenen Entscheidungen in Mailhelp**. Mehrere Mails zu demselben Vorgang
sollen einen gemeinsamen, fortgeschriebenen Vorschlag ergeben. Neue Mails ergänzen
fehlende Informationen und Quellen. Vorhandene Informationen und manuelle Änderungen
bleiben nachvollziehbar; Widersprüche werden zur Klärung vorgelegt.

Zusätzlich werden zwei einstellbare Standarddauern eingeführt:

- Videokonferenz: **60 Minuten**.
- Präsenztermin: **180 Minuten**.

Die Standarddauer ergänzt ausschließlich eine fehlende Endzeit bei eindeutigem Beginn
und belegter Teilnahmeart. Eine ausdrücklich genannte Endzeit oder Dauer hat Vorrang.
Der bereits vorhandene Termin zur Beiratssitzung wird neben der Rückmeldeaufgabe sichtbar.

Folgende Entscheidungen gelten für die Umsetzung:

1. Die kanonische Vorschlags-ID bleibt bei Ergänzungen erhalten. Die Übersicht zeigt
   einen offenen Vorschlag je Vorgang, unabhängig von der Anzahl seiner Quellenmails.
2. Zusätzliche, widerspruchsfreie Informationen dürfen lokal automatisch ergänzt werden.
   Unsichere Informationen erscheinen als gekennzeichneter Hinweis oder Klärungsfrage.
3. Unklare **Informationen** und unklare **Identität** werden unterschieden:
   Ein plausibel zugeordneter Zusatz erweitert den bestehenden Vorgang; mehrere mögliche
   Zielvorschläge verlangen eine Zuordnungsentscheidung. Titelähnlichkeit allein erlaubt
   keine Zusammenführung.
4. Jede Änderung einer Vorschlagsakte erhält eine neue Version. Bereits bekannte
   Quellen und unveränderte Fakten ergeben bei Wiederholung keine neue Version.
5. Ergänzen, Zusammenführen und Speichern autorisieren keinen externen Schreibzugriff.
   Kalender-/Aufgabenaktionen erfordern eine ausdrückliche Bestätigung der neuen Version.
6. Standarddauern werden als Anwendungseinstellung gekennzeichnet, nicht als Mailaussage.
   Sie ändern weder die Verbindlichkeit einer Einladung noch die Zuständigkeit.
7. Ein bereits vorhandener externer Eintrag wird erklärt und verlinkt. Ein neuer Eintrag
   wird dafür nicht vorgeschlagen; zusätzliche externe Änderungen benötigen eine eigene Freigabe.

## 2. Befunde aus dem aktuellen Bestand

Die folgenden Befunde stammen aus den gespeicherten Mailzuständen, Vorschlagsakten
und dem Anwendungslog. Kalenderdaten beziehen sich auf den damaligen Abgleich am
12. Oktober 2026; eine aktuelle Abfrage des externen Kalenders ist damit nicht ersetzt.
Einwahllinks, Zugangscodes, vollständige Mailtexte und personenbezogene Kontaktdaten
werden nicht in diesen Plan oder in synthetische Testfixtures übernommen.

### 2.1 Zwei Vorschläge für den Austausch Bundesverband/Landesverband

Untersuchte Entscheidungen:

- [vlf-Austausch Bundesverband und Landesverband](http://127.0.0.1:8765/vorschlag/030a20e45fe70ac57852724a/p_92631c4e370d8e6e9de9bfa8), Version 1.
- [Austausch Bundesverband und Landesverband](http://127.0.0.1:8765/vorschlag/9cb2b16be8563fb184d5cd77/p_a4e7ad51c1c5e80ef2affed5), Version 2.

Beide Mails haben denselben bereinigten Betreff und denselben Referenzanker in
`References`. Die frühere Nachricht vom 06.10.2026, 10:30 UTC kündigt die Verschiebung
des nächsten Tages in den Nachmittag an. Die spätere Nachricht um 10:41 UTC nennt
konkret **07.10.2026, 16:00 Uhr** und einen Teams-Link.

Im ersten Vorschlag ist der Beginn bereits in `known_temporal_facts.start` gespeichert,
während `start`/`end` wegen fehlender Endzeit noch leer sind. Der zweite Vorschlag hat
ein manuell geklärtes Datum, aber noch keinen Beginn. Beide stehen auf
`needs_clarification` und sind als `change` klassifiziert.

**Sollzustand:** ein offener Vorgang mit beiden Quellen, belegtem Beginn 16:00 Uhr und
vorhandenem Einwahllink. Fehlt weiterhin eine aktuelle Endzeit, wird für die Videokonferenz
17:00 Uhr als **angenommenes** Ende vorgeschlagen. Ein altes, zitiertes Zeitfenster
11:45–12:30 Uhr darf nicht als Endzeit des verschobenen 16-Uhr-Termins übernommen werden.

Die Zusammenführung löst die Frage nach dem extern zu ändernden Eintrag nicht automatisch:
Beide Bestandsvorschläge sind Änderungen. Ein gefundenes Kalenderziel wird verknüpft;
fehlt es, bleibt die Ziel-/Fallback-Frage bestehen. Eine Änderungsmail wird nicht stillschweigend
in die Erlaubnis zur Neuanlage umgewandelt.

### 2.2 Skype-Termin und frühere Videokonferenz-Abstimmung

Untersuchte Entscheidungen:

- [Skype-Termin zur Auflösung VLF](http://127.0.0.1:8765/vorschlag/29c0f8dfa9b10dc873bf939c/p_913c8f4d27cdb5759e18276b).
- [Kurze Videokonferenz](http://127.0.0.1:8765/vorschlag/30dad2e182a8afa5d1e7f30c/p_2cefa7dd833dafd69a831528).

Die Mails gehören zum selben Gespräch. Die spätere Nachricht verweist in `References`
direkt auf die frühere Mail. Am 05.10. werden mehrere Verfügbarkeiten für den nächsten
oder übernächsten Tag angeboten. Am 06.10. folgt die konkrete Ankündigung eines
Skype-Termins für **07.10.2026, 13:00 Uhr**.

Der konkretisierte Vorschlag wurde im Bestand sogar **vor** der älteren Abstimmung
verarbeitet. Verarbeitungsreihenfolge und fachliche Aktualität sind somit verschieden.

**Sollzustand:** ein Vorschlag mit der konkreten Zeit 13:00 Uhr, standardmäßig bis
14:00 Uhr, mit sichtbarer Annahme zur Dauer. Die alte Mehrdeutigkeit „morgen oder
übermorgen“ wird durch die spätere konkrete Angabe aufgelöst. Eine später eingelesene
ältere Mail darf den schon bekannten Termin nicht wieder unklar machen.

Die historischen Termine bleiben bei einer Bestandsbereinigung historische Vorgänge.
Eine Bereinigung erstellt keine Termine in der Vergangenheit und setzt keine Freigaben zurück.

### 2.3 Warum bei der Beiratssitzung nur Aufgaben sichtbar sind

Untersuchte Entscheidung:
[Teilnahme an Beiratssitzung zurückmelden](http://127.0.0.1:8765/vorschlag/ff6b89bb1b645908a71b8aac/p_b78cbaf23dd7e860516428bb).

Die gespeicherten Daten belegen folgende Verarbeitung:

| Schritt | Gespeicherter Befund |
| :--- | :--- |
| Router | `task_and_event`, zwei Aufgaben und ein Termin |
| Terminextraktion | „Beiratssitzung der ALH Kupferzell“, 20.11.2026, 14:00–15:30 Uhr, online |
| Normalisierung | vollständiger Terminvorschlag `p_da326a73740c19cb02941612`, zunächst `pending_confirmation` |
| Kalenderabgleich | vorhandener Eintrag „Einladung zur Beiratssitzung der ALH am 20.11.2026, 14 Uhr, online“, ebenfalls 14:00–15:30 Uhr |
| Ergebnis | `already_exists`, mit gespeichertem Kalenderverweis |
| Aufgaben | Rückmeldung und optional weitere Tagesordnungspunkte melden bleiben eigenständige Aufgaben |

Im Anwendungslog steht am **12.10.2026, 07:17:37 UTC** das Ereignis
`duplicate_found_calendar` für diesen Terminvorschlag. Der gespeicherte LLM-Anfragekontext
zeigt die übereinstimmenden Zeitintervalle des erkannten und des vorhandenen Termins.

**Ursache der fehlenden Darstellung:** `MailPipeline` markiert die Benachrichtigung
für `already_exists` sofort als abgeschlossen. `_notify_proposals` überspringt diese
Einträge. Die Speicherung der eigenständigen Vorschlagsakte erfolgt derzeit in
`ProposalDeliveryService`; dadurch entsteht für den übersprungenen Termin keine
`proposal-…json`-Akte. `ReviewViews` liest seine Vorschlagsansichten jedoch aus diesen
Akten. Der Termin bleibt im Mailzustand gespeichert, fehlt aber als sichtbarer Vorgang
und als Erklärung neben den Aufgaben.

**Sollzustand:** Die Rückmeldeaufgabe bleibt erhalten und zeigt „Zugehöriger Termin:
20.11.2026, 14:00–15:30 Uhr – bereits im Kalender“ samt Link. Der erkannte Termin und
sein Abgleich sind in Maildetails/Verlauf sichtbar. Es entsteht keine weitere Anlageentscheidung.
Die ausdrücklich angegebenen **90 Minuten** bleiben erhalten; die Standarddauer von
60 Minuten darf sie nicht verkürzen.

## 3. Technische Ausgangslage und Lücken

| Baustein | Aktueller Stand | Änderung in 2.4 |
| :--- | :--- | :--- |
| `precheck.py` | Abgleich mit ActionLedger, Kalender und aktiven Aufgaben; keine offenen Vorschläge | lokaler Vorschlagsabgleich mit gemeinsamem fachlichem Ergebnis |
| Kalenderabgleich | benötigt aktuell vollständiges `start` und `end` | Suche auch anhand gesicherter Teilinformationen; fehlendes Ende verhindert keine lokale Zuordnung |
| `proposal_builder.py` | Identität enthält Quellenmail und extrahierte Fakten | Quellenkandidaten bleiben identifizierbar, gemeinsamer Vorgang erhält eine stabile kanonische Identität |
| `action_normalization.py` | ohne Endzeit/explizite Dauer folgt „Wann endet der Termin?“ | belegte Teilnahmeart und Standarddauer ergänzen das Ende nachvollziehbar |
| `mail_pipeline.py` | Kandidatenliste wird mailweise verarbeitet; Speicherung teils an Zustellung gekoppelt | Speicherung und Abgleich vor jeder Entscheidungsvorlage, getrennt von Zustellung |
| `telegram/persistence.py` | Revision, Einzelakte und Mailprojektion werden wiederherstellbar geschrieben | zusätzlich Quellenverknüpfungen, Aliasakten und gemeinsame Wiederaufnahme |
| `review/views.py` | Einzelakten sind Grundlage der Übersicht | kanonische Ansicht, Quellen und sichtbarer Befund „bereits vorhanden“ |
| Einstellungen | keine Standarddauern | zwei Felder mit Hilfetext, Validierung und bestätigter Übernahme |

Der vorhandene ActionLedger enthält erfolgreich ausgeführte Aktionen. Er ist kein
Ersatz für einen Index der offenen Entscheidungen. `mail_duplicates.py` erkennt
doppelte Mails; diese Prüfung bleibt von der Erkennung gleicher fachlicher Vorgänge getrennt.

Die Umsetzung verwendet die in 2.3 eingeführten Rollen und Anbieter. Sie gilt für
Google, CalDAV und Outlook sowie Todoist, Microsoft To Do und die unterstützten
CalDAV-/Apple-Aufgabenziele. Gleiche Zielnamen verschiedener Anbieter dürfen nicht
als gleiches Ziel behandelt werden.

## 4. Fachlicher Abgleich mit offenen Entscheidungen

### 4.1 Welche Vorschläge berücksichtigt werden

- Automatisch ergänzbar: `pending_confirmation` und `needs_clarification`.
- Zusätzlich als geschützte Treffer berücksichtigen: bestätigte, laufend geschriebene,
  fehlgeschlagene oder unklare Aktionen. Sie werden nicht im laufenden Schreibvorgang verändert.
- Bereits angelegte Einträge gehen über den Ledger-/Providerabgleich ein.
- Verworfene und abgeschlossene Vorgänge werden nicht automatisch wieder geöffnet.
- Versionssnapshots, Aliasakten und der eigene neue Kandidat zählen nicht als weitere offene Vorgänge.

Ein Task und ein Event werden niemals zu demselben Vorschlag zusammengeführt. Eine
Teilnahmerückmeldung und die zugehörige Sitzung erhalten stattdessen eine Beziehung.
Ebenso bleiben „Teilnahme rückmelden“ und „Tagesordnungspunkt einreichen“ unterschiedliche Aufgaben.

### 4.2 Kandidatensuche

Ein lokaler Index grenzt mögliche Treffer ein. Die Suche darf **nicht nur** auf gleiche
Titel oder vollständig normalisierte Zeitintervalle beruhen. Verwendet werden:

- Vorgangsart, Provider und Zielbindung; Produktions- und Testzustand strikt getrennt.
- `Message-ID`, `References` und künftig bereinigt erfasstes `In-Reply-To`.
- Betreff ohne wiederholte Antwort-/Weiterleitungspräfixe, Organisation und konkreter Anlass.
- Datum, bestätigter oder bekannter Beginn, zulässige Datumsalternativen und Aufgabenfrist.
- Kalenderanhang-UID und belegte Veranstaltungs-/Aufgabenreferenz, sofern vorhanden.
- Titel und kurze, erforderliche Belegfragmente; keine vollständige Archivübermittlung an das LLM.

Ein gemeinsamer Mailthread reicht nicht allein: Ein Thread kann mehrere Sitzungen
oder Aufgaben enthalten. Auch ein wiederverwendeter Videolink, ein generischer Titel
oder derselbe Absender ist kein hinreichender Identitätsbeleg. Ein wiederkehrender
Termin braucht zusätzlich die konkrete Instanz.

Die Begrenzung muss vollständigkeitsbewusst sein: zunächst deterministische Treffer
aus dem gesamten relevanten Index, danach höchstens acht semantisch zu prüfende Kandidaten
je neuen Kandidaten. Gibt es weitere plausible Treffer, lautet das Ergebnis
„Zuordnung unvollständig“, nicht „kein Treffer“. Fehlende Datumsangaben dürfen die
Thread-/Referenzsuche nicht ausschließen.

Das Budget steht als Anwendungseinstellung `proposal_reconciliation.max_semantic_candidates`
in `config.yaml` (Standard 8, gültiger Bereich 1–50) und wird im Policy-Snapshot erfasst.
Ein Kandidatenpaket wird möglichst in einem LLM-Aufruf verglichen; globale Payload-,
Rate- und Adapterlimits gelten weiterhin. Das Prüfergebnis wird versionsgebunden
gespeichert, damit Neustarts unveränderte Vergleiche nicht erneut bezahlen.

### 4.3 Typisiertes Vergleichsergebnis

Ein optionaler Prompt `open_proposal_match` in `prompts.yaml` beurteilt begrenzte,
vorgegebene Kandidaten. Modell, Prompt und LLM-Parameter bleiben ausschließlich dort.
Die Antwort nennt eine vorhandene Kandidatenreferenz, eine Beziehung
(`same_occurrence`, `related_action`, `different`, `unclear`) und belegte Gründe.

Der Anwendungscode prüft Kandidatenzugehörigkeit, Art, Zielbindung, Referenzen und
widersprüchliche Angaben. Das LLM darf keine IDs erzeugen, Versionen erhöhen, Schreibziele
wechseln, Bestätigungsflags setzen oder den Merge selbst speichern. Ein Confidence-Wert
allein entscheidet nicht über die Identität. Fehlende oder ungültige Antworten ergeben
einen sicheren Klärungszustand.

Fehlt dieser optionale Prompt in einer vorhandenen eigenen Promptkonfiguration,
funktionieren belegte deterministische Zuordnungen weiter. Semantisch unklare Fälle
bleiben sichtbar zur Prüfung stehen. Promptfehlen wird nicht als negativer Dublettenbefund
interpretiert; neue Konfigurationsbeispiele enthalten den vollständigen Vergleichsschritt.

| Ergebnis | Verhalten |
| :--- | :--- |
| Ein eindeutig gleicher offener Vorgang | vorhandenen Vorschlag ergänzen, neue Quellenmail verknüpfen |
| Wahrscheinlich gleicher Vorgang, Zusatz unsicher | Zusatz als ungeprüfte Variante/Frage im zugeordneten Vorgang zeigen; bestehende Felder erhalten |
| Mehrere plausible Zielvorschläge | Zuordnung mit Vergleichsansicht klären; Kandidat dauerhaft zurückhalten, keine zusätzliche Anlageentscheidung |
| Nur thematisch verwandte Aufgabe/Termin | getrennte Vorschläge verknüpfen |
| Eindeutig anderer Vorgang | regulären neuen Vorschlag anlegen |
| Gleicher externer Eintrag | sichtbar als bereits vorhanden dokumentieren; zusätzliche externe Änderungen nur als bestätigungspflichtige Aktualisierung |
| Abgleich fehlgeschlagen/unvollständig | transparent blockierter Abgleich; „nicht geprüft“ niemals als „kein Treffer“ behandeln |

### 4.4 Ergänzungsregeln

1. **Fehlende Werte ergänzen:** Datum, Beginn, aktuelles Ende, Frist, Ort, Einwahllink,
   konkrete Agenda und zusätzliche Belege können übernommen werden, wenn sie zum Vorgang passen.
2. **Gleiche Fakten vereinigen:** Doppelter Text, derselbe Link und dieselbe Quellenmail
   werden nicht erneut angehängt. Beschreibungen werden begrenzt aufgebaut; Quellen bleiben separat abrufbar.
3. **Chronologie beachten:** Eine spätere konkrete Vereinbarung ersetzt eine frühere
   Auswahl unverbindlicher Zeitfenster, wenn der Bezug ausdrücklich belegt ist. Verarbeitung
   älterer Mails nach neueren Mails darf diesen Stand nicht zurückdrehen.
4. **Zitate unterscheiden:** Aktuelle Änderungen haben Vorrang vor unverändert zitierten
   alten Einladungsdaten. „Späteste verarbeitete Mail gewinnt“ ist keine Regel.
5. **Manuelle Werte schützen:** Durch die nutzende Person gesetzte oder bestätigte Felder
   werden nicht automatisch überschrieben. Abweichungen erscheinen im Diff als Konflikt.
6. **Zeitänderungen begrenzen:** Ein belegt verschobener Beginn erlaubt nicht, ein altes
   absolutes Ende auf den neuen Beginn zu übertragen. Eine unveränderte Dauer darf nur
   übernommen werden, wenn ihr Weitergelten belegt ist; sonst gelten Endzeit-/Standardregeln.
7. **Annahmen ersetzen:** Eine später ausdrücklich genannte Dauer/Endzeit ersetzt eine
   noch unbestätigte Standardannahme. Eine manuell bestätigte Dauer erzeugt dagegen einen sichtbaren Konflikt.
8. **Fragen fachlich neu berechnen:** Nur durch neue Belege beantwortete Fragen entfallen.
   Zuständigkeit, Widersprüche und unklare Änderungsziele bleiben erhalten.
9. **Änderung einer offenen Neuanlage:** Wird ein noch nicht angelegter neuer Termin verschoben,
   aktualisiert dies den offenen Anlagevorschlag. Es wird dafür kein externer Eintrag verlangt.
   Reine Änderungsakten ohne solche Grundlage behalten ihren Änderungs-/Fallback-Bedarf.
10. **Ergebnis validieren:** Kanonischer Vorschlag wird erneut durch die vollständigen
    Pydantic-/Zeit-/Statusprüfungen geführt. Die Ergänzung darf keine implizite Freigabe erzeugen.

## 5. Standarddauern und Teilnahmeart

### 5.1 Konfigurationsvertrag

Vorgeschlagener Abschnitt in `config.yaml` und `config.example.yaml`:

```yaml
event_defaults:
  video_duration_minutes: 60
  in_person_duration_minutes: 180
```

Beide Werte sind ganze Minuten im Bereich **1–1440**. Boolesche Werte, Fließkommazahlen,
unbekannte Schlüssel, Null sowie Werte außerhalb des Bereichs werden abgewiesen.
Ohne Abschnitt gelten für künftig erzeugte 2.4-Vorschläge die genannten Standardwerte.

In `/einstellungen` erscheinen „Standarddauer Videokonferenz (Minuten)“ und
„Standarddauer Präsenztermin (Minuten)“ einschließlich Hilfetext. Die vorhandenen
Admin-Kommandos sichern Sitzung, CSRF, Dateihash/Version und Idempotenz; die Sitzung
wird bei Ausführung erneut geprüft. Der Einrichtungsassistent verwendet dieselben Felder.

### 5.2 Erkennung und Priorität

Teilnahmeart wird als `video`, `in_person`, `hybrid` oder `unknown` gespeichert.
Eine belegte Formulierung wie „Videokonferenz“, „Skype-Termin“ oder „findet online statt“
genügt auch ohne Einwahllink. Bei Präsenz muss sich Ort/Teilnahmeform auf den Termin
beziehen; eine Postadresse in der Signatur genügt nicht. Hybrid oder unbekannt führt
zur Nachfrage nach der geplanten Teilnahmeart, soweit keine ausdrückliche Endzeit/Dauer vorliegt.

Reihenfolge der wirksamen Zeitangaben:

1. Manuell festgelegte/ausdrücklich bestätigte Zeitangaben.
2. Passende ausdrückliche Endzeit aus aktueller Mail oder Kalenderanhang, auch „ca. 15:30“.
3. Ausdrücklich genannte Dauer ohne einschränkende Obergrenze.
4. Konfigurierte Standarddauer für die belegte Teilnahmeart.
5. Klärungsfrage, wenn Datum, Beginn oder Teilnahmeart weiterhin unklar sind.

Ungültige oder widersprüchliche explizite Zeitangaben werden nicht durch Standardwerte
verdeckt. „Höchstens 30 Minuten“ darf insbesondere nicht durch 60/180 Minuten überschritten
oder stillschweigend in eine exakte Dauer umgewandelt werden.

Ganztags- und mehrtägige Termine behalten ihre eigene Datumslogik. Ein reines Zeitfenster
„ab 11 Uhr möglich“ erhält keinen erfundenen festen Beginn. Der Standard füllt ausschließlich
ein fehlendes Ende eines tatsächlich vorgeschlagenen Termins mit eindeutigem Beginn.

### 5.3 Herkunft, Zeitzonen und spätere Änderungen

Die Anwendung berechnet die Endzeit. Das Extraktions-LLM liefert weiterhin Rohfakten;
es soll die Standards nicht als angebliche Mailangaben ausgeben. Gespeichert werden
Teilnahmeart, Herkunft der Endzeit und der tatsächlich angewandte Standardwert.
Mögliche Endzeit-Herkünfte: Mail-Ende, Mail-Dauer, Kalenderanhang, Standard, manuelle Eingabe.

Beispielanzeige: „07.10.2026, 13:00–14:00 Uhr · Ende angenommen: Standarddauer Video 60 Min.“
Die Person kann das Ende vor Bestätigung bearbeiten. Im externen Beschreibungstext ist eine
verwendete Standardannahme nachvollziehbar, ohne zusätzliche technische Angaben im Bedienfluss.

Dauern sind verstrichene Minuten: Der Beginn wird nach UTC überführt, die Dauer addiert
und das Ende in die Terminzeitzone zurückgeführt. Tests sichern Mitternacht, Sommer-/Winterzeit,
mehrdeutige lokale Uhrzeiten und fehlende Zeitzonen. Ein unklarer Beginn bleibt unklar.

Eine Änderung der Einstellungen gilt für zukünftige Normalisierungen. Bestehende
Vorschläge, bereits genehmigte Versionen und angelegte Termine werden nicht nachträglich
umgerechnet. Für eine Neubewertung zeigt die Oberfläche einen ausdrücklich übernehmbaren Diff.

## 6. Architektur, Zustand und Wiederaufnahme

### 6.1 Geplanter Ablauf

1. Mail-/Anhangvorbereitung, Relevanz, Router und Rohextraktion wie bisher.
2. Normalisierung mit nachvollziehbaren Standardannahmen und gesicherten Teilfakten.
3. Dauerhaften Abgleichauftrag mit Eingangsreferenz und Policy-Snapshot erfassen.
4. Lokale Kandidaten einschließlich anderer Kandidaten derselben Mail/Charge bestimmen.
5. Semantische Prüfung und externe **lesende** Abgleiche außerhalb des globalen Store-Locks.
6. Unter Lock aktuelle Zielversion, Zielbindung und Ausführungszustand erneut prüfen.
7. Kanonischen Vorschlag und Beziehungen wiederherstellbar speichern.
8. Erst danach Übersicht, Historie und Benachrichtigungen aktualisieren.

`precheck.check_proposal()` liefert heute nur einen Vorschlag. Die neue Verarbeitung
braucht ein typisiertes Abgleichergebnis mit kanonischer Referenz und Ausgang
`new`, `merged`, `linked_pending`, `external_exists` oder `blocked`. Eine eigene
`ProposalReconciliationService` koordiniert diesen Schritt; Providerabgleiche bleiben
in ihren vorhandenen Adaptern. So wird kein fremder kanonischer Vorschlag fälschlich
in die Kandidatenliste einer anderen Quellenmail hineinkopiert.

### 6.2 Datenmodelle

Geplante Erweiterungen werden vor Implementierung durch Schema-Snapshots festgelegt:

- **Proposal:** Teilnahmeart und Endzeit-Herkunft; angewandter Standard; geprüfte
  Quellenreferenzen und Feldherkunft; bei Aliasakten eine kanonische Referenz.
- **Quellenreferenz:** Mail-ID, Kandidaten-ID, Nachrichtenzeit/Referenzmaterial und
  kontrollierte Belegstellen. Keine zusätzliche Volltextkopie.
- **ProposalRelation:** z. B. `merged_into`, `related_to`, `rsvp_for` mit Referenzen,
  betroffenen Versionen, nachvollziehbarem Abgleichgrund und Prüfzustand.
- **Merge-Journal:** stabile Operations-ID, Eingangs-/Zielversionen, Policy-Hash,
  beabsichtigte Revision, Alias- und Projektionsschritte, Wiederaufnahmestatus.
- **MailState:** Abgleichfortschritt und kanonische Verweise zusätzlich zu den eigenen
  ursprünglichen Kandidaten. Rohextraktion bleibt für Diagnose und Wiederaufnahme erhalten.
- **Lokaler Index:** lediglich rebuildbare Referenzen und Suchmetadaten; kanonische
  Vorschlagsakten bleiben maßgeblich. Alte Versionssnapshots sind keine Indexeinträge.

Aliasakten erhalten einen eigenen, nicht ausführbaren Status `merged` statt
`already_exists`: „zusammengeführt in einen offenen Vorschlag“ ist fachlich etwas
anderes als „schon extern vorhanden“. Zyklen, Verweise auf sich selbst, ungültige Ziele
und ungebundene Versionen werden vom Schema/Service abgewiesen.

Der Index beginnt als Cache über den bestehenden JSON-Zustand, ohne neue Datenbank
oder Suchdienste. Fehlende Einzelakten aus alten Mailprojektionen werden kontrolliert
repariert; ein kaputter Datensatz darf keine unvermerkte Dublettenneuanlage auslösen.

### 6.3 Transaktion und Parallelität

Ein Merge betrifft mehrere Dateien und ist mit Einzeldatei-Atomic-Replacement allein
nicht atomar. Das Journal wird zuerst geschrieben, dann die immutable neue Revision,
die kanonische Einzelakte, Beziehungen/Alias und zuletzt Mail-, Run- und Anzeigeprojektionen.
Benachrichtigungen werden erst nach Abschluss dieser Schritte freigegeben.

Beim Neustart werden offene Journaloperationen idempotent beendet. Die Operations-ID
bindet Quellenkandidat, Eingangsversion, Zielversion und Policy. Gleichzeitige Mails zu
demselben Vorgang benötigen einen Vergleich und eine erneute Zielsuche unter Lock,
damit nicht beide auf einem alten Snapshot jeweils einen neuen Vorschlag erzeugen.
Eingangs-/Zieländerungen führen zur kontrollierten Neuprüfung, nicht zum Überschreiben.

Während `confirmed`/`writing` oder eines unklaren Schreibresultats werden neue Fakten
zurückgehalten. Zuerst wird die bestehende Aktion abgeglichen; anschließend entsteht
gegebenenfalls ein neuer, separat zu bestätigender Aktualisierungsvorschlag.

### 6.4 Fingerprints und Retention

Standarddauern und Abgleichlogik verändern die Vorschlagsnormalisierung. Sie dürfen
weder stillschweigend aus Fingerprints verschwinden noch offene LLM-Analysen blockieren.
Deshalb wird eine separate, pro Verarbeitung persistierte **Normalisierungs-/Abgleichpolicy**
mit Konfigurationswerten und Versionshash eingeführt. Rohanalyse-Fingerprints behalten
ihre bisherige Bedeutung. Neue Matching-Prompts erhalten eigene Ergebnis-Cache-Schlüssel,
gebunden an Eingangs-/Zielversionen und Prompt-/Policy-Hash.

Ein gestarteter Auftrag verwendet nach Neustart denselben Policy-Snapshot. Neue Werte
ändern keine alte materielle Vorschlagsversion. Legacy-Fingerprint-Kompatibilität
und fehlende Policy-Felder alter Zustände werden ausdrücklich migriert und getestet.

Quellenbelege unterliegen der bestehenden Aufbewahrung. Nach Entfernung des Mailtexts
bleibt der minimale Zuordnungsnachweis für offene Vorgänge erhalten; die Oberfläche
zeigt „Quelltext nach Aufbewahrung entfernt“. Indizes und Journale dürfen Mailtexte
oder Einwahldaten nicht durch eine zweite, unbegrenzte Aufbewahrung konservieren.

## 7. Darstellung, Autorisierung und externer Schreibschutz

### 7.1 Web und Telegram

- In der Übersicht steht ein kanonischer Vorschlag mit „Ergänzt aus N Mails“.
- Die Detailansicht zeigt Quellen, neue Informationen, Konflikte und das Vorher/Nachher-Diff.
- Ein übernommener Standard ist sichtbar und bearbeitbar.
- Zusammengeführte alte GET-Links führen zur kanonischen Ansicht mit Hinweis. Alte
  POST-/Callback-Aktionen werden nicht auf eine andere Version umgeschrieben.
- Eine neue sachliche Ergänzung meldet „Vorschlag ergänzt“ statt einer zweiten Einladung.
  Reine Wiederholung erzeugt keine weitere Meldung. Inhaltsfreigaben, Ruhezeiten und
  Kanalprofil gelten unverändert; Push bleibt neutral.
- Telegram-Klärungen beziehen sich auf die aktuelle kanonische Version. Antworten zu
  älteren Versionen werden nicht nachträglich auf eine neue Frage angewandt.
- Teilnahmeaufgabe und Termin haben gegenseitige Links. Ein bereits vorhandener Termin
  wird in Maildetails/Verlauf erklärt, ohne einen zusätzlichen Bestätigungsbutton zur Neuanlage.
- Alle Basisfunktionen einschließlich Konflikt-/Zuordnungsprüfung funktionieren ohne JavaScript.

### 7.2 Prüfung bei Ausführung

Versionsbezogene Freigabe, gültige Sitzung, CSRF-Schutz und Idempotenz bleiben verbindlich.
Ein zwischen Vorschlagsanzeige und Bestätigung eingegangener Zusatz macht einen alten
Button veraltet. Ein bereits in der Kommando-Inbox liegendes Bestätigen wird bei der
Ausführung erneut gegen kanonische Identität, Version, Zielbindung und Sitzung geprüft.

Der Schreibpfad prüft den aktuellen lokalen/externalen Abgleich nochmals, bevor eine
Anlage erfolgt. Ändert sich dabei das Ergebnis, wird eine neue Prüfung/Version angezeigt;
die alte Bestätigung wird nicht auf einen anderen Eintrag oder eine Aktualisierung übertragen.
Ein Timeout oder unklarer Providerstatus wird vor Wiederholung abgeglichen.

Bei vorhandenen externen Einträgen dürfen neue Agenda-/Orts-/Einwahlinformationen nur
über den vorhandenen bestätigten Aktualisierungspfad ergänzt werden. Auch dieses
„nur Ergänzen“ ist ein externer Schreibzugriff und braucht die konkrete Versionsfreigabe.
Unterstützt ein Aufgaben-/Kalenderadapter diese Aktualisierung nicht, wird dies mit
einem Hinweis zur manuellen Bearbeitung erklärt. Daraus darf keine neue Doppelanlage
als Ersatz entstehen; eine zusätzliche generische Provider-Update-API ist kein impliziter Teil des Plans.

## 8. Beirat-Bugfix und Bereinigung des Altbestands

### 8.1 Speicherung von Zustellung entkoppeln

Alle finalen Abgleichergebnisse werden als Einzelakte/Revision und Historienereignis
gespeichert, **bevor** die Zustellentscheidung fällt. Das gilt auch für `already_exists`
und zurückgehaltene Abgleichkandidaten. Zustellung liest gespeicherte Referenzen und
ist nicht mehr für die Existenz der Vorschlagsakte verantwortlich.

Die Mailansicht erklärt getrennt „erkannt“, „im Kalender gefunden“, „offene Entscheidung“
und „zugestellt“. Beim Beirat-Fall werden beide Aufgaben sowie der bereits vorhandene
Videotermin sichtbar zugeordnet. Ein vorhandener Kalendereintrag wird dabei nicht erneut angelegt.

### 8.2 Vorschau für bestehende doppelte Entscheidungen

1. Dienst anhalten bzw. Bestandsoperationen über den gleichen Ausführungsmechanismus sperren;
   Konfiguration und JSON-Zustand sichern.
2. Aus gültigen aktuellen Akten und gespeicherten Mailprojektionen einen lesenden Bericht
   über fehlende Akten, mögliche Zusammenführungen und Konflikte erstellen.
3. Die zwei genannten VLF-Paare im Bericht mit kanonischer Zielakte, Quellen, neuem
   Zeitstand, verbleibenden Fragen und möglicher Standardannahme präsentieren.
4. Bei der kanonischen Auswahl manuell bearbeitete Akten bevorzugen; ansonsten eine
   stabile Reihenfolge nach ursprünglicher Anlage und ID verwenden. Unvereinbare manuelle
   Stände benötigen eine Auswahl. Die Auswahl bleibt nach Wiederholung/Neustart stabil.
5. Zusammenführung und Neubewertung von Standarddauern in der authentifizierten
   Oberfläche mit konkreten Versionsständen, CSRF und Idempotenz übernehmen lassen.
6. Aliasakten und alte Links erhalten, keine Versionssnapshots löschen; Index und
   Mail-/Runprojektionen nach der Journaloperation wiederherstellen.

Eine Legacy-Migration ergänzt zunächst neutrale Felder und fehlende Akten, ohne alte
Entscheidungen neu zu klassifizieren oder alte Freigaben zu übertragen. Bereits offene
Vorschläge erhalten Standarddauern nur über die beschriebene Neubewertung.

Der besondere VLF-Altbestand enthält eine weiterhin offene Vorschlagsakte, deren
Mailanalyse bereits entfernt wurde. Der Abgleich muss deshalb eigenständige aktuelle
Vorschläge berücksichtigen und darf nicht ausschließlich von vollständigen Mailanalysen abhängen.

Ein Rollback erfolgt bei gestopptem Dienst über die zuvor gesicherte Paket-/Zustandsversion.
Neue Schemas, Aliasakten und Journale dürfen nicht durch bloßes Löschen einzelner Dateien
zurückgerollt werden. Keine automatische Reparatur schreibt in Kalender oder Aufgabenlisten.

## 9. Umsetzung in überprüfbaren Phasen

| Phase | Arbeit | Abschlusskriterium |
| :--- | :--- | :--- |
| 1 – Regressionen und Verträge | synthetische Varianten der drei Beispiele, Matching-/Quellen-/Zeitmodelle, Schema- und Autorisierungsvertrag | alte Verarbeitung reproduziert zwei Vorschläge bzw. den unsichtbaren Kalenderbefund; Anforderungen sind als Tests prüfbar |
| 2 – Beirat-Befund sichtbar machen | Speicherung vor Zustellung, `already_exists` in Detail/Verlauf, Beziehung RSVP→Termin, kontrollierte Reparatur fehlender Akten | Aufgabe bleibt offen, vorhandener 90-Minuten-Termin wird verlinkt; keine externe Anlage und keine Zustellschleife |
| 3 – Standarddauern | Settings/YAML/Web/Assistent, Teilnahmeart, Herkunft, Normalisierung und Policy-Snapshot | Video 60, Präsenz 180; explizite 90 Minuten bleiben; fehlender Beginn bleibt eine Frage |
| 4 – Lokaler Abgleich | Index, deterministische Eingrenzung, typisiertes Matching, Regeln für Ergänzung/Konflikt und Reihenfolge | beide VLF-Paare ergeben jeweils einen Vorgang, auch bei umgekehrter Verarbeitung |
| 5 – Persistenz und Bedienung | Merge-Journal, Aliasakten, kanonische Views, Version/Inbox-Recheck, Telegram-/Push-Verknüpfung | Neustarts/Parallelität verlieren keine Fakten; alte Freigaben und Alias-POSTs werden abgewiesen |
| 6 – Altbestand | Vorschau und bestätigte lokale Bereinigung, Retention, Schema-/Fingerprint-Migration, Rollback | wiederholbare Vorschau/Übernahme; manuelle Versionen erhalten; kein externer Seiteneffekt |
| 7 – Abnahme | vollständige Tests, Providerintegration, Windows/WSL/Linux/Docker, Browser/Paketprüfung und Dokumentation | sämtliche Gates grün; die drei Beispielszenarien erfüllt und 2.4.0 freigabefähig |

Jede Phase enthält ihre passenden Tests und Dokumentationsänderungen. Die Umsetzung
beginnt mit einer Baseline des dann aktuellen 2.3-Stands; parallel entstandene
Provider-/Such-/Anhangänderungen werden erhalten und ihre Schnittstellen wiederverwendet.

## 10. Testmatrix und Qualitätsgate

Produktive Mails werden ausschließlich für die beschriebene lesende Diagnose verwendet.
Automatisierte Tests verwenden synthetische Mails, neue Identitäten und Fake-Provider;
keine echten Adressen, Einwahlcodes, OAuth-Daten oder vollständigen Originaltexte.

| Testbereich | Verbindliche Fälle |
| :--- | :--- |
| VLF-Austausch | ähnliche unterschiedliche Titel, gleiche Referenz, neue konkrete Uhrzeit/Link, fehlendes Ende, beide Ankunftsreihenfolgen, manuell geklärtes Datum |
| Skype/Videokonferenz | Zeitfenster→konkrete Zusage, direkte Antwortreferenz, ältere Mail nach neuerer, keine Rückstufung der bekannten Zeit |
| Beirat | Router 2 Tasks/1 Event, bestehender identischer Termin, Einzelakte/Verlauf trotz unterdrückter Zustellung, 90 Minuten vor 60-Minuten-Standard, Aufgabe nicht mit Event verschmelzen |
| Aufgaben | gleiche Handlung aus Folgemail ergänzen; unterschiedliche Fristen, Verantwortliche und Vorkommen nicht blind vereinigen; Rückmeldung und Agenda getrennt |
| Falsche Treffer | gleicher generischer Titel an anderem Tag, mehrere Termine im Thread, dauerhafter Videolink, unterschiedliche Provider/Ziele, unterschiedliche Serieninstanz |
| Unvollständigkeit | fehlende Endzeit, Teilzeitfakten, mehrere Kandidaten, überschrittenes Matchingbudget, ungültige LLM-Antwort, falsche Referenz, fehlender Quelltext, beschädigter Index |
| Ergänzung | neue Fakten einmal, identische Quelle No-op, ältere Angaben ohne Rückstufung, manuelle Werte geschützt, Widerspruch bleibt sichtbar, explizites Ende ersetzt Standardannahme |
| Dauer | Video ohne Link, Präsenz ohne Signatur-Verwechslung, Hybrid/Unbekannt, explizite Endzeit/Dauer, Obergrenze, ungültige Zeit, Ganztag, Mitternacht, DST-Lücke/-Faltung |
| Wiederaufnahme | Abbruch vor/nach jedem Journalschritt, Neustart, zwei parallel eingehende Mails, Aliaszyklen abgewiesen, Projektionen/Benachrichtigungen wiederhergestellt |
| Autorisierung | veraltete Version/Buttons, widerrufene Sitzung, fehlendes CSRF, wiederholter Schlüssel, Merge während geplanter Bestätigung, Alias-POST, Schreibzustand `uncertain` |
| Provider | Google/CalDAV/Outlook und unterstützte Aufgabenprovider, leere gültige Ergebnisse, Pagination, Cache, Timeout/401/403/ungültige Antwort, kein Write ohne neue Freigabe |
| Upgrade/Retention | 2.3-Zustände, fehlende Einzelakte, entfernte Analyse bei offener Akte, neue neutrale Felder, Policy/Fingerprint, beschädigte Teilzustände, bestätigte Bereinigung, Rollback |
| Web/Telegram | eine Karte, mehrere Quellen, Diff/Annahme/Beziehung, alte GET-Links, veraltete Aktionen, sichere Link-/Textausgabe, Desktop/Mobil/schmal/Tastatur/ohne JavaScript |

Jeder Bugfix erhält einen Regressionstest, der den Fehler über die bisherigen
Anwendungsschnittstellen reproduziert: beispielsweise zwei offene Vorschläge oder
eine fehlende Einzelakte nach erfolgreichem Kalenderabgleich. Ein Importfehler für
eine noch nicht vorhandene neue Klasse ist kein geeigneter Vorher-Nachweis.

Für eigenen Anwendungscode gelten unverändert **100 % Zeilen- und 100 % Branch-Abdeckung**;
das automatische Gate scheitert bei jeder Unterschreitung. Keine zusätzlichen
Coverage-Ausnahmen oder wirkungslosen Tests. Die komplette Browser-Suite muss das
**100-%-JavaScript-Block-Gate** bestehen. Navigationstests sichern Zähler vor dem
Dokumentwechsel, damit ausgeführte Fehlerpfade erhalten bleiben.

Die Plattformabnahme umfasst Python 3.12 gemäß Projekt-Locks auf Windows und Linux,
WSL-Ausführung als unprivilegierter Benutzer für Berechtigungstests sowie Docker mit
Produktionsmounts/UID und Neustart. Wheel-/Quellpaket werden gebaut und das tatsächliche
Wheel separat installiert; Ruff und mypy bleiben fehlerfreie Gates.

## 11. Dokumentation und Freigabe

Bei Umsetzung aktualisieren:

- `config.example.yaml` und Web-Hilfe für die zwei Dauerfelder und ihre Grenzen.
- `prompts.yaml` für Teilnahmeart und begrenzten offenen Vorschlagsvergleich;
  `topics.yaml` benötigt allein durch diese Änderung keine neuen Themen.
- Projektspezifikation für Ergänzungsregeln, Quellenherkunft, Versionsschutz,
  bereits vorhandene Einträge, Standardannahmen und Wiederaufnahme.
- README, Web-Einstellungen und `docs/Release-2.4.md` mit Beispielen, Upgrade,
  Bestandsvorschau und Rollback; Datenschutzhinweise für Quellen/Relationsjournal.
- Persistenz-Schemas und synthetische 2.3→2.4-Upgradefixtures.
- `CHANGELOG.md`, `pyproject.toml` und `src/mailhelp/__init__.py` gemäß den Commit-Regeln
  für `main` und `beta`. Die Zielversion 2.4.0 wird erst zur tatsächlichen Versionsfreigabe gesetzt.

**Abnahmebedingungen:** Die beiden VLF-Paare ergeben jeweils eine kanonische offene
Entscheidung mit nachvollziehbaren Ergänzungen; die Beiratssitzung wird als vorhandener
90-Minuten-Termin neben ihren Aufgaben erklärt; die Standarddauern funktionieren ohne
Überschreiben expliziter Angaben; Wiederholungen, Neustarts und alte Bestätigungen
erzeugen keine doppelte oder unautorisierte externe Aktion. Alle Qualitäts- und
Plattformgates sind bestanden, bevor 2.4.0 freigegeben wird.
