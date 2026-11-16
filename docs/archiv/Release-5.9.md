# Release 5.9 – Umsetzung und Abnahme

Status: Version 5.9 umgesetzt (5.9.1 bis 5.9.10) und mit 5.9.11 unter Windows 11 abgenommen,
13. November 2026. Plan: [Planung 5.9](Planung-5.9.md).

## Zuordnung der Planschritte

Die Planschritte K8 bis K10 ändern dieselben Diagrammbausteine (`charts.py`, `app.css`) und wurden
deshalb gemeinsam als 5.9.8 umgesetzt. Ein bei der Arbeit gefundener Fehler wurde als eigene
Version 5.9.9 behoben. Die Patchnummern verschieben sich damit gegenüber dem Plan:

| Planschritt | Inhalt | Version |
| :--- | :--- | :--- |
| K1 | Lesbare Zeiteinheiten | 5.9.1 |
| K2 | Konfliktmodell und Texte | 5.9.2 |
| K3 | Auswahl im Web | 5.9.3 |
| K4 | Auswahl in Telegram (mit Quittung „Endzeit 20:30 Uhr übernommen“) | 5.9.4 |
| K5 | Quellbeleg nach Bildschirmbreite | 5.9.5 |
| K6 | Themenliste für breite Bildschirme | 5.9.6 |
| K7 | Statuszähler „Mails verarbeitet“ | 5.9.7 |
| K8–K10 | Kostenmittel, Dauer-Punktwolke, Rechenzeit und Ablaufplan | 5.9.8 |
| – | Fehlerbehebung: Webbefehle in Eingangsreihenfolge | 5.9.9 |
| K11 | Aufrufliste mit `error_kind` | 5.9.10 |
| K12 | Abnahme und Release | 5.9.11 |

## Abweichungen und Präzisierungen

- **Themenliste:** Die Mindestbreiten der Spalten gelten erst ab 1280 px. Bei 1024 px lässt die
  Seitenleiste für `main` nur rund 780 px; mit den Mindestbreiten lief die Tabelle waagerecht über
  (vom Browsertest gefunden). Die Breite von 1320 px erreicht `main` erst bei rund 1600 px
  Fensterbreite.
- **Punktwolke:** Die Achsenbeschriftungen bleiben in Sekunden (0,1 s bis 1.000 s); Tabelle und
  Punktdetails nutzen `duration_text` („4 Min. 10 s“).
- **Statuszähler:** `completion == "skipped"` ist im Modell vorgesehen, wird aber derzeit nirgends
  gesetzt (in der Spezifikation festgehalten).
- **Aufrufliste:** „alle“ hat den eigenen Wert `status=alle`, weil leere Abfragewerte verworfen
  werden und eine Voreinstellung sonst nicht abwählbar wäre (vom Test gefunden).

## Bei der Umsetzung gefundene Fehler

| Fehler | Behebung | Regressionstest |
| :--- | :--- | :--- |
| Unter Windows mit Python 3.12 rückt `datetime.now()` nur alle ~15,6 ms vor. Zwei schnelle Webbefehle bekamen denselben `received_at` und wurden nach ihrer zufälligen ID sortiert; „Bestätigen“ konnte vor einem vorher gesendeten „Verwerfen“ laufen und den Eintrag anlegen. Der Sicherheitstest P4 scheiterte dadurch gelegentlich. | `ArrivalClock` (5.9.9): streng steigender Eingangszeitpunkt mit hochauflösendem Zähler | `tests/services/test_v599_arrival_order.py`; P4 fünfmal in Folge grün |
| Der Ablaufplan ist eine `figure.chart` ohne SVG; `app.js` erwartete in jeder solchen Abbildung eine Vergrößern-Schaltfläche und brach ab. | Abbildungen mit `.pipeline-figure` ausgenommen (5.9.11) | `ui_tests/test_ui_evaluation59.py` (keine Skriptfehler) |
| Die Kennzahl-Links waren auf Mobilgeräten zu kleine Tippflächen; die Tabelle „Nach Modell und Schritt“ war scrollbar, aber nicht per Tastatur erreichbar. | Tippfläche mindestens 44 px; Tabellenbereich fokussierbar (5.9.11) | `ui_tests/test_ui_evaluation59.py` (Barrierefreiheitsprüfung) |
| Die Quittung nach einer Auswahl war allgemein („Wert übernommen“), der Plan verlangt Feld und Wert. | 5.9.4 | `test_the_receipt_names_the_field_and_the_chosen_value` |

## Prüfergebnisse (Windows 11, Python 3.12)

- `ruff check src tests ui_tests` und `mypy src/mailhelp`: ohne Befund.
- `pytest` mit Coverage: 100 % Zeilen- und Branch-Abdeckung. Der Lasttest
  `test_v441_load.py::test_an_action_shows_its_result_within_half_a_second_with_two_thousand_mails`
  (Grenze 0,5 s) scheitert nur bei paralleler Ausführung mit 8 Workern und besteht einzeln; das
  Verhalten bestand schon vor 5.9.
- `pytest` (8 Worker): 4936 bestanden, 1 übersprungen, der genannte Lasttest gescheitert.
- Browser-Suite (`pytest ui_tests`, Desktop 1366 px, Mobil 390 px, schmal 320 px): 564 bestanden,
  2 übersprungen, 100 % JavaScript-Blockabdeckung in `app.js`, `sw.js`, `setup.js`, `topics.js` und
  `learning.js`; Laufzeit 19 Min. 18 s.
- Paket gebaut (`python -m build` in einer eigenen Umgebung); Wheel-Prüfungen bestanden.

**Nicht ausgeführt:** Die Prüfung unter Linux/Docker. Auf dem Abnahmerechner ist Docker nicht
installiert; sie steht noch aus.

## Dokumentation

README, CHANGELOG, Projektspezifikation, Bedienung und der eingebaute Hilfebestand wurden je Patch
aktualisiert. Es gibt keine neuen Einstellungen; die Konfigurationsbeispiele bleiben unverändert.
