# Mailhelp 6.2 – Bedienkonzept und Design vereinheitlichen

**Zielversion:** 6.2.0, Umsetzung in Patchversionen 6.2.1 bis 6.2.10

**Stand:** 13. November 2026

**Status:** In Umsetzung – E1 bis E6 mit dem jeweiligen Vorschlag übernommen (14. November 2026)

**Ausgangsstand:** 6.1.9

**Vorgänger:** [Planung 6.1](Planung-6.1.md)

**Grundlage:** [Entwicklungsregeln](../AGENTS.md), [Projektspezifikation](../Mailhelp-Projektspezifikation.md),
[Bedienung](Bedienung.md), [UI-Prüfung 5.7.5](Pruefung-UI-5.7.5.md)

---

## 0. Bestandsaufnahme

Geprüft wurden die Screenshots der Browser-Suite vom 13. November 2026 (`.test-tmp/ui-screens`,
synthetische Daten; Desktop 1366 und 1920 px, Handy 390 px, hell und dunkel), `web/pages.py`,
`static/app.css` und der Seitencode. Nicht geprüft wurden echte Daten, Screenreader und die
Bedienung im laufenden Betrieb.

**Was gut ist und bleibt:** klare Seitenleiste mit drei Gruppen, Zähler an „Offen“, Kartenfarben je
Art (Termin, Aufgabe), ausdrückliche Bestätigungen, Bedienung ohne JavaScript, heller und dunkler
Modus mit Farbvariablen, geprüfte Kontraste und Tippflächen.

**Das Kernproblem:** Die Oberfläche ist über viele Versionen seitenweise gewachsen. Jede Seite ist
für sich brauchbar, aber sie folgen keinem gemeinsamen Muster. Die Arbeitsseite „Offen“ ist
ausgereift; die Einblick-Seiten (Verlauf, Mails, Abgleich, Berichte) wirken dagegen wie
Rohfassungen.

### 0.1 Befunde

P1 = stört die tägliche Arbeit oder führt in die Irre. P2 = uneinheitlich oder umständlich.
P3 = Feinschliff.

| ID | Prio | Bereich | Befund | Nachweis |
| :--- | :--- | :--- | :--- | :--- |
| B1 | P1 | Verlauf | Zeigt interne Werte: Zeit als `2026-11-13T09:48:58.682555Z`, Status als `rejected`, `pending_confirmation`, `needs_clarification`, Akteur `system`. Filter sind sechs untereinander gestapelte Freitextfelder über die volle Breite, darunter „Aufgabe (task) oder Termin (event)“; Datum ohne Datumsfeld. | `wide60-verlauf-*.png`, `archive_pages.py` |
| B2 | P1 | Offen (Handy) | Filter, Suche, Sortierung, Gruppierung und zwei Schaltflächen füllen bei 390 × 844 fast den ganzen ersten Bildschirm; die erste Entscheidung beginnt bei rund 800 px. | `toolbar606-mobile.png` |
| B3 | P1 | Seitenkopf | Von 72 Seiten mit Überschrift nutzen 8 den gemeinsamen Kopf (Bereich, Titel, Erklärung). Bei Mails und Verlauf stehen die Filter-Chips über der Überschrift, bei Offen darunter. Die Seite hinter „Auswertung“ heißt „Kosten und Zeiten“, die hinter „Berichte“ „Tätigkeitsberichte“. | Screenshots, `grep` |
| B4 | P1 | Technische Sprache | 16 Stellen in Seiten nennen `config.yaml` oder `prompts.yaml`. Beispiel Berichte: „werden mit activity_report.enabled in config.yaml … aktiviert“ statt eines Links zur Einstellung. Abgleich zeigt „Ziel: Anbieter nicht gespeichert“. | `wide60-berichte-*.png`, `wide60-abgleich-*.png` |
| B5 | P2 | Seitenbreite | Jede Seitenart hat eine eigene Breite und Ausrichtung (Offen bis 1500 px, Einstellungen 1240 px, Themen 1320 px, Lernen 1600 px, sonst rund 1016 px mittig). Beim Wechsel springt der Inhalt waagerecht. | `app.css` (`main:has(…)`), Screenshots 1920 px |
| B6 | P2 | Karten | Karten ohne eigenen Kopf beginnen mit rund 45 px Leerraum (`h2` hat 28 px Abstand nach oben, auch als erstes Element). Sichtbar bei Status, Abgleich, Berichte, Mails. | `app.css` Zeile 157, Screenshots |
| B7 | P2 | Listen | Mails, Verlauf und Abgleich zeigen je Eintrag eine hohe Karte mit ein bis drei Zeilen Text; bei 1920 × 1080 passen etwa fünf Einträge auf den Bildschirm. Im Abgleich ist der Titel eine Schaltfläche, in Mails ein Link. | `wide60-mails-*.png`, `wide60-abgleich-*.png` |
| B8 | P2 | Einstellungen | 22 Kacheln in vier Gruppen. Überschneidungen: „Einrichtung“, „Diagnose“, „Lesender Selbsttest“ und auf der Statusseite „Verbindungen lesend prüfen“; „Benachrichtigungen“, „Benachrichtigungsprofil“ und „Zustellhistorie“; „Geräte“ steht zusätzlich in der Hauptnavigation. | `wide60-einstellungen-*.png` |
| B9 | P2 | Anrede und Zahlen | Teils „du“ („wartet auf dich“), teils „Sie“ („Verbessern Sie Ihre Themenregeln“): 24 gegenüber 11 Codezeilen. Falsche Mehrzahl: „Prüfentwurf mit 1 Vorschlägen“, „1 Durchläufe“. | `wide60-lernen-*.png`, `grep` |
| B10 | P2 | Hauptaktion | Die wichtigste Aktion einer Seite ist nicht einheitlich hervorgehoben: „Suchen“ (Mails) und „Auswerten“ grün, „Filtern“ (Verlauf) und „Anzeigen“ (Offen) grau; auf „Lernen“ ist auch bei wartendem Prüfentwurf keine Schaltfläche hervorgehoben. | Screenshots |
| B11 | P2 | Auswertung | Acht Kennzahlen als Tabelle mit unterstrichenen Werten; bei leerem Zeitraum eine Tabelle voller Nullen. Auf dem Handy folgen danach fünf Diagramme und der Ablaufplan untereinander (rund 14 Bildschirmhöhen). | `wide60-auswertung-*.png`, `evaluation59-mobile.png` |
| B12 | P2 | Handy-Navigation | Unten stehen Offen, Mails, Verlauf, Status; der zweite Arbeitsschritt „Vorschlagsabgleich“ liegt unter „Mehr“. | `navigation-more-mobile.png`, `TAB_BAR` |
| B13 | P3 | Gestaltungsregeln | Zwölf verschiedene Eckenradien und rund zwanzig Schriftgrößen, viele davon fest im CSS statt als Variable. Status erscheint in der Liste als Text, im Detail als Plakette. | `app.css` |
| B14 | P3 | Offen (Desktop) | In der Detailkarte liegt zwischen den Schaltflächen und „Was bedeuten diese Entscheidungen?“ ein großer Leerraum. Ob er im echten Fenster auftritt oder nur im Ganzseiten-Screenshot (haftende Aktionsleiste), ist zu messen. | `toolbar606-desktop.png` |

Aus der [UI-Prüfung 5.7.5](Pruefung-UI-5.7.5.md) hier aufgenommen, soweit noch offen (wird im jeweiligen Schritt zuerst geprüft): UI-07
(Einstellungen bestätigen: technischer Schlüssel statt Alt-Neu-Vergleich), UI-08 (Statusseite),
UI-11 (Abstände im Themeneditor) und UI-12 (Fachbegriffe bei Zuordnen/Verwerfen).

---

## 1. Ziele und Nichtziele

**Ziele**

1. Jede Seite folgt demselben Aufbau: Kopf, Werkzeugleiste, Inhalt.
2. Keine Seite zeigt interne Werte, Schlüsselnamen oder Dateinamen, wo ein deutsches Wort oder ein
   Link zur Einstellung möglich ist.
3. Auf dem Handy ist die erste Entscheidung ohne Scrollen sichtbar.
4. Listen sind dicht genug, um Einträge zu vergleichen.
5. Gestaltungsregeln (Abstände, Schrift, Ecken, Schaltflächen) stehen an einer Stelle und werden
   automatisch geprüft.

**Nichtziele**

- Kein neues Erscheinungsbild: Farben, Logo, Seitenleiste und Kartenfarben bleiben.
- Keine neuen Funktionen, keine Änderung an Routen, Bestätigungen, Sitzungs- und CSRF-Prüfung.
- Kein JavaScript-Zwang: Alles bleibt ohne JavaScript bedienbar.
- Telegram-Texte ändern sich nur dort, wo dieselbe Bezeichnung betroffen ist (E2, E3).

---

## 2. Entscheidungen

| ID | Frage | Vorschlag |
| :--- | :--- | :--- |
| E1 | Anrede | Durchgehend „du“ (überwiegt bereits, passt zu Telegram). |
| E2 | Namen von Navigation und Seite | Seitentitel gleich Navigationseintrag: „Auswertung“, „Berichte“; die bisherigen Titel werden zur Erklärzeile. |
| E3 | „Vorschlagsabgleich“ | Bezeichnung bleibt; auf dem Handy ersetzt er „Status“ in der unteren Leiste, Status wandert unter „Mehr“. Alternative: Reihenfolge unverändert lassen. |
| E4 | Einstellungen | Zusammenlegen auf rund 14 Kacheln: eine Kachel „Verbindungen prüfen“ (Diagnose und Selbsttest), eine Kachel „Benachrichtigungen“ mit Unterseiten Profil und Zustellhistorie; „Geräte“ nur noch in der Hauptnavigation. Alte Adressen leiten weiter. |
| E5 | Seitenbreite | Zwei Breiten: Standard 1100 px, breit 1500 px für Zweispalter und Tabellen; beide linksbündig neben der Seitenleiste. Alternative: mittig. |
| E6 | Listen | Mails, Verlauf und Abgleich als dichte Zeilenliste (eine bis zwei Zeilen je Eintrag), ab 1024 px mit Spalten; Karten nur noch für Entscheidungen. |

---

## 3. Maßnahmen

### 3.1 Gestaltungsregeln und Seitenkopf (B3, B5, B6, B10, B13)

- **Variablen:** Abstände (4, 8, 12, 16, 24, 32 px), Schriftgrößen, Ecken und Schatten als
  CSS-Variablen; feste Werte in `app.css` werden ersetzt. Das Aussehen ändert sich dabei höchstens um
  wenige Pixel. Umgesetzt (6.2.1): neun Schriftstufen (`--text-2xs` bis `--text-3xl`; fünf hätten
  Überschriften und die schmale Seitenleiste sichtbar verändert), vier Eckenstufen plus `--radius-pill`,
  vier Schatten. Abstandsvariablen gelten für Rahmen und neue Bausteine; bestehende Einzelabstände
  werden mit den jeweiligen Seiten umgestellt, nicht pauschal.
- **Seitenkopf:** eine Funktion `page_head(bereich, titel, erklärung, aktionen)` in `pages.py`; alle
  Seiten nutzen sie. Filter-Chips stehen immer unter dem Kopf.
- **Breite:** zwei Klassen statt der `main:has(…)`-Sonderfälle (E5).
- **Karten:** das erste Element einer Karte hat keinen Abstand nach oben.
- **Schaltflächen:** je Formular genau eine hervorgehobene Hauptaktion; „Zurücksetzen“ und
  Nebenwege als Text-Schaltfläche.
- **Wächtertest:** ein Test liest `app.css` und scheitert bei festen Farb-, Radius- oder
  Schriftwerten außerhalb der Variablen; ein Browsertest prüft je Kernseite genau einen Seitenkopf
  und höchstens eine Hauptaktion je Formular.

### 3.2 Verständliche Sprache (B1, B4, B9, UI-07, UI-12)

- **Eine Übersetzungsstelle** für Status, Ereignisarten, Akteure und Ziele (aufbauend auf
  `STAGE_LABELS` und den Statusbezeichnungen in `review/views.py`); der Verlauf nutzt sie.
  Unbekannte Werte erscheinen als „unbekannt (Wert)“, nie roh.
- **Zeiten** überall über `format_datetime_local`, Dauern über `duration_text`.
- **Mehrzahl:** eine Hilfsfunktion `count_text(1, "Vorschlag", "Vorschläge")`; alle zusammengesetzten
  Zähltexte nutzen sie.
- **Hinweise auf Dateien** werden zu Links auf die passende Einstellung. Wo es keine
  Web-Einstellung gibt, bleibt der Dateiname, ergänzt um einen Link in die Hilfe.
- **Anrede** nach E1 in Seiten, Hilfetexten und Doku.
- **Einstellungen bestätigen** (UI-07): Anzeigename, bisheriger und neuer Wert, konkrete Wirkung.
  Bei der Umsetzung geprüft (6.2.4): seit 5.8 bereits so umgesetzt (Anzeigename, „Bisher gespeichert“,
  „Neu“, Warnungen nur für die jeweils betroffene Einstellung); keine Änderung nötig.
- **Wächtertest:** Kernseiten mit synthetischen Daten enthalten keine internen Statuswerte, keine
  ISO-Zeitstempel und kein „Sie/Ihre“.

### 3.3 Einheitliche Werkzeugleiste und Listen (B1, B7, B10)

- Die Werkzeugleiste aus 6.0.6 (`open_toolbar.py`) wird zum gemeinsamen Baustein: Suche, Auswahlfelder,
  Hauptaktion in einer Zeile; weitere Filter in einem aufklappbaren Bereich „Mehr Filter“ mit
  Zähler der aktiven Filter.
- **Verlauf:** Suche, Auswahlfelder für Status und Art, Datumsfelder für Von/Bis; Filter bleiben in
  der Adresse erhalten. Ungültige Werte werden wie bisher abgelehnt.
- **Zeilenliste** (E6) für Mails, Verlauf und Abgleich: Titel als Link, Absender, Zeit, Status als
  Plakette; auf dem Handy zweizeilig. Die Statusplakette ist überall dasselbe Element.
  Umgesetzt (6.2.7): Auf dem Handy hat eine Zeile drei kurze Zeilen (Titel, Absender und Zeit,
  Plaketten), bei langen Plaketten vier; zwei Zeilen hätten Plaketten abgeschnitten. Im Abgleich bleiben
  Vorschläge mit Vergleich oder Angebot Karten, alle anderen sind Zeilen.

### 3.4 Offen auf dem Handy (B2, B12, B14, UI-05)

- Unter 900 px zeigt die Seite nur die Schnellfilter (waagerecht scrollbar, eine Zeile) und eine
  Schaltfläche „Suchen und sortieren“, die den Rest aufklappt. Aktive Suche oder Sortierung
  erscheint als entfernbare Plakette. Ohne JavaScript über `details`.
- **Messung im echten Fenster:** neue Browserprüfung mit Fensterausschnitt statt Ganzseitenbild bei
  390 × 844 und 320 × 640: erste Entscheidung beginnt oberhalb von 60 % der Fensterhöhe; haftende
  Aktionsleiste und untere Leiste verdecken zusammen höchstens 35 % der Höhe; Kartentitel bleibt
  sichtbar. Dabei wird B14 geklärt und, falls echt, behoben.
- Untere Leiste nach E3.

### 3.5 Einstellungen und Status (B8, UI-08, UI-11)

- Kacheln nach E4 zusammenlegen; Weiterleitungen für alte Adressen; Einstellungssuche und Hilfeindex
  finden die neuen Orte.
  Umgesetzt (6.2.9): 18 statt rund 14 Kacheln; „Einrichtung“, „Konfiguration neu laden“ und die zwei
  Inhaltskacheln haben eigene Zwecke und blieben. Da keine Seite ihre Adresse verliert, sind keine
  Weiterleitungen nötig.
- **Status:** oben eine Zeile „Alles in Ordnung“ oder der konkrete Handlungsbedarf mit Link; darunter
  die vier Kennzahlen; der Hinweis zu „Verbunden“ wandert in eine Erklärung am Verbindungszeichen.
- Themeneditor und Einstellungsformulare übernehmen die Abstände aus 3.1.

### 3.6 Auswertung (B11)

- Die acht Kennzahlen als Kacheln (wie auf der Statusseite), jede als Link zur Aufrufliste.
- Ohne Daten ein Leerzustand mit einem Satz und dem Hinweis auf den Zeitraum statt einer Tabelle
  voller Nullen.
- Abschnitte „Kosten“, „Zeiten“, „Ablauf“ mit Sprungmarken am Seitenanfang; auf dem Handy sind
  Diagramme unterhalb des ersten Abschnitts eingeklappt.
  Umgesetzt (6.2.10): Sprungmarken zu Kennzahlen, Diagrammen, Ablauf und „Nach Modell und Schritt“ –
  die Diagramme mischen Kosten und Zeiten, eine Trennung nach Kosten/Zeiten hätte sie zerrissen.

---

## 4. Umsetzungsschritte

| Schritt | Patch | Arbeitspaket | Tests |
| :--- | :--- | :--- | :--- |
| D1 | 6.2.1 | Variablen für Abstände, Schrift, Ecken; Wächtertest für `app.css` (3.1) | Wächtertest scheitert vor der Umstellung; Bildvergleich der Kernseiten hell/dunkel ohne Überlauf |
| D2 | 6.2.2 | Seitenkopf, zwei Seitenbreiten, Kartenabstand, Titel nach E2 (3.1) | Jede Kernseite: ein Kopf, eine `h1`; kein waagerechter Sprung zwischen Seiten gleicher Breite; 320 bis 2560 px |
| D3 | 6.2.3 | Übersetzungsstelle, Zeiten, Mehrzahl, Anrede (3.2) | Regression „rejected“/ISO-Zeit im Verlauf; „1 Vorschlag“; unbekannter Wert; Wächter gegen interne Werte |
| D4 | 6.2.4 | Dateihinweise zu Links; Einstellungen bestätigen mit Alt-Neu-Vergleich (3.2) | Jeder Link führt zur richtigen Einstellung; Bestätigung bleibt versionsgebunden, Sitzung/CSRF/Idempotenz unverändert geprüft |
| D5 | 6.2.5 | Gemeinsame Werkzeugleiste; Verlauf-Filter (3.3) | Kombinierte Filter, ungültige Werte, Adresse stellt Filter wieder her, ohne JavaScript, Tastatur |
| D6 | 6.2.6 | Zeilenliste für Mails, Verlauf, Abgleich; einheitliche Statusplakette (3.3) | Mindestens zwölf Einträge je Bildschirm bei 1920 × 1080; lange Titel; Handy zweizeilig; Barrierefreiheitsprüfung |
| D7 | 6.2.7 | Offen auf dem Handy; Messung im echten Fenster; untere Leiste (3.4) | Grenzwerte aus 3.4 bei 390 und 320 px; ohne JavaScript; Regression für B14, falls bestätigt |
| D8 | 6.2.8 | Einstellungen zusammenlegen, Status-Kopfzeile (3.5) | Weiterleitungen, Suche, Hilfeindex; Status mit und ohne Handlungsbedarf; Anmeldung erforderlich |
| D9 | 6.2.9 | Auswertung: Kacheln, Leerzustand, Abschnitte (3.6) | Mit Daten, ohne Daten, Handy; Links zur Aufrufliste; kein Skriptfehler |
| D10 | 6.2.10 | Doku, Abnahme, Release | Gesamtprüfung mit 100 % Abdeckung, parallele Browser-Suite, `docs/Release-6.2.md` mit Vorher-Nachher-Bildern |

D1 und D2 kommen zuerst, weil alle weiteren Schritte auf Variablen und Seitenkopf aufbauen. D3 bis
D9 sind danach voneinander unabhängig und einzeln auslieferbar.

---

## 5. Abnahmekriterien

- Alle Kernseiten (Liste aus `test_ui_widescreen60.py`) nutzen Seitenkopf, eine der zwei Breiten und
  höchstens eine Hauptaktion je Formular.
- Keine Kernseite zeigt mit synthetischen Daten interne Statuswerte, ISO-Zeitstempel oder gemischte
  Anrede.
- Handy 390 × 844: erste Entscheidung auf „Offen“ ohne Scrollen sichtbar.
- 1920 × 1080: Mails, Verlauf und Abgleich zeigen mindestens zwölf Einträge.
- Wächtertests für CSS-Variablen und Sprache sind Teil der Gesamtprüfung.
- 100 % Zeilen- und Branch-Abdeckung, 100 % JavaScript-Blockabdeckung, Barrierefreiheitsprüfung auf
  allen Geräten, hell und dunkel.
- Kein externer Schreibzugriff ohne Bestätigung; bestehende Sicherheitstests unverändert grün.

---

## 6. Risiken

- **Viele Bildvergleiche und Texte in Tests ändern sich.** Deshalb kleine Patches und je Patch nur
  eine Art Änderung (erst Variablen, dann Aufbau, dann Sprache).
- **Geänderte Bezeichnungen** betreffen Hilfeindex, `docs/Bedienung.md` und Telegram-Texte. Je Patch
  werden Hilfeindex und Doku mit aktualisiert.
- **Zusammengelegte Einstellungen** können Lesezeichen brechen; Weiterleitungen bleiben mindestens
  bis 7.0.
- **Die Befunde stammen aus synthetischen Daten.** Vor D6 und D7 sollte ein Blick auf den echten
  Bestand zeigen, ob Dichte und Grenzwerte passen.

---

## 7. Dokumentation und Release

- `README.md`, `CHANGELOG.md`, `docs/Bedienung.md` (Hilfeindex neu erzeugen) und die
  Projektspezifikation werden je Patch aktualisiert.
- `docs/Release-6.2.md` dokumentiert die Abnahme mit Vorher-Nachher-Bildern der Kernseiten.
- Die offenen Punkte der [UI-Prüfung 5.7.5](Pruefung-UI-5.7.5.md) werden dort als erledigt oder
  ausdrücklich verschoben geführt.
