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
