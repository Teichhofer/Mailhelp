# Release 5.2 – Aufgaben und Termine nach dem Eintragen überprüfen

Versionen 5.2.0 bis 5.2.9, 10. November 2026. Grundlage: [Planung 5.2](Planung-5.2.md).

Nach jeder Eintragung ruft Mailhelp die konkrete Aufgabe oder den konkreten Termin frisch beim
Anbieter ab. Erst wenn dieser Lesezugriff den Eintrag mit den bestätigten Angaben nachweist,
heißt es **„Angelegt und geprüft“**. Wiederholt werden nur Lesezugriffe: Keine Prüfung führt je
zu einer zweiten Anlage, einer Reparatur, Änderung oder Löschung. Vor jedem Schreibzugriff ist
weiterhin die ausdrückliche, versionsbezogene Bestätigung nötig.

## Neu

| Version | Schritt | Änderung |
| --- | --- | --- |
| 5.2.0 | V1 | Status `VERIFYING` („Gespeichert – Eintrag wird geprüft“), Prüfnachweis `write-verification-<id>.json`, erlaubte Übergänge; alle Statusverbraucher behandeln ihn sicher. |
| 5.2.1 | V2–V4 | Gemeinsamer Ablauf: Schreibabsicht vor, Schreibbeleg nach dem Schreiben, beides vor dem ersten Abruf; `CREATED` nur nach bestandenem Abruf. Google Kalender und Todoist mit Einzelabruf (erledigte Todoist-Aufgaben gelten als vorhanden). Konfiguration `write_verification`. |
| 5.2.2 | V5 | Outlook-Kalender und Microsoft To Do (tagesgenau, weil To Do nur den Tag speichert). |
| 5.2.3 | V6 | CalDAV-Kalender, CalDAV-Aufgaben, Apple Erinnerungen mit UID-Prüfung; nur Ressourcen der gebundenen Sammlung. |
| 5.2.4 | V7 | Änderung, Ergänzung, Absage, erkannte Dublette; Kalenderdatei als „bereitgestellt – Übernahme nicht prüfbar“. |
| 5.2.5 | V8 | `Retry-After`, höchstens eine Prüfung je Operation, keine Netzwerkzugriffe unter Zustandssperren. |
| 5.2.6 | V9 | Prüfstand in Web und Telegram mit Soll/Ist-Tabelle; geschütztes „Erneut prüfen“ (nur Lesen). |
| 5.2.7 | V10 | Aufbewahrung der Prüfnachweise, ungeprüfte Altbestände, Testmodus, `mailhelp --prepare-rollback`. |
| 5.2.8 | V11 | Anbieter-/Fehlermatrix über alle sieben Online-Adapter und harte Prozessabbrüche. |
| 5.2.9 | V12 | Abnahme und dieser Bericht. |

Die Schritte V2 bis V4 wurden gemeinsam als 5.2.1 umgesetzt, damit ein zwischenzeitlicher
Neustart nie Einträge ohne passenden Abruf auf „wird geprüft“ hinterlässt; die folgenden
Schritte rückten je eine Patchversion vor.

### Während der Entwicklung gefunden

- Ein nach unklarem Schreiben wiedergefundener Eintrag einer anderen Operation (z. B. einer
  ergänzten Dublette) wäre mit dem Sollstand einer Neuanlage verglichen worden. Seitdem wird
  jede Operation mit ihrer vor dem Schreiben gespeicherten Schreibabsicht geprüft.
- Nach „Bestätigen“ meldete die Weboberfläche „Angelegt.“, obwohl die Prüfung noch ausstand.

## Einrichtung, Upgrade und Rückkehr

Neu in `config.yaml` (Standardwerte, keine Pflicht):

```yaml
write_verification:
  max_attempts: 5                      # der erste Abruf ist Versuch 1
  retry_delays_seconds: [1, 5, 15, 60] # Wartezeit vor Versuch 2 bis 5
  max_elapsed_seconds: 300             # danach bleibt der Eintrag ausdrücklich ungeprüft
```

Nach dem Update den Dienst neu starten (vorher beenden, wenn das Paket in derselben virtuellen
Umgebung neu installiert wird). Es gibt keine Migration und keine Massenabfrage: Vor 5.2
angelegte Einträge bleiben „Angelegt“ und werden nicht rückwirkend geprüft. Die Prüfnachweise
gehören zur Sicherung und folgen der Frist `retention.full_mail_days`.

Rückkehr: 5.2.0 bis 5.2.5 lesen alle Zustände, kennen aber den Befehl „Erneut prüfen“ nicht.
Für eine Rückkehr zu einer Version vor 5.2.0 den Dienst beenden und `mailhelp --prepare-rollback`
ausführen; er stellt jeden Eintrag „wird geprüft“ auf „angelegt“ um (externe ID bleibt) und
verweigert, solange eine „Erneut prüfen“-Aktion wartet. Ältere Versionen schreiben angelegte
Einträge nie erneut.

## Abnahme

Automatisierte Tests verwenden ausschließlich synthetische Daten und simulierte Dienste; jeder
Anbieteradapter wird mit seinem tatsächlichen HTTP- bzw. CalDAV-Transport geprüft.

| Prüfung | Ergebnis |
| --- | --- |
| Windows 11, Python 3.12.10 | **4.349 bestanden**, ein POSIX-Berechtigungstest plattformbedingt übersprungen (Lasttests getrennt) |
| Zeilenabdeckung Windows | **28.064 / 28.064, 100 %** |
| Branch-Abdeckung Windows | **8.156 / 8.156, 100 %**, keine partiellen Zweige |
| Browser-Gesamtsuite | **334 von 335 bestanden** auf Desktop, Mobilgerät und 320-Pixel-Ansicht mit 44-px- und axe-core-Prüfung; der eine zeitkritische Test (`test_ui_reconciliation`, ohne JavaScript) besteht einzeln dreimal hintereinander. In 5.2.6 lief die Suite mit 335 von 335. |
| Statische Prüfung | Ruff ohne Befunde; mypy ohne Befunde in **265 Quelldateien** |
| Prompt-Qualitätsgate | Drei synthetische Tests bestanden; Prompts unverändert |
| Paketprüfung | Wheel und sdist gebaut, Paketprüfungen bestanden |
| Harte Prozessabbrüche | Windows, echter Kindprozess mit `kill`: vor dem ersten Abruf und nach bestandenem Abruf, je sieben Anbieter |
| Linux/Docker | **Nicht durchgeführt**: Docker war auf dem Abnahmerechner nicht verfügbar. Nachzuholen, bevor 5.2 als plattformübergreifend geprüft gilt; die harten Prozessabbrüche sind dort besonders zu wiederholen. |

Lasttests einzeln, Grenzen unverändert: 4.2 (fünf Browser) Median Warteschlange **336,4 ms**,
Maximum **502,5 ms**; 4.4.1 (2.000 Mails) Median Antwortzeit **334,6 ms**, Maximum **341,2 ms**.

### Anbieter und Operationen

| Anbieter | Neuanlage | Änderung / Ergänzung / Dublette / Absage | Nachweis |
| --- | --- | --- | --- |
| Google Kalender | Einzelabruf im gebundenen Kalender | ja | `test_entry_readers`, `test_write_verification_operations`, Matrix |
| Todoist | Einzelabruf, erledigte Aufgaben über die erledigten des Projekts | – (keine Aufgabenänderung) | `test_entry_readers`, Matrix |
| Outlook-Kalender | Graph-Einzelabruf, `isCancelled` | ja (gemeinsamer Kalenderablauf) | `test_microsoft_readers`, Matrix |
| Microsoft To Do | Graph-Einzelabruf, tagesgenau | – | `test_microsoft_readers`, Matrix |
| CalDAV-Kalender | Ressource mit UID | ja | `test_caldav_readers`, Matrix |
| CalDAV-Aufgaben / Apple Erinnerungen | Ressource mit UID, VTODO | – | `test_caldav_readers`, Matrix |
| Kalenderdatei (Telegram) | `unsupported` | – | `test_write_verification_operations`, `test_telegram_dialog` |

### Fachliche Nachweise (Abnahmefälle der Planung)

| Fall | Nachweis |
| --- | --- |
| Schreiben erfolgreich, Abruf korrekt | ein Schreibversuch, mindestens ein frischer Abruf, „Angelegt und geprüft“ (Matrix „korrekt“) |
| ID vorhanden, Abruf liefert andere Fälligkeit/Zeit | keine Erfolgsmeldung, konkrete Abweichung, keine Änderung oder Neuanlage (`test_write_verification_flow`, Matrix „Titel“) |
| erst 404, später sichtbar | nur Lese-Wiederholungen, derselbe Eintrag (Matrix „spaeter_sichtbar“) |
| bleibt 404 oder nicht erreichbar | begrenzte Versuche, ungeprüfter Endstand, kein zweiter Schreibversuch (Matrix) |
| 401/403/429/5xx/ungültig | korrekt unterschieden, nie als Löschung gewertet; `Retry-After` beachtet (Matrix, `test_write_verification_retries`) |
| Absturz vor bzw. nach ID-Speicherung oder nach bestandenem Abruf | Wiederfinden über den Schlüssel bzw. Fortsetzung; keine Doppelanlage oder doppelte Meldung (Hard-Kill-Tests, `test_write_verification_flow`) |
| Cache passend, frischer Abruf abweichend | der frische Abruf entscheidet (`test_a_cached_list_never_replaces_the_fresh_read`) |
| Ziel/Konto geändert | Prüfung gestoppt, kein Ausweichen (`target_changed`, `account_changed`) |
| neue Version oder parallele Prüfaktion | altes Ergebnis bestätigt keine neue Version; höchstens eine Prüfung je Operation |
| abgelaufene Sitzung, falscher CSRF-Wert, wiederholter Schlüssel | abgelehnt bzw. idempotent (`test_verification_web`) |
| bereits erledigte Aufgabe | gilt als vorhanden (Todoist, To Do, CalDAV) |
| Ganztag, UTC/Offset, Sommerzeit, fehlende Fälligkeit | fachlich korrekter Vergleich (`test_entry_comparison`, `test_entry_readers`) |
| Absage oder Dublette ohne neuen Schreibzugriff | operationsgerechter Nachweis und Meldung (`test_write_verification_operations`) |
| Testmodus, Kalenderdatei, Altbestand | keine Zugriffe; „nicht prüfbar“; „nicht nachgeprüft“ (`test_write_verification_upgrade`) |

### Grenzen

- Tests mit echten Konten bei Google, Todoist, Microsoft, CalDAV-Servern oder iCloud wurden nicht
  durchgeführt. Das Antwortverhalten (etwa ob Todoist eine erledigte Aufgabe über den
  Einzelabruf liefert) beruht auf der Anbieterdokumentation; die Adapter werten beide Varianten aus.
- Microsoft To Do wird nur tagesgenau geprüft, weil der Dienst keine Uhrzeit speichert.
- Für CalDAV dient der konfigurierte Benutzer am Server als Kontobindung; der Server bietet keine
  einheitliche Kontokennung.
- Ob eine Kalenderdatei in einen Kalender übernommen wurde, ist grundsätzlich nicht prüfbar.

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
