# Release 6.1 – Umsetzung und Abnahme

Status: Version 6.1 umgesetzt (6.1.1 bis 6.1.8) und mit 6.1.9 unter Windows 11 abgenommen,
13. November 2026. Plan: [Planung 6.1](Planung-6.1.md). Die Entscheidungen E1–E7 wurden ohne
Gegenvorschlag mit dem jeweiligen Vorschlag des Plans übernommen.

## Zuordnung der Planschritte

| Planschritt | Inhalt | Version |
| :--- | :--- | :--- |
| P1 | Meldungskatalog und Einordnung der Fehler | 6.1.1 |
| P2 | Prüfen ohne Speichern, Schritt 1, Route, Begrenzung | 6.1.2 |
| P3 | Postfach-Prüfung gegen einen echten IMAP-Server | 6.1.3 |
| P4 | KI-Anbieter und Ziele mit genauen Gründen | 6.1.4 |
| P5 | Oberfläche: Ergebnis, Feldbezug, Hinweis während der Prüfung | 6.1.5 |
| P6 | Erfassung der Schrittzeiten | 6.1.6 |
| P7 | Verdichtung und Abfragen | 6.1.7 |
| P8 | Schrittzeiten in der Auswertung | 6.1.8 |
| P9 | Doku, Abnahme, Release (zusammen mit der Abnahme von 6.0) | 6.1.9 |

## Abweichungen und Präzisierungen

- **Prüfen speichert nichts (E1).** Ein gespeichertes Prüfergebnis gibt es nicht mehr; Ordner- und
  Modellauswahl erscheinen direkt in der Antwort auf „Prüfen“. Die Route `/einrichtung/test/…`
  entfällt.
- **Hinweis „unsicheres HTTP“ in Schritt 1** aus dem Plan entfällt: Die Ersteinrichtung läuft lokal;
  ein Zugang von außen ist ohnehin nur über die bestehenden Regeln möglich.
- **Abruf vom Server** gehört nicht zu den Teilzeiten der Aufbereitung: Er läuft gebündelt je
  Postfach vor der Verarbeitung der einzelnen Mail.
- **Journalname:** `<Metrikdatei>-stages.jsonl` neben dem KI-Journal.
- **Ergebnisse eines Schritts:** `completed`, `deferred`, `failed`; ein durch Neustart abgebrochener
  Schritt hat keine Zeile, der fortgesetzte Durchlauf ist markiert.

## Bei der Umsetzung gefundene Fehler

| Fehler | Behebung | Regressionstest |
| :--- | :--- | :--- |
| Jeder Einrichtungsfehler endete in derselben Sammelmeldung; Eingaben gingen verloren; „Prüfen“ speicherte Zugangsdaten bei Erfolg. | 6.1.1, 6.1.2 | `test_v611_setup_messages.py`, `test_v612_initial_checks.py` |
| Bietet ein Server STARTTLS nicht an, hieß es „Server antwortet nicht“. | 6.1.3 | `test_v613_imap_checks.py` (echter lokaler Server) |
| Todoist meldete 403/404 als allgemeinen Fehler, die Prüfung zeigte „Unerwarteter Fehler“. | `TargetAccessError` mit Grund (6.1.4) | `test_v614_target_reasons.py` |
| Der Browser blockierte „Prüfen“ bei einem zu kurzen Passwort mit seiner eigenen Formularprüfung. | `formnovalidate` (6.1.5) | `test_ui_initial_checks615.py` |
| Die Übersicht antwortete mit HTTP 500, wenn Windows eine Eingangsquittung beim Ersetzen kurz sperrte (in einem seriellen Messlauf beobachtet). | Wiederholtes Lesen wie beim Ersetzen (6.1.5) | `test_v615_receipt_read.py` |
| Zwei Browsertests scheiterten sporadisch (mehrdeutiger Selektor, zu knappe Wartezeit unter Last). | 6.1.6 | wiederholte Gesamtläufe |
| Die Abdeckung der Konfliktprüfung beim Speichern (Änderung während der Passwortprüfung außerhalb der Sperre) hing seit 6.1.2 vom Zufall ab und fehlte in der Gesamtprüfung. | Gezielter Test (6.1.9) | `test_a_change_while_the_password_is_checked_is_a_conflict_and_saves_nothing` |

## Prüfergebnisse (Windows 11, Python 3.12, Endstand 6.1.9)

Prüfergebnisse für 6.0 und 6.1 zusammen; die Messreihe der Browsertests steht in
[Release 6.0](Release-6.0.md#leistungsnachweis-browsertests-35).

- `ruff check src tests ui_tests devtools` und `mypy src/mailhelp`: ohne Befund.
- `pytest` mit Coverage (8 Worker): 100 % Zeilen- und Branch-Abdeckung; 5060 bestanden,
  1 übersprungen. Die Lasttests `test_v42_load.py` und `test_v441_load.py` scheitern nur bei
  paralleler Ausführung mit 8 Workern und bestehen einzeln (bekannt seit 5.9).
- Browser-Suite (`pytest ui_tests -n 4 --dist worksteal --no-cov`): zwei vollständige Läufe auf dem
  Endstand, je 637 bestanden und 2 übersprungen, ohne sporadische Fehler; 100 %
  JavaScript-Blockabdeckung über alle Worker zusammengeführt; Laufzeiten 7 Min. 35 s und 6 Min. 39 s.
- Paket gebaut (`python -m build` in einer eigenen Umgebung); Wheel-Prüfungen bestanden.

**Nicht ausgeführt:** Die Prüfung unter Linux/Docker. Auf dem Abnahmerechner ist Docker nicht
installiert; sie steht noch aus.

## Dokumentation

README, CHANGELOG, Projektspezifikation, Ersteinrichtung (mit einer Tabelle der häufigsten
Prüfmeldungen) und der eingebaute Hilfebestand wurden je Patch aktualisiert. Es gibt keine neuen
Einstellungen; die Konfigurationsbeispiele bleiben unverändert.
