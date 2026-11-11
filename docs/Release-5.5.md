# Release 5.5 – Hilfschat-Feinabstimmung

Version 5.5.5, 11. November 2026. Grundlage: [Planung 5.5](Planung-5.5.md).
Vorgänger: [Release 5.4](Release-5.4.md).

## Umgesetzte Schritte

| Schritt | Version | Ergebnis |
| --- | --- | --- |
| S1 | 5.5.0 | Behoben: „crypto.randomUUID is not a function“ über `http://` im Heimnetz. `randomHexKey()` nutzt `randomUUID`, sonst `getRandomValues`, sonst eine Zufallsfolge. Pfeilschaltflächen, „Antwort prüfen“ und „Entwurf behalten“ entfallen. |
| S2 | 5.5.1 | Kosten- und Datenschutzhinweis eingeklappt hinter **Kostenpflichtig**. |
| S3 | 5.5.2 | Leseposition des Gesprächs bleibt über Seitenwechsel, Neuladen, Wiederöffnen und Dokumentationsansicht erhalten; am Ende werden neue Antworten mitgeführt. |
| S4 | 5.5.3 | Größe an allen Rändern und Ecken änderbar (280 × 180 Pixel bis Bildschirmrand), gespeichert im Tab. |
| S5 | 5.5.4 | Kurzantwort aus demselben KI-Aufruf; vollständige Antwort hinter **Ausführliche Antwort anzeigen**. |
| S6 | 5.5.5 | Gesamtabnahme, Dokumentation, dieser Bericht. |

## Abweichungen vom Plan

- **Patchnummern:** S1–S6 wurden als 5.5.0–5.5.5 umgesetzt (Plan: 5.5.1–5.5.6), damit jeder
  Commit die Version lückenlos erhöht.
- **Tastaturbedienung statt Pfeilschaltflächen:** Planung 5.4 (3.1) verlangt eine
  Positionsänderung per Tastatur. Der Fenstertitel ist fokussierbar: Pfeiltasten verschieben,
  Umschalt+Pfeiltasten ändern die Größe. Es gibt kein zusätzliches sichtbares Bedienelement.
- **Ohne JavaScript** lässt sich das Fenster nicht mehr verschieben (bisher per Formular in die
  Ecken). Verdeckt es auf kleinen Bildschirmen eine Schaltfläche, bleibt das Schließen bzw. die
  Eingabetaste im Suchfeld. Ein ungesendeter Entwurf bleibt ohne JavaScript beim Seitenwechsel
  nicht erhalten; neue Antworten erscheinen beim nächsten Seitenaufruf.
- **Lokale Hinweise** („kein passender Abschnitt“) werden nicht in Kurz- und Langfassung geteilt.

## Zusätzlich behobene Fehler

- 5.5.2: Das Öffnen des Fensters fokussierte das Fragefeld und scrollte dabei ans Ende.
- 5.5.2: Bestätigungsformulare lagen auch bei geschlossenem Fenster über dem Hilfschat; auf
  dem Handy verdeckte die Themenseite so Schließen-Knopf und Chatsymbol. Jetzt liegen nur ihre
  Schaltflächen und nur bei geöffnetem Fenster darüber.

Jeder Fehler hat einen Regressionstest, der vor dem Fix scheiterte.

## Upgrade und Rückkehr

Dienst stoppen, Konfiguration und Zustand sichern, Paket bzw. Image aktualisieren, neu starten.
Neue Anwendungs- oder LLM-Schalter sind nicht nötig. Eigene `prompts.yaml`: Das Feld
`short_answer` ist optional; ohne es leitet Mailhelp die Kurzantwort aus dem ersten Satz ab.
Zum Übernehmen den Absatz „Antworte nur als JSON …“ aus der mitgelieferten Vorlage in
`settings_help` kopieren. Gespeicherte Chatverläufe und Fensterzustände von 5.4 bleiben
gültig. Bei Rückkehr zu 5.4 kennt der ältere Stand das Feld `short_answer` nicht: Ein
Chatverlauf mit 5.5-Antworten wird beim ersten Zugriff als `.invalid` beiseitegelegt und ein
leerer Verlauf begonnen. Vorschläge, Freigaben und Einstellungen sind davon nicht betroffen;
wer den Verlauf behalten will, kehrt erst nach dessen Ablauf (24 Stunden) zurück.

## Abnahme

| Prüfung | Ergebnis |
| --- | --- |
| Windows 11, Python 3.12.10 | **4.551 bestanden, 1 gescheitert**, ein POSIX-Berechtigungstest plattformbedingt übersprungen (Lasttests getrennt); siehe Hinweis unten |
| Zeilenabdeckung Windows | **29.147 / 29.147, 100 %** |
| Branch-Abdeckung Windows | **8.458 / 8.458, 100 %** |
| Browser-Gesamtsuite | **459 bestanden**, 2 übersprungen, auf Desktop, Mobilgerät und 320-Pixel-Ansicht; JavaScript-Blockabdeckung 100 % in `app.js`, `sw.js`, `setup.js` |
| Lasttests | 4.2 (fünf Browser) Median Warteschlange **315,7 ms**, Maximum **467,7 ms**; 4.4.1 (2.000 Mails) Median Antwortzeit **331,1 ms**, Maximum **335,8 ms** (einzeln ausgeführt) |
| Statische Prüfung | Ruff ohne Befunde; mypy ohne Befunde in **272 Quelldateien** |
| Prompt-Qualitätsgate | bestanden |
| Inventur und Hilfebestand | ohne Abweichung; Hilfebestand für 5.5.5 neu erzeugt |
| Paketprüfung | Wheel und sdist 5.5.5 gebaut |
| Linux/Docker | **Nicht durchgeführt**: Docker war auf dem Prüfrechner nicht verfügbar. |

**Hinweis zum gescheiterten Test:** Im abschließenden Gesamtlauf mit acht parallelen Prozessen und
Coverage-Erfassung überschritt `tests/services/test_v44_load.py` seine Zeitgrenze (Median der
Annahmezeit 127,9 ms statt unter 100 ms). Der Test prüft die Weboberfläche unter Last und ist von
5.5 nicht berührt. Einzeln bestand er dreimal in Folge (je etwa 6,5 s), ebenso in den vier
vorherigen Gesamtläufen dieser Version. Die Grenze wurde nicht verändert. Er gehört wie die
bereits getrennt laufenden Lasttests zu den laufzeitabhängigen Prüfungen.

Tests verwenden synthetische Daten und simulierte LLMs.

## Abnahmekriterien der Planung

| Kriterium | Nachweis |
| --- | --- |
| Scroll-Erhaltung bei Seitenwechsel | `test_ui_help_window55_scroll.py` (Themenseite, Neuladen, Wiederöffnen) |
| Scroll-Erhaltung bei Dokumentationsansicht | `test_window55_returning_from_a_source_restores_the_reading_position` |
| Keine Feinpositionierungs-Pfeile | `test_window55_arrow_buttons_and_fallback_buttons_are_gone`; Ziehen in `test_window54_keyboard_position_and_drag_are_restored` |
| Größenänderung über Rand | `test_ui_help_window55_resize.py` (Zeiger, Mindestmaße, Bildschirmgrenzen, Neuladen) |
| Kurzantwort im Fenster | `test_ui_help_window55_short.py`, `tests/unit/test_help_short_answer.py` |
| Kompakter Kostenhinweis | `test_ui_help_window55_cost.py`, `tests/web/test_help_window55.py` |
| Keine überflüssigen Buttons | `test_window55_arrow_buttons_and_fallback_buttons_are_gone`; automatische Entwurfssicherung in `test_window54_failed_fallback_warns_before_unload_and_recovers_on_link_navigation` |
| Kein crypto.randomUUID-Fehler | `test_window55_fallback_keys_work_without_crypto_random_uuid` (ohne `randomUUID`, ohne jede Krypto-Zufallsquelle) |
| Testabdeckung | 100 % Zeilen und Branches (Python), 100 % der JavaScript-Blöcke |

## Grenzen

- Die Qualität echter Modell-Kurzantworten ist nicht bewertet; Tests verwenden simulierte
  Antworten. Hält ein Modell die 300 Zeichen nicht ein, kürzt Mailhelp deterministisch.
- Linux/Docker ist nicht nachgewiesen.
- Ohne Browserspeicher gelten Leseposition und Größe nur im aktuellen Dokument.

### Reproduzierbare Prüfungen

```powershell
python -m devtools.check full --workers 8
python -m pytest ui_tests --no-cov -q
python -m ruff check src tests ui_tests devtools
python -m mypy
python -m devtools.check prompts
python -m devtools.inventory --check
python -m devtools.help_index --check
```
