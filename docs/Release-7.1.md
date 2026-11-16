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

## 7.1.2 – Beispielbestand aus dem echten Verarbeitungspfad (D2)

**Werkzeug.** `python -m devtools.demo.dataset --env .env` erzeugt eine Wegwerf-Konfiguration für
die Demo-Persona (Alex Beispiel; Testmodus, ohne Telegram, Weboberfläche nur konfiguriert und nie
gestartet), baut die Anwendung mit `build_application` wie `mailhelp` selbst und übergibt die Mails
am normalen Eingang (`Orchestrator.process`). Ersetzt ist nur der Postfachtransport. Die
Dublettenprüfung erhält kein Ziel; Kalender und Aufgabenlisten werden weder gelesen noch beschrieben.
Aus `.env` liest das Werkzeug nur `OPENROUTER_API_KEY`; der Schlüssel landet nicht im Ergebnis.

**Mails.** `devtools/demo/mails.py` enthält die 30 synthetischen Mails: zehn für die Abläufe des
Plans und 20 nicht relevante (Werbung, Newsletter, Automatikmeldungen). Alle Adressen liegen unter
reservierten `.example`-Domains.

**Ergebnis** (`src/mailhelp/defaults/demo/standard-v1`, Modell `deepseek/deepseek-v4.1-flash`):
30 Originalmails, 104 Zustandsdateien und ein Manifest mit Prüfsummen, Referenzzeit
16. November 2026, 9:00 Uhr, Quellcommit und Analyse-Fingerabdruck. Fachlich geprüft:

| Nr. | Ziel aus dem Plan | Ergebnis im echten Pfad |
| ---: | :--- | :--- |
| 1 | klarer Termin | Termin „Elternabend der Klasse 4b“, 26. 11., 19:30 Uhr, zur Bestätigung |
| 2 | Aufgabe mit Frist | Aufgabe „Einverständniserklärung … zurückgeben“, fällig 20. 11.; dazu Termin „Ausflug ins Planetarium“ mit Rückfrage zur Uhrzeit |
| 3 | Aufgabe ohne feste Uhrzeit | Aufgabe „Bastelmaterial besorgen und mitbringen“, fällig 21. 11.; Workshop-Termin mit Rückfrage |
| 4 | mehrere Vorschläge | Termin „Adventsbasar“ und Aufgabe „Kuchenspende anmelden“ (Rückfrage zur Zuständigkeit) |
| 5 | Terminänderung | als Änderung erkannt; Rückfrage „Welcher bestehende Eintrag soll geändert werden?“, weil im (leeren) Kalender kein Elternabend steht |
| 6 | Dubletten-/Zuordnungsprüfung | Aufgabe zur Erinnerung; der Ausflugstermin wurde mit dem bestehenden Vorschlag zusammengeführt |
| 7 | Rückfrage statt Anlage | Termin „Vorspielnachmittag“ mit Rückfrage „Wann beginnt der Termin?“ |
| 8 | offene Relevanzentscheidung | **nicht erreicht**: irrelevant (siehe unten) |
| 9 | relevant ohne Anlage | relevant, kein Vorschlag |
| 10 | Werbung | irrelevant, kein Vorschlag |
| 11–30 | nicht relevant | alle 20 irrelevant, kein Vorschlag |

**Abweichung Nr. 8.** Der Plan verlangt, die Eingangsmail anzupassen, wenn ein Fall nicht entsteht.
Drei Fassungen (Hausgemeinschaft ohne Zuständigkeit, Fahrgemeinschaft einer Mannschaft, private
Absprache mit möglichem Bezug zum Basar) ergaben „irrelevant“ oder „relevant“, nie „unklar“; das
Modell ordnet nicht belegte Bezüge als irrelevant ein. Die letzte Fassung bleibt im Bestand und zeigt
das Aussortieren einer privaten Nachricht ohne Themenbezug. Vorschläge wurden nicht von Hand
nachgebessert. **Abweichung Nr. 5.** Eine Verknüpfung mit dem offenen Vorschlag aus Nr. 1
entstand nicht; die Rückfrage nach dem bestehenden Eintrag ist das tatsächliche Verhalten.

Insgesamt fünf Erzeugungsläufe (Anpassung von Nr. 5 und Nr. 8) mit je 30 Mails, jeweils rund
3,5 Minuten. Automatische Tests ersetzen die Anwendung und rufen nie ein Modell auf
(`tests/release/test_demo_dataset.py`).

**Zeilenenden.** `.gitattributes` nimmt `src/mailhelp/defaults/demo/` von der Umwandlung der
Zeilenenden aus. Sonst schriebe ein Windows-Checkout die Dateien um, und die Prüfsummen im Manifest
stimmten nicht mehr.

Prüfung: 5 482 Python-Tests mit voller Abdeckung; Browser 921 bestanden, zwei Lastfehler
(Live-Suche und ein weiterer) bestanden im Wiederholungslauf.
