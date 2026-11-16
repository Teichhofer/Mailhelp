# Mailhelp 7.2 – Notion und Google Tasks als Aufgabenziele

Geprüft für Mailhelp 7.2.

Umsetzung von [Planung 7.2](Planung-7.2.md). Zwischenstand: Google Tasks ist ab 7.2.1 als
Aufgabenziel nutzbar; Notion folgt. Der Plan ist erst mit der Abnahme in 7.2.5 erfüllt.

## 7.2.1 – Google Tasks, Fähigkeit „Entfernen“, Anmelderechte (P1, P2)

**Bestandsaufnahme nach 7.1 (P1).** Aufgabenziele sind `TargetWriter` mit `check_access`,
`reconcile`, `prepare`, Lesevertrag (`account_binding`, `expected_facts`, `read_entry`) und
`fetch_active_tasks`. Das Lesemodell `TodoistTaskResponse` wird schon von Microsoft To Do und CalDAV
als neutrales Aufgabenmodell genutzt; es bleibt, ein Umbenennen brächte nur Umbau ohne Wirkung.
Die Konfiguration bleibt abwärtskompatibel: Neue Felder haben Standardwerte, bestehende Dateien
laden unverändert, und die Analyse-Fingerabdrücke aller früheren Versionen bleiben gleich
(`google_tasks_list` und `timeouts.google_tasks` zählen nicht zur Analyse).

**Fähigkeit statt Anbietername.** `TargetWriter.supports_remove` sagt, ob „Wieder entfernen“
angeboten wird. Web, Telegram und der Befehl selbst fragen nur diese Fähigkeit ab. Nur Kalender und
Todoist entfernen sicher. Google Tasks bietet keine Bedingung, die ein Löschen gegen eine Änderung
nach dem letzten Lesen schützt. **Fehlerkorrektur:** Bei Microsoft To Do, CalDAV-Aufgaben und
Apple Erinnerungen wurde „Wieder entfernen“ bisher angezeigt, und der Befehl scheiterte intern mit
`NotImplementedError`. Jetzt fehlt die Aktion, und ein direkter Befehl wird mit Hinweis abgelehnt
(Regressionstests in `tests/external/test_providers.py`, `tests/review/test_remove_created.py`,
`tests/web/test_remove_created_web.py`, `tests/release/test_deployment_edges.py`).

**Google Tasks (P2)** (`external/google_tasks.py`):

- Ziel `targets.task_provider: google_tasks` mit `targets.google_tasks_list` (Listen-ID oder
  `@default`), ebenso in Zielprofilen. Zeitlimits unter `timeouts.google_tasks`.
- Anlage mit Titel, Notizen und Status „offen“. Der Vorgangsschlüssel `[mailhelp:…]` steht in den
  Notizen. Die Kontobindung ist die tatsächliche Listen-ID, nie der Alias `@default`.
- Datum: Google speichert nur einen Tag. Mailhelp schreibt den bestätigten Tag in der
  konfigurierten Zeitzone, eine Zeitumstellung verschiebt ihn nicht. Eine genaue Frist steht
  zusätzlich lesbar im Text. Ohne Frist bleibt das Datum leer, es gibt kein erfundenes „heute“.
- Längen: Titel (höchstens 500) und Beschreibung (höchstens 4 000) eines Vorschlags liegen mit
  Fristzeile und Schlüssel sicher unter Googles Grenzen (1 024 und 8 192). Gekürzt wird nie; ein
  Test hält das fest.
- Abgleich: alle Seiten der Liste einschließlich erledigter, ausgeblendeter und gelöschter
  Aufgaben. Ein doppelt gefundener Schlüssel oder eine zu lange Liste (mehr als 100 Seiten) bleiben
  unklar; es folgt kein zweiter POST. Ein unklarer POST (Zeitüberschreitung, 5xx) wird nie blind
  wiederholt.
- Fehler nach strukturiertem Grund, nie nach Meldungstext: API nicht aktiviert, fehlendes Recht,
  Liste fehlt, Anmeldung abgelehnt. Links übernimmt Mailhelp nur als `https`-Adresse unter
  `google.com`.
- Dublettenprüfung und Tagesübersicht lesen offene Aufgaben über Seiten; ein Lesefehler ist mit
  `strict` nie eine leere Liste.

**Anmelderechte.** Eine Google-Anmeldung dient Kalender und Google Tasks eines Profils gemeinsam.
Sie fordert genau die Rechte an, die das Profil nutzt (`google_scopes`): Kalender, Google Tasks
(`https://www.googleapis.com/auth/tasks`) oder beides. Mit `include_granted_scopes` behält eine neue
Anmeldung früher erteilte Rechte. Die Rechte gehören zur Bindung der Web-Anmeldung; ändert sich das
Ziel währenddessen, wird die Anmeldung abgelehnt. `mailhelp --google-auth` lehnt ein Profil ohne
Google-Ziel ab, statt Rechte anzufordern, die nichts nutzt.

**Offen für die nächsten Patches.** Hinweis „Google Tasks übernimmt das Datum; die genaue Frist
steht im Text.“ in Vorschau, Bestätigung und Telegram sowie Listenauswahl in der Oberfläche (7.2.2);
Notion (7.2.3, 7.2.4); Abnahme mit echtem Testkonto (7.2.5). Bis dahin ist Google Tasks über die
Konfiguration nutzbar; die Liste wird als ID eingetragen.

Prüfung 7.2.1: 5 579 Python-Tests mit 100 % Zeilen- und Branch-Abdeckung (ein Dokumentationszitat
danach korrigiert, die betroffenen Prüfungen bestehen). Browser 928 bestanden; die Auswahl des
Aufgabendienstes zeigt jetzt fünf Einträge (Test nennt sie namentlich). Einmal scheiterte unter Last
`test_charts_zoom_and_show_details_with_pointer_keyboard_and_touch[desktop]`; er bestand danach
dreimal einzeln.
