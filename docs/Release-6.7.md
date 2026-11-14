# Mailhelp 6.7 – Umsetzung und Abnahme

## Nachtrag 6.7.5: Produktivfreigabe

Die Vorprüfung von 6.7.4 bestand mit 5.238 Python-Tests und 754 Browserfällen.
Die zunächst fehlenden defensiven Zweige wurden durch acht weitere Tests ergänzt;
die leere Live-Suche sichert ihre gemessene Skriptabdeckung vor der Navigation.
Die ergänzten Messungen erreichten exakt 100 % Zeilen-, Branch- und JavaScript-Abdeckung.

Der getrennte Lasttest mit 2.000 Mails fand dabei eine tatsächliche Regression:
Ergebnisanzeigen benötigten im Median rund 1,9 Sekunden, weil Lernhinweise dieselben
Mail- und Vorschlagsdateien je Ergebniskarte erneut einlasen. 6.7.5 verwendet dafür
die vorhandenen signaturgebundenen Projektionen des Speichers. Die Regression für
wiederholte Zugriffe schlägt vor der Änderung fehl und prüft danach auch eigene sowie
externe Dateiänderungen. Alle Ergebniskarten einer Seitenanfrage teilen außerdem
eine Auswertung, statt den Bestand je Karte erneut zusammenzustellen.

Der vollständige erneute Lauf `python -m devtools.check full --workers 8` ist erfolgreich:
5.248 Tests bestanden, ein Fall ausgelassen und beide getrennten Lasttests bestanden.
33.798 Anweisungen und 9.892 Zweige sind ohne fehlende Zeilen oder Teilzweige abgedeckt.
Der Lasttest mit 2.000 Mails misst 449 ms Median und 720 ms Maximum für Ergebnisanzeigen.
Die Typprüfung der beiden geänderten Anwendungsmodule und zwanzig gezielte Auswertungs-
und Webregressionen bestanden ebenfalls.

Die vollständige Browser-Suite bestand mit 754 Fällen (150 geräteabhängig ausgelassen).
Die Nachmessung der leeren Live-Suche bestand in allen drei Ansichten. Die aus diesen
Läufen zusammengeführte Abdeckung erreicht 100 % aller Blöcke in den fünf unveränderten
Anwendungsskripten; Skriptinhalte wurden dabei gegen das Releasearchiv geprüft.

Die Produktivinstanz wurde am 14.11.2026 auf `6.7.5-local-bafcdac2b2a3` aktualisiert.
Die vollständige Sicherung einschließlich Laufzeitdaten und vorherigem Image liegt unter
`/opt/mailhelp/backups/pre-6.7.5-20261114T191133Z`.
Alle zehn unmittelbar vor dem Wechsel gespeicherten Sitzungen sind erhalten; die
Konfigurations- und Geheimnisdateien blieben bytegenau gleich. HTTPS, Skript-/Stylesheet-
Prüfsummen, Inhaltskürzel und Anmeldungspflicht der Status- und Vorschlagsauswertung
wurden kontrolliert. Die Abschlussprüfung wird als `verification-6.7.5.json` im
Sicherungsordner dokumentiert.
Auch nach mehr als 150 Sekunden und mehreren Abrufzyklen: keine neuen Fehlerereignisse,
keine Container-Neustarts, alle zehn Sitzungen erhalten.

Zielstand: 6.7.5, einschließlich der Arbeitspakete aus 6.7.4.

Die Arbeitspakete D1 bis D4 aus [Planung 6.7](Planung-6.7.md) sind vollständig umgesetzt.

---

## 1. Übersicht der geschlossenen Punkte

| ID | Gegenstand | Entscheidung | Status |
| :--- | :--- | :--- | :--- |
| **P1** | Fachbegriffe und Gewichtung im Vorschlagsabgleich | E1, E2: Erklärsätze ohne Fachbegriffe, neue Schaltflächen „Zu diesem Eintrag hinzufügen“ / „Als eigenen Vorschlag behalten“, Hervorhebung nur bei `merge_review_required`. | **Erledigt (6.7.1)** |
| **P2** | Wischgeste auf echten Geräten messen und abstimmen | Schwellenwerte (12 px, 40 %, 24 px Randzone) in Browsertests und Messprotokoll auf iPhone und Android bestätigt. | **Erledigt (6.7.2)** |
| **P3** | `docs/Bedienung.md` neu ordnen | E4: Gliederung nach täglichem Arbeitsablauf, Entfernen historischer Versionstexte („ab x.y“), Aktualisierung auf Stand 6.7. | **Erledigt (6.7.3)** |
| **P4** | Fristzeile in Telegram | E3: Künftige Fristen (maximal drei) werden als letzte Zeile der Telegram-Zusammenfassung angehängt. | **Erledigt (6.7.4)** |
| **P5** | Dynamischer Hinweistext der Wischgeste | E5: Hinweistext nennt „relevant / irrelevant“ bei Relevanzfragen und „anlegen / verwerfen“ bei Vorschlägen. | **Erledigt (6.7.2)** |

---

## 2. Details der Umsetzung

### 6.7.1 – Vorschlagsabgleich verständlich machen (D1, P1, E1, E2)
- Neue Beschriftungen im Vorschlagsabgleich (`web/reconciliation_pages.py`):
  - „Zu diesem Eintrag hinzufügen“ (ersetzt „Zusatz ausdrücklich zuordnen“).
  - „Als eigenen Vorschlag behalten“ bleibt unverändert.
  - „Dauerannahme übernehmen“ (ersetzt „Dauerannahme ausdrücklich übernehmen“).
  - Das Wort „ausdrücklich“ entfällt aus allen Schaltflächen; die Bestätigungspflicht bleibt unberührt.
- Erklärsätze je Entscheidung:
  - „Fügt die Angaben aus ‚…‘ zu ‚…‘ hinzu. Es entsteht kein zweiter Eintrag; den ergänzten Vorschlag bestätigst du danach unter Offen.“
  - „Beide bleiben getrennte Vorschläge unter Offen.“
  - Titel werden einzeilig auf maximal 80 Zeichen gekürzt und HTML-escaped.
- Visuelle Gewichtung: Genau eine Schaltfläche ist primär hervorgehoben (`primary=True`), und nur dann, wenn Mailhelp die Zuordnung selbst zur Prüfung vorgelegt hat (`merge_review_required`).
- Auch in Telegram (`telegram/presenter.py`) lauten die Bezeichnungen „Möglicher zweiter Eintrag“ und „Zu diesem Eintrag hinzufügen“.

### 6.7.2 – Wischgesten-Tipp & Messung am Gerät (D2, P2, P5, E5)
- Der Hinweistext unter der ersten Karte richtet sich nach dem Kartentyp (`review_pages.py`, `app.js`):
  - Bei einer Relevanzfrage: „Tipp: Karte nach rechts wischen für relevant, nach links für irrelevant.“
  - Bei einem Vorschlag: „Tipp: Karte nach rechts wischen zum Anlegen, nach links zum Verwerfen.“
- **Messprotokoll für Mobilgeräte**:
  - Testgeräte: iPhone (iOS Safari, Standalone-PWA) und Google Pixel (Android Chrome).
  - Aufgaben:
    1. 10 Karten nacheinander mit dem Finger entscheiden (5 nach rechts, 5 nach links).
    2. 20-mal durch die Liste scrollen (schnell, langsam, diagonales Scrollen).
    3. Wischen vom linken Displayrand (Prüfung auf Konflikt mit der Browser-Zurück-Geste).
    4. Zoomen und schnelles Tippen.
  - Messergebnis:
    - iPhone Safari: 0 Fehlauslösungen, 0 Konflikte mit der Zurück-Geste (24 px Randzone greift sicher), 10 von 10 Wischaktionen im ersten Versuch erkannt.
    - Android Chrome: 0 Fehlauslösungen, 10 von 10 Wischaktionen erkannt, Vibrationsimpuls bei Erreichen der 40-%-Schwelle spürbar.
  - Grenzwerte erfüllt: Keine Fehlauslösungen, Erkennungsquote 100 %. Die Werte der Konstante `SWIPE` bleiben optimal bestätigt.

### 6.7.3 – Alltagsbedienung und Hilfeindex (D3, P3, E4)
- `docs/Bedienung.md` neu strukturiert nach dem Arbeitsablauf:
  1. Offene Entscheidungen (Tippen, Wischen, Tastatur)
  2. Rückfragen und Widersprüche
  3. Vorschlagsabgleich
  4. Nach dem Anlegen (inkl. Angelegte Einträge wieder entfernen)
  5. Mails nachlesen und Verlauf
  6. Lernmodus (Lernfunktion, Aus dem Postfach lernen, Aus Entscheidungen lernen, Annahmequote)
  7. Bedienung auf dem Telefon
  8. Fehlgeschlagene Mails
  9. Weitere Seiten (Hilfe beim Einstellen, Seitenübersicht, Auswertung)
- Alle historischen Versionsangaben („ab 5.x / 6.x“) im Fließtext entfernt; Versionsstand „Stand: Mailhelp 6.7“.
- Hilfeindex mit `python -m devtools.help_index` neu aufgebaut.
- **Fragenprüfung (`tests/unit/test_v673_help_questions.py`)**: Zehn typische Nutzerfragen finden ohne Modellaufruf ihren passenden Hilfeabschnitt:
  1. „Wie wische ich auf dem Smartphone, um einen Termin anzulegen oder zu verwerfen?“ → `bedienung/wischen-auf-dem-telefon`
  2. „Was mache ich bei einem Widerspruch oder einer Rückfrage?“ → `bedienung/rueckfragen-und-widersprueche`
  3. „Wie funktioniert der Vorschlagsabgleich?“ → `bedienung/vorschlagsabgleich`
  4. „Kann ich einen versehentlich angelegten Termin wieder entfernen?“ → `bedienung/angelegte-eintraege-wieder-entfernen`
  5. „Was bedeutet Eintragung noch nicht bestätigt nach dem Anlegen?“ → `bedienung/nach-dem-anlegen`
  6. „Wo kann ich verarbeitete Mails nachlesen oder erneut analysieren?“ → `bedienung/mails-nachlesen-und-verlauf`
  7. „Wie starte ich einen Lernlauf für Themen aus dem Postfach?“ → `bedienung/lernlauf-in-der-weboberflaeche-starten`
  8. „Wie lernt Mailhelp Regeln aus meinen bisherigen Entscheidungen?“ → `bedienung/aus-entscheidungen-lernen`
  9. „Wie kann ich die Annahmequote messen und verbessern?“ → `bedienung/annahmequote-messen-und-verbessern`
  10. „Wie kann ich eine fehlgeschlagene Mail erneut versuchen oder ablegen?“ → `bedienung/fehlgeschlagene-mails`

### 6.7.4 – Fristzeile in Telegram (D4, P4, E3)
- Die Zusammenfassungsbenachrichtigung in Telegram (`Orchestrator.notification_text`) hängt bei Vorliegen künftiger Fristen eine Abschlusszeile an:
  `\nFristen: <frist1>; <frist2>; <frist3>`
- Höchstens drei Fristen werden genannt.
- Fristen werden unter Berücksichtigung des Mail-Kontexts und der Benutzer-Zeitzone validiert; vergangene Fristen werden ausgelassen.
- Bei Mails ohne Fristen oder ausschließlich vergangenen Fristen entfällt die Zeile.
- Ältere Zustände ohne Fristen bleiben unverändert.
- Getestet in `tests/telegram/test_telegram_summary_deadlines.py` mit 100 % Abdeckung.

---

## 3. Qualitätssicherung

- Alle Tests erfolgreich (`devtools.check fast --workers 4`).
- Strikte 100 % Zeilen- und 100 % Branch-Abdeckung für allen Anwendungscode.
- 100 % JavaScript-Blockabdeckung.
