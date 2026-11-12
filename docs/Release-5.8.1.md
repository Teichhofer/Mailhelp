# Release 5.8.1 – Statuskennzahlen als Navigation

Stand: 12. November 2026. Umsetzung und automatisierte Abnahme abgeschlossen.

| Kachel | Ziel |
| --- | --- |
| Offene Vorschläge | Eigene Übersicht `/status/vorschlaege`; einzelne Vorschläge mit Details-Link |
| Relevanzfragen | Eigene Übersicht `/status/relevanzfragen`; Details der jeweiligen Mail |
| Mails mit Fehler | Bestehende Mailablage `/mails?state=failed`, mit Suche und Seitennavigation |
| Wartende Web-Aktionen | `/status/web-aktionen`, nur aktuell wartende Einträge und Fortschrittslinks eigener Aktionen |

Die ganze Kachel ist ein nativer Link mit Tastaturfokus und ausreichend großer
Touchfläche. Die Ziele funktionieren ohne JavaScript und erfordern eine Anmeldung.
Null Einträge führen zu einer verständlichen leeren Übersicht. Manuelles Aktualisieren
führt keine Aktion aus. Andere Sitzungen werden in der Warteschlange ohne private
Inhalte und ohne unberechtigten Fortschrittslink mitgezählt.

Es entstehen keine neuen Konfigurationseinstellungen. README, Bedienung,
Projektspezifikation und eingebauter Hilfebestand wurden aktualisiert. Die vorhandenen
Arbeiten aus 5.8.0 und andere bereits vorhandene Änderungen bleiben erhalten.

Der vorher fehlende Klickpfad wurde mit einem Regressionstest vor der Umsetzung
reproduziert (`.test-tmp/status581-red.log`).

| Prüfung | Ergebnis |
| --- | --- |
| Windows, vollständige Python-Prüfung | 4812 bestanden, 1 plattformbedingter Skip; 100 % Zeilen und Branches (30481 Anweisungen, 8856 Branch-Ziele); beide Lasttests bestanden |
| Linux/Docker, vollständige Python-Prüfung ohne Netzwerk | 4813 bestanden; dieselben 100 % Zeilen und Branches; beide Lasttests bestanden |
| Neue Status-Navigation im Browser | 6 Durchläufe: Desktop, Mobil, schmal, jeweils mit und ohne JavaScript; alle vier Ziele per Tastatur, große Klickflächen, axe und Schutz vor unbeabsichtigten Aktionen geprüft |
| Bestehende Status- und Fehleransichten im Browser | 12 zusätzliche Prüfungen bestanden, einschließlich Hell-/Dunkeldarstellung |
| Statische Prüfung | Ruff fehlerfrei; Mypy: 288 Quelldateien fehlerfrei |

Nachweise: `.test-tmp/status581-full.log`, `.test-tmp/status581-linux-full.log`,
`.test-tmp/status581-ui.log`, `.test-tmp/status581-existing-ui.log` und
`.test-tmp/status581-target-final.log`. Die 13 neuen Python-Prüfungen decken auch
Anmeldung, fremde Aktionen, Leerzustände, Neustarts, wiederholtes Lesen und das
Verschwinden begonnener oder abgeschlossener Aktionen aus der Warteliste ab.

JavaScript wurde nicht geändert; für dieses Patch wurden gezielt die betroffenen
Oberflächen geprüft. Es wurden keine echten Mails übertragen, keine Modellaufrufe
ausgeführt und keine externen Termine oder Aufgaben angelegt. Die Linux-Prüfung nutzt
das vorhandene Testimage mit isoliertem aktuellem Quellstand und `PYTHONPATH=/workspace/src`.

Die abschließende Commit-Abnahme berücksichtigt zusätzlich den inzwischen in `main`
enthaltenen Regellernkern aus 5.7.7. Der gemeinsame Stand wurde erneut geprüft:

| Prüfung | Ergebnis beim Commit |
| --- | --- |
| Windows, vollständige Python-Prüfung | 4839 bestanden, 1 plattformbedingter Skip; beide Lasttests bestanden |
| Linux/Docker, vollständige Python-Prüfung ohne Netzwerk | 4840 bestanden; beide Lasttests bestanden |
| Abdeckung auf beiden Plattformen | 100 % Zeilen und Branches; 30599 Anweisungen, 8894 Branch-Ziele, keine fehlenden Zeilen oder Teilbranches |
| Gezielte Python-Regressionen | 95 bestanden, einschließlich Statusnavigation, Vorschauen und Regellernkern |
| Gezielte Browserprüfungen | 15 bestanden für Statusnavigation und Regellernen, einschließlich mobiler Größen und Abläufe ohne JavaScript |
| Statische Prüfung und generierte Bestände | Ruff für Quellcode, Tests und Entwicklungswerkzeuge fehlerfrei; Mypy: 289 Quelldateien fehlerfrei; Hilfe und Inventar aktuell |

Nachweise dieser erneuten Abnahme: `.test-tmp/commit581-full.log`,
`.test-tmp/commit581-linux-full.log`, `.test-tmp/commit581-target.log` und
`.test-tmp/commit581-ui.log`. Seit Beginn der vollständigen Prüfungen wurde der
Anwendungscode nicht verändert.

Eine laufende Mailhelp-Instanz muss neu gestartet werden, um die neuen Klickpfade zu verwenden.
