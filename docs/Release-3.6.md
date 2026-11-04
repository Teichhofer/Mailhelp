# Mailhelp 3.6 – Fundament und Absicherung

Arbeitsstand 3.6.38, 3. November 2026. Die Patch-Zuordnung der einzeln beschriebenen
Schritte steht in [Planung 3.6](Planung-3.6.md); dieser Arbeitsstand bündelt die restliche
Umsetzung. Es wurden keine Zwischenversionen veröffentlicht.

„Erneut prüfen“, Entkopplung von Mailabruf und Bedienung, strikte Web-Typprüfung und
Paketbündelung sind ergänzt um die vollständigen Konkurrenz- und Prozessabbruchtests.
Versionsbezogene Entscheidungen vergleichen den aktuellen Stand vor dem Speichern erneut.
Web-Schreibfreigaben behalten ihre Sitzungsbindung über Neustarts und Provider-Vorprüfungen.
Wiederholte identische Web-Anfragen liefern denselben Inbox-Eintrag auch nach Abschluss.
Merge-Wiederherstellung erkennt fehlende Quellakten sowie fehlende oder isolierte Journale.

Die neuen Modellfelder `confirmed_web_actor`, `reconciliation_journal` und
`source_was_present` sind additive Felder mit Standardwerten für ältere Akten. Neue
Revisionen verwerfen die bisherige Web-Freigabe und brauchen separate Bestätigung.
Historische noch nicht begonnene Freigaben brauchen einen passenden Ausführungsbeleg mit
weiterhin gültiger Websitzung oder weiterhin erlaubter Telegram-Identität. Fehlt er,
bleiben sie sichtbar gesperrt. Bereits erfolgte Anlagen werden weiterhin lesend
abgeglichen und nicht wiederholt.
Ein Backup des Datenverzeichnisses vor dem Update bleibt sinnvoll; Anwendung vorher beenden.
Für eine Rückkehr zu einer älteren Programmversion muss auch die dazugehörige Datensicherung
verwendet werden: Ältere strikte Modelle kennen die neuen Felder nicht.

Die [Zustandsregeln](Zustandsregeln-3.6.md) enthalten Persistenzreihenfolge, Zustandsmatrix,
Testwerkzeuge, P1–P7, A1–A7 und den protokollierten Antwortzeitnachweis mit synthetischen Diensten.
Die automatisierte Gesamtabnahme erzwingt weiterhin 100 % Zeilen und 100 % Branches;
Kindprozess-Coverage wird vor harten Abbrüchen gespeichert und im Gesamtlauf kombiniert.

Abnahme am 3. November 2026:

| Prüfung | Ergebnis |
| --- | --- |
| Windows, Python 3.12.14, vollständiger Testlauf | 2.865 bestanden, keine Fehler oder übersprungenen Tests |
| Ubuntu, Python 3.12.3, vollständiger Testlauf als unprivilegierter Benutzer | 2.865 bestanden, keine Fehler oder übersprungenen Tests |
| Zeilenabdeckung, jeweils Windows und Ubuntu | 22.107 von 22.107, 100 % |
| Branch-Abdeckung, jeweils Windows und Ubuntu | 6.386 von 6.386, 100 % |
| Zusätzlicher Sicherheitslauf, jeweils Windows und Ubuntu | 35 bestanden, einschließlich des zuletzt ergänzten Falls eines unversionierten Altbestands |
| Browserprüfung mit unabhängigen Sitzungen und Wiederherstellung | 10 bestanden |
| Ruff und mypy | Ohne Befund; mypy prüft 211 Quelldateien |
| Gebautes Wheel außerhalb des Quellverzeichnisses installiert und geprüft | 38 Paket- und Sicherheitsprüfungen bestanden |

Die vollständigen Läufe enthalten noch nicht die zuletzt ergänzte Parametervariante
für unversionierte Altbestände. Diese ist durch die zusätzlichen Sicherheitsläufe
auf beiden Plattformen abgedeckt; danach wurde kein Anwendungscode geändert.
Alle externen Dienste waren simuliert, alle Daten synthetisch.
Die Prozessabbruchtests verwenden echte Prozessabbrüche, Dateisperren und Neustarts.
Der Antwortzeitnachweis mit blockierter Analyse ergab 125,102 ms Befehlslatenz und
86,667 ms Ausführungszeit. Dies ist eine Messung mit synthetischen Diensten und
keine Aussage über die Laufzeit produktiver Konten.

Die Testberichte und Coverage-JSON-Dateien liegen lokal unter `.test-tmp-36/`
(`windows-results.xml`, `linux-results.xml`, `coverage.json`,
`linux-coverage.json`, `linux-post-results.xml`, `wheel-final-results.xml`);
sie sind keine Paketbestandteile. Wheel und Quelldistribution für 3.6.38 wurden
unter `dist/` gebaut. Es wurde weder ein Commit erstellt noch veröffentlicht.
