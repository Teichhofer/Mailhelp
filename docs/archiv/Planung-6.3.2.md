# Mailhelp 6.3.2 – Fehlerbehebungen: Endlose Wiederaufnahme und Wischgeste auf echten Telefonen

**Zielversion:** 6.3.2 (Teil A und Teil B; bei getrennten Commits 6.3.2 und 6.3.3)

**Stand:** 14. November 2026 (um Teil B ergänzt)

**Status:** Umgesetzt und automatisiert geprüft. E1 und F1 bis F3 übernommen. Produktivserver auf 6.3.2 aktualisiert und Bestandsprüfung erfolgreich; Gerätetest durch den Betreiber steht aus. Ergebnisse im [Release-Nachtrag](Release-6.3.md).

**Ausgangsstand:** 6.3.1

**Grundlage:** [Entwicklungsregeln](../../AGENTS.md), [Projektspezifikation](../../Mailhelp-Projektspezifikation.md),
[Zustandsregeln 3.6](../Zustandsregeln-3.6.md)

Dieser Plan hat zwei unabhängige Teile. **Teil A** (Abschnitte 0 bis 6) behebt die endlose
Wiederaufnahme einer Mail. **Teil B** (Abschnitt 7) behebt, dass die Wischgeste aus 6.3.1 auf einem
echten Telefon nicht zuverlässig funktioniert.

---

# Teil A – Endlose Wiederaufnahme

## 0. Befund

Geprüft wurden die lokalen Protokolle vom 10. bis 13. November 2026 (rund 240 000 Zeilen), der
gespeicherte Zustand der betroffenen Mail und der Code von Wiederaufnahme, Pipeline und Aufbewahrung.

| Beobachtung | Nachweis |
| :--- | :--- |
| Eine Mail scheitert bei jedem Abrufzyklus: 3 468-mal `processing_failed` und ebenso oft `resume_failed` in knapp drei Tagen (etwa alle 70 Sekunden). | `logs/application.jsonl*` |
| Die Ausnahme ist immer dieselbe: `AssertionError` in `MailPipeline.advance`, Zeile `assert state.relevance is not None`. | `processing/mail_pipeline.py`, Zeile 130 |
| Der Zustand der Mail: `steps.relevance = "completed"`, aber `relevance = null`; `steps.completion = "completed"`, `steps.action_detection = "failed"`; gespeicherter Fehler vom 6. November. | `mail-….json` im Produktionsbestand |
| Im ganzen Bestand (1 922 Mails) ist es genau diese eine Mail. | Auszählung |

### Ursache

Zwei Regeln, die einzeln richtig sind, widersprechen sich:

1. **Die Wiederaufnahme** (`mailbox/mailbox_run.py`) nimmt nicht nur unfertige Mails erneut auf, sondern
   auch abgeschlossene mit `steps.action_detection == "failed"`, um die Aktionserkennung nachzuholen.
2. **Die Aufbewahrung** (`runtime/retention.py`) entfernt nach `debug_llm_days` das Relevanzergebnis
   (`state.relevance = None`), lässt aber `steps.relevance` auf `"completed"`.

Die Pipeline überspringt deshalb den Relevanzschritt (er gilt als erledigt) und stößt dann auf das
fehlende Ergebnis. Die Mail wird weder fertig noch je aufgegeben.

### Folgen

- Jeder Zyklus ruft die Mail per IMAP erneut ab und verbraucht ein Stück des Wiederaufnahme-Budgets.
- Die Protokolle füllen sich mit Stacktraces; zusammen mit den Routinemeldungen reichen sie nur
  noch rund drei Tage zurück (siehe [Planung 6.4](Planung-6.4.md)).
- Dieselbe Lage kann jede weitere Mail treffen, deren Aktionserkennung scheitert und die älter als
  `debug_llm_days` wird.

---

## 1. Ziele und Nichtziele

**Ziele**

1. Keine Mail wird endlos wiederholt, weil ein von der Aufbewahrung entferntes Ergebnis fehlt.
2. Die betroffene Mail im Bestand kommt ohne Handarbeit an der Zustandsdatei zur Ruhe.
3. Ein `assert` in der Pipeline ist nie die einzige Antwort auf einen Zustand, den das Programm
   selbst herstellen kann.

**Nichtziele**

- Kein allgemeiner Wiederholungsstopp und keine Anzeige wiederkehrender Fehler; das ist
  [Planung 6.4](Planung-6.4.md).
- Keine Änderung der Aufbewahrungsfristen.

---

## 2. Entscheidung

| ID | Frage | Vorschlag |
| :--- | :--- | :--- |
| **E1** | Was geschieht mit einer abgeschlossenen Mail, deren Aktionserkennung fehlschlug und deren Analyse-Daten die Aufbewahrung schon entfernt hat? | **Nicht mehr automatisch nachholen.** Die Mail bleibt abgeschlossen und im Mailarchiv unter „mit Fehler“ sichtbar; der Fehler nennt „Aktionserkennung nicht nachholbar – Analyse-Daten nach Aufbewahrung entfernt“. Wer sie doch auswerten will, nutzt eine bewusste Neuprüfung. **Alternative:** Relevanz neu berechnen und die Kette fortsetzen. Das kostet einen Modellaufruf für eine Mail, die älter als die Aufbewahrungsfrist ist, und kann ein anderes Ergebnis liefern als damals. |

---

## 3. Maßnahmen

### 3.1 Wiederaufnahme: nur nachholen, was nachholbar ist

- Die Auswahl in `mailbox_run.py` bekommt eine benannte Prüfung „nachholbar“: Eine abgeschlossene
  Mail mit fehlgeschlagener Aktionserkennung wird nur aufgenommen, wenn die Ergebnisse aller als
  erledigt markierten Vorschritte noch vorhanden sind (mindestens `relevance`; zu prüfen in der
  Umsetzung: `mail`, `summary`).
- Ist sie nicht nachholbar, schreibt die Wiederaufnahme **einmal** den Fehler aus E1 in den Zustand,
  setzt `steps.action_detection` auf einen Endzustand, der nicht mehr aufgenommen wird, und
  protokolliert ein Ereignis `resume_abandoned` mit Mail-ID und Grund.
- Ein zweiter Lauf ändert nichts mehr (idempotent, auch nach Neustart).

### 3.2 Pipeline: kein `assert` als Fehlerweg

- `advance` prüft nach dem Relevanzschritt ausdrücklich und meldet einen benannten, dauerhaften
  Fehler statt `AssertionError`, falls doch ein Zustand ohne Ergebnis ankommt. Die Sicherung in 3.1
  bleibt der eigentliche Weg; diese Prüfung ist der Auffang.

### 3.3 Aufbewahrung: Zustand bleibt stimmig

- Zu klären in der Umsetzung (zuerst mit Test): Reicht 3.1, oder soll die Aufbewahrung beim
  Entfernen zusätzlich festhalten, dass die Analyse-Daten entfernt wurden (zum Beispiel ein
  Zeitstempel im Zustand)? Vorschlag: Zeitstempel, weil dann jede spätere Stelle denselben einfachen
  Test nutzen kann und der Grund im Maildetail erklärbar ist.

### 3.4 Bestand

- Keine Migration: Der erste Lauf mit 6.3.2 bringt die betroffene Mail über 3.1 zur Ruhe.
- Das Release-Dokument hält fest, dass danach in den Protokollen kein `resume_failed` mit dieser
  Mail-ID mehr erscheint (Prüfung am echten Bestand durch den Betreiber).

---

## 4. Tests

| Test | Inhalt |
| :--- | :--- |
| **Regressionstest (Pflicht)** | Zustand genau wie im Bestand: `relevance` und `completion` erledigt, `action_detection` fehlgeschlagen, `relevance = None`. Vor dem Fix: `AssertionError` bei jeder Wiederaufnahme. Nach dem Fix: genau ein `resume_abandoned`, kein IMAP-Abruf, kein Modellaufruf. |
| Wiederholung | Zweiter und dritter Zyklus: kein Ereignis, kein Abruf, Zustand unverändert. |
| Neustart | Prozessneustart zwischen erstem und zweitem Zyklus: gleiches Ergebnis. |
| Nachholbar | Dieselbe Mail **mit** vorhandenem Relevanzergebnis wird wie bisher nachgeholt. |
| Aufbewahrung, dann Wiederaufnahme | Ende-zu-Ende: Aktionserkennung schlägt fehl, Aufbewahrung läuft, Wiederaufnahme läuft – kein Fehler, Mail unter „mit Fehler“ mit dem Text aus E1. |
| Auffang | `advance` mit erledigtem Relevanzschritt ohne Ergebnis: benannter Fehler, kein `AssertionError`. |
| Budget | Eine nicht nachholbare Mail verbraucht kein Wiederaufnahme-Budget. |

100 % Zeilen- und Branch-Abdeckung; simulierte Dienste und synthetische Daten.

---

## 5. Abnahme

- Der Regressionstest scheitert auf 6.3.1 und besteht auf 6.3.2.
- `python -m devtools.check full` ist grün.
- Am echten Bestand: nach dem Start höchstens ein `resume_abandoned`, danach kein `resume_failed`
  und kein `processing_failed` für die betroffene Mail.

## 6. Dokumentation

- `CHANGELOG.md`, `README.md` (Versionsstand), Projektspezifikation (Abschnitte Wiederaufnahme und
  Aufbewahrung: Regel „nachholbar“), `docs/Fehlerbehebung.md` (neuer Fehlertext und was er bedeutet).

---

# Teil B – Wischgeste auf echten Telefonen

## 7. Wischgeste: Befund, Ursachen und Behebung

### 7.0 Befund

Gemeldet: Das Wischen der Karten aus 6.3.1 funktioniert nicht. Die Browser-Suite von 6.3.1 ist
dagegen grün. Geprüft wurden deshalb die Stellen, an denen sich ein echtes Telefon von der
Emulation unterscheidet. Auf welchem Gerät und gegen welche Instanz der Fehler auftrat, ist nicht
bekannt; die Ursachen U1 und U2 wurden im Browser nachgestellt, U3 und U4 sind aus Code und
Dateiständen abgeleitet.

| ID | Ursache | Nachweis | Gewicht |
| :--- | :--- | :--- | :--- |
| **U1** | **Ein gerader Wisch mit etwas Höhenversatz wird verworfen.** `app.js` prüft zuerst „mehr als 8 px senkrecht“ und bricht ab, bevor es prüft, ob die Bewegung waagerecht überwiegt. Ein Telefon liefert die erste Bewegung erst nach der Toleranzschwelle des Browsers, also als einen großen Schritt. Ein Daumen zieht dabei immer einen leichten Bogen. | Nachgestellt (390 × 844): 200 px nach rechts mit 20 px Versatz in zwei Schritten – keine Geste. Dieselbe Strecke mit 30 px Versatz in 20 kleinen Schritten – Geste erkannt. Die Tests von 6.3.1 nutzten nur exakt waagerechte Bewegungen in kleinen Schritten. | Hauptursache |
| **U2** | **Auf 37 bis 49 % der Kartenfläche kann kein Wisch beginnen.** Ausgeschlossen sind alle Links, Schaltflächen und Zusammenfassungen – also der Titel (ein Link), die Zeile „Beschreibung und Beleg“ und die ganze Entscheidungsleiste. Genau dort liegt der Daumen meist. | Ausgemessen an den Vorschlagskarten des Testszenarios: Elternabend 37 %, Zahnarzt 43 %, Formular 46 %, Rechnung 48 %, Herbstfest 49 %. Wisch ab Titel, Zusammenfassung oder Schaltfläche: keine Geste. Die Tests von 6.3.1 setzten den Finger immer auf die Absenderzeile. | Hauptursache |
| **U3** | **Nach einem Update passen Stylesheet und Skript einmal nicht zusammen.** Der Service Worker liefert `app.css` aus seinem Zwischenspeicher, `app.js` kommt frisch vom Server. Beim ersten Seitenaufruf nach dem Update fehlt deshalb `touch-action: pan-y` (der Browser übernimmt die Berührung und bricht die Geste ab) und der Hintergrund hat keine Gestaltung. Erst ein weiterer Aufruf lädt beides passend. In einer installierten Web-App bleibt eine Seite lange offen. | Aus `static/sw.js` (`SHELL` enthält `/static/app.css`, zuerst aus dem Zwischenspeicher) und `web/pages.py` (feste Adressen ohne Versionsangabe). Nicht nachgestellt; die Browser-Suite blockiert Service Worker. | Wahrscheinlich, tritt je Update einmal auf |
| **U4** | **Die benutzte Instanz enthält 6.3.1 möglicherweise gar nicht.** 6.3.1 ist nicht committet und nicht auf GitHub. Der Dienst aus diesem Arbeitsverzeichnis schrieb zuletzt am 13. November um 14:15 Uhr, also vor der Umsetzung; am 14. November lief hier kein Dienst auf Port 8765. Der Server liest `app.js` und `app.css` außerdem nur beim Start. | `git status`, Zeitstempel in `data/production` und `logs`, `web/app.py` (`self.assets`) | Zuerst ausschließen |

### 7.1 Ziele und Nichtziele

**Ziele**

1. Ein natürlicher Daumenwisch – schnell, mit leichtem Bogen, von jeder Stelle der Karte außer
   Eingabefeldern – wird erkannt.
2. Die Schutzwirkung bleibt: Scrollen, Zoomen und Tippen lösen nichts aus; ausgelöst wird weiterhin
   nur durch Weg (40 % der Kartenbreite, höchstens 160 px).
3. Nach einem Update passen Stylesheet und Skript beim ersten Seitenaufruf zusammen.
4. Die Tests bilden ab, was ein Telefon wirklich liefert.

**Nichtziele**

- Keine Änderung an Richtungen, Schwelle, Hintergrund, Sperren und Tipp aus 6.3.1.
- Weiterhin kein Wischen mit der Maus und ab 1024 px.

### 7.2 Entscheidungen

| ID | Frage | Vorschlag |
| :--- | :--- | :--- |
| **F1** | Erkennen (U1) | Zuerst prüfen, ob waagerecht überwiegt: Geste ab 12 px waagerecht und `|dx| ≥ 1,5·|dy|` (bisher 2). Abbruch nur noch, wenn senkrecht überwiegt (`|dy| > 8 px` **und** `|dy| ≥ |dx|`). Dazwischen wartet die Geste auf die nächste Bewegung. Senkrechtes Scrollen übernimmt ohnehin der Browser (`touch-action: pan-y`) und meldet den Abbruch selbst. **Alternative:** Verhältnis 2 beibehalten und nur die Reihenfolge tauschen; dann scheitern Bögen über etwa 27°. |
| **F2** | Startfläche (U2) | Ein Wisch darf überall beginnen außer in `input`, `textarea` und `select` sowie in seitlich scrollendem Inhalt. Links, Schaltflächen und Zusammenfassungen sind erlaubt: Ein Tipp ohne Bewegung bleibt ein Tipp. Wurde eine Geste erkannt, wird der folgende Klick auf das Startelement unterdrückt. |
| **F3** | Zusammenpassende Dateien (U3) | `app.css` und `app.js` werden mit einem Inhaltskürzel eingebunden (`/static/app.css?v=…`). Die Seite kommt immer frisch vom Server und verweist damit stets auf den aktuellen Stand; der Service Worker findet dafür keinen alten Eintrag und lädt neu. Die Offline-Seite nutzt weiter den gespeicherten Stand. **Alternative:** Stylesheet im Service Worker zuerst vom Netz laden; das ändert das Offline-Verhalten und wird nicht empfohlen. |
| **F4** | Abnahme (U4 und allgemein) | Die Emulation hat U1 und U2 nicht gefunden. Teil B gilt erst als abgenommen, wenn der Betreiber die Geste auf einem echten Telefon gegen eine Instanz mit sichtbarer Versionsnummer 6.3.2 geprüft hat. Die Grundprüfung am Gerät wird damit aus [Planung 6.7](Planung-6.7.md) (P2) vorgezogen; dort bleibt die Feinabstimmung der Werte. |

### 7.3 Maßnahmen

**Vorab (U4), ohne Codeänderung**

- 6.3.1 committen und veröffentlichen; die genutzte Instanz aktualisieren und **neu starten**
  (statische Dateien werden nur beim Start gelesen).
- Auf dem Telefon die Statusseite öffnen und die Versionsnummer prüfen; die Seite einmal neu laden
  (wegen U3, solange F3 nicht ausgeliefert ist).
- Erst wenn das Wischen danach weiter scheitert, sind U1 bis U3 die Erklärung. Die Behebung von U1
  bis U3 erfolgt in jedem Fall, weil U1 und U2 nachweislich bestehen.

**Erkennen (U1, F1)** – `static/app.js`, Behandlung von `pointermove`

- Reihenfolge und Verhältnis nach F1; das Verhältnis wird Teil der Konstante `SWIPE`.
- Der Zustand „wartet“ endet wie bisher bei `pointerup`, `pointercancel` oder einem zweiten Finger.

**Startfläche (U2, F2)** – `static/app.js`, Behandlung von `pointerdown` und `click`

- Ausschlussliste auf `input, textarea, select` kürzen.
- Nach einer erkannten Geste wird genau der nächste `click` innerhalb der Karte abgefangen
  (Erfassungsphase, `preventDefault` und Stopp); ohne erkannte Geste nie.
- Links und Bilder in wischbaren Karten erhalten `-webkit-user-drag: none` und
  `-webkit-touch-callout: none`, damit der Browser beim Ziehen keine eigene Ziehvorschau beginnt
  (nur unter 1024 px).
- Eine laufende Texteingabe bleibt geschützt: Die Sperre bei ungesendetem Antworttext aus 6.3.1
  gilt weiter.

**Zusammenpassende Dateien (U3, F3)** – `web/app.py`, `web/pages.py`

- Zuerst ein Test, der U3 nachstellt (Service Worker erlaubt, alter Stand gespeichert, Server mit
  geändertem Stylesheet). Er entscheidet, ob U3 so besteht wie abgeleitet. Besteht er schon ohne
  Änderung, entfällt F3 und der Befund wird im Release-Dokument als widerlegt geführt.
- Sonst: Inhaltskürzel je Datei beim Start berechnen (die Dateien liegen dort bereits im Speicher)
  und in `layout` an die beiden Adressen anhängen. Der Server beantwortet die Adresse mit und ohne
  Kürzel.

**Tests an die Wirklichkeit anpassen**

- Der Touch-Helfer der Browser-Suite liefert die erste Bewegung als einen Schritt von mindestens
  15 px (wie ein Telefon nach der Toleranzschwelle) und unterstützt Höhenversatz und Bogen.
- Alle bestehenden Wischtests laufen zusätzlich mit 10 % Höhenversatz.

### 7.4 Tests

| Test | Inhalt |
| :--- | :--- |
| **Regression U1 (Pflicht)** | 200 px waagerecht mit 20 px und mit 40 px Versatz, je in zwei und in zwanzig Schritten: Geste erkannt, Loslassen jenseits der Schwelle sendet genau eine Anfrage. Scheitert auf 6.3.1. |
| **Regression U2 (Pflicht)** | Wisch ab Titel-Link, ab „Beschreibung und Beleg“ und ab einer Schaltfläche der Entscheidungsleiste: Geste erkannt; kein Seitenwechsel, kein Aufklappen, keine zweite Anfrage. Scheitert auf 6.3.1. |
| **Regression U3 (Pflicht, falls bestätigt)** | Service Worker mit altem Stand, danach Server mit neuem Stylesheet: Der erste Seitenaufruf lädt das neue Stylesheet; `touch-action` der Karte ist `pan-y pinch-zoom`. |
| Tippen bleibt Tippen | Tipp auf Titel öffnet die Detailseite, Tipp auf „Verwerfen“ verwirft, Tipp auf die Zusammenfassung klappt auf – jeweils ohne Bewegung und mit 5 px Zittern. |
| Schutz bleibt | Senkrechtes Scrollen mit 10 px Seitenversatz; Bewegung unter 45°; steile Diagonale: keine Geste, keine Anfrage. Start im Antwortfeld: keine Geste, Text und Cursor bleiben. |
| Klick-Unterdrückung | Nach erkannter Geste ab einem Link: kein Seitenwechsel, auch unterhalb der Schwelle; der nächste gewöhnliche Tipp funktioniert wieder. |
| Adressen mit Kürzel | Seite verweist auf beide Dateien mit Kürzel; geänderter Inhalt ändert das Kürzel; Adresse ohne Kürzel bleibt abrufbar; Offline-Seite unverändert. |

Der Test „kein Wisch ab Schaltfläche“ aus 6.3.1 wird bewusst umgekehrt (F2); die übrigen
Ausschlüsse (Rand, markierter Text, seitlich scrollender Inhalt, Maus, zweiter Finger) bleiben.
100 % Zeilen- und Branch-Abdeckung, 100 % JavaScript-Blockabdeckung.

### 7.5 Abnahme Teil B

- Die Regressionstests scheitern auf 6.3.1 und bestehen auf 6.3.2.
- Vollständige Browser-Suite grün, `python -m devtools.check full` grün.
- **Am Gerät (F4):** Statusseite zeigt 6.3.2. Zehn Karten nacheinander per Wisch entschieden, davon
  mindestens drei mit Start auf Titel oder Entscheidungsleiste; zwanzigmal durch die Liste
  gescrollt. Grenzwerte: keine Fehlauslösung, höchstens ein nicht erkannter Wisch. Gerät, Browser
  und Ergebnis stehen in `docs/archiv/Release-6.3.md`.

### 7.6 Risiken

| Risiko | Gegenmaßnahme |
| :--- | :--- |
| Die größere Startfläche und das lockerere Verhältnis führen zu versehentlichen Gesten. | Ausgelöst wird unverändert erst jenseits der Schwelle; der Hintergrund zeigt den Zustand; Zurückziehen bricht ab. Die Messung am Gerät zählt Fehlauslösungen. |
| Ein unterdrückter Klick verschluckt einen gewollten Tipp. | Unterdrückt wird nur nach erkannter Geste (mindestens 12 px Weg) und nur der unmittelbar folgende Klick. |
| Adressen mit Kürzel brechen Tests und Werkzeuge, die die festen Adressen erwarten. | Beide Adressen bleiben gültig; Tests auf die Seitenverweise werden angepasst. |
| Die eigentliche Ursache am Gerät ist eine andere als U1 bis U4. | Abnahme nur am Gerät (F4); scheitert sie, wird mit Fern-Debugging am Telefon weitergesucht, bevor weitere Änderungen folgen. |

### 7.7 Dokumentation Teil B

`CHANGELOG.md`, `README.md`, Projektspezifikation (Abschnitt „Wischen“: Erkennen nach F1, Startfläche
nach F2, Adressen mit Kürzel), `docs/Bedienung.md` („Wischen beginnt nicht in Eingabefeldern“ statt
„nicht auf Schaltflächen, Links und Eingabefeldern“; Hilfeindex neu erzeugen), `docs/Betrieb.md`
(nach einem Update neu starten), `docs/archiv/Release-6.3.md` (Nachtrag mit Ursachen U1 bis U4 und
Messprotokoll).
