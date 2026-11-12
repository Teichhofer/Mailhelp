# Alltagsbedienung

Stand: Mailhelp 5.3. Was im Alltag zu tun ist: Vorschläge prüfen und entscheiden, Mails
nachlesen, Rückfragen beantworten und den Stand von Eintragungen verfolgen.

## Offene Entscheidungen

**Offen** zeigt alle Vorschläge, die eine Entscheidung brauchen. Jede Karte nennt Art (Aufgabe
oder Termin), Titel, Zeiten, Ziel und den Beleg aus der Mail. Auf großen Bildschirmen steht die
Liste links und der gewählte Vorschlag rechts; die Taste `A` legt den gewählten Vorschlag an.

| Schaltfläche | Wirkung |
| --- | --- |
| **Als Aufgabe anlegen** / **Im Kalender anlegen** | legt genau diese Version an; 5 Sekunden lang rückgängig zu machen |
| **Verwerfen** | keine Anlage |
| **Schon erledigt** | als erledigt vermerken, keine Anlage |
| **Antwort senden** | beantwortet eine Rückfrage oder ändert Angaben („Titel: …“, „Ort: …“) |
| **Bearbeitung beenden** | verwirft eine angefangene Änderung |
| **Dublettenprüfung wiederholen** | nach einer fehlgeschlagenen Prüfung auf vorhandene Einträge |
| **Erneut anlegen** | nur nach Rückfrage, wenn derselbe Eintrag schon früher angelegt wurde |

Bei Änderungen oder Absagen eines vorhandenen Termins heißt die Schaltfläche **Bestehenden
Termin aktualisieren** bzw. **Termin absagen**. Passt eine Änderung zu mehreren Terminen, wählst
du mit „Diesen Termin meinen: …“ den richtigen. Hält Mailhelp zwei Vorschläge für dieselbe
Sache, entscheidest du im **Vorschlagsabgleich**.

## Nach dem Anlegen

Mailhelp ruft jeden geschriebenen Eintrag frisch beim Anbieter ab:

| Anzeige | Bedeutung |
| --- | --- |
| Gespeichert – Eintrag wird geprüft | geschrieben, Kontrollabruf läuft |
| Angelegt und geprüft | der Anbieter zeigt den Eintrag mit den bestätigten Angaben |
| Eintragung noch nicht bestätigt | nicht auffindbar oder Abruf nicht möglich; der Grund steht dabei |
| Eintrag vorhanden, Angaben weichen ab | Tabelle „Bestätigt / Beim Anbieter“ |
| Kalenderdatei bereitgestellt – Übernahme in den Kalender nicht prüfbar | per Telegram gesendete Datei |

**Erneut prüfen** liest nur noch einmal; Mailhelp ändert, repariert oder wiederholt nie eine
Anlage.

## Mails nachlesen

**Mails** listet alle verarbeiteten Mails. Die Mailseite zeigt „So wurde diese Mail
verarbeitet“ mit jedem Schritt und seinem Ergebnis. Hat Mailhelp etwas übersehen, startet
**Aufgabe oder Termin übersehen?** eine gezielte Nachanalyse (**Erneut analysieren**, begrenzt
durch ein Tageslimit). Neue Befunde übernimmst du mit **Ergebnis übernehmen** als unbestätigte
Vorschläge; **Nachanalyse abbrechen** beendet eine laufende.

## Lernmodus (Lernfunktion)

Der Lernmodus hilft, Themen und Filter einzurichten: Mailhelp liest eine Auswahl vorhandener
Mails, ordnet sie frei ein und schlägt daraus Themen, Ausschlussthemen, zu ignorierende Absender
und zusätzliche Abrufordner vor. Er liest nur: Das Postfach wird nicht verändert, und es entstehen
keine Termine oder Aufgaben. Übernommen wird erst, was du ausdrücklich bestätigst.

Alle Lernfunktionen liegen unter **Lernen** (`/lernen`). Die Lernübersicht zeigt zwei Karten mit
Zweck, aktuellem Stand und einem Kostenhinweis: **Aus dem Postfach lernen** (der Lernlauf unten)
und **Aus Entscheidungen lernen** (Regeln aus deinen bisherigen Entscheidungen verbessern, siehe
[Aus Entscheidungen lernen](#aus-entscheidungen-lernen)). Das Öffnen der Übersicht oder einer
Karte startet nichts und kostet nichts. Die Themen selbst werden unter Einstellungen → Themen
verwaltet.

### Lernlauf in der Weboberfläche starten

1. In der Navigation unter **Verwaltung** die Seite **Lernen** öffnen (`/lernen`) und
   „Aus dem Postfach lernen öffnen“ wählen (`/lernen/postfach`). Die Übersicht startet nichts.
2. Unter **Neuer Lernlauf** im Schritt „1. Postfach und Ordner“ das **Postfach** wählen und die
   **Ordner laden** wählen. Die gespeicherten Ordner dieses Postfachs ankreuzen; weitere
   Ordner sind unter **Weitere Ordner (ein Name je Zeile)** möglich. Das Laden startet
   keinen Mailabruf und funktioniert ohne JavaScript. Im Schritt „2. Umfang“ die
   **Anzahl Mails** (1–1000, vorbelegt 20) angeben.
3. Im Schritt „3. Kosten und Budget“ **Preisobergrenze USD je Million Tokens** und **Budget USD** angeben. Die Preisobergrenze ist
   deine Annahme; aktuelle Modellpreise einschließlich Ausgabe und Reasoning selbst prüfen.
4. **Schätzung anzeigen** wählen. Mailhelp nennt die typische Schätzung und den ungünstigsten
   Fall in Tokens und USD. Reicht das Budget nicht, steht dort der nötige Mindestbetrag.
   Postfach, Ordner, Anzahl, Preis und Budget bleiben im Formular erhalten. Die aufgeführten
   Modelle stammen aus der Konfiguration; die Preisobergrenze bleibt deine manuelle Annahme.
5. **Lesenden Lernlauf kostenpflichtig starten** wählen. Für 20 Mails reicht je nach Modell
   typischerweise ein Budget von etwa 1 USD.

Während des Laufs zeigt die Seite „Läuft: … Mails geprüft, … Fehler“. Mit **Pausieren**,
**Fortsetzen** und **Abbrechen** steuerst du ihn. Das Budget wird vor jedem KI-Aufruf geprüft;
der Lauf hält an, bevor es überschritten würde. Wurde die Konfiguration seit dem Start geändert,
lässt sich der Lauf nicht fortsetzen; ein neuer Lernlauf ersetzt ihn.

### Ergebnis prüfen und übernehmen

Nach dem Lauf zeigt **Themen, Ausschlüsse und Belege** je Vorschlag Titel, Beschreibung, die
Belege aus den Mails und die Absender:

- **Übernahme:** **Nicht übernehmen**, **Thema** (relevant, `topics.yaml`) oder **Ausschlussthema**
  (irrelevant, `irrelevant_topics.yaml`).
- **Für alle Postfächer** übernimmt das Thema global statt nur für das gewählte Postfach.
- **Absender bei Ausschlussthema ignorieren** setzt bei einem Ausschlussthema die Absender
  zusätzlich auf die Liste der ignorierten Absender (`irrelevant-senders.json`).
- **Auswahl als Entwurf speichern** merkt die Entscheidung je Vorschlag.

Unter **Zusätzliche Abrufordner** wählst du Ordner aus, die künftig mit abgerufen werden
(**Ordnerauswahl speichern**). Erst **Ausgewählte Themen, Filter und Ordner ausdrücklich
übernehmen** schreibt alles gemeinsam in die Konfiguration; **Verwerfen** verwirft das Ergebnis.
Danach **Konfiguration neu laden** wählen, damit der Mailabruf die neuen Themen verwendet.

### Lernmodus im Terminal und Einstellungen

Alternativ läuft der Lernmodus interaktiv im Terminal. Dieser Befehl liest 20 Mails und fragt
die Themen nacheinander ab:

```sh
mailhelp --learn 20 --mailbox 1 --config-directory .
```

Bei mehreren
Postfächern ist `--mailbox NUMMER` oder `--mailbox alle` nötig. In Docker ist dafür
`compose.learn.yaml` mit schreibbarer Konfiguration vorgesehen.

Unter **Einstellungen → KI und Auswertung** stehen dazu `learning.parallel_llm_calls`
(gleichzeitige KI-Aufrufe im Lernmodus, Standard 4) und `learning.decision_llm_content`.

### Lernbestand

Unabhängig vom Lernmodus legt Mailhelp jede manuelle Entscheidung über einen Vorschlag mit Mail,
KI-Ergebnissen, ursprünglichem und entschiedenem Vorschlag im Lernbestand ab
(`data/<Betriebsart>/learning/decisions.jsonl`). Er ist das Material für
[Aus Entscheidungen lernen](#aus-entscheidungen-lernen); Mailhelp ändert dadurch nicht
selbständig seine Themen oder Entscheidungen, sondern nur nach deiner Freigabe und Bestätigung. Vollständige
KI-Anfragen und -Antworten kommen nur mit `learning.decision_llm_content` hinzu. Die
Aufbewahrung regelt `retention.decision_learning_days` (Standard unbegrenzt).

### Aus Entscheidungen lernen

Das Regellernen findest du unter Lernen: „Aus Entscheidungen lernen öffnen“ wählen
(`/lernen/entscheidungen`). Auch
die Themenverwaltung (Einstellungen → Themen) verlinkt diese Seite. Diese Funktion verwendet die
bereits protokollierten Entscheidungen; sie ruft keine Mails ab. Die Funktion benötigt den
Promptblock `decision_rule_learning` in `prompts.yaml`. Bei älteren Installationen den Block
aus dem mitgelieferten Beispiel übernehmen und die Promptkonfiguration wie üblich neu laden.

1. Unter „Welche Entscheidungen?“ wählen: **Nur neue Entscheidungen seit der letzten Analyse**
   (Standard, höchstens 100) oder **Alle bisherigen verwertbaren Entscheidungen** (höchstens 500,
   mehr Belege und höhere Kosten). Hinter jeder Option steht die aktuelle Anzahl. Gibt es keine
   neuen, „Alle bisherigen“ wählen. Den Hinweis zur Datenübertragung und möglichen Kosten lesen. Nur nach Ankreuzen der
   ausdrücklichen Freigabe „Entscheidungen analysieren“ wählen. Begrenzte Auszüge und
   Korrekturen werden an den aktiven KI-Anbieter übertragen. Ohne Freigabe erfolgt kein Aufruf.
2. Nach Abschluss oben die Zusammenfassung lesen; die Links springen zu den einzelnen
   Vorschlägen. Sie nennt auch, wie viele gleichartige Ablehnungen nur als Anzahl an die KI
   gingen (ab 5.7.7). In jeder Karte zeigt „Bisherige Regel und Vorschlag“ nur die geänderten Felder;
   neue und entfernte Beispiele sind mit „+ neu“ und „− entfernt“ markiert, unveränderte Felder
   öffnet „Unveränderte Felder anzeigen“. „Entscheidungsbelege“ listet Betreff, Entscheidung und Datum; der
   Auszug öffnet sich mit „Auszug anzeigen“. Eine abgelehnte Aufgabe macht
   ihre Mail nicht automatisch irrelevant; „bereits erledigt“ bleibt ein positives Beispiel.
3. Name, Beschreibung, Beispiele, Ausschlüsse und Aktivierung bei Bedarf ändern. Beispiele
   und Ausschlüsse stehen einzeln je Zeile. Vorhandene Themen-IDs und Postfachbereiche bleiben
   stabil. Optional unter „Vollständiges Themen-YAML bearbeiten (optional)“ ein vollständiges
   Thema eintragen; dieses ersetzt dann die Feldwerte.
4. Gewünschte Vorschläge oben in der jeweiligen Karte auswählen; die Leiste am unteren Rand
   zeigt, wie viele ausgewählt sind. **Ausgewählte Änderungen prüfen** wählen. Der gesonderte
   Vergleich **Bearbeitete Änderungen prüfen** zeigt genau deine Feld- oder YAML-Änderungen.
   Erst dort **Ausgewählte Regeländerungen ausdrücklich bestätigen** ankreuzen und
   **Geprüfte Änderungen übernehmen** wählen. „Weiter bearbeiten“ öffnet die Bearbeitung;
   anschließend erneut prüfen. Ein neuer Prüfstand ersetzt den vorherigen. Ohne Auswahl oder
   bei ungültigem YAML/Schema wird nichts übernommen. Die Eingaben bleiben zur Korrektur stehen. Bei extern
   geänderten Dateien den Konflikt klären und eine neue Analyse des aktuellen Standes starten.
5. Bei „Analyse fehlgeschlagen“ steht die Ursache darunter. Nach „am Ausgabelimit
   abgeschnitten“ hat Mailhelp bereits einen zweiten, verkleinerten Versuch gemacht. Später
   erneut versuchen oder „Nur neue Entscheidungen“ wählen. Im KI-Protokoll stehen dazu
   Tokenverbrauch und Länge der abgeschnittenen Antwort.
6. Bei unterbrochenem Schreiben nach Anmeldung „Übernahme abschließen“ ausdrücklich bestätigen.
   Mailhelp prüft alle Dateien erneut und vervollständigt nur die bereits freigegebene lokale
   Änderung. Es startet keinen neuen KI-Aufruf und überschreibt keine fremden Änderungen.

Neue Analysen übernehmen relevante Regeln am nächsten sicheren Verarbeitungspunkt. Die
Ausschlussthemen behalten ihre bisherige Bedeutung im Lern-/Entscheidungstestmodus; für
normale Mailanalysen wirken die relevanten Themen und deren Ausschlüsse. Bestehende
Kalendereinträge und Aufgaben werden durch Regellernen nicht geändert. Eine neue Analyse
ersetzt einen noch offenen Prüfentwurf; ein Neustart wiederholt keine laufende KI-Analyse.

## Weitere Seiten

### Hilfe beim Einstellen

Das Chatsymbol unten rechts öffnet **Hilfe zu Einstellungen** als kleines Fenster über der
aktuellen Einstellungsseite. „Dazu fragen“ übernimmt den Bezug einer Einstellung, ohne einen
vorhandenen Frageentwurf zu überschreiben. Frage eingeben und **Frage senden** wählen. Die
Antwort erscheint zuerst kurz; **Ausführliche Antwort anzeigen** zeigt alle Schritte.
Während die Antwort entsteht, kannst du suchen, Werte bearbeiten und Änderungen bestätigen
und speichern. Der Chat bleibt geöffnet; Antworten laden die Einstellungsseite nicht neu.

Quellen öffnen sich im Fenster; **Zurück zum Gespräch** kehrt an dieselbe Stelle im Verlauf
zurück. Auch nach einem Seitenwechsel, Neuladen oder erneutem Öffnen steht das Gespräch an der
zuletzt gelesenen Stelle; wer ganz unten liest, sieht neue Antworten automatisch. Den Kopf
ziehen (oder den Titel fokussieren und die Pfeiltasten verwenden), um verdeckte Einstellungen
freizugeben. Für mehr Platz am Rand oder an einer Ecke ziehen (per Tastatur Umschalt+Pfeiltasten
auf dem Titel); die Größe bleibt beim Seitenwechsel erhalten.
**Hilfschat schließen** blendet das Fenster aus. Beim Wiederöffnen sind Gespräch und Entwurf
noch vorhanden, solange die Sitzung und Aufbewahrung gelten. **Chat leeren** verwirft die Inhalte
und hält das Fenster offen. Die ungesendete Frage sichert Mailhelp beim Tippen automatisch;
ohne JavaScript erscheinen neue Antworten beim nächsten Seitenaufruf. Der Chat erklärt nur und
verändert selbst keine Daten.

### Seitenübersicht

| Seite | Inhalt |
| --- | --- |
| **Verlauf** | jede Änderung und Entscheidung mit Version |
| **Briefing** | Tagesüberblick über offene Entscheidungen und Termine |
| **Themen** | was als relevant gilt (Einstellungen → Themen): Übersicht, Suche, Bearbeitung mit Vorschau |
| **Lernen** | Lernlauf aus dem Postfach und Regeln aus Entscheidungen verbessern |
| **Status** | letzter Kontakt je Dienst, laufender Schritt; anklickbare Kennzahlen öffnen passende Übersichten |

Auf **Status** öffnet ein Klick auf eine der vier Kennzahlen die zugehörigen Einträge:
**Offene Vorschläge** und **Relevanzfragen** führen zu getrennten Übersichten mit
Details je Vorschlag beziehungsweise Mail. **Mails mit Fehler** öffnet die Mailablage
mit dem Filter „mit Fehler“. **Wartende Web-Aktionen** zeigt die Warteschlange mit
Links zu deinen einzelnen Aktionen. Andere Sitzungen werden ohne private Inhalte
aufgeführt. Auch bei null Einträgen ist die Übersicht erreichbar. „Übersicht aktualisieren“
lädt den aktuellen Stand; das Öffnen und Aktualisieren führt keine Aktion aus.

Antwortentwürfe legt Mailhelp nur im Entwurfsordner ab; es versendet nie Mails.
