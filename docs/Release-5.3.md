# Release 5.3 – Live-Suche, Hilfschat und geprüfte Dokumentation

Versionen 5.3.0 bis 5.3.11, 10. November 2026. Grundlage: [Planung 5.3](Planung-5.3.md);
Nachweise der Dokumentationsprüfung: [Prüfbericht 5.3](Pruefung-Dokumentation-5.3.md).

5.3 hilft beim Finden und Verstehen von Einstellungen: Treffer erscheinen beim Tippen, ein
Hilfschat erklärt Einstellungen und Abläufe mit der geprüften, mitgelieferten Dokumentation, und
die Dokumentation selbst ist vollständig gegen den Code abgeglichen. Der Chat erklärt nur; er
ändert keine Einstellungen, Konten oder externen Daten. Jede Kalender- oder Aufgabenanlage
braucht weiterhin die ausdrückliche, versionsbezogene Bestätigung.

## Neu

| Version | Schritt | Änderung |
| --- | --- | --- |
| 5.3.0 | H1 | Bestandsaufnahme: aus dem Code erzeugte Inventur aller 229 Einstellungen und Kommandozeilenoptionen (`python -m devtools.inventory`), Funktionsinventur der Weboberfläche, festgelegte Verträge |
| 5.3.1 | H2 | Vollständige Einstellungsreferenz (117 Einträge neu); Grenzen, Standards und Vollständigkeit automatisch gegen den Code geprüft |
| 5.3.2 | H3 | Gemeinsamer Suchkatalog mit Synonymen, Sonderseiten, Rangfolge und stabilen Feldankern |
| 5.3.3 | H4 | Live-Suche ab dem ersten Zeichen mit authentifiziertem Endpunkt |
| 5.3.4 | H5 | Anleitungen [Ersteinrichtung](Ersteinrichtung.md) und [Konten verwalten](Konten-verwalten.md) |
| 5.3.5 | H6 | Anleitungen [Ziele einrichten](Ziele-einrichten.md), [Bedienung](Bedienung.md), [Fehlerbehebung](Fehlerbehebung.md), [Betrieb](Betrieb.md) |
| 5.3.6 | H7 | Dokumentation als versionsgebundene Paketressource, lokaler Leser `/hilfe/dokumentation`, deterministische Kontextauswahl |
| 5.3.7 | H8 | Prompt-Schritt `settings_help` mit Routenreferenz auf `action_router` und Quellenvertrag |
| 5.3.8 | H9 | Sitzungsgebundener Chatdienst mit Aufträgen, Versionen, Idempotenz, Grenzen, Neustartverhalten und Bereinigung |
| 5.3.9 | H10 | Chatseite **Hilfe zu Einstellungen** mit „Dazu fragen“, Quellenlinks und Betrieb ohne JavaScript |
| 5.3.10 | H11 | Fragenkorpus (40 Fälle), Abnahmematrix, Paketbetrieb außerhalb des Checkouts |
| 5.3.11 | H12 | Abnahme und dieser Bericht |

### Während der Prüfung gefundene und behobene Fehler

- Aufbewahrungshilfen nannten offene Vorgänge „geschätzt“ statt „geschützt“ (Regressionstest).
- Die neue Ersteinrichtungsanleitung nannte eine Schaltfläche „Bestätigen“, die es in der
  Weboberfläche nicht gibt; ein Test prüft seither jede genannte Bedienbezeichnung.
- Fehlende Wertebereiche und Standards in der Referenz, beschädigte Umlaute in einer Tabelle.
- Die Kontextauswahl fand bei mehreren Alltagsfragen keinen Abschnitt (Wortformen, Synonyme,
  seltene Fachwörter); der Korpus sichert die Verbesserung ab.

## Einrichtung, Upgrade und Rückkehr

Neu in `config.yaml` (Standardwerte, keine Pflicht):

```yaml
help_chat:
  enabled: true
  max_question_chars: 4000
  max_context_bytes: 24000
  requests_per_minute_per_session: 6
```

Für den Hilfschat den Block `settings_help` aus der mitgelieferten `prompts.yaml` in eine eigene
`prompts.yaml` übernehmen; er wird nicht still eingefügt. Ohne ihn bleibt der übrige Betrieb
unverändert, und der Chat nennt einen Einrichtungshinweis. Der Schritt ändert den Fingerprint
der Mail-Analyse nicht: Vorhandene Mails werden nicht neu analysiert, Lernläufe bleiben gültig.
Prompt-Gate und Qualitätsgrundlage 5.1 bewerten `prompts.yaml` ohne diesen Schritt.

Rückkehr zu 5.2: den Block `help_chat` entfernen; `help-chat-*.json` im Zustandsverzeichnis
werden von 5.2 nicht gelesen und können gelöscht werden. Der Schritt `settings_help` in
`prompts.yaml` muss für 5.2 entfernt werden, da 5.2 ihn nicht kennt.

## Abnahme

| Prüfung | Ergebnis |
| --- | --- |
| Windows 11, Python 3.12.10 | **4.476 bestanden**, ein POSIX-Berechtigungstest plattformbedingt übersprungen (Lasttests getrennt) |
| Zeilenabdeckung Windows | **28.904 / 28.904, 100 %** |
| Branch-Abdeckung Windows | **8.396 / 8.396, 100 %**, keine partiellen Zweige |
| Browser-Gesamtsuite | **351 von 351 bestanden** auf Desktop, Mobilgerät und 320-Pixel-Ansicht mit 44-px- und axe-core-Prüfung |
| Live-Suche | 100 von 100 Suchläufen innerhalb von 300 ms (Median 217,8 ms, 95. Perzentil 240,9 ms), kein KI-Aufruf |
| Statische Prüfung | Ruff ohne Befunde; mypy ohne Befunde in **271 Quelldateien** |
| Prompt-Qualitätsgate | bestanden; Fingerprints der Mail-Analyse unverändert |
| Paketprüfung | Wheel und sdist gebaut; Hilfebestand im Wheel, außerhalb des Checkouts lauffähig |
| Linux/Docker | **Nicht durchgeführt**: Docker war auf dem Prüfrechner nicht verfügbar. Ersteinrichtung über `compose.setup.yaml` und der Paketbetrieb im Image sind dort nachzuholen. |

Lasttests einzeln, Grenzen unverändert: 4.2 (fünf Browser) Median Warteschlange **276,6 ms**,
Maximum **438,4 ms**; 4.4.1 (2.000 Mails) Median Antwortzeit **335,8 ms**, Maximum **425,3 ms**.

## Grenzen

- **Modellqualität nicht nachgewiesen.** Alle Tests verwenden simulierte Antworten; der Korpus
  prüft deterministisch Kontextauswahl und Quellenvertrag. Die in Planung 14 geforderte Bewertung
  echter Modellantworten (mindestens 90 % richtig) braucht eine ausdrückliche Freigabe für Modell,
  Datenübertragung und Kosten und wurde nicht durchgeführt.
- **Bedienform des Chats:** Der Chat ist eine eigene Seite, erreichbar über „Hilfe zu
  Einstellungen“ und „Dazu fragen“. Ein einklappbarer Hilfebereich neben dem Inhalt auf großen
  Bildschirmen (Planung 3) wurde nicht umgesetzt; auf allen Geräten gilt dieselbe Seite.
- **Prozessabbrüche** des Chats sind prozessintern simuliert (offene Fragen werden nach dem
  Neustart „unterbrochen“, nie erneut gesendet); ein harter Prozessabbruchtest fehlt.
- Die Verständlichkeitsprüfung hat alle neuen Texte nach dem Standard der Planung verfasst und alle
  Zahlenangaben automatisch abgeglichen; ältere Feldhilfen wurden nicht einzeln sprachlich neu
  gefasst. Anbieterangaben (OAuth, App-Passwörter) beruhen auf den vorhandenen Adaptern und ihren
  Fehlermeldungen; eine erneute Prüfung der Anbieterunterlagen mit Datum steht aus.

### Reproduzierbare Prüfungen

```powershell
python -m pytest -n 8 --dist loadgroup -q --ignore=tests/services/test_v42_load.py --ignore=tests/services/test_v441_load.py
python -m pytest tests/services/test_v42_load.py tests/services/test_v441_load.py --no-cov -q -s
python -m pytest ui_tests --no-cov -q
python -m ruff check src tests ui_tests devtools
python -m mypy
python -m devtools.check prompts
python -m devtools.inventory --check
python -m devtools.help_index --check
python -m hatchling build
```
