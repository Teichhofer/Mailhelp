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

## 7.7.2 – Pipeline und Aufrufstellen

- **Relevanzschritt (`processing/mail_pipeline.py`):** Die Reihenfolge ist Briefing, IServ,
  `prefilter()`, Postfach ohne Thema, eigene Notiz, Sprachmodell.
  - Ein VIP-Treffer setzt `relevant` mit den eingeschalteten VIP-Themen des Postfachs, danach läuft die
    Analyse normal weiter.
  - Ein Sperrtreffer setzt `irrelevant`, alle Folgeschritte entfallen.
  - Die Begründung nennt die Regel. „So wurde diese Mail verarbeitet“ zeigt sie als Regelentscheidung
    „… – ohne KI-Aufruf“ und nicht als Modellbegründung.
- **Trefferzähler:** `MailState.prefilter_rule` hält die Regel. Erst nachdem die Entscheidung
  gespeichert ist, zählt `prefilter-hits.json` den Treffer. Die Regeldatei bleibt dabei unverändert.
  Eine doppelt eingehende Mail ist ein Duplikat und wird nicht erneut gezählt.
- **Aufrufstellen:**
  - Bilderkennung: dieselbe Regel wie der Relevanzschritt.
  - Entscheidungstest: mit Betreff.
  - Lernmodus: mit Kopfzeilen.
  - Aktivitätsbericht und Mailseite: nutzen weiter `is_irrelevant_sender`, das jetzt ebenfalls über
    `prefilter()` entscheidet.
- **Tests (`tests/services/test_prefilter_pipeline.py`):**
  - VIP ohne Relevanz-Aufruf, mit Themenfilter und weiterhin `pending_confirmation`, auch bei einer
    gefälschten VIP-Mail.
  - Muster ohne jeden Modellaufruf, ohne Doppelzählung.
  - Kopfzeilen-Vorfilter nur, wenn er eingeschaltet ist.
  - Entscheidungstest mit Betreff- und VIP-Regel.
  - Lernmodus mit Verteiler-Kopfzeile.

**Abweichung vom Plan:** Die Regelkennung steht in `MailState.prefilter_rule` und nicht zusätzlich in
`analysis-<id>.json`. Die Auswertung in 7.7.5 liest sie von dort; so braucht das Analyseformat keine
neue Version.

Nebenbei korrigiert: `i18n._templates` hatte seit 7.5.4 einen falschen Typvermerk (drei statt vier
Werte). `mypy` meldete ihn, der Prüflauf führt `mypy` aber nicht aus.

**Prüfung 7.7.2:**

- `python -m devtools.check full --workers 12`: 5.854 Tests bestanden, 100 % Zeilen- und
  Branch-Abdeckung, Lasttests bestanden. `mypy src/mailhelp` ohne Befund.
- `python -m pytest ui_tests -n 6 --dist worksteal --no-cov`: 960 Tests bestanden, 234 übersprungen,
  JavaScript-Abdeckung 100 %.

## 7.7.3 – Regeln verwalten im Web und per Telegram

- **Seite `/einstellungen/absender`** (`web/sender_pages.py`, `web/sender_site.py`): Die alte Adresse
  leitet weiter.
  - Abschnitte: VIP-Absender, ignorierte Absender (Listen aus Schema 2 und Regeln) und Ausnahmen, je
    mit Postfach, Treffern und letztem Treffer.
  - Regeln lassen sich ein- und ausschalten und entfernen.
  - Eine neue Regel wird zuerst gegen die letzten 200 Mails gezählt. Erst diese Vorschau bietet
    „Regel speichern“. Bei großen Mailanbietern erscheint eine Warnung.
- **Befehl `RuleChange`** (`config/configuration.py`): `add`, `remove`, `enable`, `disable` und
  `promote` laufen über den bestehenden `AdminCommand` im Hauptthread.
  - Von der Regelseite ist jede Änderung an den Hash der Regeldatei gebunden.
  - Die stabile Regelkennung macht jede Änderung idempotent.
  - `promote` macht aus einer Postfach-Ausnahme eine VIP-Regel desselben Postfachs.
- **Mailseite:** Neu sind „Domain … ignorieren“ (nicht für große Mailanbieter) und „Als VIP einstufen“.
- **Telegram:** Die Relevanzrückfrage hat den Knopf „🚫 Absender immer ignorieren“, die Antwort trägt
  „Rückgängig“. Die Reihenfolge ist Prüfung auf eine offene Rückfrage, dann Regel, dann Antwort.
  Dadurch legt eine veraltete Rückfrage keine Regel an, und ein Neustart dazwischen ergibt genau
  eine Regel.
- **Sprache:** 70 neue Texte stehen in `i18n/en.py`.
- **Fehlerkorrektur während der Umsetzung:** Die Vorschau des vollständigen Formulars endete im Browser
  mit „Interner Fehler“. Die Ergebnisanzeige liest höchstens fünf Felder der Adresse, das Formular
  sendet sechs. Eine Vorschau liest jetzt keine Ergebnisanzeige mehr. Regressionstest:
  `test_regression_the_preview_of_the_complete_form_is_shown`.
- **Tests:** Web (Vorschau, Speichern, Doppelung, Aktionswechsel, veralteter Stand, Ein/Aus,
  Entfernen, ungültige Regeln, Ausnahme → VIP, Mailseiten-Knöpfe), Telegram (Knopf, doppelter Druck,
  Neustart zwischen Regel und Antwort, Rückgängig, mehrdeutiger Absender) und der Browsertest
  `ui_tests/test_ui_sender_rules.py` auf Desktop und Telefon.

**Abweichungen vom Plan:**

- **Geltungsbereich des Telegram-Knopfs:** Die Regel gilt global, wie beim Knopf „Absender
  ignorieren“ an der Mailseite. Der Plan nannte das Eingangspostfach. Beide Knöpfe verhalten sich so
  gleich, und eine Postfachregel lässt sich auf der Regelseite anlegen.
- **„Absender ignorieren“ an der Mailseite** bleibt ein Eintrag der einfachen Adressliste. Damit
  bleibt „Absender wieder zulassen“ wie bisher nutzbar. Neue Einträge auf der Regelseite sind Regeln.
- **Die Nachwirkung aus 3.7** („N frühere Mails“) zeigt die Vorschau vor dem Speichern als Trefferzahl
  der letzten 200 Mails. Eine Neuprüfung früherer Mails startet wie bisher von der Mailseite aus.

**Prüfung 7.7.3:**

- `python -m devtools.check full --workers 12`: 5.864 Tests bestanden, 100 % Zeilen- und
  Branch-Abdeckung, Lasttests bestanden.
- `python -m pytest ui_tests -n 6 --dist worksteal --no-cov`: 963 Tests bestanden, 234 übersprungen,
  JavaScript-Abdeckung 100 %.

## 7.7.4 – Kopfzeilen-Vorfilter

- **Schalter:** Auf der Regelseite stehen „Automatische Systemmails“ und „Newsletter und Verteiler“
  je auf aus, Probelauf oder an. Nach dem Update sind beide aus.
- **Probelauf:** Entscheidet keine Regel, zählt der Relevanzschritt jede Mail, die ein Filter im
  Probelauf aussortiert hätte, in `prefilter-hits.json` unter `trial`. Die Entscheidung trifft
  weiter die KI. Die Seite zeigt Beginn, Anzahl und letzten Treffer des Probelaufs.
- **Verteiler-Ausnahmen:** Der Filter für Newsletter sortiert diese Verteiler nie aus. Eine `List-Id`
  wird auf ihre Kennung in spitzen Klammern verkürzt (`"Schule" <eltern.schule.test>` →
  `<eltern.schule.test>`), damit Ausnahmen zuverlässig greifen.
- **Tests:**
  - Probelauf: Er zählt nur, die Entscheidung bleibt beim Modell, und eine Ausnahme wird nicht
    gezählt.
  - Ein erneuter Probelauf behält seinen Beginn.
  - Moduswechsel, Ausnahmen hinzufügen und entfernen, ungültiger Modus und leere `List-Id`.
  - Der Browsertest schaltet den Newsletter-Filter in den Probelauf.

**Abweichung vom Plan:** Der Probelauf zeigt Anzahl und letzten Treffer, aber keine Liste der
einzelnen Mails. Die betroffenen Mails stehen wie alle anderen im Mailarchiv; eine eigene Liste
hätte eine weitere Zustandsdatei je Mail gebraucht.

**Prüfung 7.7.4:**

- `python -m devtools.check full --workers 12`: 5.872 Tests bestanden, 100 % Zeilen- und
  Branch-Abdeckung, Lasttests bestanden.
- `python -m pytest ui_tests -n 6 --dist worksteal --no-cov`: 963 Tests bestanden, 234 übersprungen,
  JavaScript-Abdeckung 100 %.

## 7.7.5 – Hinweise für Regeln und Kennzahlen

- **Hinweise (`review/prefilter_hints.py`):** Sie entstehen ohne Modellaufruf aus gespeicherten
  Mailzuständen der letzten 30 Tage. Zwei neue Quellen ergänzen die Absenderhinweise aus 6.5:
  - **Relevanzprüfung:** Mindestens drei Mails eines Absenders hat die KI alle als irrelevant
    eingestuft. Gezählt wird nur ohne Regelentscheidung und ohne menschliche Antwort.
  - **Bestätigte Vorschläge:** Mindestens fünf Mails eines Absenders, die alle zu einem bestätigten
    Vorschlag führten, ergeben einen VIP-Hinweis.

  Zwei oder mehr Adressen derselben Domain ergeben zusätzlich einen Domain-Hinweis, außer bei großen
  Mailanbietern. Die Schwellwerte stehen unter `learning.prefilter_hint_*` in `config.yaml`.
- **Anzeige unter Lernen → Vorschläge:** „Als Regel übernehmen“ nutzt den normalen Regelbefehl mit
  `origin: hint`. „Nicht mehr vorschlagen“ nutzt die vorhandene Ablehnungsliste. Die Regelseite
  verlinkt auf die Hinweise.
- **Kennzahlen (`web/prefilter_stats.py`, Abschnitt „Vorfilter“ auf `/auswertung`):**
  - vermiedene Relevanzprüfungen nach Grund;
  - geschätzte Ersparnis aus dem Median der echten Relevanzprüfungen, ohne Vergleich „nicht
    schätzbar“;
  - die fünf Regeln mit den meisten Treffern und Regeln ohne Treffer seit 90 Tagen.
- **Tests:**
  - Hinweise: Schwellwerte, Zeitfenster, Regel- und Antwortausschluss, Ausnahmen, Ablehnungsliste,
    Domain-Hinweis und große Mailanbieter, VIP mit bestätigten Vorschlägen.
  - Kennzahlen: Gründe, Schätzung für Cloud, Ollama und Aufrufe ohne Kostenangabe, Abschnitt mit
    Regelnamen.
  - Web: Übernahme mit `origin: hint`, Ausblenden, Auswertung mit und ohne Konfiguration.

**Abweichungen vom Plan:**

- **Mailseite:** Sie verlinkt nicht auf offene Hinweise. Die Hinweise stehen gesammelt unter
  Lernen, und die Regelseite verlinkt dorthin.
- **VIP-Hinweis:** Er verlangt nicht ausdrücklich „nie irrelevant“, sondern dass jede Mail relevant
  war und zu einem bestätigten Vorschlag führte. Das schließt eine irrelevante Mail ebenfalls aus.

**Prüfung 7.7.5:**

- `python -m devtools.check full --workers 12`: 5.881 Tests bestanden, 100 % Zeilen- und
  Branch-Abdeckung, Lasttests bestanden.
- `python -m pytest ui_tests -n 6 --dist worksteal --no-cov`: 963 Tests bestanden, 234 übersprungen,
  JavaScript-Abdeckung 100 %.

## 7.7.6 – Dokumentation und Abnahme

- **Bedienung:** neuer Abschnitt „Absender-Regeln und Vorfilter“. Die Hilfe ist neu erzeugt.
- **Beispiel:** `irrelevant-senders.example.json` zeigt Schema 3 mit leeren Regeln und
  ausgeschalteten Kopfzeilen-Vorfiltern. Ältere Dateien liest Mailhelp weiter und stellt sie beim
  nächsten Schreiben mit Sicherung um.

### Abnahme nach Planung 7.7, Abschnitt 5

| Nr. | Kriterium | Nachweis |
| :-- | :--- | :--- |
| 1 | Eine Ignorier-Regel löst keinen Modellaufruf aus, auch keine Bilderkennung. Die Mail ist mit Regelname als irrelevant eingeordnet. | `test_an_ignore_rule_files_the_mail_without_any_model_call`, `test_blocked_senders_never_reach_the_vision_model` |
| 2 | Ein VIP-Absender löst keinen Relevanz-Aufruf aus. Die Analyse läuft weiter, und jeder Eintrag braucht die Bestätigung. | `test_a_vip_sender_skips_only_the_relevance_call_and_keeps_the_confirmation` |
| 3 | Schema 1 und 2 verhalten sich nach der Migration identisch, einschließlich exakter Domains und `allow`. Die alte Datei wird gesichert. | `test_migrated_lists_decide_exactly_as_before`, `test_schema_1_and_2_documents_become_schema_3_without_loss`, `test_the_older_schema_is_kept_once_before_schema_3_is_written` |
| 4 | Der Kopfzeilen-Vorfilter ist nach dem Update aus. Der Probelauf ändert keine Entscheidung. | `test_header_filters_are_off_by_default_and_a_trial_never_decides`, `test_a_header_trial_only_counts_and_an_exception_is_never_counted` |
| 5 | Entscheidungstest, Lernmodus, Aktivitätsbericht und Verarbeitung kommen zum selben Ergebnis. | Ein Auswerter für alle Aufrufer: `test_the_decision_test_follows_subject_and_vip_rules`, `test_the_learning_mode_skips_newsletters_once_the_header_filter_is_on`. Aktivitätsbericht und Mailseite nutzen `is_irrelevant_sender`, das über `prefilter()` entscheidet. |
| 6 | Die Ersparnis ist als Schätzung gekennzeichnet und aus echten Aufrufen abgeleitet. | `test_the_saving_is_estimated_from_real_relevance_calls_only`, `test_the_section_shows_the_counts_the_estimate_the_busiest_and_unused_rules` |
| 7 | Der Telegram-Knopf legt genau eine Regel an, auch bei doppeltem Druck und nach einem Neustart. Auf eine veraltete Rückfrage wirkt er nicht. „Rückgängig“ entfernt nur die Regel. | `test_the_relevance_question_ignores_the_sender_once_and_undoes_only_the_rule`, `test_a_restart_between_rule_and_answer_keeps_exactly_one_rule`, `test_without_one_clear_sender_there_is_no_button_and_no_rule` |
| 8 | Alle neuen Seiten und Meldungen gibt es auf Deutsch und Englisch. | `test_every_literal_text_has_an_english_entry_with_the_same_placeholders`: 108 neue Einträge in `i18n/en.py` |
| 9 | 100 % Zeilen- und Branch-Abdeckung; die Browsersuite ist grün. | Prüfung unten |

**Offene Punkte:**

- **Begründungen bleiben deutsch:** Die gespeicherten Begründungen („Vorfilter: …“, „VIP-Absender: …“)
  werden wie alle Analysebegründungen deutsch gespeichert. Die Erklärung „So wurde diese Mail
  verarbeitet“ ist noch nicht zweisprachig. Beides gehört zur ausstehenden Lokalisierung der
  Mailseiten (Planung 7.8).
- **Aktivitätsbericht ohne neue Regeln:** Er arbeitet mit dem Absenderstand, der zum Bericht gehört.
  Die neuen Regeln (Muster, Betreffe, VIP) wirken dort erst, wenn das Berichtsformat sie aufnimmt.

**Prüfung 7.7.6** Vollständiger Python-Lauf laut `check776b.log` mit 5 881 bestandenen Tests,
100 % Zeilen- und Branch-Abdeckung sowie bestandenen Lasttests. Die Browsersuite meldet
962 bestandene, 234 übersprungene und einen fehlgeschlagenen Diagramm-Hoverfall.
Die unveränderte Einzelwiederholung dieses Falls besteht mit einem Test.
