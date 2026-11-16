# Release 6.3 – Umsetzung und Abnahme

## Nachtrag 6.3.2

Die Umsetzung folgt [Planung 6.3.2](Planung-6.3.2.md). E1 und F1 bis F3 sind übernommen.
Die automatisierte Schlussprüfung und die Bestandsprüfung auf dem Produktivserver sind erfolgreich.
Die Abnahme am echten Telefon (F4) steht aus.

### Wiederaufnahme nach Aufbewahrung

Eine abgeschlossene Mail mit fehlgeschlagener Aktionserkennung wird vor Abruf und
Budgetverbrauch auf fehlende Ergebnisse erledigter Vorbereitung, Relevanzprüfung und
Zusammenfassung geprüft. Fehlen Ergebnisse, wird die Aktionserkennung einmalig beendet.
`analysis_data_removed` hält den dauerhaften Fehler und seinen Zeitpunkt fest,
`resume_abandoned` nennt Mail-ID und fehlende Schritte. Wiederholungen und Neustarts ändern
den Zustand anschließend nicht mehr. Die Pipeline meldet fehlende Ergebnisse ausdrücklich.

Ein zusätzlicher Entfernungszeitstempel entfällt. Die Prüfung erkennt auch bereits bereinigte
Altzustände. Der neue Fehlercode ergänzt das bestehende Format, alle bisherigen Fehlercodes
bleiben lesbar. Der MailState-Schema-Snapshot ist entsprechend aktualisiert.
Ältere Programmversionen kennen den neuen Fehlercode noch nicht. Vor einem Rückwechsel muss
dieser Code im aktuellen Zustand kompatibel umgewandelt werden.

Die Regressionen stellten auf 6.3.1 wiederholte Abrufe und den `AssertionError` nach.
Geprüft werden Aufbewahrung vor Wiederaufnahme, Wiederholungen, Neustart, fehlende weitere
Vorschritte, nachholbare Mails, Budget und Sichtbarkeit des Fehlers im Status.

### Wischen und Dateien nach Updates

| Befund | Ergebnis und Korrektur |
| --- | --- |
| U1 | Reproduziert mit 200 px waagerecht und 20 bzw. 40 px Höhenversatz in zwei Schritten. Die Erkennung prüft zuerst die waagerechte Dominanz und verwendet das Verhältnis 1,5. |
| U2 | Reproduziert ab Titel-Link, Zusammenfassung und Entscheidungsschaltfläche. Diese Elemente erlauben jetzt den Beginn einer Geste. Nach erkannter Bewegung wird der folgende Touch-Klick abgefangen. |
| U3 | Mit zugelassenem Service Worker reproduziert. Ein alter Controller lieferte beim ersten Aufruf das alte Stylesheet. Inhaltskürzel für Stylesheet und Skript beheben den Fall. Die Offline-Seite nutzt weiterhin ihren gespeicherten Stand. |
| U4 | Die Produktivinstanz wurde am 14.11.2026 auf den lokalen Stand `6.3.1-local-30575275bbf5` aktualisiert. Version und ausgelieferte Skript-/Stylesheet-Dateien wurden überprüft. |

Der Touch-Helfer liefert eine erste Bewegung von mindestens 15 px, sofern der ganze Weg
größer ist. Alle bisherigen Telefonfälle laufen auch mit 10 % Höhenversatz.
Zusätzliche Fälle prüfen zwei und zwanzig Schritte, Tippen mit 5 px Zittern, Startflächen,
Klick-Unterdrückung, den nächsten Tipp, Tastaturaktivierung, Scrollen und mehrdeutige Bewegungen.
Die Abdeckungsmessung erkennt auch Skriptadressen mit Inhaltskürzel.

### Prüfergebnisse 6.3.2

- `python -m devtools.check full --workers 4` ist erfolgreich. 5.124 Tests bestanden,
  ein Fall wurde ausgelassen. Die beiden getrennt ausgeführten Lasttests
  bestanden ebenfalls. Zeilen- und Branch-Abdeckung betragen jeweils exakt 100 %.
- Die vollständige Browser-Suite mit drei Workern besteht mit 751 erfolgreichen Fällen.
  150 Fälle wurden entsprechend ihrer Geräteauswahl ausgelassen. Alle Blöcke in `app.js`,
  `sw.js`, `setup.js`, `topics.js` und `learning.js` sind abgedeckt.
- Der Folgetipp wurde zusätzlich sechzehnmal geprüft. Der Touch-Helfer trennt den gewöhnlichen
  nächsten Tipp um 600 ms von der vorherigen Geste, damit Chrome ihn als eigene Aktivierung
  verarbeitet. Die Anwendung fängt den verspäteten Klick der vorherigen Geste unmittelbar ab.
- Die Einrichtungsprüfung wertet die vollständige Skriptabdeckung zentral nach dem Zusammenführen
  aller Worker-Daten aus. Die frühere Prüfung innerhalb eines einzelnen Microsoft-Testfalls hing
  von der Verteilung anderer Einrichtungstests auf denselben Worker ab.
- Ruff, Mypy, Schema-Snapshots und der erzeugte Hilfeindex sind geprüft.

### Produktivprüfung und ausstehende Geräte-Abnahme

Die lesende Vorprüfung des Produktivbestands am 14.11.2026 unter 6.3.1 fand genau eine
abgeschlossene Mail mit fehlgeschlagener Aktionserkennung. Ihr fehlen die als erledigt
markierten Relevanz- und Zusammenfassungsergebnisse. Sie erfüllt die neue Abbruchregel.

Die Produktivinstanz wurde anschließend auf `6.3.2-local-cb4b681c02b8` aktualisiert.
Eine vollständige Sicherung liegt unter
`/opt/mailhelp/backups/pre-6.3.2-20261114T131905Z`; das vorherige Image bleibt erhalten.
Alle zehn unmittelbar vor dem Wechsel gespeicherten Web-Sitzungen sind erhalten,
Konfiguration und Geheimnisdateien stimmen bytegenau mit dem gesicherten Stand überein.
HTTPS, Anmeldung und die ausgelieferten Skript-/Stylesheet-Dateien einschließlich ihrer
Inhaltskürzel wurden geprüft. Die betroffene Mail hat jetzt dauerhaft
`action_detection=skipped` und `analysis_data_removed` mit `retryable=false`.
Genau ein `resume_abandoned` wurde protokolliert. Über mehr als 150 Sekunden und mehrere
Verarbeitungszyklen blieben Wiederholungsfehler, neue Fehlerereignisse und Container-Neustarts
aus. Die Abschlussprüfung ist zusätzlich als `verification-6.3.2.json` im Sicherungsordner dokumentiert.

Am echten Telefon muss die Statusseite 6.3.2 anzeigen. Zehn Karten nacheinander per Wisch
entscheiden, davon mindestens drei ab Titel oder Entscheidungsleiste. Zwanzigmal durch die
Liste scrollen. Zulässig sind keine Fehlauslösung und höchstens ein nicht erkannter Wisch.
Gerät, Browser und Messwerte sind anschließend hier einzutragen.

Am echten Bestand ist nach Installation höchstens ein `resume_abandoned` für die betroffene
Mail zu erwarten, danach kein `resume_failed` oder `processing_failed` für diese Mail.

---

## Ausgangsrelease 6.3.1

Status: Version 6.3 mit 6.3.1 umgesetzt und unter Windows 11 mit simulierten Diensten geprüft,
14. November 2026. Plan: [Planung 6.3](Planung-6.3.md). Die Entscheidungen E1 bis E8 wurden mit dem
jeweiligen Vorschlag übernommen; für E2/E3 also: Der Wisch sendet direkt, ausgelöst nur durch Weg.

## Zuordnung der Planschritte

Der Plan sah fünf Patchversionen vor. Weil D1 bis D4 dieselben drei Dateien (`actions.py`,
`app.css`, `app.js`) betreffen und die JavaScript-Abdeckung erst mit der fertigen Geste vollständig
prüfbar ist, wurden alle Schritte in einer Version zusammengefasst.

| Planschritt | Inhalt | Version |
| :--- | :--- | :--- |
| D1 | Hintergrund mit den Zuständen hell, kräftig, gesperrt; `data-swipe-blocked`; Tipp-Zeile; `.card.leaving` entfernt | 6.3.1 |
| D2 | Erkennen und Ziehen: Achsenentscheidung, Folgen, Dämpfung, Umschlag, Rückweg | 6.3.1 |
| D3 | Auslösen in beide Richtungen über `requestSubmit()` | 6.3.1 |
| D4 | Gesperrte Richtung mit Grund, Sperre bei ungesendeter Antwort, Tipp mit Merker | 6.3.1 |
| D5 | Doku, Abnahme | 6.3.1 |

## Umgesetzte Werte

| Wert | Plan | Umgesetzt |
| :--- | :--- | :--- |
| Erkennen | 12 px, `|dx| ≥ 2·|dy|` | wie geplant |
| Senkrecht zuerst | 8 px | wie geplant |
| Schwelle | 40 % der Kartenbreite, höchstens 160 px | wie geplant (390 × 844: 143 px) |
| Jenseits der Schwelle | Faktor 0,25 | wie geplant |
| Gesperrt | Faktor 0,15, höchstens 24 px | wie geplant |
| Randzone | 24 px | wie geplant |
| Rückweg | 0,2 s | 0,2 s über den vorhandenen Kartenübergang; Hintergrund nach 220 ms entfernt |

Alle Werte stehen als Konstante `SWIPE` an einer Stelle in `app.js`.

## Abweichungen

- **Messung auf einem echten Telefon (D2) steht aus.** Die Werte sind in der Browser-Suite mit echten
  Touch-Ereignissen über die Chrome-DevTools-Schnittstelle geprüft (Chrome mit Telefon-Emulation,
  390 × 844). Ein Gerätetest unter iOS Safari und Android Chrome sollte die Startwerte bestätigen.
- **Kontrast „Irrelevant“:** wie geplant rot statt grau, da beide Richtungen links den Vorgang ohne
  Eintrag beenden.
- **Lage des Tipps:** unter der ersten wischbaren Karte statt darüber. Über der Liste schob er die erste
  Entscheidung bei 390 × 844 auf 507 px, über die Grenze von 60 % der Fensterhöhe aus 6.2.8 (506 px).
  Er ist außerdem kein `.notice` mehr: Als Hinweisklasse wurde er (auch versteckt) für die
  Ergebnismeldung einer Aktion gehalten; dafür gibt es einen Regressionstest.
- **Tipp-Text** nennt „Anlegen“ und „Verwerfen“ auch bei Relevanzfragen; der Hintergrund zeigt dort
  „Relevant“ bzw. „Irrelevant“.

## Prüfergebnisse

- Python: 100 % Zeilen- und Branch-Abdeckung (`tests/web/test_v631_swipe.py`: Sperrgründe in ihrer
  Reihenfolge, Escaping, Tipp nur mit Karten; Kontrastpaar Schrift auf kräftigem Rot im Tokentest).
- Python-Gesamtlauf: 5116 Tests bestanden. Der Lasttest `test_v42_load` (Median unter 500 ms bei
  fünf Browsern) überschritt die Grenze nur im Lauf mit 16 parallelen Workern und besteht einzeln.
- Browser: Gesamtsuite 694 Tests bestanden; `ui_tests/test_ui_swipe63.py` mit 23 Fällen – Anlegen und Verwerfen per Wisch mit
  bytegleicher Anfrage, Relevanz in beide Richtungen, Zustände in hell und dunkel mit Kontrast- und
  axe-Prüfung, gesperrte Richtung mit Grund, ungesendete Antwort, Scrollen und schräge Bewegungen,
  Start auf Schaltfläche, am Rand, mit Markierung, in seitlich scrollendem Inhalt, ohne
  Verwerfen-Formular und mit der Maus, zweiter Finger und Systemabbruch, Karte in Verarbeitung,
  veraltete Version, reduzierte Bewegung, breite Fenster, Tipp mit und ohne `localStorage`,
  ohne Touch und ohne JavaScript.
- JavaScript: 100 % Blockabdeckung in `app.js` über die gesamte Browser-Suite.

Bilder der drei Zustände (Fensterausschnitt, 390 × 844) erzeugt die Suite als
`swipe63-karte-hell-*.png`, `swipe63-karte-kraeftig-*.png` und `swipe63-karte-gesperrt.png` unter
`.test-tmp/ui-screens`.
