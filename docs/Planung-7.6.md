# Mailhelp 7.6 – Klärungsfreie Demo-Vorschläge und Flow-Optimierung

**Zielversion:** 7.6, Umsetzung in Patchversionen ab 7.6.1  
**Stand:** 16. November 2026  
**Status:** Geplant; noch nicht implementiert.  
**Ausgangsstand:** Nach Umsetzung von 7.1 (Demo-Modus) und den Folgeversionen.  
**Grundlage:** [Entwicklungsregeln](../AGENTS.md), [Projektspezifikation](../Mailhelp-Projektspezifikation.md), [Planung 7.1](Planung-7.1.md).

---

## 1. Ziel und Anlass

Mit Mailhelp 7.1 wurde der eigenständige Demo-Modus (`mailhelp --demo`) eingeführt.
Der Beispielsatz aus 7.1.2 enthält derzeit 11 Vorschläge, von denen jedoch **7 Vorschläge
den Status `needs_clarification` oder `merged` mit offenen Rückfragen** aufweisen
(z. B. fehlende Uhrzeit, unklare persönliche Zuständigkeit oder Zuordnungsfragen).

### Das Problem für Demo-Besucher:
Wenn ein Interessent oder Erstnutzer die Demo startet, soll er ein intuitives
Gefühl dafür bekommen, **wie extrem schnell, flüssig und leicht** die Bedienung
von Mailhelp ist:
* Karte nach rechts wischen (oder Taste `1`): Sofort annehmen.
* Karte nach links wischen (oder Taste `2`): Sofort verwerfen.
* Undo-Möglichkeit bei Fehlklick.
* Reibungsloser Flow: Ein Stapel von Vorschlägen ist in unter einer Minute entschieden.

Aktuell wird dieser Geschwindigkeits- und Flow-Eindruck jäh unterbrochen:
Statt schnellem Entscheiden öffnet sich bereits bei der zweiten Karte ein Klärungsdialog
(*„Welcher bestehende Eintrag soll geändert werden?“*, *„Wann beginnt der Termin?“*,
*„Ist die Nutzerin oder der Nutzer zuständig?“*). Der Betrachter empfindet das System
als zögerlich und dialoglastig, anstatt die Effizienz der Kernbedienung zu erleben.

### Ziel von Version 7.6:
1. **100 % bestätigungsbereite Demo-Vorschläge:**  
   Alle im Demo-Modus generierten Aufgaben und Termine sind **vollständig geklärt**
   (`status: pending_confirmation`, `open_questions: []`).
2. **Keine offenen Fragen oder Klärungsbremsen:**  
   Keine Rückfragen bezüglich Uhrzeit, Datum oder Zuständigkeit. Jede Karte kann
   unmittelbar mit einer einzigen Geste oder einem Tastendruck entschieden werden.
3. **Echter Pipeline-Nachweis bleibt erhalten:**  
   Die Daten werden nicht künstlich von Hand „zurechtgebogen“, sondern entstehen
   weiterhin über den echten Mailhelp-Verarbeitungspfad (`devtools.demo.dataset`).
   Die synthetischen Eingangs-Mails in `devtools/demo/mails.py` werden so formuliert,
   dass sie alltagsnahe, aber in sich präzise und vollständige Nachrichten darstellen.
4. **Flow-Optimierung:**  
   Prominente Desktop-Tastaturhinweise (`[1] Annehmen  [2] Verwerfen  [Z] Rückgängig`),
   flüssige Wisch-Animationen (< 50 ms Latenz) und eine motivierende Abschlusskarte
   (*„Alles erledigt! 🎉 Alle Vorschläge in Rekordzeit verarbeitet.“*).

---

## 2. Analyse des Ist-Zustands im Demo-Bestand

Eine Inspektion der aktuellen Demo-Vorschläge in `src/mailhelp/defaults/demo/standard-v1/state/` zeigt:

| Vorschlags-ID | Typ | Titel | Aktueller Status | Offene Fragen |
| :--- | :--- | :--- | :--- | :--- |
| `p_c4cccbc381d6` | Termin | Elternabend der Klasse 4b | `pending_confirmation` | keine (bereits optimal) |
| `p_ec41035e8e84` | Termin | Elternabend Klasse 4b (Verlegung) | `needs_clarification` | *Welcher bestehende Eintrag soll geändert werden?* |
| `p_c4d92d28e945` | Termin | Adventsbasar | `pending_confirmation` | keine (bereits optimal) |
| `p_e07cbc1ff923` | Aufgabe | Kuchenspende anmelden | `needs_clarification` | *Zuständigkeit unklar, unverbindlicher Hinweis* |
| `p_ef1a5cfa5c2e` | Termin | Vorspielnachmittag Geigenklasse | `needs_clarification` | *Wann beginnt der Termin?* |
| `p_7b829eb5ac13` | Aufgabe | Einverständniserklärung Planetarium | `needs_clarification` | *Information sicher belegt?* |
| `p_8716aa81279d` | Termin | Ausflug ins Planetarium | `merged` | *Wann beginnt der Termin? Zuständigkeit unklar.* |
| `p_2a6ade23d43e` | Aufgabe | Bastelkleber und Fotokarton besorgen | `pending_confirmation` | keine (bereits optimal) |
| `p_dc79805a03dd` | Termin | Bastel-Workshop Jugendabteilung | `needs_clarification` | *Wann beginnt der Termin? Wann endet er?* |
| `p_b9e428b08085` | Termin | Ausflug ins Planetarium | `needs_clarification` | *Uhrzeiten und Zuständigkeit unklar* |
| `p_d12ad8fba315` | Aufgabe | Einverständniserklärung zurückgeben | `pending_confirmation` | keine (bereits optimal) |

**Ergebnis:** Nur 4 von 11 Vorschlägen sind aktuell direkt bestätigbar. Über 60 %
erfordern langwierige Klärungen.

---

## 3. Fachliches Soll-Konzept

### 3.1 Neugestaltung der synthetischen Originalmails (`devtools/demo/mails.py`)
Die synthetischen E-Mails werden so überarbeitet, dass sie alle erforderlichen
Details präzise enthalten, wie es bei gut organisierten Einladungen und Arbeitsaufträgen
im Geschäfts- und Schulalltag der Fall ist:

1. **Mail 1 – Elternabend:**  
   *Bleibt erhalten:* Vollständiger Termin mit Datum, Uhrzeit (19:30–21:00 Uhr) und Raum.
2. **Mail 2 – Schulausflug Planetarium:**  
   *Neu formuliert:* Klare Zuweisung an die nutzende Person (*„Liebe Alex, du bist als Begleitperson eingeteilt. Bitte sei am Freitag, 27.11.2026 von 08:30 bis 13:00 Uhr dabei. Das unterschriebene Formular bitte bis 20.11. abgeben.“*).  
   → Ergibt 1 klaren Termin (Begleitung) und 1 klare Aufgabe mit Frist (Formular).
3. **Mail 3 – Workshop-Material:**  
   *Neu formuliert:* Präzise Frist (*„Bitte besorge das Fotopapier bis spätestens Samstag, 21.11.2026.“*).
4. **Mail 4 – Adventsbasar & Kuchenspende:**  
   *Neu formuliert:* Klare persönliche Bitte (*„Liebe Alex, wir freuen uns auf deinen Schokokuchen für den Basar am 04.12.“*).  
   → Ergibt 1 klaren Termin und 1 klare Aufgabe ohne Zuständigkeitszweifel.
5. **Mail 5 – Terminverschiebung:**  
   *Neu formuliert:* Statt Verweis auf einen unauffindbaren Kalendereintrag wird der Termin als in sich geschlossene neue Bestätigung mit klarer Zeitspanne formuliert.
6. **Mail 6 – Konzert / Aufführung (Vorspielnachmittag):**  
   *Neu formuliert:* Exakte Zeitangabe (*„Das Vorspiel findet am Mittwoch, 09.12.2026 von 16:00 bis 17:30 Uhr im Musiksaal statt.“*).  
   → Ergibt 1 klaren Termin ohne fehlende Beginnzeit.
7. **Mail 7 – Jugend-Workshop:**  
   *Neu formuliert:* Feste Workshop-Zeiten (*„Samstag, 05.12.2026 von 10:00 bis 12:30 Uhr“*).
8. **Mails 8 bis 10 – Relevante Mails zur Kenntnisnahme:**  
   Klare Einordnung als relevant, ohne unnötige Pseudo-Aufgaben zu provozieren.
9. **Mails 11 bis 30 – 20 irrelevante Mails:**  
   Verbleiben als Hintergrundbestand; sie demonstrieren weiterhin das geräuschlose Aussortieren von Newslettern und Spam.

### 3.2 Das Demo-Erlebnis auf `/offen`
* Beim Klick auf **„Demo starten“** landet der Nutzer unmittelbar auf `/offen`.
* Dort liegt ein sauberer Stapel von ca. **6 bis 8 perfekten Vorschlagskarten**
  (Termine und Aufgaben).
* **Jede Karte ist sofort entscheidbar:**
  * Grüner Button: *„Im Kalender anlegen“* bzw. *„Als Aufgabe anlegen“* (simuliert).
  * Roter Button: *„Verwerfen“*.
  * Wischgeste links/rechts auf Mobilgeräten.
  * Tasten `1` (Annehmen) und `2` (Verwerfen) auf dem Desktop.
* **Keine Unterbrechungen:** Der Anwender kann alle Karten in 20–30 Sekunden
  unterbrechungsfrei „wegswipen“.
* **Abschluss-Zustand („Inbox Zero“):**
  Sobald die letzte Karte entschieden ist, erscheint die gestaltete Leeransicht:
  * *„Alles erledigt! 🎉“*
  * *„Du hast alle 8 Vorschläge in Rekordzeit verarbeitet. Die Termine und Aufgaben wurden in der Demo simuliert angelegt.“*
  * Schaltfläche: *„Demo zurücksetzen und nochmals testen“*.

---

## 4. Technische Umsetzung

### 4.1 Anpassung des Erzeugungswerkzeugs
* `devtools/demo/mails.py` wird mit den geschärften Mail-Texten aktualisiert.
* Der Erzeugungslauf wird ausgeführt:
  ```powershell
  python -m devtools.demo.dataset --env .env
  ```
* Das Werkzeug erzeugt die 30 synthetischen Originalmails, jagt sie durch die echte
  Mailhelp-Pipeline (Aufbereitung, Relevanz, Router, Extraktion, Normalisierung)
  und schreibt den Export nach `src/mailhelp/defaults/demo/standard-v1/`.

### 4.2 Automatisierte Qualitätsgarantie
Ein dedizierter Test `tests/release/test_demo_flow.py` prüft den generierten Demo-Bestand:
```python
def test_all_demo_proposals_are_confirmation_ready():
    manifest, proposals = load_demo_dataset()
    assert len(proposals) >= 6, "Zu wenige Vorschläge im Demo-Datensatz"
    for proposal in proposals:
        assert proposal.status == "pending_confirmation", (
            f"Vorschlag {proposal.id} ({proposal.title}) ist nicht bestätigungsbereit: {proposal.status}"
        )
        assert proposal.open_questions == [], (
            f"Vorschlag {proposal.id} ({proposal.title}) hat offene Fragen: {proposal.open_questions}"
        )
```
Damit wird automatisiert verhindert, dass künftige Pipeline-Änderungen versehentlich
wieder unklare Vorschläge in den Demo-Bestand einbringen.

### 4.3 UI- und Performance-Optimierung
* In `src/mailhelp/web/static/open-list.js`:
  * Beschleunigung der Karten-Übergangsanimation bei schnellen aufeinanderfolgenden
    Tastendrücken (Keydown-Debounce optimiert).
  * Sichtbarer, dezenter Tasten-Hinweis im Demo-Modus:  
    `<p class="demo-flow-hint">Tipp: Mit den Tasten <strong>1</strong> (Annehmen) und <strong>2</strong> (Verwerfen) rasend schnell entscheiden.</p>`

---

## 5. Umsetzungsschritte (Patch-Plan 7.6.1 bis 7.6.4)

| Schritt | Patch | Inhalt |
| :--- | :--- | :--- |
| **Q1** | 7.6.1 | **Überarbeitung der Demo-Mails:** `devtools/demo/mails.py` mit klaren, vollständigen Angaben (Zeiten, Fristen, direkte Ansprache) ausstatten. Syntax- und Textprüfung. |
| **Q2** | 7.6.2 | **Pipeline-Erzeugungslauf & Manifest:** Datensatz über `devtools.demo.dataset` neu generieren. Manifest und Prüfsummen in `standard-v1` aktualisieren. |
| **Q3** | 7.6.3 | **Automatisierte Flow-Prüfung:** `test_demo_flow.py` erstellen; Prüfung auf `pending_confirmation` und `open_questions == []` für alle Demo-Vorschläge. |
| **Q4** | 7.6.4 | **UI-Flow-Hinweise & Gesamtabnahme:** Tastatur-Hinweise in der Weboberfläche, Playwright-Browser-Test für den unterbrechungsfreien Schnelldurchlauf (Inbox Zero in < 30s), 100 % Coverage, Dokumentation. |

---

## 6. Tests und Abnahmekriterien

1. **Keine offenen Fragen:**
   * Jeder einzelne Vorschlag im mitgelieferten Demo-Datensatz besitzt `open_questions: []`
     und `status: "pending_confirmation"`.
   * Kein Vorschlag steht auf `needs_clarification`.
2. **Reibungsloser Bedien-Flow:**
   * Im Browser (Desktop und Mobil) lässt sich der gesamte Vorschlagsstapel per Taste `1`/`2`
     bzw. Swipe von rechts nach links ohne Unterbrechung durch Popups oder Fehlermeldungen
     durcharbeiten.
   * Reaktionszeit je Aktion unter 50 Millisekunden.
3. **Erfolgs-Zustand:**
   * Nach Abarbeitung aller Karten wird die Abschlussseite mit der Reset-Schaltfläche
     angezeigt.
4. **Qualitätsvorgaben gemäß AGENTS.md:**
   * 100 % Zeilen- und Branch-Abdeckung für allen geänderten Code.
   * `python -m devtools.check full --workers 12` und Browsertests bestehen ohne Fehler.
   * Dokumentation in Projektspezifikation, README und Release-Bericht aktualisiert.
