# Release 4.9 – Konfigurierbare Postfach-Briefings

Versionen 4.9.0 bis 4.9.6, 8. November 2026. Grundlage: [Planung 4.9](Planung-4.9.md), Stufe 20.

## Verhalten und Einrichtung

Mailhelp erstellt zu frei gewählten Tageszeiten ein Briefing als IMAP-Entwurf mit
HTML und gleichwertigem Klartext. Es enthält alle offenen Termin- und Aufgabenkarten,
offene Relevanzfragen sowie neue abgeschlossene Zusammenfassungen und deren Fristen
seit dem vorherigen erfolgreichen Briefing. Der Betreff lautet etwa
`[Mailhelp Briefing 07:00] 3 Termine, 2 Aufgaben`. Kein SMTP-Versand, kein zusätzlicher LLM-Aufruf.

```yaml
web:
  enabled: true
briefings:
  enabled: false
  times: ['07:00', '13:00', '18:00']
  mailbox: default
  skip_empty: true
```

Die Funktion bleibt nach dem Update ausgeschaltet. Nach dem Softwareupdate den Dienst
neu starten. Unter Einstellungen → Postfach-Briefings (`/einstellungen?bereich=briefing`)
lassen sich alle vier Briefing-Felder nach ausdrücklicher Speicherung ohne Neustart ändern.
Uhrzeiten werden als `HH:MM` eingegeben; Komma, Semikolon oder Leerraum trennen mehrere
Zeiten. Ungültige und doppelte Zeiten sowie eine leere Liste bei aktivierter Funktion
werden abgelehnt. Zeiten gelten auch am Wochenende.

Der Scheduler läuft mit der aktivierten Weboberfläche im bestehenden Hintergrunddienst.
`mailbox: default` verwendet das erste aktive IMAP-Postfach; alternativ wählt eine stabile
Postfachnummer das Ziel. `drafts.folder` überschreibt den Ordner global, ansonsten gelten
`drafts_folder` des Zielpostfachs und der bewährte SPECIAL-USE-/Namens-Fallback.
Es werden keine Ordner angelegt. `briefings.enabled` wirkt unabhängig von `smart_reply`,
`auto_draft` und `drafts.enabled`; `daily_briefing` steuert weiterhin die bisherige Tagesübersicht.
`test_mode: true` simuliert die Briefing-Ablage ohne IMAP-Verbindung.

## Zeitfenster und Wiederanlauf

Die Einstellung `timezone` bestimmt die Tageszeiten. Der bestehende Hintergrunddienst
prüft alle fünf Sekunden. Verspätete Starts holen fällige Zeiten des aktuellen Tages
chronologisch nach; vollständig ausgefallene Tage werden nicht nacherzeugt.
Das erste Zusammenfassungsfenster beginnt um lokaler Mitternacht, spätere Fenster beim
letzten erfolgreichen oder bewusst ausgelassenen Slot. Offene Karten erscheinen unabhängig
von diesem Fenster. Ein späterer Nutzereingriff zählt eine alte Mail nicht erneut als neue Analyse.

Eine doppelte Uhrzeit bei der Herbstumstellung wird nur beim ersten Auftreten berücksichtigt.
Eine im Frühjahr fehlende Uhrzeit wird um die Zeitlücke verschoben (Berlin: 02:30 → 03:30).
Ein rückwärts springendes Datum erzeugt keine alten Slots. Änderungen an Zeitzone oder
Zielpostfach erzeugen keinen zweiten Entwurf für einen bereits abgearbeiteten lokalen Slot.

`briefing_state.json` enthält Schema 1, Slots, Ausgänge, Versuche, Wiederholungszeit und
`last_briefing_at`. Vor dem APPEND werden Inhalt, Message-ID, Konto und Ordner dauerhaft
gesichert. Nach unklarem Resultat wird im ursprünglichen Ordner über Message-ID abgeglichen.
Fehlt dieser Ordner oder hat sich das Konto geändert, findet keine weitere Ablage statt.
Fehlversuche warten mindestens 60 Sekunden. Erfolgreiche Slots enthalten keine kopierten
Mailinhalte mehr; bei Fehlern bleibt der eingefrorene Inhalt zur sicheren Wiederholung erhalten.
Der Zustand muss beim Upgrade und bei einer Wiederherstellung erhalten bleiben.

Unverändert wieder abgerufene eigene Briefings werden anhand des vor APPEND gespeicherten
SHA-256-Inhaltsabdrucks und des Kontos ohne LLM als irrelevant abgeschlossen. Das verhindert
eine Rückkopplung, wenn der Entwurfsordner mit abgerufen wird. Ein Betreff oder eine Message-ID
allein lösen diese Ausnahme nicht aus; bearbeitete oder in ein anderes Konto kopierte Nachrichten
durchlaufen die normale Prüfung. Die Erkennung bleibt nach unterbrochener MIME-Vorbereitung erhalten.

`skip_empty: true` lässt Briefings ohne offene Karten, neue Zusammenfassungen oder Diagnosehinweis
aus und setzt trotzdem den Zeitfenster-Checkpoint. Mit `false` wird „Alles ruhig“ abgelegt.
Pro Inhaltsgruppe werden höchstens 50 Einträge gezeigt; ein Hinweis nennt weitere Einträge.

## Sicherheit und Rückkehr

Mailtexte werden HTML-escaped; das Briefing lädt keine externen Bilder oder Skripte.
Links führen ausschließlich zu lesenden Mail-/Vorschlagsseiten. Sie enthalten keine
Sitzung, Freigabetoken oder ausführende Aktion. Die bestehende Anmeldung und die separate,
versionsbezogene Bestätigung mit Sitzung, CSRF-Prüfung und Idempotenz gelten unverändert.
Vor APPEND werden Aktivierung, Uhrzeit und Zielkonto erneut geprüft. Logs enthalten nur
Slotkennung, Ausgang oder Fehlerklasse, keine Briefing-Inhalte oder Zugangsdaten.

Zum Abschalten `briefings.enabled: false` speichern. Vorhandene Entwürfe bleiben im Mailprogramm.
Bei einer Rückkehr zu 4.8 den neuen `briefings`-Block aus der Konfiguration entfernen und
`briefing_state.json` für ein späteres Upgrade sichern. Kalender-/Aufgabenzustände und die
Bestätigungsregeln benötigen keine Migration.

## Abnahme

Automatisierte Tests verwenden ausschließlich synthetische Daten und simulierte externe
Dienste; echte Postfächer werden nicht verändert.

| Prüfung | Ergebnis |
| --- | --- |
| Windows 11, Python 3.12.10 | 3.975 bestanden, ein POSIX-Berechtigungstest plattformbedingt übersprungen; anschließend 44 einschlägige Tests mit ergänzt erfasstem Randfall und plattformunabhängigen Replay-Prüfungen bestanden. Danach kein Anwendungscode geändert. |
| Zeilenabdeckung Windows | **26.074 / 26.074, 100 %** |
| Branch-Abdeckung Windows | **7.526 / 7.526, 100 %**, keine partiellen Zweige |
| Linux/Docker, Python 3.12.10 | **3.976 bestanden**, kein übersprungener Test; **26.074 / 26.074 Zeilen** und **7.526 / 7.526 Branches, jeweils 100 %**, keine partiellen Zweige |
| Browser-Gesamtsuite | **286 bestanden** auf Desktop, Mobilgerät und 320-Pixel-Ansicht; **100 % JavaScript-Blöcke** in `app.js`, `sw.js`, `setup.js` |
| Statische Prüfung | Ruff ohne Befunde; mypy ohne Befunde in **253 Quelldateien** |
| Paketprüfung | Wheel und sdist gebaut; zwei Paketprüfungen gegen das separat installierte Windows-Wheel bestanden |
| Prompt-Qualitätsgate | Drei synthetische Tests bestanden; Prompt-Fingerabdrücke unverändert |

Das globale automatische 100-%-Gate bleibt unverändert; es gibt keine neuen
Coverage-Ausschlüsse. Der zusätzliche Regressionstest gegen die Eigenbriefing-Rückkopplung
schlug vor der Korrektur fehl und besteht mit der Korrektur. Manipulierte Inhalte,
fremde Konten und ein Neustart nach MIME-Vorbereitung werden ebenfalls geprüft.

Die beiden Windows-Lasttests bestehen separat mit unveränderten Grenzen:
4.2 (fünf Browser) Median Warteschlange **352,2 ms**, Maximum **521,0 ms**;
4.4.1 (2.000 Mails) Median Antwortzeit **324,5 ms**, Maximum **331,4 ms**.
Beide Linux-Lasttests bestehen ebenfalls: 4.2 Median Warteschlange **24,4 ms**,
Maximum **34,7 ms**; 4.4.1 Median Antwortzeit **203,9 ms**, Maximum **307,7 ms**.

### Fachliche Nachweise

| Verhalten | Synthetischer Nachweis |
| --- | --- |
| Einstellungen und Zugriff | Ungültige/mehrfache Zeiten, Postfachbindung, Sitzung, CSRF, Dateiversion, Replay und Live-Übernahme |
| Zeitsteuerung | 07/13/18 Uhr, Werktage und Wochenende, heutiges Nachholen, Rückwärtsuhr und beide DST-Wechsel mit `time-machine` |
| Inhalt | Alle aktuellen offenen Karten, stabile Analysezeitpunkte, Fenstergrenzen, Fristen, Retention und beschädigte Akten ohne Änderung der Originaldateien |
| Darstellung | HTML-Escaping, Textalternative, große Listen, sichere Ursprungsadresse, nur lesende Links; Layout- und Kontrastprüfung auf drei Bildschirmgrößen |
| IMAP | Korrektes Zielkonto und MIME, `\Draft \Seen`, voller Ordner, Verbindungsverlust nach Annahme und Prozessabbruch; Abgleich ohne zweiten APPEND |
| Wiederholung | Eingefrorener Inhalt, feste Message-ID, ursprünglicher Ordner trotz geänderter Vorgabe, Konto-/Schalterprüfung unmittelbar vor APPEND |
| Keine externen Aktionen | Browserlinks führen zur Anmeldung beziehungsweise Prüfkarte; kein Kalendereintrag und keine Aufgabenanlage durch das Briefing |

### Reproduzierbare Prüfungen

```powershell
$env:COVERAGE_FILE = '.test-tmp/v49-windows-final/.coverage'
python -m pytest -n 4 --dist loadgroup -q --ignore=tests/services/test_v42_load.py --ignore=tests/services/test_v441_load.py --cov-report=term-missing --cov-report=json:.test-tmp/coverage-v49-windows-final.json
python -m pytest tests/services/test_v42_load.py tests/services/test_v441_load.py --no-cov -q -s
python -m pytest ui_tests --no-cov -q
python -m ruff check src tests ui_tests devtools
python -m mypy
python -m devtools.check prompts
python -m hatchling build
```

Unter Linux läuft dieselbe Python-Suite mit Python 3.12.10 in einem Docker-Container
ohne Netzwerkzugang, unter UID/GID 65532 und mit separatem temporären Zustand.
Nur öffentliche Projektdateien und die Release-Artefakte werden als Testeingang kopiert;
lokale Konfiguration, `.env` und Produktionszustand werden nicht eingebunden.
Die importierten Module stammen aus dem aktuellen `src`-Verzeichnis.
Lasttests laufen wegen ihres Laufzeitbudgets getrennt von der parallelen Coverage-Messung.

Die Abnahme belegt das Protokoll mit simuliertem IMAP und das Layout in Chrome.
Tests mit echten Postfächern oder einem echten Modell wurden nicht durchgeführt.
