# Mailhelp 7.6 – Klärungsfreie Demo-Vorschläge und Flow-Optimierung

Geprüft für Mailhelp 7.6.

Umsetzung von [Planung 7.6](Planung-7.6.md).

## 7.6.1 – Klärungsfreie Demo-Mails, neuer Bestand und Flow-Prüfung (Q1–Q3)

- **Demo-Mails (`devtools/demo/mails.py`):** Jede der zehn relevanten Mails nennt Datum, Beginn,
  Ende und die gemeinte Person. Alex ist bei Planetarium und Bastel-Workshop fest eingeteilt, die
  Kuchenspende ist zugesagt statt erbeten.
- **Neuer Bestand:** `standard-v1` ist über die echte Pipeline neu erzeugt. Der Lauf ging einmal über
  OpenRouter (`deepseek/deepseek-v4.1-flash`) und verarbeitete nur synthetische Mails, ohne Telegram
  und ohne Ziele. Ergebnis:

  | Mail | Vorschläge |
  | :--- | :--- |
  | 01 Elternabend | Termin 26.11., 19:30–21:00 |
  | 02 Planetarium | Termin Begleitung 04.12., 08:30–13:00 · Aufgabe Einverständniserklärung bis 20.11. |
  | 03 Bastel-Workshop | Termin 21.11., 10:00–12:30 · Aufgabe Material bis 20.11. |
  | 04 Adventsbasar | Termin 05.12., 14:00–17:00 · Aufgabe Kuchen bringen am 05.12. |
  | 05 Lesepaten | Termin 01.12., 18:00–19:00 |
  | 06 Planetarium-Eintritt | Aufgabe Überweisung bis 25.11. |
  | 07 Vorspielnachmittag | Termin 09.12., 16:00–17:30 |
  | 08 Trikots, 09 Speiseplan | relevant, kein Vorschlag (zur Kenntnisnahme) |
  | 10 Black Week, 11–30 | irrelevant |

  Alle zehn Vorschläge stehen auf `pending_confirmation`, keiner hat offene Fragen, und keine Mail
  wartet auf eine Relevanzentscheidung. `answers.json` ist leer.
- **Flow-Prüfung:** `tests/release/test_demo_flow.py` lässt die Prüfung scheitern, sobald der Bestand
  wieder eine offene Frage, einen nicht bestätigungsbereiten Vorschlag oder eine offene
  Relevanzfrage enthält. `tests/web/test_demo_site.py` prüft dasselbe an der ausgelieferten Seite.
- **Vorbereitete Antworten bleiben:** Die Demo spielt weiterhin aufgezeichnete Antworten ab, wenn ein
  Bestand Rückfragen hat. Die Tests dafür nutzen eine Kopie des Bestands mit genau einer Rückfrage
  (`tests/fakes/demo_questions.py`), Web- und Browsertest eingeschlossen.

**Abweichungen vom Plan:**

- **Patchschnitt:** Q1 bis Q3 sind ein Patch. Ein neu erzeugter Bestand ohne die Prüfung, die ihn
  absichert, hätte keinen eigenen Wert.
- **Mail 05:** Statt einer in sich geschlossenen Verschiebung des Elternabends kommt das Treffen der
  Lesepaten. Eine Verschiebung bezieht sich immer auf den Elternabend aus Mail 01 und löst die Frage
  „Welcher bestehende Eintrag soll geändert werden?“ oder eine Zusammenführung aus.
- **Mail 06:** Aus der Erinnerung an die Einverständniserklärung wird die Bitte um den Eintritt. Eine
  Erinnerung wird mit dem Vorschlag aus Mail 02 zusammengeführt und brachte deshalb Rückfragen.
- **Mail 08:** Die mehrdeutige Nachricht „Wegen Samstag“ wird zu einer Vereinsinformation ohne
  Aufgabe. Sie war die einzige Mail mit offener Relevanzfrage.
- **Workshop:** Material und Workshop-Zeiten stehen in einer Mail, da der Bestand bei 30 Mails bleibt.

**Prüfung 7.6.1:**

- `python -m devtools.check full --workers 12`: 5.793 Tests bestanden, 100 % Zeilen- und
  Branch-Abdeckung.
- Ein Lasttest (`test_load_result_latency`) lag im Gesamtlauf knapp über der Grenze (Median 511 ms
  statt unter 500 ms). Einzeln bestanden beide Latenztests. 7.6.1 ändert keinen Webcode.
- `python -m pytest ui_tests -n 6 --dist worksteal --no-cov`: 956 Tests bestanden, 232 übersprungen,
  JavaScript-Abdeckung 100 %.

## 7.6.2 – Tasten, Abschluss und Schnelldurchlauf (Q4)

- **Tasten `1` und `2`:** `1` bestätigt wie `A`, `C` und Enter, `2` verwirft wie `X` und `D`. Die
  Hilfe „Tastenkürzel“ nennt sie. Nach einer Entscheidung per Taste wählt die Liste die nächste Karte
  aus, sodass sich ein Stapel Taste für Taste entscheiden lässt (`dialogs.js`).
- **Hinweis in der Demo:** Über der Liste offener Entscheidungen steht auf dem Desktop „Tipp: Mit den
  Tasten 1 (anlegen) und 2 (verwerfen) …“. Auf Telefonen bleibt der vorhandene Wischhinweis.
- **Abschluss:** Ist alles entschieden, zeigt die vorhandene Abschlussansicht („Alles erledigt!“ mit den
  heutigen Ergebnissen) in der Demo zusätzlich „Demo zurücksetzen und nochmals testen“.
- **Browsertests:**
  - `ui_tests/test_ui_demo.py` entscheidet den ganzen Demo-Stapel per Taste `1`, bis die
    Abschlussansicht erscheint. Das muss in unter 30 Sekunden geschehen; lokal dauert es etwa 6 Sekunden.
  - `ui_tests/test_ui_shortcuts.py` prüft `2` und den Sprung zur nächsten Karte.

**Abweichungen vom Plan:**

- **Keine Taste `Z` für Rückgängig:** Entscheidungen wirken sofort, seit 2.0 gibt es keine
  Rückgängig-Frist mehr. Ein angelegter Eintrag lässt sich wie bisher über „Eintrag wieder entfernen“
  zurücknehmen.
- **Keine eigene Messung „unter 50 ms je Aktion“:** Die Annahme einer Aktion prüfen weiterhin die
  vorhandenen Lasttests. Der neue Browsertest misst den ganzen Durchlauf statt einzelner Gesten.
- **Wischgesten unverändert:** Sie bestehen seit 6.9. Die Animation brauchte keine Änderung.

**Prüfung 7.6.2:**

- `python -m devtools.check full --workers 12`: 5.795 Tests bestanden, 100 % Zeilen- und
  Branch-Abdeckung, Lasttests bestanden. Die Golden-Seiten wurden neu geschrieben. Geändert haben sich
  nur die Prüfsummen von `app.css` und `dialogs.js` in den Asset-Links.
- `python -m pytest ui_tests -n 6 --dist worksteal --no-cov`: 960 Tests bestanden, 234 übersprungen,
  JavaScript-Abdeckung 100 %.

## 7.6.3 – Fehlerkorrektur: Ergebnisanzeige bei großem Bestand

Der Lasttest `tests/services/test_load_result_latency.py` scheiterte im Gesamtlauf von 7.6.1. Auch
einzeln überschritt er die Grenze in zwei von drei Läufen (Median 465–515 ms bei einer Grenze von
500 ms). Schon 7.4 hatte ihn mit 490 ms knapp bestanden.

- **Ursache 1, Telegram-Ausgang:** Warten Nachrichten auf eine offene Entscheidung, sucht jeder
  Durchlauf des Hauptthreads die aktuelle Entscheidung neu (`outbox.shown_open_decisions`). Dabei
  wurde jede gespeicherte Vorschlagsversion (`proposal-…-v1`) erst gelesen und dann verworfen. Bei
  500 Vorschlägen waren das über 1.000 Dateien und rund 350 ms je Durchlauf, und eine gleichzeitig
  eintreffende Web-Aktion wartete darauf.
  - Versionen werden jetzt am Namen erkannt (`state_names.is_proposal_snapshot`), ebenso in
    `/status`, in der Schreibwiederaufnahme, beim Pausenstatus und in der Systemansicht.
  - Entschiedene Vorschläge überspringt der Ausgang über ihren zwischengespeicherten Status
    (`store.scan` und `store.cached`). Nur offene Vorschläge werden vollständig gelesen.
  - Der Suchlauf dauert damit 24 ms; nur der erste nach einem Start liest alles (≈ 110 ms).
- **Ursache 2, Abgleich:** `ProposalReconciliationService.recover()` läuft bei jeder Aktion und in
  jedem Durchlauf. Es las das Zustandsverzeichnis viermal: zweimal für die Prüfung auf isolierte
  Dateien, je einmal für Journale und Vorschläge. Jetzt genügt eine Auflistung (`store.inventory`).
  Nur nachdem ein Journal abgeschlossen wurde, wird neu gelistet.
- **Regressionstests:**
  - `test_regression_held_outbox_and_status_never_read_stored_versions` scheitert ohne die Korrektur,
    weil Versionsdateien gelesen werden.
  - `test_regression_recover_lists_the_state_directory_once` scheitert ohne die Korrektur mit
    4 statt 1 Auflistung.
- **Ergebnis:** Der Lasttest erreicht einzeln 377–453 ms im Median (Maximum ≈ 690 ms, Grenze
  1.000 ms). Die Grenzen des Tests bleiben unverändert.

**Prüfung 7.6.3:**

- `python -m devtools.check full --workers 12`: 5.797 Tests bestanden, 100 % Zeilen- und
  Branch-Abdeckung. Der Lasttest erreichte im Gesamtlauf 376 ms Median und 641 ms Maximum.
- `python -m pytest ui_tests -n 6 --dist worksteal --no-cov`: 960 Tests bestanden, 234 übersprungen,
  JavaScript-Abdeckung 100 %.
