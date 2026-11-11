# Mailhelp 5.7 – Lernen an einem Ort, übersichtliche Themenverwaltung

**Zielversion:** 5.7.0–5.7.5, eine Patch-Version je Arbeitspaket (S1–S6)

**Stand:** 11. November 2026

**Status:** S1–S3 umgesetzt und gezielt abgenommen; S4–S6 folgen.

**Ausgangsstand:** 5.6.0 ([Planung 5.6](Planung-5.6.md), [Release 5.6](Release-5.6.md)).
Version 5.7 beginnt erst, wenn 5.6.0 vollständig abgenommen und committet ist.

**Grundlage:** [Entwicklungsregeln](../AGENTS.md), [Projektspezifikation](../Mailhelp-Projektspezifikation.md)

---

## 1. Ausgangslage

### 1.1 Lernfunktionen an zwei Stellen

Mailhelp hat zwei Lernfunktionen. Beide verbessern dieselben Themenregeln, liegen aber an
verschiedenen Stellen:

| Funktion | Seit | Erreichbar über | Aktiver Menüpunkt |
| --- | --- | --- | --- |
| Lernlauf aus dem Postfach | 5.4 | Hauptmenü **Lernen** (`/lernen`) | Lernen |
| Regeln aus Entscheidungen lernen | 5.6 | Einstellungen → Kachel Themen → kleiner Textlink (`/themen/lernen`) | Einstellungen |

Wer etwas lernen lassen will, sucht zuerst unter **Lernen** und findet dort die neue
5.6-Funktion nicht. Sie ist drei Klicks tief versteckt, als schlichter Textlink über einer
langen Formularliste. Beide Seiten sehen außerdem verschieden aus: Die Lernlauf-Seite
hat keine Seitenüberschrift im Stil der Einstellungen, die Regellernen-Seite hat keine
Einleitung, die erklärt, wann sich eine Analyse lohnt.

### 1.2 Die Themenseite ist ein Formularstapel

`topics_page` in [settings_pages.py](../src/mailhelp/web/settings_pages.py) zeigt für jedes
Thema ein eigenes vollständiges Bearbeitungsformular. Darunter folgt je Datei ein leeres
Formular für neue Themen. Beim heutigen Bestand (15 relevante Themen, 33 Ausschlussthemen)
sind das 50 Formulare untereinander auf einer Seite. Im Einzelnen:

- Die Feldbeschriftungen sind die YAML-Schlüssel (`id`, `enabled`, `examples`,
  `exclusions`), keine deutschen Bezeichnungen.
- Listen stehen als `a; b; c` in einem einzeiligen Feld. Ein Beispiel, das selbst ein
  Semikolon enthält, wird beim Speichern zerlegt. Die Regellernen-Seite verwendet dagegen
  „ein Eintrag je Zeile“; die beiden Seiten sind also uneinheitlich.
- `enabled` ist ein freies Textfeld mit `true`/`false` statt eines Schalters.
- Es gibt keine Übersicht: kein Status auf einen Blick, keine Suche, kein Filter, keine
  Anzahl. Der Unterschied zwischen „relevant“ und „Ausschluss“ wird nur über den Dateinamen
  (`topics.yaml`, `irrelevant_topics.yaml`) angedeutet.
- Jedes Formular hat eine eigene Bestätigungs-Checkbox. Was sich ändert, sieht man vor
  dem Speichern nicht.
- Ein optionaler Postfachbereich (`mailboxes`, seit 3.2) wird wie jedes andere Feld
  generisch dargestellt. Ob er beim Speichern erhalten bleibt, ist zu prüfen
  (`save_topic` übernimmt nur id, name, description, enabled, examples, exclusions).

## 2. Ziele

1. **Ein Ort für alles Lernen.** Der Menüpunkt **Lernen** wird zur Übersicht über beide
   Lernfunktionen. Beide Unterseiten tragen das aktive Menü „Lernen“.
2. **Themen auf einen Blick.** Die Themenseite wird eine kompakte, durchsuchbare Liste.
   Bearbeitet wird auf einer eigenen Seite je Thema.
3. **Verständliche Bearbeitung.** Deutsche Beschriftungen mit Erklärung, ein Eintrag je
   Zeile, ein Schalter für „aktiv“, eine Vorschau „vorher/nachher“ vor dem Speichern.
4. **Ein Gestaltungsmuster.** Themenbearbeitung, Lernlauf-Ergebnis und Regellernen
   verwenden dieselben Bausteine (Seitenkopf, Karten, Alt-Neu-Vergleich, Statusabzeichen).
5. **Keine Abstriche bei der Sicherheit.** Sitzung, CSRF, Versionsprüfung,
   Idempotenzschlüssel und ausdrückliche Bestätigung bleiben für jeden Schreibzugriff
   unverändert. Alles funktioniert weiterhin ohne JavaScript, auf dem Desktop und mobil.

**Nicht Ziel von 5.7:** neue Lernlogik, andere Prompts oder Modelle, Löschen von Themen
(es bleibt bei „deaktivieren statt löschen“), Änderungen an Telegram.

## 3. Arbeitspakete

### S1 (5.7.0) – Lernen als gemeinsamer Bereich

**Neue Seitenstruktur:**

| Adresse | Inhalt |
| --- | --- |
| `/lernen` | Übersicht mit zwei Karten: „Aus dem Postfach lernen“ und „Aus Entscheidungen lernen“ |
| `/lernen/postfach` | der bisherige Lernlauf (bisher direkt unter `/lernen`) |
| `/lernen/entscheidungen` | das Regellernen (bisher `/themen/lernen`) |

- **Jede Karte zeigt:**
  - einen Satz, wofür die Funktion da ist und wann sie sich lohnt;
  - den aktuellen Stand (z. B. „Lernlauf läuft: 12 von 20 Mails“, „Prüfentwurf mit
    3 Vorschlägen wartet“, „Übernahme unvollständig – Abschluss nötig“);
  - eine Kennzahl: für Entscheidungen die Anzahl verwertbarer Entscheidungen seit der
    letzten Analyse, für den Lernlauf das Datum des letzten Laufs;
  - den Hinweis „kostenpflichtig“ im selben eingeklappten Stil wie der Hilfschat
    (`help-cost-hint`);
  - einen deutlichen Startknopf. Dieser startet nichts, er öffnet nur die Unterseite;
    die Freigaben bleiben dort.
- Fehlt der Promptblock `decision_rule_learning`, sagt die Karte das schon in der
  Übersicht und nennt den Weg zur Behebung, statt erst nach dem Start zu scheitern.
- Beide Unterseiten bekommen den Seitenkopf der Einstellungen (Eyebrow „Lernen“,
  Überschrift, Einleitung) und einen Rückweg „Zur Lernübersicht“.
- **Alte Adressen:**
  - `GET /themen/lernen` leitet dauerhaft auf `/lernen/entscheidungen` um.
  - Formulare, die noch auf `POST /themen/lernen` oder `POST /lernen` zeigen (offene Tabs
    während des Updates), werden nicht stillschweigend ausgeführt. Sie zeigen die neue
    Seite mit dem Hinweis „Seite wurde aktualisiert, bitte erneut bestätigen“. Die
    Versionsprüfung verhindert ohnehin eine doppelte Ausführung.
  - `/api/lernen` bleibt als Zustandsadresse erhalten.
- Auf der Themenseite ersetzt eine kleine Hinweiskarte den heutigen Textlink: „Regeln aus
  Ihren Entscheidungen verbessern → Lernen“. Damit bleibt der Weg auch von dort erhalten.
- Der Hilfschat-Knopf erscheint auf allen Lernseiten (`shows_help_button`).
- Einstellungssuche und Hilfe kennen die neuen Adressen (z. B. „Regeln lernen“ findet
  `/lernen/entscheidungen`).

**Abnahme:**
- Hauptmenü → Lernen → beide Funktionen sind mit einem Klick erreichbar.
- Die alte URL leitet um; ein alter POST führt nichts aus.
- Das aktive Menü ist auf allen drei Seiten „Lernen“.

### S2 (5.7.1) – Themenübersicht statt Formularstapel

`/themen` zeigt keine Formulare mehr, sondern eine Liste:

- **Zwei Reiter:**
  - „Relevante Themen (15)“ mit dem Satz „Mails zu diesen Themen werden ausgewertet.“
  - „Ausschlussthemen (33)“ mit dem Satz „Mails zu diesen Themen werden übersprungen.“

  Ohne JavaScript sind die Reiter normale Links (`?art=relevant` / `?art=ausschluss`).
- **Eine Zeile je Thema:**
  - Name, darunter die ID klein;
  - Abzeichen „aktiv“ oder „deaktiviert“;
  - Geltungsbereich („alle Postfächer“ oder die Postfachnamen);
  - Anzahl Beispiele und Ausschlüsse;
  - der erste Satz der Beschreibung;
  - der Link „Bearbeiten“.

  Auf dem Desktop ist das eine Tabelle, mobil eine Kartenliste.
- **Suche und Filter:** ein Suchfeld über Name, ID, Beschreibung und Beispiele sowie die
  Filter „alle / aktiv / deaktiviert“. Beides arbeitet serverseitig per GET (ohne
  JavaScript); mit JavaScript filtert die Liste sofort, wie die Einstellungssuche.
- **Knopf „Neues Thema“** je Reiter statt der leeren Formulare.
- Deaktivierte Themen stehen am Ende und sind abgeblendet.
- Ausstehende, noch nicht bestätigte Themenänderungen werden wie bei den Einstellungen als
  Abzeichen „Änderung ausstehend“ gezeigt.

**Abnahme:** Bei 48 Themen passt die Übersicht ohne Formularfelder auf wenige Bildschirmhöhen.
Die Suche „Rechnung“ findet ein Thema über ein Beispiel. Ohne JavaScript funktionieren
Reiter, Suche und Filter.

### S3 (5.7.2) – Bearbeitungsseite je Thema mit Vorschau

Neue Seiten `/themen/<art>/<id>` (bearbeiten) und `/themen/<art>/neu`:

- **Deutsche Beschriftungen mit Kurzhilfe:**

  | Feld | Kurzhilfe |
  | --- | --- |
  | Name | – |
  | Beschreibung | „Woran erkennt man das Thema?“ |
  | Beispiele | „Ein typischer Betreff oder Satz je Zeile“ |
  | Ausschlüsse | „Was trotz Ähnlichkeit nicht dazugehört, je Zeile“ |
  | Aktiv | Schalter (Checkbox), kein Textfeld |

- **ID:**
  - Bei bestehenden Themen ist die ID nur Anzeige.
  - Bei neuen Themen wird sie aus dem Namen vorgeschlagen (`[a-z0-9_-]+`, höchstens
    64 Zeichen) und darf vor dem ersten Speichern noch geändert werden.
- **Geltungsbereich:** Der Postfachbereich wird angezeigt und beim Speichern unverändert
  übernommen. Hier wird zuerst ein Test geschrieben, der prüft, ob er heute verloren geht;
  falls ja, gilt es als Bugfix mit Regressionstest.
- **Listen:** Ein Eintrag je Zeile, wie im Regellernen. Ein Beispiel mit Semikolon bleibt
  ein Eintrag; das wird als Regressionstest zum heutigen `;`-Trenner festgehalten.
- **Ablauf in zwei Schritten (wie bei den Einstellungen):**
  1. „Änderung prüfen“ zeigt eine Vorschau vorher/nachher mit markierten Feldern.
  2. Erst dort folgen die Checkbox „Änderung ausdrücklich speichern“ und der Speicherknopf.

  Ohne Änderung gibt es nichts zu bestätigen.
- **Fehler:** Validierungsfehler stehen am betroffenen Feld; die Eingaben bleiben erhalten.
  Ist die Datei inzwischen geändert worden, erscheint ein Konflikthinweis mit dem Link „Neu
  laden“, wie bisher.
- **Schreibzugriff:** Sitzung, CSRF, `expected_hash`, Idempotenzschlüssel und
  Bestätigung bleiben der bestehende `AdminCommand`-Weg; es entsteht kein neuer
  Schreibzugriff.
- Ein **Erweitert**-Bereich zeigt das Thema als YAML, nur zum Lesen (zum Kopieren).

**Abnahme:** Bearbeiten, Vorschau, Bestätigen, Konflikt und Validierungsfehler auf Desktop,
mobil und ohne JavaScript. Postfachbereiche und Semikolons bleiben erhalten.

### S4 (5.7.3) – Einheitliches Aussehen der Lernseiten

- **Gemeinsame Bausteine** in [app.css](../src/mailhelp/web/static/app.css): Seitenkopf,
  Statuskarte, Alt-Neu-Vergleich (`rule-diff`, bisher nur im Regellernen) und
  Abzeichen „neu“, „geändert“, „unverändert“. Themenvorschau (S3), Lernlauf-Ergebnis und
  Regellernen verwenden sie gemeinsam.
- **Regellernen, Prüfansicht:**
  - Oben steht eine Zusammenfassung („3 Vorschläge: 2 Änderungen, 1 neues Thema · aus
    87 Entscheidungen“) mit Sprunglinks zu den Vorschlägen.
  - Jeder Vorschlag ist eine einklappbare Karte; die Auswahl-Checkbox steht im Kopf der
    Karte, nicht mitten im Formular.
  - Im Vergleich sind nur geänderte Felder offen. Unveränderte Felder stehen eingeklappt
    unter „Unveränderte Felder anzeigen“.
  - Geänderte Beispiele und Ausschlüsse werden zeilenweise markiert (hinzugefügt /
    entfernt) statt als ganzer Block.
  - Belege werden als kurze Liste gezeigt (Betreff, Entscheidung, Datum); der Auszug
    lässt sich aufklappen.
  - Unten steht eine feste Aktionsleiste: „n Vorschläge ausgewählt“, die Bestätigung
    und der Übernahmeknopf.
- **Lernlauf:** Das Startformular wird in Schritte gegliedert (Postfach und Ordner →
  Umfang → Kosten und Budget → Schätzung). Die Ordnerliste wird zu Auswahlfeldern,
  wo der Ordnerkatalog vorhanden ist.
- **Barrierefreiheit:**
  - Überschriftenfolge ohne Sprünge;
  - Abzeichen nicht nur über Farbe, sondern auch als Text;
  - Fokusreihenfolge prüfen;
  - Kontrast in hellem und dunklem Design.

**Abnahme:** Sichtprüfung als Bildschirmfotos vorher/nachher (Desktop, mobil, schmal, hell
und dunkel). Die Fotos werden im Releasebericht verlinkt.

### S5 (5.7.4) – Dokumentation, Hilfe und Suche

- Anpassen:
  - [Bedienung](Bedienung.md): Abschnitte „Lernmodus“ und „Aus Entscheidungen lernen“
    unter einem gemeinsamen Kapitel „Lernen“ mit den neuen Wegen;
  - [Web-Einstellungen](Web-Einstellungen.md): Themenverwaltung;
  - Projektspezifikation, README, CHANGELOG.
- Den Hilfebestand neu erzeugen (`python -m devtools.help_index`). Synonyme der
  Einstellungssuche ergänzen („Regeln lernen“, „Themen verbessern“, „Themenregeln“).
- Den Hilfschat mit dem bestehenden Prüfskript gegen die Fragen „Wo finde ich das
  Regellernen?“ und „Wie bearbeite ich ein Thema?“ prüfen. Das geschieht nur mit
  ausdrücklicher Freigabe für einen kostenpflichtigen Lauf.

### S6 (5.7.5) – Abnahme und Release

- `python -m devtools.check full --workers 8`, Lasttests, die Browser-Suite seriell
  (`python -m pytest ui_tests --no-cov -q`), Ruff, Mypy, Prompt-Gate,
  `devtools.inventory --check` und `devtools.help_index --check`.
- 100 % Zeilen- und Branch-Abdeckung für Python und für die JS-Abdeckung der Browsertests.
- Releasebericht [Release-5.7.md](Release-5.7.md) mit Bildschirmfotos und Prüfergebnissen.

## 4. Tests (je Arbeitspaket, nicht erst am Ende)

| Bereich | Pflichtfälle |
| --- | --- |
| Navigation | Lernübersicht zeigt beide Karten und Stände; aktives Menü; alte URL leitet um; alter POST führt nichts aus; Hilfeknopf |
| Autorisierung | Jede neue Seite ohne Sitzung → Anmeldung; abgelaufene Sitzung bei Vorschau und beim Speichern; fremde Sitzung sieht keine Regellern-Belege |
| Schreiben | CSRF fehlt/falsch, alte Version, Idempotenzschlüssel doppelt, Bestätigung fehlt, Datei extern geändert, Schreibfehler |
| Themen | Suche, Filter, Reiter, neues Thema mit ID-Vorschlag, ID nicht änderbar, Postfachbereich bleibt, Semikolon im Beispiel bleibt (Regression), letzte aktive relevante Regel nicht deaktivierbar |
| Neustart | Ausstehende Themenänderung und unvollständige Regelübernahme nach Neustart korrekt in der Übersicht |
| Browser | Desktop/mobil/schmal, ohne JavaScript, Tastaturbedienung, dunkles Design |

Alle Tests verwenden synthetische Themen und Entscheidungen und simulierte Anbieter.

## 5. Offene Entscheidungen

Für jede Frage ist die empfohlene Lösung genannt. Ohne Rückmeldung wird sie umgesetzt.

1. **Adressen.** Empfehlung: `/lernen` als Übersicht, `/lernen/postfach`,
   `/lernen/entscheidungen`. Alternative: Lernlauf bleibt direkt auf `/lernen`, das
   Regellernen kommt als Reiter dazu (weniger Umbau, aber keine Übersicht).
2. **Themen auch unter Lernen?** Empfehlung: nein. Themen bleiben unter Einstellungen
   (dort wird verwaltet), Lernen schlägt Änderungen nur vor. Beide Seiten verweisen
   gegenseitig aufeinander.
3. **Postfachbereich in der Themenbearbeitung ändern?** Empfehlung: in 5.7 nur anzeigen und
   erhalten, Bearbeiten erst in einer späteren Version (eigene Prüfung gegen konfigurierte
   Postfächer).
4. **Eine Version je Paket oder eine gemeinsame 5.7.0?** Empfehlung: je Paket eine
   Patch-Version wie bei 5.5, damit jede Stufe einzeln abgenommen werden kann.
