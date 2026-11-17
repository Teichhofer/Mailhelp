# Mailhelp 7.5 – Mehrsprachigkeit und englische Lokalisierung

Geprüft für Mailhelp 7.5.

Umsetzung von [Planung 7.5](Planung-7.5.md) in Patches ab 7.5.1. Zwischenstand: Der Plan ist erst
erfüllt, wenn Weboberfläche, JavaScript, Telegram, CLI und Hilfetexte zweisprachig sind; die
Prompts, Themen und die Auswertung der Mails bleiben nach der Kernvorgabe deutsch.

## 7.5.1 – Sprachkern, Spracheinstellung und Seitenrahmen (L1)

- **Modul `mailhelp.i18n`:** `Locale` (de, en), die aktive Sprache als Kontextvariable je Anfrage,
  `tr()` zum Übersetzen, `use_locale()` für einen begrenzten Abschnitt und `negotiate()` für die
  Sprachwahl. Englische Texte stehen in `i18n/en.py`.
- **Abweichung vom Plan bei den Schlüsseln:** Statt Punktschlüsseln (`status.needs_clarification`)
  ist der deutsche Text selbst der Schlüssel, wie bei gettext. Fehlt eine Übersetzung, erscheint der
  deutsche Text, nie ein Schlüssel; der deutsche Katalog ist damit der Code selbst und kann nicht
  vom Code abweichen. Der Vollständigkeitstest (`tests/unit/test_i18n.py`) findet jeden wörtlichen
  `tr()`-Aufruf ohne englischen Eintrag und jeden Eintrag mit abweichenden Platzhaltern.
- **Sprachwahl:** Ein Browser, der eine Sprache gewählt hat (Cookie `mailhelp_lang`), sieht diese;
  sonst die erste unterstützte Sprache aus `Accept-Language`; sonst die Einstellung `language`
  (`de` Standard, `en`). Unbekannte Sprachen fallen auf die nächste Stufe zurück.
- **Einstellung `language`** unter Einstellungen → Mailabruf und Betrieb und in `config.yaml`; wirkt
  nach einem Neustart. Sie zählt nicht zur Analyse; alle Analyse-Fingerabdrücke bleiben gleich.
- **Seitenrahmen:** `<html lang>` folgt der Sprache; Navigation, Bereichsnamen, Sprunglink, Menü
  „Mehr“ und die Zahl offener Entscheidungen sind übersetzt. Am Ende der Navigation steht ein Link
  zur anderen Sprache (`/sprache?wert=en`), der die Wahl im Cookie merkt und zur Seite zurückführt;
  er folgt nur einem Rückweg auf denselben Host.
- **Statusbezeichnungen:** Status, Ereignisse, Quellen und Arten (`web/labels.py`) erscheinen in der
  aktiven Sprache, auch in jedem Status-Badge.
- Die deutsche Ausgabe bleibt bis auf den neuen Sprachlink unverändert (Golden-Seiten neu
  geschrieben; geändert hat sich nur dieser Link).

**Offen für die nächsten Patches.** Datums-, Zeit- und Zahlenformate (7.5.2), Telegram (7.5.3), die
übrigen Seiteninhalte (7.5.4), JavaScript und Einstellungshilfen (7.5.5), CLI und Abnahme (7.5.6).
Bis dahin sind auf Englisch nur Rahmen, Navigation und Statusbezeichnungen übersetzt.

Prüfung 7.5.1: 5 720 Python-Tests mit 100 % Zeilen- und Branch-Abdeckung; Browser 956 bestanden ohne
Fehler, JavaScript zu 100 % abgedeckt.
