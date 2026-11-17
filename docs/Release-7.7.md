# Mailhelp 7.7 – Vorfilter-Regeln und VIP-Absender

Geprüft für Mailhelp 7.7.

Umsetzung von [Planung 7.7](Planung-7.7.md) in Patches ab 7.7.1.

## 7.7.1 – Datenmodell, Migration und Auswerter

- **Schema 3 (`domain/relevance.py`):** `SenderRule` (Art, Wert, Aktion `ignore`/`vip`/`allow_only`,
  Subdomains, VIP-Themen, Postfach, an/aus, Notiz, Herkunft, stabile Kennung), `HeaderPrefilter`
  (`automated` und `lists` je `off`/`trial`/`on`, Verteiler-Ausnahmen) und `ListSignals`.
- **Auswerter (`mailbox/sender_filter.prefilter`):** Er prüft VIP vor jeder Sperre. Eine Ausnahme hebt
  alle Sperren und Kopfzeilen-Vorfilter für den Absender auf. Danach folgen Sperrregeln und Betreffe,
  zuletzt die eingeschalteten Kopfzeilen-Vorfilter. `is_irrelevant_sender` ist jetzt ein dünner
  Wrapper darum. Muster werden segmentweise ohne reguläre Ausdrücke abgeglichen; ein Test prüft die
  lineare Laufzeit bei 100.000 Zeichen.
- **Kopfzeilen:** `List-Id`, `List-Unsubscribe` (nur vorhanden ja/nein), `Precedence` und
  `Auto-Submitted` werden aus einem begrenzten Kopfblock gelesen, bereinigt, gekürzt und
  kleingeschrieben. Sie liegen als `MailState.list_signals` neben der Mail.
- **Sicherung:** Vor dem ersten Schreiben von Schema 3 bleibt die bisherige Datei als
  `irrelevant-senders.json.v1` bzw. `.v2` erhalten.
- **Gleichheitsnachweis:** `tests/unit/test_prefilter_rules.py` vergleicht den neuen Auswerter mit dem
  Algorithmus von 7.6 über Listen, Absender und Postfächer hinweg. Bestehende Listen entscheiden
  identisch, einschließlich exakter Domains und `allow`-Ausnahmen.
- Die Verarbeitung ändert sich in diesem Patch nicht. Neue Regeln kann noch niemand anlegen, und die
  Kopfzeilen-Vorfilter sind aus.

**Abweichungen vom Plan:**

- **Die Listen aus Schema 2 bleiben Felder von Schema 3,** statt in `rules` umgeschrieben zu werden.
  Rund 25 Module und Tests lesen `addresses`, `domains` und `mailboxes`, darunter Lernmodus,
  Lernaufträge, Entscheidungstest, Aktivitätsbericht und Auswertung. So bleibt die Migration ohne
  jede Umrechnung verlustfrei. Der Auswerter liest beide Formen und vergibt auch den alten Einträgen
  stabile Regelkennungen (aus Art, Wert und Postfach), sodass Trefferzahlen später für alle Regeln
  gelten.
- **Kopfzeilen neben der Mail:** Das `mail`-Dokument geht vollständig an das Sprachmodell. Die
  Kopfzeilen liegen deshalb in `MailState.list_signals` statt in `mail.headers`. So ändert sich keine
  Modelleingabe und kein Analyse-Fingerabdruck.

**Prüfung 7.7.1:**

- `python -m devtools.check full --workers 12`: 5.847 Tests bestanden, 100 % Zeilen- und
  Branch-Abdeckung, Lasttests bestanden.
- `python -m pytest ui_tests -n 6 --dist worksteal --no-cov`: 960 Tests bestanden, 234 übersprungen,
  JavaScript-Abdeckung 100 %.
