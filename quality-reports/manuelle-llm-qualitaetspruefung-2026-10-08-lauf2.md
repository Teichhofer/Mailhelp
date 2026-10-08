# Manuelle Qualitätsprüfung der LLM-Anfragen – Lauf 2

**Prüfdatum:** 8. Oktober 2026
**Grundlage:** `logs/llm/requests.jsonl` (Lauf 08:05:49–08:15:46 UTC, 692 Ereignisse), `prompts.yaml` in Commit `abbfb8c` (um 08:04 UTC committet und in diesem Lauf verwendet), Telegram-Log des Vormittagslaufs, Anwendungscode
**Methode:** Jeder der 173 Aufrufe wurde mit Eingabe, Reasoning-Text und Ausgabe aufbereitet. Alle 19 als relevant eingestuften Mails wurden über sämtliche Stufen hinweg nachvollzogen (Relevanz → Zusammenfassung → Router → Extraktion → Rückfrageauflösung → Revision). Die 74 irrelevanten Mails wurden einzeln anhand von Absender, Betreff, Textanfang und Begründung geprüft. Es wurden keine Prompts oder Laufzeitdateien geändert.
**Vorgänger:** `manuelle-llm-qualitaetspruefung-2026-10-08.md` (Lauf 05:46 UTC)

## Kurzurteil

Die Empfehlungen der ersten Prüfung haben gewirkt:
- Begründungen bleiben unter 250 Zeichen.
- Reine Teams- und Skype-Zugangsdaten erzeugen keinen Termin mehr (3 von 3).
- Zitierte Rückmeldefristen werden nicht mehr als aktuelle Aufgabe übernommen.
- Die Revision erfindet keinen UTC-Offset mehr.

Formal ist das Ergebnis weiter sehr stabil: 172 von 173 Antworten sind schema-valide, alle Aufrufe enden mit `finish_reason=stop`.

Fachlich zeigt der Lauf drei neue kritische Probleme. Keines davon wird durch die Schema-Validierung sichtbar:

1. **Termine werden um eine Stunde verschoben.** Automatische Kalendererinnerungen enthalten den Zusatz „(UTC+01:00)“. Das ist die Windows-Zeitzonenbezeichnung für Berlin, nicht der am Termin gültige Versatz. Die Terminextraktion übernimmt ihn wörtlich (4 von 4 Erinnerungen). Im Telegram-Log des Vormittagslaufs erscheint deshalb „Beginn: 07.10.2026 · 17:00 Uhr“ für einen Termin um 16:00 Uhr und 14:00 Uhr für einen Termin um 13:00 Uhr.
2. **Eine Phishing-Mail wird zur Aufgabe.** Die Mail „Hast du das schon mal gesehen?“ von einer unbekannten Adresse mit Kurzlink wird als „persönliche Korrespondenz“ relevant eingestuft. Die Aufgabenextraktion macht daraus `"Link anschauen und testen"` mit `user/certain/new`, also einen vollständigen Todoist-Vorschlag mit Bestätigungsknopf.
3. **Zeitrevisionen laufen ins Leere.** Die neue Regel gegen erfundene Offsets ist richtig. Weil die Anwendung aber nie einen vertrauenswürdigen Offset übergibt, liefert die Revision bei 4 von 6 Terminrevisionen `changes: {}`. Eine korrekt aus der Mail gelesene Startzeit (13:00 Uhr) wird dadurch nie übernommen, und die Frage geht stattdessen an den Nutzer.

Dazu kommt ein struktureller Mangel, der viele kleinere Fehler erklärt: **Kein Prompt weiß, wer die nutzende Person ist.** Die Prompts sagen „die Mail ist an die nutzende Person gerichtet“. Der Payload enthält aber weder ihren Namen noch ihre Adressen, und auch keine An- und Cc-Kopfzeilen. Die Folgen:
- Eine Bitte an „Daniela“ wird als Aufgabe gezählt.
- „Herr Stefan Hartmann werden ab 11 Uhr vor Ort sein“ wird nicht als eigener Termin erkannt.
- Zusammenfassungen sprechen vom Nutzer in der dritten Person.

## Umfang und Kennzahlen

| Stufe | Aufrufe | Prompt-Tokens gesamt | Ø Prompt-Tokens | Reasoning-Tokens | Kosten (USD) | Ø Dauer | Schema ok |
|---|---:|---:|---:|---:|---:|---:|---:|
| relevance | 93 | 283.737 | 3.051 | 560 | 0,0372 | 2,7 s | 93/93 |
| summary | 19 | 34.509 | 1.816 | 1 | 0,0058 | 2,6 s | 19/19 |
| action_router | 19 | 39.699 | 2.089 | 728 | 0,0068 | 3,7 s | 19/19 |
| task_extraction | 6 | 11.478 | 1.913 | 345 | 0,0023 | 4,7 s | 6/6 |
| event_extraction | 11 | 27.017 | 2.456 | 1.755 | 0,0062 | 10,3 s | 11/11 |
| mail_question_resolution | 18 | 27.486 | 1.527 | 409 | 0,0044 | 2,1 s | 18/18 |
| proposal_revision | 7 | 4.124 | 589 | 607 | 0,0012 | 3,9 s | 6/7 |
| **Summe** | **173** | **428.050** | | **4.405** | **0,0638** | | **172/173** |

Provider: Together 77, Parasail 72, OpenInference 16, Sail Research 8. Die Relevanzprüfung verursacht 66 % aller Prompt-Tokens und 58 % der Kosten.

### Fachliche Trefferquote je Stufe (manuelle Bewertung)

| Stufe | fachlich korrekt | problematisch | Hauptprobleme |
|---|---:|---:|---|
| relevance | 92/93 | 1 | Phishing als privat relevant; 6× trotz Verbot Themenaufzählung in der Begründung |
| summary | 15/19 | 4 | Nutzer in 3. Person, Personen falsch zugeordnet, `deadlines` fehlt einmal |
| action_router | 14/19 | 5 | Floskel als Aufgabe, Bitte an Dritte gezählt, unverbindliche Terminabsprache als Event, eigener Termin übersehen |
| task_extraction | 2/6 | 4 | Phishing-Aufgabe, Floskel-Aufgabe mit falscher Frist, Aufgabe für Dritte, Titel ohne Handlung |
| event_extraction | 3/11 | 8 | 4× falscher Offset, alte Uhrzeit bei Verschiebung, zitierter Termin extrahiert, „Jour Fixe“-Erinnerung als `recurring` |
| mail_question_resolution | 9/18 | 9 | 8× grundsätzlich nicht beantwortbare Meta-/Hinweisfragen, 1× selbst ergänzter Offset |
| proposal_revision | 2/7 | 5 | 4× Sackgasse ohne Offset, 1× Ganztagsumwandlung samt Schemafehler |

## Befunde

### K1 – Kritisch: Zeitzonenbezeichnungen werden als Offset übernommen

**Beobachtung.** Alle vier web.de-Terminerinnerungen haben die Form
`Erinnerung: vlf - Austausch … am Mi, 07.10.2026, 16:00 Uhr - 16:45 Uhr (UTC+01:00)`.
Die Terminextraktion liefert jedes Mal `"timezone_offset_text":"UTC+01:00"` (Mails 8afe10bf, e02fa30f, 27b82a40, 4e834d68). Am 7. Oktober gilt in Berlin aber Sommerzeit (UTC+02:00). Der Zusatz ist die Windows-Zeitzonenbezeichnung „(UTC+01:00) Amsterdam, Berlin, …“, die immer den Standardversatz nennt.

Der Gegenbeleg im selben Lauf: Die Webex-Einladung schreibt „07:30 | (UTC+02:00) Amsterdam, Berlin, Bern, Rom, Stockholm, Wien“ und zeigt damit den tatsächlichen Versatz. Die Quellen sind also nicht einheitlich.

**Auswirkung.** Die Anwendung berechnet 16:00+01:00 = 17:00 MESZ. Im Telegram-Log des Vormittagslaufs ist das direkt sichtbar:
- „Beginn: 07.10.2026 · 17:00 Uhr (UTC+0200)“ für den Termin um 16:00 Uhr.
- „14:00 Uhr“ für den Skype-Termin, den der Organisator ausdrücklich für „13.00 Uhr“ angesetzt hatte.

Bestätigt der Nutzer, landet der Termin eine Stunde falsch im Kalender.

**Ursache.** Die Promptregel verlangt nur, dass ein Offset „ausdrücklich beim Termin genannt“ ist. Für das Modell erfüllt eine Bezeichnung in Klammern diese Bedingung.

**Vorschlag für `event_extraction`** (ersetzt den Absatz zu `timezone_offset_text`):

> timezone_offset_text ist nur ein Versatz, der ausdrücklich als am Termin geltender Versatz direkt bei der Uhrzeit steht, zum Beispiel „16:00 Uhr (UTC+02:00)“ in einer Nachricht, die den Versatz als Terminangabe nennt, oder „16:00 +02:00“. Zeitzonenbezeichnungen aus Kalendersystemen sind kein Versatz: „(UTC+01:00) Amsterdam, Berlin, Bern, Rom, Stockholm, Wien“ und ein bloßes „(UTC+01:00)“ am Ende automatischer Terminerinnerungen bezeichnen die Zone mit ihrem Standardversatz und gelten nicht für Sommerzeit. In diesen Fällen ist timezone_offset_text null. Leite den Versatz nie aus Ortsnamen, Absendern, Weltwissen, Nutzerzeitzone oder Mail-Headern ab. Die Anwendung bestimmt den gültigen Versatz aus user_timezone.

**Anwendungsseitig (zwingend, Prompt allein reicht nicht):** Ein extrahierter Offset darf nur übernommen werden, wenn er dem tatsächlichen Versatz der Nutzerzeitzone am Termindatum entspricht oder die Mail ihn nachweislich als abweichende Zone meint. Weicht `UTC+01:00` bei einem Sommerzeit-Datum in `Europe/Berlin` ab, die lokale Uhrzeit verwenden und den Offset verwerfen. So wird der Fehler deterministisch abgefangen, auch wenn ein Provider die Promptregel ignoriert.

### K2 – Kritisch: Phishing-Mail wird relevant und zur bestätigungsfähigen Aufgabe

**Beobachtung (Mail 8ffdf34b).** Absender `Tanja Schmidt <demon1@ruinpvtltd.com>`, Betreff „Hast du das schon mal gesehen?“, Text: „Guten Tag, wie geht es dir? Das solltest du dir anschauen. https://rb.gy/aba85s … Teste es auf jeden Fall …“

- Relevanz: `relevant`, Thema `personlicher-smalltalk-private-korrespondenz`, Begründung „Private Nachricht mit persönlicher Begrüßung“.
- Zusammenfassung: erkennt richtig „ohne inhaltliche Begründung einen externen Kurzlink … Zweck bleibt unklar“, warnt aber nicht.
- Router: `unclear` und nennt den Link selbst „verdächtig“.
- Aufgabenextraktion: `"Link anschauen und testen"`, `user/certain/new` → vollständiger Vorschlag „In Todoist anlegen“.

**Ursache.** Kein Prompt enthält eine Regel zu Spam oder Phishing. Die Relevanzregel für private Korrespondenz prüft nur, ob die Mail automatisch erzeugt ist, nicht ob sie vertrauenswürdig ist. Die Aufgabenextraktion behandelt jede direkt formulierte Bitte als „new“.

**Vorschlag für `relevance`** (neuer Absatz nach dem Social-Media-Absatz):

> Unaufgeforderte Nachrichten mit typischen Spam- oder Phishing-Merkmalen sind keine persönliche Korrespondenz, auch wenn sie freundlich und persönlich formuliert sind. Merkmale sind insbesondere: unbekannte oder fachfremde Absenderdomain, keine Anrede mit Namen oder nur eine generische Anrede, kein erkennbarer gemeinsamer Bezug, ein Kurzlink oder ein Link ohne inhaltliche Erklärung, die Aufforderung, einen Link zu öffnen, etwas zu „testen“, Zugangsdaten einzugeben oder zu zahlen. Ordne solche Mails keinem Thema zu und entscheide "irrelevant", Begründung „Verdacht auf Spam/Phishing“.

Dazu ein synthetisches Beispiel:

> - Themen: [{"id":"private","name":"Persönlicher Smalltalk & private Korrespondenz"}]
>   Mail von „Anna <x7@unbekannt-shop.example>“: "Hallo, wie geht's? Schau dir das an: https://kurz.example/ab12 Teste es unbedingt!"
>   Ausgabe: {"decision":"irrelevant","topic_ids":[],"reason":"Verdacht auf Spam/Phishing: unbekannter Absender, Kurzlink ohne Kontext."}

**Vorschlag für `action_router` und `task_extraction`** (gleichlautend):

> Die Aufforderung, einen Link aus einer unaufgeforderten Nachricht zu öffnen, anzusehen oder zu testen, Zugangsdaten einzugeben oder eine Zahlung auszulösen, ist keine Aufgabe, wenn Absender und Anlass nicht erkennbar vertrauenswürdig sind. Liefere dann keine Aufgabe (Router: "none").

**Vorschlag für `summary`:**

> Weist die Mail Spam- oder Phishing-Merkmale auf, beginne den ersten Satz mit „Vorsicht, möglicher Phishing-Versuch:“ und gib Links nicht wieder.

**Anwendungsseitig:** Sinnvoll ist eine deterministische Vorprüfung, die nicht vom Modell abhängt, z. B. Kurzlink-Domains (`rb.gy`, `bit.ly`, …) plus unbekannter Absender → Zusammenfassung mit Warnung, keine Aufgabenextraktion. Außerdem den Absender in `irrelevant-senders.json` aufnehmen.

### K3 – Kritisch: Zeitrevision ohne vertrauenswürdigen Offset führt in eine Sackgasse

**Beobachtung (7 Revisionsaufrufe):**

| Frage | normalized_answer | Ergebnis |
|---|---|---|
| Welches Datum ist mit „morgigen“ gemeint? | 2026-10-07 | 1. Versuch `start=end=2026-10-07, all_day=true` → Schemafehler „Terminende muss nach dem Beginn liegen“; 2. Versuch `start=2026-10-07, all_day=true` |
| Welches Datum ist mit „morgen“ gemeint? (Aufgabe) | 2026-10-07 | `due=2026-10-07` ✔ |
| Bitte die Uhrzeit als HH:MM … angeben. | 13:00 | `changes: {}` |
| Wann beginnt der Termin? | 2026-10-07T13:00:00+02:00 | `changes: {}`, weil der Offset nur in der Antwort steht |
| Welches Datum ist mit „17.10.“ gemeint? | 2026-10-17 | `changes: {}` |
| Welches Datum ist mit „kommenden Freitag“ gemeint? (Startzeit 08:00 bekannt) | 2026-10-02 | `changes: {}` |

Das Reasoning lautet jedes Mal sinngemäß: „Kein UTC-Offset vorhanden → kein vollständiger Zeitstempel möglich → changes {}“.

**Bewertung.**
- Die Regel gegen erfundene Offsets wirkt wie gewünscht.
- Dem Datenvertrag fehlt aber genau die Information, die das Modell bräuchte: Die Anwendung kennt `user_timezone=Europe/Berlin`, übergibt sie der Revision aber nicht.
- Dazu kommen zwei Folgeprobleme:
  - Ein Datum aus der Antwort kann nicht gespeichert werden, weil `temporal_fact.normalized_date` nicht beschreibbar ist. Die Information geht verloren.
  - Ob ein Termin ganztägig ist, entscheidet das Modell selbst. „morgigen Austausch“ war eine Besprechung mit Uhrzeit, wurde aber ganztägig. Die Regel „eine Datumsantwort darf einen zeitgebundenen Termin niemals ganztägig machen“ greift nicht, weil `all_day=false` ohne Uhrzeit für das Modell kein zeitgebundener Termin ist.
- Die drei Stufen verwenden unterschiedliche Formate:
  - `mail_question_resolution` liefert mal „13:00“, mal „2026-10-07T13:00:00+02:00“ (Offset aus Weltwissen ergänzt).
  - `telegram_answer_interpretation` verlangt „JJJJ-MM-TT HH:MM“.
  - `proposal_revision` verlangt ISO mit Offset.

**Empfehlung (Datenvertrag vor Prompt):**
1. Antworten auf Datums- und Uhrzeitfragen **deterministisch** in den Vorschlag übernehmen, statt `proposal_revision` aufzurufen. `parse_deterministic_temporal_answer` existiert bereits für Telegram-Antworten. Die Anwendung setzt Datum, Uhrzeit und `user_timezone` per `zoneinfo` zu einem gültigen Zeitpunkt zusammen. Das LLM wird für diese Fragen nicht gebraucht.
2. Wo die Revision bleibt, übergibt die Anwendung `{"user_timezone":"Europe/Berlin","utc_offset_for_date":"+02:00"}` als vertrauenswürdigen Kontext. Den Versatz berechnet sie pro Termindatum.
3. Ein einheitliches Antwortformat für die Rückfrageauflösung.

**Vorschlag für `mail_question_resolution`** (neuer Absatz):

> Normalisiere ausschließlich in diesen Formaten, jeweils als lokale Angabe ohne UTC-Offset und ohne Zeitzonenkürzel: Datum „JJJJ-MM-TT“; Uhrzeit „HH:MM“; Datum mit Uhrzeit „JJJJ-MM-TT HH:MM“; Zeitspanne „JJJJ-MM-TT HH:MM bis HH:MM“. Ergänze nie einen Offset aus Weltwissen, Ortsangaben oder Sommerzeitregeln. Relative Angaben („morgen“, „kommenden Freitag“) löst du nur anhand des Mail-Datums auf; nenne dieses Bezugsdatum in reason.

**Vorschlag für `proposal_revision`** (Ergänzung, falls Punkt 2 umgesetzt wird):

> utc_offset_for_date ist ein vertrauenswürdiger, von der Anwendung für das Termindatum berechneter Versatz und darf für start und end verwendet werden. Eine Antwort, die nur ein Datum liefert, macht einen Termin ohne bekannte Uhrzeit nicht ganztägig: Setze all_day nur auf true, wenn proposal_fields oder die Frage ausdrücklich einen Ganztagstermin betreffen. Bei einem eintägigen Ganztagstermin lasse end weg.

**Begründung.** Die Ganztags-Fehlentscheidung und der Schemafehler beim ersten Versuch zeigen, dass weder die Konvention für das Ende von Ganztagsterminen noch die Bedeutung von `all_day=false` ohne Uhrzeit im Prompt geklärt ist.

### H1 – Hoch: Kein Wissen über die nutzende Person und die Empfänger

**Beobachtungen:**
- **fb2a0f1f „AW: Postkarten / Arbeitsgruppe“:** Michael schreibt an „Hallo Daniela“; der Nutzer ist nur in Cc (`vorsitzender@vlf-bawue.de`).
  - Der Router zählt „Karten für Daniela bereitstellen“ als Aufgabe.
  - Die Extraktion liefert `responsibility:"other"`.
  - Die Anwendung erzeugt daraus die Rückfrage „Ist die Nutzerin oder der Nutzer für diesen Eintrag zuständig?“, also Rauschen.
  - Übersehen wird dagegen der eigentliche Bezug zum Nutzer: „Gut, wenn **Stefan Hartmann** zu unserer Mitgliederversammlung kommt und weiter berichten kann“. Das ist der Nutzer.
- **50e6affd „Kurzfristige Änderungen vlf Bildungspreisübergabe“:** „Frau Lienhard, **Herr Stefan Hartmann** werden ab 11 Uhr vor Ort in Halle 8 sein.“
  - Der Router liefert `none` („keine Terminangabe“).
  - Die Zusammenfassung schreibt falsch „sie und zwei weitere Beteiligte“ und unterschlägt damit gerade die Information zum Nutzer.
- **5c1c7fe1:** Die Zusammenfassung schreibt „eine Teilnahme von Herrn Hartmann ist optional“, obwohl die Nachricht direkt an ihn geht.
- **Event-Prompt:** Er behauptet „Die Mail ist an die nutzende Person gerichtet“. Das stimmt bei Verteiler-, Cc- und Weiterleitungsmails nicht.

**Ursache.** Der Payload enthält nur `from`, `subject`, `date`, `message_id`. Es fehlen `to` und `cc` sowie Name, Adressen und Rollen der nutzenden Person. Bei Verteilermails ist Zuständigkeit dadurch grundsätzlich nicht entscheidbar.

**Empfehlung (Anwendung und Konfiguration):** In `config.yaml` ein Profil anlegen, z. B.

```yaml
user_profile:
  display_name: Stefan Hartmann
  addresses: [S.H.-Teichhof@web.de, vorsitzender@vlf-bawue.de, stefan-hartmann@email.de]
  roles: [Vorsitzender vlf Baden-Württemberg]
```

Dieses Profil als vertrauenswürdiges Objekt `recipient_context` an `summary`, `action_router`, `task_extraction`, `event_extraction` und `mail_question_resolution` übergeben. Zusätzlich `headers.to` und `headers.cc` übergeben, gekürzt auf Adressen, sowie ein abgeleitetes Feld `user_addressed_as: "to" | "cc" | "bcc_or_list" | "unknown"`. Die Rollen gehören in die Konfiguration, nicht in den Prompt.

**Gemeinsamer Promptbaustein** für Router, Aufgaben- und Terminextraktion (ersetzt „Die Mail ist an die nutzende Person gerichtet …“):

> recipient_context beschreibt vertrauenswürdig die nutzende Person (Name, Adressen, Rollen); user_addressed_as gibt an, ob sie direkt (An), in Kopie (Cc) oder über einen Verteiler adressiert ist. Eine Bitte oder Einladung betrifft die nutzende Person ("user"), wenn sie sie namentlich, über eine ihrer Rollen oder als direkte Empfängerin anspricht. Eine Bitte, die namentlich an eine andere Person gerichtet ist (z. B. Anrede „Hallo Daniela“), ist "other" und wird vom Router nicht als Kandidat gezählt. Bei Verteilern, die eine Rolle der nutzenden Person ansprechen (z. B. „Vorsitzende der Mitgliedsverbände“), gilt "user". Erwähnt die Mail die nutzende Person in der dritten Person mit einer Handlung oder einem Termin („Herr Hartmann ist ab 11 Uhr vor Ort“, „Stefan Hartmann kommt zur Versammlung“), ist das ein Kandidat für sie.

**Für `summary`:**

> Bezeichne die nutzende Person (recipient_context) mit „du“ und nie mit ihrem Namen in der dritten Person. Ordne Handlungen den richtigen Personen zu; kürze Personenangaben nur, wenn dadurch keine Zuordnung verloren geht. Ist die nutzende Person nur in Kopie, beginne mit „Zur Kenntnis (Cc):“.

### H2 – Hoch: Erinnerungen aus dem eigenen Kalender werden als neue Termine vorgeschlagen

**Beobachtung.** 4 der 11 Terminextraktionen betreffen Mails von `Terminerinnerung <keineantwortadresse@web.de>`. Das sind Erinnerungen aus einem Kalender, in dem der Termin bereits existiert. Alle werden als `classification:"new"` vorgeschlagen, eine als `recurring` (H3).
- Die Erinnerungen werden 2,5 Stunden vor Beginn verschickt. Wenn der Nutzer entscheidet, ist der Termin meist vorbei.
- Zum 07.10. gibt es außerdem Vorschläge aus der Einladung, der Verschiebung und der Erinnerung, also bis zu drei Vorschläge für dasselbe Ereignis.

**Produktentscheidung erforderlich.** Empfehlung: automatische Erinnerungen aus dem eigenen Kalender erzeugen **keine** Vorschläge, nur eine Zusammenfassung.
- Umsetzung bevorzugt deterministisch über eine Absenderregel (kein Aktionsschritt für bekannte Erinnerungsabsender).
- Ersatzweise im Router:

> Automatische Erinnerungen eines Kalendersystems an einen bereits bestehenden Termin („Erinnerung: … am …“, Absender ohne Antwortadresse) erzeugen keinen neuen Terminkandidaten, weil der Termin bereits im Kalender steht. Liefere "none" und nenne den Grund.

**Zusätzlich anwendungsseitig:** Termine, deren Ende zum Verarbeitungszeitpunkt schon vorbei ist, nicht mehr zur Bestätigung vorlegen. Betroffen waren in diesem Lauf 02.10., 05.10. und 07.10.; verarbeitet wurde am 08.10.

### H3 – Hoch: Terminextraktion ignoriert die Grenze zwischen aktuellem und zitiertem Text und übernimmt alte Zeiten bei Verschiebungen

**Beobachtungen:**
- **9cb2b16b (Verschiebung „in den Nachmittag“):** Die Extraktion liefert `time_text:"11.45 Uhr"`, `end_time_text:"12.30 Uhr"` aus der zitierten Ursprungsmail, mit `classification:"change"`. Der Vorschlag zeigt damit die aufgehobene Uhrzeit als neue Uhrzeit.
- **30dad2e1:** Neben der (unverbindlichen) Videokonferenz wird „Mitgliederversammlung 17.10.“ aus einem zitierten Absatz einer anderen Person als zweiter Termin extrahiert (`user/uncertain/new`). Der Router hatte ein Event gezählt → Zählerabweichung → Hinweis „Zählerabweichung …“ in Telegram.
- **27b82a40:** Die Erinnerung „Jour Fixe vlf Landesverband am Mo, 05.10.2026“ wird `recurring`, nur weil „Jour Fixe“ im Titel steht. Folge: der Hinweis „Wiederkehrende Einträge werden nicht automatisch angelegt.“ geht als Rückfrage an die Rückfrageauflösung.
- **Mehrere `evidence`-Werte sind nicht wörtlich**, sondern mit „…“ zusammengesetzt (030a20e4, 9cb2b16b, 199e0c29).

**Ursache.** Die Regel zu zitierten Teilen („Bewerte Aufgaben aus dem aktuellen Nachrichtenteil …“) steht nur in Router und Aufgabenextraktion, nicht in der Terminextraktion. Für `change` fehlt die Vorgabe, welche Werte zu übernehmen sind.

**Vorschlag für `event_extraction`** (neuer Absatz):

> Bewerte Termine aus dem aktuellen Nachrichtenteil. Ein Termin, der nur in einer zitierten oder weitergeleiteten älteren Nachricht vorkommt, ist kein eigener Kandidat, außer der aktuelle Teil lädt dazu ein, bestätigt, verschiebt oder sagt ihn ab. Bei classification "change" enthalten date_text, time_text und end_time_text ausschließlich die neuen Werte aus dem aktuellen Teil; der alte Termin gehört nur in description. Ist der neue Wert nicht konkret genannt („in den Nachmittag“), setze das betroffene Feld auf null und time_requirement auf "required_unknown"; übernimm nie den alten Wert. "recurring" gilt nur bei einer ausdrücklichen Wiederholungsregel („jeden Montag“, „wöchentlich“); eine Erinnerung an eine einzelne Sitzung eines Jour Fixe ist kein wiederkehrender Kandidat. evidence ist ein einziger zusammenhängender, wörtlich kopierter Abschnitt ohne Auslassungszeichen; wähle den Abschnitt mit Datum und Uhrzeit.

Die letzte Regel sollte in allen drei Extraktions- und Routerprompts gleich lauten.

### H4 – Hoch: Höflichkeitsfloskeln und doppelte Folgeaufgaben

**Beobachtung (9cb2b16b).** „Wir hoffen, dass Sie die Verschiebung einrichten können“ (gemeint: es zeitlich einrichten, also teilnehmen können) wird zur Aufgabe „Verschobenen Austauschtermin einrichten“, `due_text:"morgen"`.
- Die Aufgabe doppelt den ohnehin erzeugten Änderungsvorschlag zum Termin.
- `due_text` enthält das Datum des Termins, keine Frist.
- Der Nutzer bekommt deshalb die Rückfrage „Welches konkrete Datum ist mit ‚morgen‘ gemeint?“.

**Vorschlag für `action_router` und `task_extraction`:**

> Höflichkeits-, Hoffnungs- und Schlussformeln sind keine Aufgaben, z. B. „Wir hoffen, dass Sie es einrichten können“, „Wir freuen uns auf Ihr Kommen“, „Bis gleich“, „Vielen Dank für eine kurze Rückmeldung“ ohne konkrete Frage an die nutzende Person. Eine Terminverschiebung oder -absage erzeugt keine zusätzliche Aufgabe „Kalender anpassen“ oder „Verschiebung einrichten“; das deckt der Terminkandidat mit classification "change" bzw. "cancellation" ab.

**Für `task_extraction` zusätzlich:**

> due_text ist nur eine Frist für die Aufgabe selbst („bis 16.10.“, „spätestens Freitag“). Das Datum eines Termins, auf den sich die Aufgabe bezieht, ist keine Frist. title beginnt mit einem Verb in der Grundform und beschreibt die Handlung der nutzenden Person (z. B. „Terminwunsch für Videokonferenz mitteilen“, nicht „Videokonferenz zur VLF-Auflösung (Skype-Link)“).

### M1 – Mittel: Rückfrageauflösung erhält Fragen, die eine Mail nie beantworten kann

**Beobachtung.** 8 der 18 Aufrufe betreffen von der Anwendung erzeugte Prüffragen aus [domain/proposal.py](../src/mailhelp/domain/proposal.py) (Zeilen 248–262):

| Frage | Anzahl | Ergebnis |
|---|---:|---|
| „Ist die extrahierte Information sicher belegt?“ | 3 | stets `usable:false` („Meta-Frage“) |
| „Welcher bestehende Eintrag soll geändert werden?“ | 3 | stets `usable:false` |
| „Ist die Nutzerin oder der Nutzer für diesen Eintrag zuständig?“ | 1 | `usable:false` |
| „Wiederkehrende Einträge werden nicht automatisch angelegt.“ (keine Frage) | 1 | `usable:false` |

Das Modell reagiert korrekt. Die Aufrufe kosten aber Zeit und Geld, und dieselben Formulierungen landen danach unverändert beim Nutzer. Dort sind sie ebenso schwer zu beantworten: Was genau soll „sicher belegt“ sein?

**Empfehlung (Anwendung):**
- Nur Fragen mit konkreter Sachangabe an `mail_question_resolution` schicken: Datum, Uhrzeit, Ende, Ort, Link, Frist.
- Hinweise wie „Wiederkehrende Einträge …“ nicht als Frage behandeln.
- Die Prüffragen konkret formulieren, mit dem unsicheren Feld und dem Belegtext, z. B. „Findet ‚Treffen der Arbeitsgruppe‘ am Freitag um 8 Uhr sicher statt? Beleg: ‚Wir würden uns trotzdem am Freitag um 8 Uhr treffen.‘“
- Für die Zuständigkeitsfrage: Sobald `recipient_context` existiert (H1), kann die Stufe sie beantworten.

**Vorschlag für `mail_question_resolution`** (Ergänzung):

> Beantworte die Zuständigkeitsfrage mit „Ja“, wenn die Mail die nutzende Person laut recipient_context namentlich, über eine ihrer Rollen oder als direkte Empfängerin um die Handlung bittet, und mit „Nein“, wenn die Bitte ausdrücklich an eine andere Person gerichtet ist; sonst usable=false. Ist die übergebene Frage keine Frage nach einer Sachangabe, liefere usable=false mit reason „keine Sachfrage“.

### M2 – Mittel: Unverbindliche Terminabstimmungen werden zu Terminkandidaten

**Beobachtung.**
- **30dad2e1:** „Gerne können wir morgen oder übermorgen eine kurze Videokonferenz machen. Morgen würde es bei mir ab ca. 11 Uhr gehen …“
  - Router: `unclear`, event 1.
  - Extraktion: Termin mit `date_text:"morgen oder übermorgen"`, `non_binding`.
  - Folge: Telegram-Frage „Welches konkrete Datum ist mit ‚morgen oder übermorgen‘ gemeint?“.
- **b39cc458:** Die Frage „Geht bei euch Skype? Dann könnte ich einen Link verschicken.“ wird zur Aufgabe mit dem Titel „Videokonferenz zur VLF-Auflösung (Skype-Link)“, `non_binding/uncertain`.
- Der feste Termin entsteht erst mit der nächsten Mail (29c0f8df: „morgen (07.10.2026) um 13.00 Uhr“). Damit gibt es zwei bis drei Vorschläge für dieselbe Videokonferenz.

**Vorschlag für `action_router`** (an die Regel zur Gesprächsdauer anschließen):

> Eine Terminabstimmung ohne Festlegung ist noch kein Termin: Nennt der aktuelle Teil nur mögliche Zeitfenster, Alternativen („morgen oder übermorgen“, „ab 11 Uhr oder nachmittags“) oder die Bereitschaft zu einem Treffen, zähle kein Event. Wird die nutzende Person dabei ausdrücklich nach ihrer Verfügbarkeit oder einer technischen Möglichkeit gefragt („Geht bei euch Skype?“), zähle genau eine Aufgabe „Verfügbarkeit bzw. Antwort mitteilen“. Erst ein festgelegter Zeitpunkt („dann schicke ich für morgen um 13 Uhr einen Termin“) ist ein Terminkandidat.

Dieselbe Grenze gehört in `event_extraction`: „Alternativen ohne Festlegung → kein Event“.

### M3 – Mittel: Zusammenfassungen – Zuordnung, Vollständigkeit und Anhangshinweise

**Beobachtungen:**
- 50e6affd: falsche Zuordnung (siehe H1).
- 227a274e (Provider Sail Research): Das Feld `deadlines` fehlt ganz. Die Schema-Validierung hat es akzeptiert, ein Pflichtfeld wird also nicht erzwungen.
- 30c522e9: Der zweite Satz lautet nur „Die Einladung liegt als Anhang bei.“ und verbraucht den einzigen Platz für eine Folge oder Handlung (die Rückmeldung bis 16.10.).
- Vier Zusammenfassungen für reine Zugangsdaten-Mails (Teams/Skype ohne Termin) sind korrekt, haben für den Nutzer aber kaum Wert.

**Vorschläge für `summary`:**
- Den Satz zu Anhängen schärfen: „Erwähne einen Anhang nur, wenn sein Inhalt für eine Handlung nötig ist; ein Satz, der nur auf einen Anhang hinweist, ist unzulässig.“
- Bei Mails, die nur Zugangsdaten enthalten: „Enthält die Mail nur Zugangsdaten zu einer Besprechung ohne Termin, fasse in einem Satz zusammen, wer zu welcher Besprechung Zugangsdaten schickt; nenne keine Kennungen oder Passcodes.“
- **Anwendungsseitig:** `deadlines` im JSON-Schema als `required` erzwingen. Die Validierung hat die Antwort ohne das Feld durchgelassen.

### N1 – Niedrig: Relevanz-Begründungen und Token-Verbrauch

**Begründungen.**
- 6 von 74 `irrelevant`-Begründungen zählen trotz Verbot die Themen auf („kein Bezug zu Wohnung, Gemeinderat, Landfrauen, Ausländerbehörde, …“). Das Verbot greift also meistens, aber nicht immer.
- Vorschlag: Das positive Beispiel um ein negatives ergänzen.

> Unzulässige Begründung: "kein Bezug zu Wohnung, Gemeinderat, Landfrauen oder Vereinen". Zulässig: "Werbe-Newsletter eines Online-Shops."

**Token-Verbrauch.** Die Relevanzstufe macht 66 % der Prompt-Tokens aus. Die größten Treiber stehen nicht im Prompt, sondern im Mailtext:
- DHL-Benachrichtigungen mit bis zu 16.388 Zeichen bzw. 8.687 Prompt-Tokens.
- Unsichtbare Preheader-Füllzeichen („͏ ͏ ͏ …“, „&zwnj; &zwnj; …“) bei Lieferando, Zamnesia und Microsoft.
- Lange Tracking-URLs.

Empfehlung für die Vorverarbeitung:
- Unsichtbare Füllzeichen und HTML-Entities-Ketten entfernen.
- Tracking-URLs auf die Domain kürzen.
- Für die Relevanzprüfung den Text auf etwa 3.000 Zeichen begrenzen (Anfang plus Signaturblock reichen für die Einordnung).
- Häufige Massenabsender (Facebook 19, Apple 5, Zamnesia 4, DHL 4, Amazon 4, Lieferando 3) über die vorhandene Absenderliste vorab ausfiltern. Das betrifft in diesem Lauf 39 der 74 irrelevanten Mails.

Die Topic-Liste (9 Themen, 3.379 Zeichen) ist dagegen angemessen.

### N2 – Niedrig: Providerabhängige Ausreißer

- **Sail Research:** lässt in der Zusammenfassung das Pflichtfeld `deadlines` weg; gibt bei Relevanz und Terminextraktion die Felder in anderer Reihenfolge aus (unkritisch).
- **OpenInference:** braucht für die erste Revision 13,9 s und liefert den einzigen Schemafehler; bei Relevanz, Zusammenfassung und Router stehen führende Leerzeichen vor dem JSON (unkritisch).
- **Empfehlung:** Ergebnisse des Qualitätskorpus künftig je Provider auswerten. Falls ein Provider wiederholt Pflichtfelder auslässt, über die OpenRouter-Providerreihenfolge ausschließen. Eine belastbare Rangfolge erlaubt dieser Lauf nicht.

## Konsolidierte Prompt-Änderungen je Stufe

| Stufe | Änderung | Befund |
|---|---|---|
| relevance | Spam-/Phishing-Regel + Beispiel; Negativbeispiel für Begründungen | K2, N1 |
| summary | „du“-Perspektive mit `recipient_context`; Cc-Kennzeichnung; Phishing-Warnung; kein Satz nur über Anhänge; Zugangsdaten-Mails | K2, H1, M3 |
| action_router | Identitätsbaustein; Bitten an Dritte nicht zählen; Floskeln; keine Folgeaufgabe bei Terminänderung; unverbindliche Abstimmung; eigene Kalendererinnerungen; Phishing-Links | K2, H1, H2, H4, M2 |
| task_extraction | wie Router; `due_text` nur echte Frist; Titel als Handlung; `evidence` wörtlich | K2, H1, H3, H4 |
| event_extraction | Zeitzonenbezeichnung ≠ Offset; Regel zu zitierten Teilen; neue Werte bei `change`; `recurring` nur mit Wiederholungsregel; Alternativen ohne Festlegung; `evidence` wörtlich; Identitätsbaustein statt „Mail ist an die nutzende Person gerichtet“ | K1, H1, H3, M2 |
| mail_question_resolution | einheitliche lokale Formate ohne Offset; Zuständigkeitsfrage mit `recipient_context`; „keine Sachfrage“ | K3, M1 |
| proposal_revision | `utc_offset_for_date` als vertrauenswürdige Quelle; `all_day` nur bei ausdrücklichem Ganztag; Konvention für `end` bei Ganztagsterminen | K3 |

Die Sicherheitsregeln (nicht vertrauenswürdige Mailinhalte), die geschlossenen Enums, die Regel zu Zugangsdatenblöcken und die Regel zu zitierten Fristen in Router und Aufgabenextraktion haben sich bewährt und sollten unverändert bleiben.

**Redaktioneller Hinweis zu `task_extraction`:** Der Absatz ab „Erfinde oder entferne keine Aufgabe, um den Zähler zu erfüllen. Erfinde oder entferne dennoch keine Kandidaten, sondern prüfe bei einer Korrektur …“ wiederholt sich direkt hintereinander und ist durch einen Zeilenumbruch mitten im Satz zerteilt. Dasselbe gilt in `event_extraction`. Beide Stellen zu einem Satz zusammenfassen.

## Voraussetzungen in der Anwendung (keine Promptänderung)

1. **Offset-Plausibilisierung** für extrahierte Offsets gegen `user_timezone` am Termindatum (K1).
2. **Deterministische Übernahme** von Datums- und Uhrzeitantworten mit `zoneinfo`; `utc_offset_for_date` an die Revision übergeben (K3).
3. **`recipient_context`** aus einem neuen Konfigurationsblock `user_profile`; `to`/`cc` und `user_addressed_as` in den Payload aufnehmen (H1). Bei Verhaltensänderung Spezifikation und `config.example.yaml` aktualisieren.
4. **Absenderregeln:** keine Aktionsvorschläge für eigene Kalendererinnerungen (Produktentscheidung, H2); Kurzlink- und Phishing-Vorprüfung (K2).
5. **Vergangene Termine** nicht mehr zur Bestätigung vorlegen (H2).
6. **Prüffragen konkretisieren** und nur Sachfragen an `mail_question_resolution` senden (M1).
7. **Schema:** `deadlines` als Pflichtfeld erzwingen (M3).
8. **Vorverarbeitung:** unsichtbare Füllzeichen entfernen, Tracking-URLs kürzen, Relevanztext begrenzen (N1).

## Empfohlene Regressionstests (synthetische Daten)

| Nr. | Stufe | Eingabe (synthetisch) | Erwartung |
|---|---|---|---|
| 1 | event_extraction | „Erinnerung: Team-Treffen am Mi, 07.10.2026, 16:00 Uhr - 16:45 Uhr (UTC+01:00)“ | `timezone_offset_text: null`; Anwendung ergibt 16:00 MESZ |
| 2 | event_extraction | Webex-Block „07:30 \| (UTC+02:00) Amsterdam, Berlin …“ im Oktober | Uhrzeit 07:30 lokal; kein abweichender Zeitpunkt |
| 3 | Anwendung | extrahierter Offset `UTC+01:00` für ein Datum mit Sommerzeit | Offset verworfen, lokale Zeit verwendet |
| 4 | relevance | unbekannte Domain, generische Anrede, Kurzlink, „teste es“ | `irrelevant`, keine Themen |
| 5 | action_router/task_extraction | gleiche Phishing-Mail | `none` bzw. `tasks: []` |
| 6 | mail_question_resolution | „Wann beginnt der Termin?“, Mail „morgen (07.10.2026) um 13.00 Uhr“ | `"2026-10-07 13:00"` ohne Offset |
| 7 | Anwendung | Antwort „2026-10-07 13:00“ auf Startfrage | `start = 2026-10-07T13:00:00+02:00` deterministisch, kein LLM-Aufruf |
| 8 | proposal_revision | Datumsantwort, `all_day=false`, keine Uhrzeit | `all_day` bleibt false |
| 9 | action_router | „Hallo Daniela, könnte ich 50 Karten mitnehmen?“, Nutzer in Cc | `task_count: 0` |
| 10 | action_router | „Herr Stefan Hartmann ist ab 11 Uhr vor Ort in Halle 8“ mit passendem `recipient_context` | ein Event-Kandidat |
| 11 | summary | Mail an den Nutzer mit seinem Namen in der dritten Person | Zusammenfassung mit „du“, kein Eigenname |
| 12 | action_router/task_extraction | „Wir hoffen, dass Sie die Verschiebung einrichten können.“ | keine Aufgabe |
| 13 | event_extraction | Verschiebung „in den Nachmittag“, alte Zeit 11:45–12:30 im Zitat | `classification:"change"`, `time_text: null` |
| 14 | event_extraction | zitierter Absatz „Mitgliederversammlung am 17.10.“, aktueller Teil ohne Bezug | kein Event |
| 15 | event_extraction | „Erinnerung: Jour Fixe … am Mo, 05.10.2026, 20:00 Uhr“ | nicht `recurring` (bzw. kein Kandidat bei Absenderregel) |
| 16 | action_router | „Gerne morgen oder übermorgen, ab 11 Uhr oder nachmittags“ | kein Event |
| 17 | action_router | „Geht bei euch Skype? Dann schicke ich einen Link.“ | eine Aufgabe „Antwort mitteilen“, kein Event |
| 18 | alle Extraktionen | `evidence` aus Mail mit mehreren Belegstellen | `evidence` ist wörtlicher Teilstring des Mailtexts |
| 19 | relevance | Werbe-Newsletter | Begründung nennt keine Themenliste |

## Priorisierte Umsetzung

1. **K1 Zeitverschiebung:** Prompt plus Offset-Plausibilisierung in der Anwendung. Ohne diesen Schritt landen Termine aus Erinnerungen und Kalendersystemen falsch im Kalender.
2. **K2 Phishing:** Relevanz- und Aufgabenregel plus Vorprüfung. Mailhelp darf keine Aufgabe „Link öffnen“ zur Bestätigung anbieten.
3. **K3 Zeitrevision:** deterministische Übernahme von Datum und Uhrzeit, einheitliches Format in der Rückfrageauflösung.
4. **H1 Nutzeridentität:** `user_profile`, `to`/`cc` und gemeinsamer Promptbaustein. Das behebt mehrere Router-, Extraktions- und Zusammenfassungsfehler zugleich.
5. **H2 Kalendererinnerungen und vergangene Termine:** Produktentscheidung, dann Absenderregel.
6. **H3/H4/M2 Kandidatengrenzen:** Thread-, Änderungs-, Floskel- und Abstimmungsregeln in Router und Extraktion angleichen.
7. **M1, M3, N1, N2:** Prüffragen, Schema, Vorverarbeitung, providerweise Auswertung.

Nach jeder Stufe den Qualitätskorpus (`tests/fixtures/mail_corpus_v2`) um die passenden Regressionsfälle ergänzen und mit dem produktiven Provider-Fallback mehrfach ausführen. Erfolg ist nicht am Schema-Anteil zu messen, sondern an den Erwartungen der Tabelle oben.
