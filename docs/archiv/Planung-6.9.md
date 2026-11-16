# Mailhelp 6.9 – Karten, die am Finger kleben, und eine ruhigere Liste „Offen“

**Zielversion:** 6.9 (Patches 6.9.1 bis 6.9.7)

**Stand:** 14. November 2026

**Status:** W1 bis W12 und U2 bis U6 in 6.9.1 umgesetzt; automatisierte Abschlussprüfung am
15. November 2026 bestanden.
Die Arbeitspakete sind in einer Veröffentlichung gebündelt; 6.9.2 ergänzt die Abschlussprüfung. U1 ist nicht Teil von 6.9.
Reale Geräteabnahme offen; Nachweise und Messprotokoll in [Release 6.9](Release-6.9.md).

**Ausgangsstand:** 6.7.5 (Wischgeste aus 6.3.1/6.3.2, Feinabstimmung aus 6.7)

**Grundlage:** [Entwicklungsregeln](../../AGENTS.md), [Projektspezifikation](../../Mailhelp-Projektspezifikation.md),
[Planung 6.3](Planung-6.3.md), [Planung 6.3.2](Planung-6.3.2.md) Teil B, [Planung 6.7](Planung-6.7.md) Abschnitt 3.2

Der Plan hat zwei Teile. **Teil A** baut die Wischgeste so um, dass die Karte dem Finger in jede
Richtung folgt, sich dabei leicht neigt und beim Loslassen glaubwürdig wegfliegt oder zurückfedert.
**Teil B** sammelt weitere Verbesserungen der Oberfläche, die beim Prüfen von „Offen“ auf dem
Telefon aufgefallen sind.

---

# Teil A – Wischen, das sich natürlich anfühlt

## 0. Befund

Geprüft: `web/static/app.js` (Abschnitt „6.3“, Zeilen 418–559), `web/static/app.css` (Zeilen 506–526)
und die Screenshots der Browsertests (`swipe63-*`, `open628-mobile`).

| ID | Beobachtung | Folge für das Gefühl | Nachweis |
| :--- | :--- | :--- | :--- |
| S1 | Die Karte bewegt sich nur waagerecht: `translateX(…)`. Die senkrechte Fingerbewegung wird verworfen. | Wer schräg nach rechts oben wischt, sieht den Finger von der gegriffenen Stelle wegrutschen; die Karte wirkt wie ein Schieberegler, nicht wie ein Gegenstand. | `follow()`, Zeile 515 |
| S2 | Ab der Schwelle (`min(40 % der Breite, 160 px)`) folgt die Karte nur noch zu 25 % (`beyond: 0.25`). | Genau im Moment der Entscheidung löst sich die Karte vom Finger. | `follow()`, Zeile 511 |
| S3 | Die Geste beginnt erst, wenn der waagerechte Weg das 1,5-Fache des senkrechten ist (≈ 34° über der Waagerechten). Der Browser übernimmt bei `touch-action: pan-y` das Scrollen aber erst bei steileren Bewegungen. | Zwischen etwa 34° und der Browsergrenze passiert **gar nichts**: weder scrollt die Seite noch bewegt sich die Karte. Ein Wisch „leicht nach rechts oben“ fällt oft genau in diese Lücke. Die genaue Browsergrenze wird in Schritt D1 gemessen. | Zeilen 526–527 |
| S4 | Keine Neigung. | Ohne Drehung fehlt der wichtigste Hinweis, dass man etwas „wegschiebt“. | `follow()` |
| S5 | Beim Loslassen gleitet die Karte immer in 220 ms an ihren Platz zurück, auch wenn die Aktion ausgelöst wurde; dann erscheint „Wird verarbeitet …“ auf der Karte. | Die Geste endet nicht dort, wo sie hinwollte. Die Karte kommt zurück, obwohl sie entschieden ist. | `finish()`, Zeilen 536–547 |
| S6 | Nur die Strecke zählt, nie das Tempo (Entscheidung 6.3). | Ein kurzer, schneller Wisch aus dem Handgelenk, der übliche Weg in anderen Apps, springt zurück. | Kommentar Zeile 419 |
| S7 | Während des Wischens wird das Dokument breiter: Der Screenshot `swipe63-kraeftig-light.png` ist 1 302 statt 1 170 Pixel breit (44 CSS-Pixel bei dreifacher Dichte). | Die Seite lässt sich während und nach dem Wischen seitlich verschieben und wackelt. Mit freier Bewegung und Drehung würde das schlimmer. | Screenshot-Breiten |
| S8 | Bei gesperrter Karte bremst sie hart bei 24 px (`resist 0.15`, `stop 24`). | Richtig als Aussage („geht nicht“), wirkt aber wie ein Anschlag statt wie ein Gummiband. | `follow()`, Zeile 510 |

Unverändert gut und bleibt erhalten: kein Wischen mit Maus und ab 1 024 px, 24 px Randzone für die
Zurück-Geste, Schutz von Eingabefeldern und waagerecht scrollenden Tabellen, Abbruch beim zweiten
Finger, Abfangen des Klicks nach einem Wisch, das Senden genau des Formulars der Schaltfläche.

---

## 1. Ziele und Nichtziele

**Ziele**

1. Der Punkt, an dem der Finger die Karte gegriffen hat, bleibt während der ganzen Geste unter dem
   Finger, auch schräg und über die Schwelle hinaus (Abweichung höchstens 2 px im Browsertest).
2. Jede Bewegung bis etwa 45° über oder unter der Waagerechten bewegt die Karte; steilere Bewegungen
   scrollen die Liste. Es gibt keine Lücke, in der nichts passiert.
3. Die Karte neigt sich mit dem Weg; die Richtung der Neigung hängt davon ab, ob oben oder unten
   gegriffen wurde.
4. Eine ausgelöste Karte verlässt den Bildschirm in Wischrichtung; eine nicht ausgelöste federt aus
   ihrer aktuellen Lage zurück.
5. Die Seite wird beim Wischen nie breiter (S7).
6. Sicherheit und Ablauf bleiben exakt wie bisher: Session, CSRF-Token, Version und
   Idempotenzschlüssel kommen unverändert aus dem Formular der Karte; ein Wisch löst nur aus, was
   ein Tippen auf die Schaltfläche auslösen würde.

**Nichtziele**

- Keine Wischgeste auf dem Desktop oder mit der Maus.
- Keine neuen Aktionen per Wisch (z. B. „Schon erledigt“ nach oben). Senkrecht entscheidet nie.
- Keine Änderung an Routen, Befehlen oder Datenmodell.

---

## 2. Entscheidungen

| ID | Frage | Vorschlag |
| :--- | :--- | :--- |
| **W1** | Wie folgt die Karte dem Finger? | **1 : 1 in beiden Achsen** ab dem Startpunkt: `translate(dx, dy)`. Keine Bremse über der Schwelle (S2 entfällt). Die Seite scrollt während der Geste nicht, weil der Browser sie der Karte überlassen hat. |
| **W2** | Neigung | Drehwinkel `θ = dx / Kartenbreite · 10°`, höchstens ±10°. Gedreht wird **um den Griffpunkt** (`transform-origin` = Fingerposition in der Karte); so bleibt der gegriffene Punkt exakt unter dem Finger. Griff in der oberen Kartenhälfte → Rechtswisch dreht im Uhrzeigersinn; untere Hälfte → gegen den Uhrzeigersinn, wie bei einem Blatt Papier. Hohe Karten drehen weniger: Höchstwinkel `10° · min(1, 400 px / Kartenhöhe)`, damit die Ecken nicht weit über den Bildschirm schwenken. |
| **W3** | Was entscheidet? | Nur der **waagerechte** Weg: ausgelöst, wenn `|dx| ≥ Schwelle` (unverändert `min(40 %, 160 px)`, nach der Messung in 6.7). Senkrechte Bewegung ändert nichts an der Entscheidung. |
| **W4** | Wer entscheidet Wischen gegen Scrollen? | **Der Browser.** Die eigene Verhältnisregel (1,5) und der eigene Abbruch bei senkrechter Bewegung entfallen. Was der Browser bei `touch-action: pan-y pinch-zoom` nicht als Scrollen übernimmt, gehört der Karte; sie startet ab 10 px Gesamtweg. Übernimmt der Browser doch (`pointercancel`), federt die Karte ohne Auslösung zurück. Damit gilt die Grenze des Browsers (etwa 45°); steiler bleibt Scrollen, sonst ließe sich die Liste auf Karten nicht mehr scrollen. **Nachtrag Umsetzung:** Damit die Karte nicht kurz zuckt, bevor der Browser abbricht, startet sie erst, wenn die Bewegung nicht steiler als 45° ist (gemessene Browsergrenze, siehe Risiko „`pan-y`-Grenze“). |
| **W5** | Zählt Schwung? | **Ja, begrenzt (übernommen; ersetzt die Regel „nur die Strecke“ aus 6.3).** Ausgelöst wird auch, wenn beim Loslassen die waagerechte Geschwindigkeit der letzten 100 ms mindestens 0,9 px/ms beträgt, in Richtung der Verschiebung zeigt **und** `|dx|` mindestens die halbe Schwelle erreicht hat. Damit löst kein Antippen und kein Scrollen aus, aber der kurze Wisch aus dem Handgelenk. |
| **W6** | Loslassen nach Auslösung | Die Karte fliegt in Wischrichtung aus dem Bild: Geschwindigkeit und Neigung werden fortgesetzt, mindestens bis zum Bildschirmrand, 180–240 ms, ausklingend. Danach schließt sich ihr Platz in 200 ms auf einen **Ergebnisstreifen** (Höhe 56 px, Farbe der Seite, z. B. „✓ Im Kalender anlegen – wird verarbeitet …“). Der Streifen trägt die vorhandene Statusmeldung (`data-card-command-status`) und wird wie bisher durch die vom Server gelieferte Karte ersetzt, inklusive Ablehnungsgründen nach „Verwerfen“ und „Wieder entfernen“ aus 6.6, soweit angeboten. **Nicht angenommen** (Fehlerantwort): Die Karte kommt von der Seite zurück, die Schaltflächen sind wieder bedienbar, die Fehlermeldung steht auf der Karte. **Antwort unterbrochen:** Der Streifen zeigt den bestehenden Text; nichts wird erneut gesendet. |
| **W7** | Loslassen ohne Auslösung | Die Karte federt aus ihrer aktuellen Lage (Position und Neigung) zurück: Dauer je nach Weg 150–300 ms, leichtes Überschwingen (`cubic-bezier(.2, 1.3, .4, 1)`). |
| **W8** | Gesperrte Karte oder getippter Text | Die Karte folgt senkrecht 1 : 1, waagerecht als Gummiband: `32 px · (1 − e^(−|dx| / 80 px))`, keine Neigung, Schloss-Symbol, beim Loslassen der bekannte Grund als Ansage. |
| **W9** | Rückmeldung während der Bewegung | Der Hintergrund färbt sich stufenlos mit dem Fortschritt (Deckkraft 0 → 1 bis zur Schwelle), das Symbol wächst von 80 % auf 100 %. An der Schwelle: Vibration 10 ms (wie bisher) und ein kurzer Puls des Symbols. Unter die Schwelle zurück: Farbe kehrt in den hellen Ton zurück, keine zweite Vibration. |
| **W10** | Darstellung beim Ziehen | Die Karte hebt sich (stärkerer Schatten), liegt über den Nachbarkarten und unter Kopf- und Tab-Leiste. Der Listenbereich erhält `overflow-x: clip`. `clip` statt `hidden`, damit die klebenden Bereiche (`sticky`) weiter funktionieren; das behebt S7. |
| **W11** | Flüssigkeit | Position wird einmal pro Bild in `requestAnimationFrame` aus dem jüngsten Ereignis gesetzt; nur `transform` und `opacity` ändern sich. Die Geschwindigkeit wird aus `getCoalescedEvents()` (wo vorhanden) über die letzten 100 ms gemessen. Keine Vorhersage mit `getPredictedEvents()` in 6.9, weil sie bei Richtungswechseln zittert; als spätere Option vermerkt. |
| **W12** | Weniger Bewegung | Bei `prefers-reduced-motion: reduce` folgt die Karte weiter dem Finger (das ist direkte Bedienung, keine Animation), aber ohne Neigung, ohne Überschwingen und ohne Flug: Ausgelöst blendet sie in 100 ms zum Ergebnisstreifen über, sonst springt sie in 100 ms zurück. |

---

## 3. Maßnahmen

### 3.1 Bewegungsmodell (W1–W4, W10, W11)

- `SWIPE` erhält: `start: 10`, `tilt: 10`, `tiltHeight: 400`, `fling: 0.9`, `flingShare: 0.5`,
  `window: 100`. Es entfallen `ratio`, `vertical`, `beyond`.
- `pointerdown` merkt sich zusätzlich den Griffpunkt relativ zur Karte (`offsetX/offsetY` über
  `getBoundingClientRect`) und ob er in der oberen Hälfte liegt.
- `pointermove` sammelt nur Ereignisse; ein `requestAnimationFrame` setzt
  `transform: translate(dx, dy) rotate(θ)` mit `transform-origin` am Griffpunkt. `setPointerCapture`
  hält die Geste auch außerhalb der Karte fest.
- `pointercancel` vor oder während der Geste: zurückfedern, nichts auslösen (bisheriges Verhalten,
  jetzt der einzige Weg, auf dem Scrollen gewinnt).
- CSS: `.open-items { overflow-x: clip; }`, `.swipe-card.swiping { will-change: transform;
  box-shadow: var(--shadow-lift); z-index: 2; }` (neue Variable `--shadow-lift` in hell und dunkel).

### 3.2 Loslassen (W5–W7)

- `release()` unterscheidet: ausgelöst (Strecke oder Schwung) → `flyOut(side, velocity)` und erst
  danach `requestSubmit()`; das Formular wird also wie bisher genau einmal gesendet. Nicht
  ausgelöst → `springBack()`.
- Der Ergebnisstreifen ist ein Element vor der Karte, das die Statusmeldung aufnimmt. Die Karte selbst
  bleibt bis zur Server-Antwort unsichtbar im DOM (`hidden`), damit `pollCard()` sie wie bisher
  findet und ersetzt und die Detailansicht unverändert arbeitet.
- Die Fehlerantwort im `submit`-Handler (`!response.ok`) ruft `flyBack()` auf, wenn die Karte
  geflogen war.
- Doppelte Sendung bleibt ausgeschlossen: `form.dataset.sending` und die Prüfung auf
  `data-card-command-status` gelten unverändert; ein zweiter Wisch auf eine fliegende Karte startet
  nicht.

### 3.3 Rückmeldung, Sperre, weniger Bewegung (W8, W9, W12)

- `follow()` setzt `--swipe-progress` (0 bis 1) am Hintergrund; CSS leitet Deckkraft und Symbolgröße
  daraus ab.
- Gesperrt oder getippter Text: Gummiband nach W8, Ansage beim Loslassen wie bisher.
- Eine Abfrage `matchMedia("(prefers-reduced-motion: reduce)")` schaltet Neigung, Überschwingen
  und Flug ab.

---

# Teil B – Weitere Verbesserungen der Oberfläche

## 4. Befund

Gesichtet in den Telefon-Screenshots der Browsertests (`open628-mobile`, `card-kinds-mobile`) und im
Code von `web/actions.py` und `app.js`.

| ID | Beobachtung | Nachweis |
| :--- | :--- | :--- |
| B1 | Eine Vorschlagskarte ist auf dem Telefon etwa eine Bildschirmhöhe hoch; davon ist rund ein Viertel Leerraum zwischen „Details“ und „Ändern“. „Beschreibung und Beleg“ und „Details“ sind zwei getrennte Zeilen. Man sieht fast nie mehr als eine Karte. **Nicht Teil von 6.9** (U1 entfällt). | Screenshots `open628-mobile`, `card-kinds-mobile` |
| B2 | Auf dem Telefon stehen „Verwerfen / Schon erledigt“ und die Hauptaktion **über** Titel, Absender und Datum (6.2.8: erste Entscheidung im oberen Fensterbereich). Man entscheidet, bevor man liest, worüber. In den Testdaten steht oben nur „—“; ob echte Karten dort einen Titel zeigen, wird in U2 geprüft. | Screenshots, `actions.py` Zeile 128 |
| B3 | Nach einer Entscheidung ersetzt `pollCard()` nur die Karte und „Zuletzt erledigt“. Die Zahl neben „Offene Entscheidungen“ und das Abzeichen am Tab „Offen“ bleiben auf dem alten Stand, bis die Seite neu lädt. | `app.js` Zeilen 342–346 |
| B4 | Die Filterchips („Alle“, „Termine“, „Aufgaben“, „Klärung nötig“, …) laufen rechts aus dem Bild, ohne Hinweis, dass man sie seitlich schieben kann. | Screenshot, `app.css` Zeile 1230 |
| B5 | Die Relevanzkarte zeigt ihren Erklärsatz („Relevant: Mail weiter auswerten. Irrelevant: …“) immer; bei Vorschlägen steht die gleiche Art Erklärung bereits aufklappbar („Was bedeuten diese Entscheidungen?“). | Screenshot, `review_pages.py` |
| B6 | Der Tipp zur Wischgeste ist ein Textkasten mit Schaltfläche „Verstanden“ zwischen erster und zweiter Karte. Er erklärt eine Bewegung mit Worten. | Screenshot, `showHint()` |

## 5. Entscheidungen

Kompaktere Karten (U1 zu B1) sind ausdrücklich **nicht** Teil von 6.9.

| ID | Frage | Vorschlag |
| :--- | :--- | :--- |
| **U2** | Reihenfolge auf dem Telefon (B2) | **Titel zuerst (übernommen):** Titel, Absender, Datum/Ort, dann die Schaltflächen. Damit die erste Entscheidung ohne kompaktere Karten (U1) im oberen Fensterbereich bleibt, ist der Kopf knapp: Titel höchstens zwei Zeilen, Absender und Datum/Ort in einer gemeinsamen Zeile, Statusmarken („Wartet auf Bestätigung“, „Aktuell in Telegram“) und Fristen erst unter den Schaltflächen. Die Prüfung aus 6.2.8 (erste Entscheidung im oberen Bereich) bleibt bestehen und gilt als Abnahme für U2. Mit der Wischgeste ist der Weg zu den Schaltflächen ohnehin seltener nötig. Vorher wird geprüft, ob echte Karten oben einen Titel haben (in den Testdaten steht nur „—“); fehlt er, ist das ein eigener Fehler mit Regressionstest. |
| **U3** | Zähler aktuell halten (B3) | `pollCard()` übernimmt aus der frisch geladenen Übersicht auch die Überschriftenzahl und das Tab-Abzeichen. Bei 0 erscheint die vorhandene „Alles erledigt“-Karte ohne Neuladen. |
| **U4** | Filterchips (B4) | Weicher Ausblendverlauf am rechten Rand, solange weitere Chips folgen; der aktive Chip wird beim Laden in den sichtbaren Bereich gescrollt. |
| **U5** | Relevanzkarte (B5) | Der Erklärsatz wird wie bei Vorschlägen ein aufklappbares „Was bedeuten diese Entscheidungen?“. |
| **U6** | Einführung der Geste (B6) | **Anstupsen statt Text (übernommen),** Einzelheiten in 5.1. Der Textkasten mit „Verstanden“ entfällt. |

### 5.1 Anstupsen im Einzelnen (U6)

**Ablauf beim ersten Öffnen von „Offen“ auf dem Telefon**

1. Die Seite ist geladen und die erste wischbare Karte vollständig im Bild. Nach 600 ms Ruhe bewegt
   sie sich einmal von selbst. Es geht nichts davon aus, wenn der Nutzer in dieser Zeit schon
   scrollt oder tippt; dann folgt das Anstupsen erst, sobald die Karte wieder 600 ms ruhig im Bild ist.
2. Die Karte schwenkt etwa 3 cm (≈ 110 px, höchstens ein Drittel der Kartenbreite) nach rechts und
   neigt sich dabei wie beim echten Wischen (W2, Griffpunkt gedacht in der Kartenmitte oben).
3. Darunter wird der Hintergrund des echten Wischens sichtbar: grün mit „✓“ und der Beschriftung der
   Hauptschaltfläche, z. B. „✓ Im Kalender anlegen“; bei einer Relevanzfrage „✓ Relevant“. Er bleibt
   im hellen Ton; die Schwelle wird nicht erreicht, es vibriert nichts.
4. Die Karte federt mit dem Überschwingen aus W7 zurück. Gesamtdauer etwa 500 ms.
5. Es wird **nichts gesendet**: Das Anstupsen ist eine reine Darstellung ohne Formular, ohne
   Klickereignis und ohne Zustandsänderung.

**Die Zeile darunter**

- Unter der ersten Karte steht eine schmale Zeile ohne Kasten und ohne Hintergrund, in
  Sekundärschrift: „Nach rechts wischen: anlegen · nach links: verwerfen“ mit einem kleinen „×“
  (Tippfläche 44 × 44 px, Beschriftung für Bildschirmleser „Hinweis schließen“).
- Ist die erste Karte eine Relevanzfrage: „Nach rechts wischen: relevant · nach links: irrelevant“.
- Ist die Hauptaktion gesperrt (z. B. erst die Rückfrage beantworten), wird die erste Karte gewählt,
  bei der beide Richtungen möglich sind; gibt es keine, entfällt das Anstupsen und nur die Zeile
  steht unter der ersten Karte.

**Wann es dauerhaft verschwindet**

- Nach dem ersten erfolgreich ausgelösten Wisch oder nach einem Tipp auf „×“. Gemerkt wird das wie
  bisher im Browser (`localStorage`, Schlüssel `mailhelp-swipe-hint`); ein schon gesetzter Schlüssel
  aus 6.3 gilt weiter, wer den Kasten bereits weggeklickt hat, sieht auch das Anstupsen nicht.
- Kann der Browser nichts speichern (privates Fenster, gesperrter Speicher), erscheint die Zeile bei
  jedem Besuch, das Anstupsen aber höchstens einmal je geöffneter Seite.

**Wann sich die Karte nicht bewegt**

- Am Computer, mit der Maus und ab 1 024 px Breite: weder Bewegung noch Zeile (wie heute beim Kasten).
- Bei `prefers-reduced-motion: reduce`: keine Bewegung, nur die Zeile.
- Wenn die Seite durch neue Daten ersetzt wird (`mailhelp:stale`), wird nicht erneut angestupst.

---

## 6. Umsetzungsschritte

| Schritt | Patch | Arbeitspaket | Tests |
| :--- | :--- | :--- | :--- |
| D1 | 6.9.1 | **Messung und Bewegungsmodell:** Browsergrenze für `pan-y` auf Android Chrome und iOS Safari messen (Winkel, ab dem `pointercancel` kommt), Ergebnis in `docs/archiv/Release-6.9.md`. Danach W1–W4, W10, W11. | Browsertest mit CDP-Touch: Wisch unter 20°, 35° und 44° nach rechts oben löst aus; 60° scrollt und löst nicht aus. **Regressionstest S3:** 40° nach rechts oben bewegt die Karte (scheitert vor dem Fix). **Regressionstest S7:** `scrollWidth == clientWidth` des Dokuments während und nach dem Wisch. Griffpunkt-Test: Der mit `DOMMatrix` transformierte Griffpunkt liegt höchstens 2 px neben dem Finger, auch bei 1,5-facher Schwelle. **Regressionstest S2:** keine Bremse über der Schwelle. |
| D2 | 6.9.2 | **Loslassen:** W5–W7, Ergebnisstreifen, Rückkehr bei Fehler. | Ausgelöst → genau eine POST-Anfrage, Streifen sichtbar, danach Serverkarte. Fehlerantwort → Karte zurück, Schaltflächen aktiv. Abbruch der Verbindung → kein zweites Senden. Schwung: 0,9 px/ms bei halber Schwelle löst aus; bei einem Drittel nicht; Schwung gegen die Verschiebungsrichtung nicht. Nicht ausgelöst → Karte am Ende exakt an alter Stelle (`transform` leer). Wiederholter Wisch während des Flugs startet nicht. |
| D3 | 6.9.3 | **Rückmeldung und Sperre:** W8, W9, W12. | Gesperrt: Versatz ≤ 32 px, keine Drehung, Ansage. Fortschritt 0/0,5/1 setzt `--swipe-progress`. `emulateMedia(reducedMotion)` → keine Drehung, kein Flug. Screenshots hell/dunkel bei halber Schwelle, an der Schwelle, im Flug. |
| D4 | 6.9.4 | **Titel zuerst:** U2. | Reihenfolge Titel → Absender/Datum → Schaltflächen auf dem Telefon für Termin, Aufgabe, Terminänderung und Relevanzfrage; ab 1 024 px unverändert; 6.2.8-Prüfung (erste Entscheidung im oberen Bereich) besteht auf 390 × 844 und 360 × 740; Titel auf zwei Zeilen gekürzt und maskiert; Python-Tests für das neue Markup. |
| D5 | 6.9.5 | **Zähler, Chips, Relevanzkarte:** U3–U5. | **Regressionstest B3:** Nach einer Entscheidung zeigen Überschrift und Tab-Abzeichen die neue Zahl ohne Neuladen; bei 0 erscheint „Alles erledigt“. Ausblendverlauf nur, solange rechts weitere Chips liegen. |
| D6 | 6.9.6 | **Einführung der Geste:** U6 nach 5.1; Textkasten entfällt. | Schwenk genau einmal, erst nach 600 ms Ruhe, höchstens ein Drittel der Kartenbreite, keine POST-Anfrage und kein Klickereignis; Zeile mit Text je Kartentyp; gesperrte erste Karte → nächste Karte mit beiden Richtungen, sonst nur Zeile; Schlüssel nach erstem Wisch und nach „×“ gesetzt; Schlüssel aus 6.3 unterdrückt beides; nicht bei Maus, nicht ab 1 024 px, nicht bei weniger Bewegung, nicht nach `mailhelp:stale`; Speicherfehler (`localStorage` wirft) zeigt die Zeile, ohne Fehler. Screenshots hell/dunkel während des Schwenks. |
| D7 | 6.9.7 | **Geräteabnahme und Dokumentation.** | Messprotokoll nach Abschnitt 7; Spezifikation, `docs/Bedienung.md`, Hilfeindex, `docs/archiv/Release-6.9.md`, README, CHANGELOG. |

In jedem Patch: 100 % Zeilen- und Branch-Abdeckung (Python) und 100 % JS-Blockabdeckung der
Browsersuite; volle Prüfung mit `python -m devtools.check full`; UI- und Python-Suite nicht
gleichzeitig. Versionsnummer, CHANGELOG und README je Commit.

---

## 7. Abnahmekriterien

**Automatisiert:** alle Tests aus Abschnitt 6 grün, Abdeckung vollständig.

**Am Gerät** (je ein iPhone mit Safari und als installierte Web-App, ein Android-Telefon mit Chrome;
Protokoll in `docs/archiv/Release-6.9.md`):

| Prüfung | Grenzwert |
| :--- | :--- |
| Zehn Karten schräg nach rechts oben (etwa 20–40°) wischen | 10 von 10 ausgelöst |
| Zehn Karten schräg nach links unten wischen | 10 von 10 ausgelöst |
| Griffpunkt bleibt sichtbar unter dem Daumen, auch über die Schwelle hinaus | Sichtprüfung bestanden |
| Zwanzigmal durch die Liste scrollen, auch mit leicht schrägem Daumen | keine Auslösung |
| Kurzer, schneller Wisch aus dem Handgelenk | 9 von 10 ausgelöst |
| Karte halb ziehen und loslassen | federt zurück, nichts gesendet |
| Wisch vom linken Rand | Zurück-Geste des Systems, keine Karte bewegt |
| Seite nach dem Wischen seitlich verschieben | nicht möglich |
| Gesperrte Karte | Gummiband, Ansage, nichts gesendet |
| Flugzeugmodus, dann wischen | Karte kommt mit Meldung zurück, nach Verbindung kein Doppel |
| Erste Karte zeigt Titel vor den Schaltflächen; die erste Entscheidung ist ohne Scrollen sichtbar | bestanden |
| Erstes Öffnen nach gelöschten Websitedaten | Karte schwenkt einmal, Zeile darunter, nichts gesendet |
| Ersten Wisch auslösen, Seite neu laden | kein Schwenk, keine Zeile mehr |
| „Weniger Bewegung“ im System eingeschaltet | kein Schwenk, nur die Zeile |

---

## 8. Risiken

| Risiko | Gegenmaßnahme |
| :--- | :--- |
| Mehr Fehlauslösungen durch Schwung (W5) | Untergrenze halbe Schwelle, Richtung muss zur Verschiebung passen; Geräteprüfung „Scrollen ohne Auslösung“. Notfalls W5 abschalten (eine Konstante). |
| Browser unterscheiden sich bei der `pan-y`-Grenze (W4) | Messung in D1 vor dem Umbau; liegt eine Grenze deutlich unter 45°, zusätzlich eine eigene Mindestneigung als Konstante. |
| Hohe Karten schwenken beim Drehen weit (W2); da U1 entfällt, bleiben Karten so hoch wie heute | Höchstwinkel sinkt mit der Kartenhöhe (`10° · min(1, 400 px / Höhe)`); Screenshot-Test mit einer Karte von voller Bildschirmhöhe. |
| Titel zuerst schiebt ohne U1 die Schaltflächen nach unten (U2) | Knapper Kopf nach U2; die 6.2.8-Prüfung auf 360 × 740 ist Abnahme. Scheitert sie, rückt nur die Zeile mit Absender und Datum unter die Schaltflächen. |
| Anstupsen wirkt wie ein Fehler oder stört beim Lesen (U6) | Nur einmal, erst nach Ruhe, nie während Scrollen oder Tippen, ohne Vibration und ohne Auslösung. |
| Ruckeln auf älteren Telefonen | Nur `transform`/`opacity`, ein Schreibvorgang pro Bild, keine Layoutabfragen während der Bewegung (Maße einmal beim Start). |
| Fliegende Karte verschwindet, Ergebnis bleibt unklar | Ergebnisstreifen mit Statusmeldung an derselben Stelle; Serverkarte ersetzt ihn wie bisher; Ansage für Bildschirmleser unverändert. |
| Ausgeblendete Karte stört Detailansicht oder Polling | Karte bleibt im DOM; Tests für geteilte Ansicht und für `pollCard()` mit ausgeblendeter Karte. |

---

## 9. Dokumentation

- `Mailhelp-Projektspezifikation.md`: Abschnitt Wischgeste (Bewegung, Schwung, Flug, Ergebnisstreifen,
  weniger Bewegung) und Kartenaufbau auf dem Telefon.
- `docs/Bedienung.md`: „Offen entscheiden – Wischen“ neu beschreiben; Hilfeindex neu erzeugen.
- `docs/archiv/Release-6.9.md`: Messung der Browsergrenze, Geräteprotokoll, Screenshots.
- README und CHANGELOG je Patch.
