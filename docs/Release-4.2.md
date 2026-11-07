# Release 4.2 – Web-Aktionen und „Schon erledigt“

Version 4.2.0, 6. November 2026. Umsetzung und Plattformabnahme abgeschlossen.

## Bedienung

„Schon erledigt“ auf einer Vorschlagskarte schließt die dargestellte Version lokal
ab. Der Vorschlag wird als `rejected` mit `resolution="already_done"` gespeichert;
es entsteht keine externe Aufgabe und kein externer Termin. Im Lernbestand bleibt
der Fall positiv relevant. Die Aktion ist auch bei offenen Rückfragen verfügbar.
Wiederholte oder inzwischen veraltete Entscheidungen erzeugen keine zweite Wirkung.
Telegram entfernt nach der Entscheidung die Schaltflächen.
Der Neustart-Abgleich akzeptiert dafür nur dieselbe Vorschlagsversion mit dem
Kennzeichen `already_done`; eine fremde Entscheidung oder spätere Version erzeugt
kein fälschlich positives Lernprotokoll.

Web-Aktionen werden nach dem Neustart-Abgleich vor Wartungsarbeiten abgearbeitet.
Telegram-Versand hält keine gemeinsame Dialog- oder Ablagesperre. Die dauerhafte
Outbox bewahrt während des Versands neu eingehende Nachrichten und vermeidet eine
automatische Wiederholung unklarer Zustellungen. Die Aktionsseite prüft ihren Stand
über `/api/aktion/<id>`; ohne JavaScript bleibt automatisches Neuladen erhalten.
Eine unterbrochene Verbindung wiederholt ausschließlich die lesende Statusabfrage.

`/status` zeigt Wartezeit bis zum Ausführungsbeginn (Median und Maximum der letzten
20 gemessenen Web-Aktionen). Das Inhaltsprotokoll wird dafür nicht aktiviert.
Die Sperrmessung umfasst auch den indirekten Zugriff der Sitzungsprüfung auf die
gemeinsame Ablagesperre; ein Regressionstest reproduziert die zuvor fehlende Wartezeit.
Die Berichtsübersicht und Statusseite zählen „Schon erledigt“ getrennt von echten
Verwerfungen. Die Berichtsübersicht bezeichnet diese Zahlen als aktuellen Bestand;
sie werden nicht als Ergebnisse des gewählten Berichtszeitraums ausgegeben.

## Lernbestand und Upgrade

Das optionale neue Feld benötigt beim Lesen früherer Akten keine Migration:
fehlend bedeutet `None`. Die bestehenden echten Upgrade-Fälle bleiben verbindliche
Tests. Die JSON-Schema-Snapshots für `Proposal`, `MailState` und `ProposalMergeJournal`
erfassen die additive Änderung. Vor dem Upgrade die Zustandsablage sichern;
eine Rückkehr zu 4.1 benötigt die dazu passende Sicherung, weil frühere strikte
Leser das neue Feld nicht kennen.

Das Lernlog enthält `operation="already_done"`, `decision="relevant"` und
`relevance_preserved=true`; der Idempotenzschlüssel bleibt separat erhalten.
CLI- und Web-Lernen verwenden die tatsächliche Mailablage zusätzlich zur separaten
Absenderkonfiguration. Sie klassifizieren bekannte positive Beispiele nicht negativ
neu. Maßgebliche Vorschlagsakten schützen den Fall bereits dann, wenn ein Absturz
das Aktualisieren der Mailprojektion oder Schreiben des Lernlogs unterbrochen hat.
Kostenpflichtige Modelle und echte Zielanbieter wurden für diese Tests nicht verwendet.

## Abnahme

Die Regressionen für blockierenden Telegram-Versand und falsche Befehlsreihenfolge
schlugen vor der Korrektur fehl und bestehen danach. Dasselbe gilt für den Schutz
nach fehlender Mailprojektion und für eine unvalidierte Statuskopie einer erledigten
Aktion an der externen Schreibgrenze.

Der synthetische Lasttest führt fünf regulär angemeldete Browser gegen die echten
Web-/Befehlspfade aus. Ein echter Mailbox-Durchlauf bleibt in einer simulierten
Analyse blockiert, gleichzeitig hängt ein Telegram-Versand. Gleichzeitige
Browserwiederholungen werden über denselben Idempotenzschlüssel abgeglichen.
Der endgültige Windows-Lauf erreichte 163,59 ms Median und 291,20 ms Maximum bis zum Beginn.
Linux und Docker bestanden denselben Test ebenfalls; die vollständigen Messwerte
stehen im maschinenlesbaren Abschlussbericht.
Gemessen wird ab Eingang des abgesendeten Befehls. Die vorhandene Rückgängig-Frist
der Weboberfläche vor dem Absenden ist eine separate Bedienfunktion und bleibt bestehen.
Das ist ein gemessener Simulationswert, keine Garantie bei beliebiger Systemlast
oder während eines bereits laufenden, langsamen externen Schreibaufrufs.
Ein zusätzlicher Docker-Lauf während gleichzeitig laufender Windows-/Linux-
Volltests und des Mutationsaudits überschritt die Grenze: 860,60 ms Median und
1.161,21 ms Maximum. Die 68 übrigen Fälle bestanden. Dieser Befund bleibt im
maschinenlesbaren Bericht erhalten; die Plattformabnahme misst das vorgesehene
Anwendungsszenario ohne diese zusätzlichen ressourcenintensiven Tests.

| Prüfung | Ergebnis |
| --- | --- |
| Windows 11, Python 3.12.10, vier Worker mit sequenzieller Prozessgruppe | 3.498 bestanden, ein POSIX-spezifischer Skip, 467,83 s |
| Ubuntu/WSL, Python 3.12.3, gleiche Gruppierung | 3.499 bestanden, 360,13 s |
| Python-Abdeckung auf beiden Plattformen | 24.031 Statements und 6.934 Branches, jeweils 100 % |
| Vollständige Browser-Suite | 233 bestanden, 539,45 s; 100 % JavaScript-Blöcke in `app.js`, `sw.js`, `setup.js` |
| Finale Docker-Prüfung der neuen und Authentifizierungsfälle | 69 bestanden; alle Dienste simuliert, Netzwerk gesperrt |
| Docker: harte Prozessabbrüche und Wiederaufnahme | 28 bestanden; außerdem Konfigurationsprüfung, Dienst- und Lernmodus-Neustarts bestanden |
| Ergänzende endgültige Linux-Prüfung | 69 neue und Authentifizierungsfälle bestanden |
| Ruff / mypy | Keine Befunde; mypy prüft 230 Quelldateien |
| Kern-Mutationsaudit | 1.027 / 1.053 getötet (97,53 %); alle 26 Überlebenden analysiert; keine unbewerteten Fälle |

| Lastlauf mit fünf Browsern | Median bis Beginn | Maximum bis Beginn |
| --- | ---: | ---: |
| Windows | 163,59 ms | 291,20 ms |
| Linux | 334,90 ms | 509,41 ms |
| Docker | 159,78 ms | 300,73 ms |

Die 100-%-Schranken bleiben unverändert verpflichtend. Die abschließende Korrektur
der Sitzungs-Sperrmessung ist in beiden vollständigen Plattformläufen enthalten.
Ihr Regressionstest schlug vor der Korrektur fehl und besteht danach.
Die Browser-Abnahme umfasst
auch eine abgebrochene Anmeldeweiterleitung: Es folgt weder ein erneuter POST noch
eine erneute Statusabfrage mit abgelaufener Sitzung. Der Code dieser Weiterleitung
wird dabei vor dem Verlust des alten Dokuments vollständig gemessen.

Maschinenlesbare Nachweise im Repository: [Gesamtabnahme](../quality-reports/quality-4.2.json)
und [Mutationsaudit](../quality-reports/mutation-4.2.json), dazu die
[Einzelbewertung aller Mutanten](../quality-reports/mutation-4.2.md).
Die Prüfungen legen keine echten Aufgaben oder Termine an und messen keine
tatsächliche Qualität kostenpflichtiger Sprachmodelle.

Ein bestehender PIN-Speichertest hatte einen zufälligen Fehlalarm: Die vierstellige
Test-PIN konnte als Teilzeichenfolge im korrekt gespeicherten HMAC vorkommen.
Der Fall wird jetzt deterministisch reproduziert und die gesamte gespeicherte
Struktur gegen unabhängig berechnete Hashwerte geprüft. Die Authentifizierung wurde
dafür nicht geändert oder gelockert.
