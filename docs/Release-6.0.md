# Release 6.0 – Umsetzung und Abnahme

Status: Version 6.0 umgesetzt (6.0.1 bis 6.0.7) und unter Windows 11 abgenommen,
13. November 2026. Plan: [Planung 6.0](Planung-6.0.md).

Der Planschritt W8 (Abnahme 6.0.8) erscheint nicht als eigene Version: Während der Messreihe für
die parallelen Browsertests war 6.1 bereits begonnen (6.1.1 bis 6.1.8). Damit die Versionsnummern
steigend bleiben, wurde die Abnahme von 6.0 zusammen mit der von 6.1 als **6.1.9** veröffentlicht
(siehe [Release 6.1](Release-6.1.md)).

## Zuordnung der Planschritte

| Planschritt | Inhalt | Version |
| :--- | :--- | :--- |
| W1 | Layout der Lernseite auf breiten Bildschirmen | 6.0.1 |
| W2 | Breitbild-Prüfung aller Kernseiten | 6.0.2 |
| W3 | Datenmodell, Änderungsmenge, Fingerabdruck abgelehnter Regelvorschläge | 6.0.3 |
| W4 | Verwerfen, Vorschau, Bestätigung, Wieder zulassen | 6.0.4 |
| W5 | Abgelehnte Vorschläge nicht wieder vorschlagen (Prompt und Filter) | 6.0.5 |
| W6 | Kompakte Werkzeugleiste der Offen-Ansicht | 6.0.6 |
| W7 | Browsertests parallelisieren | 6.0.7 |
| W8 | Abnahme und Release | 6.1.9 |

## Abweichungen und Präzisierungen

- **Workerzahl:** Voreinstellung und empfohlener Aufruf ist `-n 4 --dist worksteal`. Der serielle
  Lauf (`pytest ui_tests` ohne `-n`) bleibt für die Fehlersuche erhalten.
- **Messung mit einem Worker:** Als Vergleichsbasis dient der serielle Lauf ohne xdist; er
  entspricht einem Worker ohne Verteilungsaufwand. Gemessen wurden zusätzlich 2, 3, 4 und 6 Worker.
- **CPU-Auslastung und Speicherbedarf** sind nicht belegt: Die Messung las Windows-Leistungsindikatoren
  über ihre englischen Pfadnamen, die auf dem deutschsprachigen System nicht existieren, und lieferte
  keine Werte. Die Messreihe wurde deshalb nicht wiederholt; der Zeitnachweis ist davon unberührt.

## Leistungsnachweis Browsertests (3.5)

**Rechner:** Intel Core i5-12400F (6 Kerne, 12 Threads), 31,8 GiB Arbeitsspeicher, Windows 11 Pro,
Python 3.12, Chromium über Playwright. **Quellstand:** 6.0.7 (`c08ca6f`) in einem eigenen
Arbeitsverzeichnis. **Umfang:** 624 Tests (622 ausgeführt, 2 übersprungen), Gerätematrix Desktop,
Mobil und schmal, Zugänglichkeitsprüfungen und JavaScript-Abdeckung unverändert. Gemessen ist die
Gesamtlaufzeit des Prozesses einschließlich Start, Zusammenführung der Abdeckung und deren Prüfung.

| Lauf | Worker | Laufzeit | Ergebnis |
| ---: | :--- | ---: | :--- |
| 1 | seriell | 1288 s | 1 Fehler (siehe unten, behoben in 6.1.5) |
| 2 | 4 | 419 s | 1 Fehler (siehe unten, behoben in 6.1.6) |
| 3 | seriell | 1313 s | bestanden |
| 4 | 4 | 416 s | bestanden |
| 5 | seriell | 1335 s | bestanden |
| 6 | 4 | 385 s | bestanden |
| 7 | 2 | 683 s | 1 Fehler (wie Lauf 2) |
| 8 | 3 | 482 s | bestanden |
| 9 | 6 | 307 s | 1 Fehler (wie Lauf 2) |

- **Median seriell 1313 s, Median mit 4 Workern 416 s, Faktor 3,16** – das Ziel von mindestens
  Faktor 3 ist erreicht. Mit 4 Workern liegt der bisherige Umfang bei knapp 7 Minuten.
- 6 Worker sind schneller (307 s), aber der Vorsprung ist klein; 4 Worker lassen auf dem Rechner
  genug Reserve für den laufenden Dienst und bleiben deshalb die Voreinstellung.
- Die Läufe fanden auf dem Entwicklungsrechner statt; zeitweise liefen kurze Einzelprüfungen
  parallel (einzelne Testdateien). Die Streuung der seriellen Läufe (1288–1335 s) bleibt unter 4 %.

### In der Messreihe gefundene Fehler

| Fehler | Behebung | Nachweis |
| :--- | :--- | :--- |
| Die Übersicht antwortete mit HTTP 500, wenn Windows eine Eingangsquittung beim Ersetzen kurz sperrte (Lauf 1, `test_ui_pending_selection`). | Wiederholtes Lesen wie beim Ersetzen (6.1.5) | `tests/services/test_v615_receipt_read.py` |
| `test_ui_reconciliation` fand unter Last zwei gleichnamige Elemente (strikter Selektor) (Läufe 2, 7, 9). | Eindeutiger Selektor (6.1.6) | wiederholte parallele Gesamtläufe auf dem Endstand |

Beide Fehler betreffen nicht die Parallelisierung selbst: Der erste trat im seriellen Lauf auf, der
zweite ist ein mehrdeutiger Selektor, den höhere Last nur sichtbar macht. Automatische
Wiederholungen werden nicht verwendet.

## Prüfergebnisse

Die Gesamtprüfung auf dem Endstand 6.1.9 ist in [Release 6.1](Release-6.1.md#prüfergebnisse)
festgehalten; sie umfasst alle Tests aus 6.0.

**Nicht ausgeführt:** Die Prüfung unter Linux/Docker. Auf dem Abnahmerechner ist Docker nicht
installiert; der Aufruf ist im README für beide Plattformen beschrieben.

## Dokumentation

README, CHANGELOG, Projektspezifikation, Bedienung und der eingebaute Hilfebestand wurden je Patch
aktualisiert; die Anleitung für Browsertests nennt den parallelen und den seriellen Aufruf.
