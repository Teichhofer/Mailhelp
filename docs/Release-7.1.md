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

## 7.1.3 – Besucherbereiche, Demo-Start und lokale Ziele (D3, D4, Teile von D5)

- **Bestand prüfen und kopieren** (`runtime/demo_dataset.py`): Das Manifest wird streng geprüft
  (Version, genau 30 eindeutige Mails, nur relative `.json`-Pfade, SHA-256 jeder Datei). Die
  Zustandsdateien werden in einen Zwischenordner kopiert, dort erneut geprüft und erst dann
  umbenannt; ein Abbruch hinterlässt keinen halben Bereich.
- **Besucherbereiche** (`runtime/demo_visitors.py`): Die Sitzung bestimmt den Bereich, nie ein
  Pfad, Cookie oder Formularfeld. Derselbe Startschlüssel ergibt denselben Bereich; ein fremder
  Schlüssel wird abgelehnt. Höchstens 50 Bereiche; ist alles belegt, erklärt die Seite das, und kein
  fremder Bereich wird gelöscht. „Zurücksetzen“ und die Bereinigung abgelaufener Sitzungen sind
  vorbereitet (Oberfläche folgt).
- **Demo starten** (`web/demo_site.py`): Die Anmeldeseite bietet nur „Demo starten“; der POST prüft
  CSRF und Idempotenzschlüssel und öffnet eine Sitzung von zwei Stunden. `WebAuth.demo_session` gibt
  es nur hierfür; die Sitzungsgrenze ist dafür ein Attribut (`max_sessions`, sonst unverändert 20).
- **Normale Oberfläche je Besucher** (`app/demo.py`): je Bereich Store, Befehlseingang, Dialog im
  Testmodus und `MailhelpSite`; ein Arbeitsfaden führt Web-Aktionen aus wie der Hauptthread einer
  normalen Instanz. Der Dialog erhält einen Telegram-Eingang, damit er nie auf Telegram wartet.
- **Gesperrte Wege**: Einrichtung, Zugangsdaten, Postfächer, IServ, Zielprofile, Geräte, Push,
  Diagnose, Hilfschat, Tätigkeitsberichte, Regel- und Postfachlernen, Antwortentwürfe, Neustart und
  Beenden antworten mit 403 „In der Demo nicht verfügbar“, auch bei direktem Aufruf.
- **Lokale Ziele**: Kalender und Aufgabenliste sind ein Demo-Ziel, das jeden echten Schreibversuch
  ablehnt; im Testmodus endet eine Bestätigung als „simuliert“ im eigenen Bereich.

- **Neustart** (Vorgabe vom 16. November 2026): Ein Neustart über die Weboberfläche startet Mailhelp
  mit denselben Startparametern, im Demo-Modus also wieder die Demo. Das galt schon (`cli._restart`
  übergibt `sys.argv`); `test_a_restart_keeps_every_start_parameter_also_in_the_demo_mode` sichert es
  für `--demo` und `-demo` auf beiden Neustartwegen ab. In der Demo selbst ist der Neustart über die
  Oberfläche für Besucher gesperrt.

Tests: `tests/unit/test_demo_visitors.py`, `tests/web/test_demo_site.py` (Start, Wiederholung, zwei
Besucher, falsche Anfragen, volle Demo, gesperrte Wege, Bestätigung nur im eigenen Bereich).
Offen für die nächsten Patches: Beschriftung „In der Demo angelegt“, vorbereitete Rückfrage-Antworten,
„Demo neu starten“, Ablauf und Bereinigung im Betrieb, Startgrenzen je Client, Demozeit,
Browsertests und Docker.

## 7.1.4 – Vorbereitete Antworten, Neustart der Demo, Grenzen und Browserprüfung (D5, D6)

- **Vorbereitete Rückfrage-Antworten** (`runtime/demo_answers.py`): Der Erzeugungslauf beantwortet
  drei Rückfragen über den normalen Antwortweg (Web-Befehl „Antwort“, echter Dialog, echtes Modell)
  und zeichnet die Aufrufe des Antwortdienstes in `answers.json` auf (im Manifest mit Prüfsumme).
  Zur Laufzeit liefert die Demo für dieselbe Frage, Antwort und Vorschlagsversion genau das
  aufgezeichnete Ergebnis. Jede andere Antwort lehnt sie mit einem Hinweis auf die Demo-Grenze ab,
  ohne Modell und ohne erfundenes Ergebnis. Das Antwortfeld ist mit der vorbereiteten Antwort
  vorbelegt („In der Demo vorbereitet“). Zeitangaben, die Mailhelp ohne KI auswertet, funktionieren
  wie sonst.
- **Beschriftungen**: „Simulieren“ heißt in der Demo „In der Demo anlegen“, simulierte Ergebnisse
  „In der Demo angelegt“; die Ersetzungen gelten nur für Texte, die im Code vorkommen (Test).
- **Demo neu starten**: Jede Seite trägt den Demo-Hinweis mit dem Verweis „Demo neu starten“. Nach
  einer Bestätigungsseite (CSRF an die Sitzung gebunden, Idempotenzschlüssel) wird nur der eigene
  Bereich neu aus dem Bestand kopiert; andere Besucher bleiben unberührt.
- **Grenzen**: höchstens 5 Starts je Client und 60 insgesamt pro Stunde. Der Client ist die
  Socket-Adresse; `X-Forwarded-For` gilt nur mit `MAILHELP_DEMO_TRUST_PROXY=1` (hinter dem eigenen
  Reverse Proxy), und dann nur der letzte Eintrag, den der Proxy anhängt. Frühere Einträge kann der
  Besucher frei setzen; mit ihnen ließe sich die Grenze umgehen (Regressionstest). Die Werte sind im Code festgelegt, weil die Demo keine `config.yaml` besitzt
  (Abweichung vom Plan, der sie dort vorsah).
- **Ablauf und Bereinigung**: Der Arbeitsfaden entfernt jede Minute die Bereiche abgelaufener
  Sitzungen und verwaiste Verzeichnisse. Eine abgelaufene Sitzung führt keinen Befehl mehr aus.
- **Neuer Bestand**: Mit der Antwortphase wurde der Bestand neu erzeugt (30 Mails,
  109 Zustandsdateien, vier aufgezeichnete Aufrufe). Jetzt entsteht auch Nr. 8: Die private Nachricht
  „wegen Samstag“ wird als „unklar“ eingestuft und zeigt die offene Relevanzentscheidung. Damit
  sind alle zehn Fälle des Plans erreicht: acht relevante Mails, eine unklare, 21 irrelevante. Nr. 3
  ergibt jetzt die Aufgabe „Bastelkleber und Fotokarton besorgen“ und den Workshop-Termin mit
  Rückfrage; die übrigen Zeilen der Tabelle in 7.1.2 gelten unverändert.

**Abweichung Demozeit.** Der Plan (6.3) lässt die fachliche Zeit an der Referenzzeit beginnen. Die
Oberfläche und die Fristen lesen die Zeit an 17 Stellen direkt; eine gemeinsame Uhr dafür wäre ein
eigener Umbau. Die Demo läuft deshalb in der echten Zeit. Die Beispieltermine liegen nach der
Referenzzeit (16. November 2026) im November und Dezember 2026; nach diesen Daten muss der Bestand
neu erzeugt werden.

Tests: `tests/web/test_demo_site.py` (vorbereitete Antworten, Beschriftungen, Neustart, Grenzen,
Bereinigung, Arbeitsfaden), `tests/release/test_demo_dataset.py` (Antwortphase und Export) und die
Browserprüfung `ui_tests/test_ui_demo.py`: Demo starten ohne Telegram, in der eigenen Kopie
bestätigen (Desktop, Telefon, schmal), vorbereitete Antwort und Neustart, gesperrte Wege, zwei
getrennte Browserkontexte, WebKit auf einem iPhone-Profil.

Prüfung: 5 541 Python-Tests mit 100 % Zeilen- und Branch-Abdeckung; Browser 932 bestanden ohne
Fehler.

