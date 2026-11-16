# Mailhelp 7.1 – Demo-Modus

Geprüft für Mailhelp 7.1.

Umsetzung von [Planung 7.1](Planung-7.1.md). Ergänzung des Auftraggebers vom 16. November 2026:
Der Beispielbestand umfasst neben den zehn Mails für die gezeigten Abläufe 20 nicht relevante
Mails (30 Mails); der einmalige Erzeugungslauf über OpenRouter ist freigegeben.

## 7.1.1 – Startmodus und Verzeichnisgrenze (D1)

- `mailhelp --demo` und `mailhelp -demo` setzen denselben Startmodus. Er lässt sich mit keiner
  anderen Option kombinieren (Fehler mit Exitcode 2, Liste der störenden Optionen).
- Das Laufzeitverzeichnis muss beim ersten Start leer sein und erhält die Markierung
  `mailhelp-demo.json`. Ein Verzeichnis mit Konfiguration, `.env` oder anderen Dateien wird
  abgelehnt; eine beschädigte oder fremde Markierung ebenfalls. Umgekehrt lehnt der normale Start
  (auch `--check` und die Ersteinrichtung) ein Demo-Verzeichnis ab.
- Der Web-Schlüssel wird beim ersten Start erzeugt und in `demo-secret` gespeichert; Besucher geben
  keinen Schlüssel an. Port, Adresse und Hostnamen kommen aus `MAILHELP_DEMO_PORT`,
  `MAILHELP_DEMO_HOST` (Standard nur lokal) und `MAILHELP_DEMO_ALLOWED_HOSTS`.
- Der Server zeigt die Anmeldeseite „Gerät koppeln“ mit dem Demo-Hinweis, ohne Telegram-Code,
  Konsolenweg oder Passwort. „Demo starten“ folgt mit dem Beispielbestand (D3/D4).

Tests: `tests/web/test_demo_mode.py` (Aliasse, Kombinationen, leeres, fremdes und beschädigtes
Verzeichnis, Wiederstart, Schlüssel, Einstellungen, Normalstart unverändert).

Prüfung: 5 474 Python-Tests mit voller Abdeckung; Browser 922 bestanden, einmal scheiterte
`test_a_card_being_processed_cannot_be_swiped_again[drift-mobile]` unter Last und bestand danach
sechsmal einzeln (die normale Oberfläche ist in 7.1.1 unverändert).
