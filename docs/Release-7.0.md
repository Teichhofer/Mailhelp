# Mailhelp 7.0 – Code aufräumen und Dokumentation prüfen

Umsetzung von [Planung 7.0](Planung-7.0.md). 7.0 ändert kein Verhalten; jeder Patch wird gegen
die in 7.0.1 festgehaltenen Vorher-Werte geprüft.

## 7.0.1 – Sicherungsnetz

Ausgangsstand ist 6.9.3 (Commit `68d6250`).

**Eingefrorene Ausgaben.** `tests/golden/test_frozen_output.py` erzeugt aus synthetischen Daten
bei fester Uhr elf Kernseiten (Übersicht, gefilterte Liste, Mails, Mail, Vorschlag, Verlauf,
Lernen, Auswertung, Status, Einstellungen, Abgleich) und die Telegram-Darstellung aller
14 Vorschläge. Ersetzt werden nur Werte, die sich bei jedem Lauf ändern: Sitzungs- und
Formular-Token, Fingerabdrücke, Ablaufzeiten und Rückruf-Token. Die Vergleichsdateien liegen
unter `tests/golden/output` und dürfen sich in ganz 7.0 nicht ändern.

**Kennzahlen vorher** (`python -m devtools.code_metrics`, gespeichert in
`quality-reports/refactoring-7.0-vorher.json`):

| Kennzahl | Wert |
| :--- | :--- |
| Python-Dateien / Zeilen | 305 / 54 539 |
| Funktionen | 3 037 |
| davon über 60 / 80 / 100 Zeilen | 46 / 16 / 7 |
| längste Funktion | `proposal_evaluation_page`, 179 Zeilen |
| Funktionen mit mehr als 10 Parametern | 20 (höchstens 32, `logging.__init__`) |
| Importe innerhalb von Funktionen | 328 |

**Bestandsprüfung.** `python -m devtools.state_roundtrip <Verzeichnis>` lädt jede Zustandsdatei
einer Kopie mit ihrem Modell und serialisiert sie wie der Speicher. Der Bericht enthält nur
Zählwerte und eine SHA-256-Prüfsumme. Auf einer festen lokalen Kopie des Bestands
(4 840 Dateien, keine ungültig) ist die Vorher-Prüfsumme festgehalten; Kopie und Bericht bleiben
lokal und unversioniert. Nach 7.0 muss dieselbe Prüfsumme entstehen.

**Mutationswerte vorher** (WSL, `python -m devtools.check mutation` auf 6.9.3, gespeichert in
`quality-reports/mutation-7.0-vorher.json`): 1 478 Mutanten, 1 158 getötet (78,35 %), 185 überlebt,
135 ohne Test. Je Kernbereich getötet / überlebt / ohne Test: `domain` 520 / 26 / 135,
`storage.py` 454 / 69 / 0, `external/confirmed.py` 184 / 90 / 0. Der Ausgangsstand erreicht die
90 %, die der wöchentliche Mutationslauf verlangt, schon vor 7.0 nicht; Maßstab für 7.0 ist,
dass kein Wert schlechter wird. `core_mutation_scores` in `devtools/check.py` bricht bei Mutanten
ohne Test (Code 33) ab; die Werte oben sind deshalb direkt aus den Metadaten gezählt.

**Abweichung vom Plan.** Die Kennzahlen erzeugt ein eigenes Werkzeug `devtools/code_metrics.py`
statt einer Erweiterung von `devtools/inventory.py`; die Inventur der Einstellungen bleibt davon
getrennt.

## 7.0.2 – Nur Mailhelp im Repository (R1)

Nach Bestätigung der Liste durch den Betreiber sind 186 Dateien aus der Versionierung genommen
und in `.gitignore` eingetragen: `output/` (Auswertungen und PDFs anderer Arbeiten), `tmp/`
(Bildschirmfotos und PDF-Seiten), `.tools/` (OCR- und Instaloader-Werkzeuge samt virtueller
Umgebung) und im Wurzelverzeichnis `irrelevant-senders.json`, `irrelevant-senders.json.v1`,
`irrelevant-senders.corrupt`, `.coverage-spec-audit`, `coverage-audit.json` und
`spec-audit-coverage.json`. Die Dateien liegen weiter auf der Festplatte; die Git-Historie ist
unverändert. Kein Test, kein Paketbau und keine Konfiguration las eine davon; die CI legt
`irrelevant-senders.json` für den Containertest weiterhin aus `tests/fixtures` an.
`tests/release/test_repository_scope70.py` verhindert, dass sie wieder versioniert werden.

**Hinweis Datenschutz.** Die beiden Dateien `irrelevant-senders.json*` enthielten rund 54 echte
Absenderadressen und liegen in früheren Commits auf GitHub. Entfernen aus der Historie wäre ein
Umschreiben der Historie und ist nach Plan nicht Teil von 7.0; es bleibt eine Entscheidung des
Betreibers.
