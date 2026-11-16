# Release 5.0 – Oberfläche und Bedienung

Versionen 5.0.0 bis 5.0.12, 10. November 2026. Grundlage: [Planung 5.0](Planung-5.0.md), Stufe 21.

5.0 ändert Darstellung und Bedienung der Weboberfläche. Bestätigung, Versionen, CSRF-Schutz
und Idempotenz bleiben unverändert: Kein Schritt dieser Version löst selbst einen Schreibzugriff
auf Kalender oder Aufgabenliste aus. Eingeschoben wurden fünf Korrekturen aus dem laufenden
Betrieb (5.0.2 bis 5.0.6).

## Neu für die Bedienung

| Version | Änderung |
| --- | --- |
| 5.0.0 | Farben als Design-Tokens für hell und dunkel; jede Text-/Flächen-Kombination erreicht mindestens WCAG AA (4,5:1), ein Test berechnet die Werte aus `app.css`. |
| 5.0.1 | Seitenleiste ab 900 px (bis 1.199 px als Symbolleiste, ab 1.200 px einklappbar); auf dem Telefon eine feste Leiste unten mit „Mehr“; „Offen“ zählt offene Entscheidungen. |
| 5.0.7 | Karten tragen ihre Art als Streifen, Symbol und Text: Termin, Aufgabe, Terminänderung, Terminabsage, Antwortentwurf; der Beleg erscheint als Zitat. |
| 5.0.8 | Die Entscheidungsleiste bleibt im Detailbereich der geteilten Ansicht beim Scrollen sichtbar. |
| 5.0.9 | `A` bestätigt wie `C` und Enter; die Seitenleiste bietet „? Tastenkürzel“. |
| 5.0.10 | „Alles erledigt“ zeigt die Tageswerte als Kacheln; die Einblendung entfällt bei reduzierter Bewegung. |
| 5.0.11 | Alle Tippflächen auf Telefonen sind mindestens 44 px hoch; die Browser-Prüfung erzwingt den Wert. |

## Korrekturen aus dem Betrieb

| Version | Fehler und Behebung |
| --- | --- |
| 5.0.2 | Bestätigte Aufgaben einer Mail mit mehreren Aufgaben kamen nicht in Todoist an, weil Geschwisteraufgaben als mögliche Dublette galten. Aufgaben werden jetzt eher angelegt als zurückgehalten. |
| 5.0.3 | Die Zuordnungsfrage ließ sich per Text beantworten, wurde verworfen und trotzdem als „übernommen“ gemeldet. Sie führt jetzt in den Vorschlagsabgleich; Antworten melden ihr tatsächliches Ergebnis. |
| 5.0.4 | Bei Vorschlägen mit Original-Mail-Link meldete die geteilte Ansicht „Details nicht geladen“, weil sie diesen Link statt der Detailseite lud. |
| 5.0.5 | Der Abgleich zeigt von einer Karte aus nur den betroffenen Vorschlag und seine Vergleichskandidaten. |
| 5.0.6 | Jeder Vergleich zeigt beide Vorschläge vollständig nebeneinander; der betroffene ist farbig hervorgehoben. |

Jede Fehlerbehebung enthält einen Regressionstest, der vor der Korrektur fehlschlug.

## Upgrade und Rückkehr

Keine Konfigurations- oder Zustandsmigration. Nach dem Update den Dienst neu starten und die
Weboberfläche einmal neu laden; der Service Worker liefert die neuen Stile mit der Version aus.
Bereits blockierte Vorschläge aus der Zeit vor 5.0.2/5.0.3 werden nicht automatisch freigegeben:
im Vorschlagsabgleich „Als eigenen Vorschlag behalten“ wählen und danach bestätigen.

Eine Rückkehr zu 4.9 ist ohne Datenänderung möglich. Die Einstellung
`mailhelp.nav-collapsed` liegt nur im Browser (`localStorage`) und wird von 4.9 ignoriert.

## Abnahme

Automatisierte Tests verwenden ausschließlich synthetische Daten und simulierte externe Dienste.

| Prüfung | Ergebnis |
| --- | --- |
| Windows 11, Python 3.12.10 | **4.029 bestanden**, ein POSIX-Berechtigungstest plattformbedingt übersprungen (Lasttests getrennt) |
| Zeilenabdeckung Windows | **26.222 / 26.222, 100 %** |
| Branch-Abdeckung Windows | **7.576 / 7.576, 100 %**, keine partiellen Zweige |
| Browser-Gesamtsuite | **324 bestanden** auf Desktop, Mobilgerät und 320-Pixel-Ansicht mit 44-px-Tippflächenprüfung und axe-core; **100 % JavaScript-Blöcke** in `app.js`, `sw.js`, `setup.js` |
| Statische Prüfung | Ruff ohne Befunde; mypy ohne Befunde in **253 Quelldateien** |
| Paketprüfung | Wheel und sdist gebaut; Paketprüfungen bestanden |
| Prompt-Qualitätsgate | Drei synthetische Tests bestanden; Prompt-Fingerabdrücke unverändert |
| Linux/Docker | **Nicht durchgeführt**: Auf dem Abnahmerechner war Docker nicht verfügbar. Die Linux-Abnahme ist nachzuholen, bevor 5.0 als plattformübergreifend geprüft gilt. |

Die beiden Windows-Lasttests bestehen separat mit unveränderten Grenzen:
4.2 (fünf Browser) Median Warteschlange **422,9 ms**, Maximum **642,2 ms**;
4.4.1 (2.000 Mails) Median Antwortzeit **448,5 ms**, Maximum **554,3 ms**.
Im parallelen Gesamtlauf scheitern beide gelegentlich an ihrem Zeitbudget; das ist seit 4.4
bekannt und betrifft nicht die Funktion.

Das 100-%-Gate bleibt unverändert; es gibt keine neuen Coverage-Ausschlüsse. 5.0.7 ergänzte
einen deterministischen Test für den gleichzeitigen Eingang desselben Befehls, der zuvor nur
zufällig unter Last abgedeckt war.

### Reproduzierbare Prüfungen

```powershell
python -m pytest -n 8 --dist loadgroup -q --ignore=tests/services/test_v42_load.py --ignore=tests/services/test_v441_load.py
python -m pytest tests/services/test_v42_load.py tests/services/test_v441_load.py --no-cov -q -s
python -m pytest ui_tests --no-cov -q
python -m ruff check src tests ui_tests devtools
python -m mypy
python -m devtools.check prompts
python -m hatchling build
```

Die Abnahme belegt Darstellung und Bedienung in Chrome (Playwright) auf drei Bildschirmgrößen,
hell und dunkel. Tests mit echten Postfächern, echten Zielanbietern oder einem echten Modell
wurden nicht durchgeführt.
