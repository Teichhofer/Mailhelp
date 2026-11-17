# Mailhelp 7.5 – Mehrsprachigkeit und englische Lokalisierung

**Zielversion:** 7.5, Umsetzung in Patchversionen ab 7.5.1  
**Stand:** 16. November 2026  
**Status:** In Umsetzung ab 7.5.1 (17. November 2026); Stand in [Release 7.5](Release-7.5.md).  
**Ausgangsstand:** Nach Umsetzung von 7.2 (Aufgabenziele), 7.3 (Fehlerverwaltung) und 7.4 (Mehrtägige Termine).  
**Grundlage:** [Entwicklungsregeln](../AGENTS.md), [Projektspezifikation](../Mailhelp-Projektspezifikation.md), [Architektur](Architektur.md).

---

## 1. Ziel und Umfang

Mailhelp soll international nutzbar werden. In Version 7.5 wird die Codebasis
für Mehrsprachigkeit (Internationalisierung / i18n) vorbereitet und direkt eine
vollständige, qualitätsgeprüfte **englische Lokalisierung (`en`)** neben der
bestehenden deutschen Fassung (`de`) ausgeliefert.

### Verbindliche Kernvorgabe des Auftraggebers:
> **Die LLM-Abrufe bleiben vorerst unlokalisiert.**  
> Prompts, Modellparameter, Systemtexte in `prompts.yaml`, Themen in `topics.yaml`,
> Extraktionsschemata und interne LLM-Verarbeitungsketten verbleiben unverändert in
> deutscher Sprache. Die Lokalisierung konzentriert sich vollständig auf die
> **menschliche Interaktionsebene**: Weboberfläche, Telegram-Bot, Benachrichtigungen,
> Status- und Fehleranzeigen, CLI und Hilfetexte.

### Übersicht des Zielumfangs:

| Bereich | Lokalisierungsumfang |
| :--- | :--- |
| **Weboberfläche** | Alle Seiten (Offen, Mails, Verlauf, Abgleich, Einstellungen, Berichte, Setup), Badges, Aktionsschaltflächen, Dialoge, Tabellen, Filter |
| **JavaScript / Interaktion** | Swipe-Hinweise (Accept / Dismiss), Rückgängig-Toast (Undo), Tastaturkürzel-Hilfe, Modals |
| **Telegram-Bot** | Nachrichtenkarten (📅 Event / ✅ Task, Due, Responsible, Open questions), Inline-Buttons, Quittungen, Rückfragen |
| **CLI & Dienst** | Konsolenbefehle, Hilfetexte (`--help`), Status- und Fehlerausgaben |
| **Datums-, Zeit- & Zahlenformate** | Gebietsschema-abhängige Formatierung von Zahlen (`1.234` vs. `1,234`), Zeitangaben (`14:30 Uhr` vs. `2:30 PM` / `14:30`) und Datumsspannen |
| **Einstellungen & Dokumentation** | `config.yaml` (`language: de \| en`), Einstellungs-Hilfetexte, Glossar und Hilfebereiche |
| **LLM & Pipeline** | **Ausdrücklich ausgenommen:** `prompts.yaml`, Modell-Prompts und Extraktionsschemas bleiben auf Deutsch |

---

## 2. Architektur des i18n-Subsystems

Um die strikten Projektvorgaben (100 % Zeilen- und Branch-Abdeckung, keine unnötigen
externen Laufzeit-Abhängigkeiten, deterministisches Verhalten unter Windows 11 und
Linux-Docker) zu erfüllen, wird ein schlankes, typsicheres Lokalisierungsmodul
unter `src/mailhelp/i18n/` etabliert:

### 2.1 Modulaufbau

```
src/mailhelp/i18n/
├── __init__.py          # Öffentliche Schnittstelle: t(), format_date(), format_time(), Locale, get_locale()
├── core.py              # Übersetzungs-Engine, String-Interpolation, Fallback-Kette
├── context.py           # ContextVar für thread- und async-sichere Spracherkennung je Request/Task
├── locales/
│   ├── de.py            # Deutsche Referenz-Texte (Schlüssel-Wert-Katalog)
│   └── en.py            # Englische Übersetzungen (strukturgleich zu de.py)
└── formatting.py        # Lokalisierte Formatierer für Datum, Uhrzeit, Dauern und Zahlen
```

### 2.2 Typsicherheit und Vollständigkeitsprüfung
* Alle Übersetzungsschlüssel werden in einer flachen oder typisierten Hierarchie
  (z. B. `actions.confirm`, `status.needs_clarification`, `telegram.button.create_event`) geführt.
* Ein automatisierter Unit-Test (`tests/unit/test_i18n_completeness.py`) vergleicht
  `de.py` und `en.py` bidirektional:
  * Jeder in `de.py` definierte Schlüssel muss in `en.py` existieren.
  * Jeder Format-Platzhalter (z. B. `{count}`, `{title}`) muss in beiden Sprachen identisch vorhanden sein.
  * Fehlende oder überflüssige Schlüssel lassen die Testsuite scheitern.

### 2.3 Sprachauflösung und Kontext
Die wirksame Sprache wird hierarchisch ermittelt:
1. **Expliziter Parameter im Aufruf:** z. B. `t("key", locale=Locale.EN)`.
2. **Sitzungskontext (Web / Request):**
   * Gespeicherte Benutzereinstellung / Cookie (z. B. `mailhelp_lang=en`).
   * Browser-Header `Accept-Language` (falls keine manuelle Wahl getroffen wurde).
3. **Anwendungs-Konfiguration:** Einstellung `language` in `config.yaml` (Standard: `de`).
4. **Fallback:** Bei unbekannten Sprachen oder fehlenden Einzelschlüsseln greift immer `de`.

---

## 3. Anpassung der Funktionsbereiche

### 3.1 Weboberfläche (`src/mailhelp/web/`)
1. **HTML-Struktur & Layout ([src/mailhelp/web/pages.py](file:///c:/Users/User/Documents/Projekte/mailhelp/Mailhelp/src/mailhelp/web/pages.py)):**
   * `<html lang="de">` wird dynamisch zu `<html lang="en">` bzw. zur aktiven Sprache.
   * `NAVIGATION`: Navigationsbeschriftungen („Open“, „Mails“, „History“, „Review“, „Settings“) werden über `t()` bezogen.
   * Neuer kompakter Sprachwähler im Header bzw. Menü (Umschalten zwischen `DE` und `EN` mit sofortiger Wirkung).
2. **Karten und Statusanzeigen ([src/mailhelp/web/labels.py](file:///c:/Users/User/Documents/Projekte/mailhelp/Mailhelp/src/mailhelp/web/labels.py)):**
   * Die Dictionaries `STATUSES`, `EVENTS`, `SOURCES`, `KINDS` werden internationalisiert:
     * `needs_clarification`: *„Klärung nötig“* / *„Needs clarification“*
     * `pending_confirmation`: *„Wartet auf Bestätigung“* / *„Pending confirmation“*
     * `confirmed`: *„Bestätigt“* / *„Confirmed“*
     * `failed`: *„Fehler“* / *„Failed“*
     * `event` / `task`: *„Termin“* / *„Aufgabe“* bzw. *„Event“* / *„Task“*
3. **Client-seitiges JavaScript (`static/open-list.js`, `dialogs.js`):**
   * Dynamische Texte werden beim Seitenaufbau über ein serialisiertes JSON-Objekt
     `window.MailhelpI18n` an das Frontend übergeben:
     * Swipe-Labels: „Annehmen“ → „Accept“, „Verwerfen“ → „Dismiss“.
     * Toast-Meldungen: „Aktion rückgängig machen“ → „Undo action“.
     * Tastatur-Dialog: „Schließen“ → „Close“, „Hilfe“ → „Help“.

### 3.2 Telegram-Bot (`src/mailhelp/telegram/`)
1. **Nachrichtenformatierung ([src/mailhelp/telegram/formatting.py](file:///c:/Users/User/Documents/Projekte/mailhelp/Mailhelp/src/mailhelp/telegram/formatting.py)):**
   * Kopfzeile: `📅 Termin` → `📅 Event`, `✅ Aufgabe` → `✅ Task`.
   * Felder:
     * `🕒 Fällig:` → `🕒 Due:`
     * `Zuständig:` → `Responsible:`
     * `Sicherheit:` → `Certainty:`
     * `Einordnung:` → `Classification:`
     * `❓ Offen:` → `❓ Open:`
     * `Beleg:` → `Evidence:`
     * `Original-Mail:` → `Original Email:`
2. **Inline-Tastatur ([src/mailhelp/telegram/presenter.py](file:///c:/Users/User/Documents/Projekte/mailhelp/Mailhelp/src/mailhelp/telegram/presenter.py)):**
   * Schaltflächen:
     * *„Im Kalender anlegen“* → *„Add to Calendar“*
     * *„Als Aufgabe anlegen“* → *„Add as Task“*
     * *„Termin aktualisieren“* → *„Update Event“*
     * *„Termin absagen“* → *„Cancel Event“*
     * *„Ändern“* → *„Edit“*
     * *„Verwerfen“* → *„Dismiss“*
     * *„Klären“* → *„Clarify“*
     * *„Schon erledigt“* → *„Already done“*
     * *„Simulieren“* → *„Simulate“* (Demo-Modus)

### 3.3 Formatierung von Datum, Uhrzeit und Zeitspannen
In [src/mailhelp/review/cards.py](file:///c:/Users/User/Documents/Projekte/mailhelp/Mailhelp/src/mailhelp/review/cards.py):
* **Deutsch:** `Donnerstag, 07.01.2027, 11:30–12:30 Uhr` bzw. `07.01.2027 – 08.01.2027, ganztägig`
* **Englisch:** `Thursday, Jan 7, 2027, 11:30 AM – 12:30 PM` (oder 24h: `11:30–12:30`) bzw. `Jan 7, 2027 – Jan 8, 2027, all-day`
* Annahmen: *„Ende angenommen: Standarddauer 60 Min.“* → *„Assumed end: default duration 60 min.“*

### 3.4 CLI & Systemmeldungen (`src/mailhelp/cli.py`)
* Hilfetexte des ArgumentParsers werden entsprechend der System-/Umgebungssprache
  oder `--lang en` ausgegeben.
* Statusausgaben bei Start, Stop, Check und Fehlerbehebung werden übersetzt.

### 3.5 Einstellungs- und Hilfedokumentation
* [src/mailhelp/web/setting_help.py](file:///c:/Users/User/Documents/Projekte/mailhelp/Mailhelp/src/mailhelp/web/setting_help.py)
  erhält englische Entsprechungen für alle Hilfetexte der Webeinstellungen.
* `helpdocs/` wird um englische Dokumentationsfragmente (`en/sections.json`, `en/settings.json`) ergänzt.

---

## 4. Konfiguration und Abwärtskompatibilität

In `config.yaml` wird der optionale Schlüssel `language` ergänzt:

```yaml
# Standardsprache der Benutzeroberfläche und Benachrichtigungen.
# Werte: 'de' (Deutsch, Standard) oder 'en' (Englisch).
# Hinweis: LLM-Prompts und -Extraktion verbleiben unlokalisiert.
language: de
```

* **Vollständige Abwärtskompatibilität:** Fehlt der Schlüssel in einer bestehenden
  `config.yaml`, gilt wie bisher strikt `de`. Vorhandene Installationen ändern ihr
  Verhalten nicht.
* **Kein Einfluss auf Fingerabdrücke:** Die Spracheinstellung ist ein rein darstellendes
  Merkmal der Präsentationsebene und verändert weder den Analyse-Fingerabdruck noch
  gespeicherte Mail-Zustände.

---

## 5. Umsetzungsschritte (Patch-Plan 7.5.1 bis 7.5.7)

| Schritt | Patch | Inhalt |
| :--- | :--- | :--- |
| **L1** | 7.5.1 | **i18n-Kernmodul & Katalog:** `src/mailhelp/i18n/` anlegen, Engine `t()` und ContextVar implementieren, vollständige Basiskataloge `de.py` und `en.py` erstellen. Bidirektionaler Vollständigkeitstest. |
| **L2** | 7.5.2 | **Formatierung:** Datums-, Uhrzeit-, Zahlen- und Dauer-Formatierer in `formatting.py` umsetzen. Integration in `cards.py` und `labels.py`. Unit-Tests. |
| **L3** | 7.5.3 | **Telegram-Lokalisierung:** `formatting.py` und `presenter.py` für Telegram auf das i18n-Modul umstellen. Prüfung von Buttons, Bestätigungen und Rückfragen in beiden Sprachen. |
| **L4** | 7.5.4, 7.5.5 | **Web-Lokalisierung (Templates & HTML):** Navigation, Badges, Tabellen, Formulare und Überschriften auf `t()` umstellen. Sprachwähler im Header und in den Einstellungen einbauen. Umgesetzt in zwei Patches: 7.5.4 Offen, Aktionen und Telegram-Meldungen, 7.5.5 die übrigen Seiten. |
| **L5** | 7.5.6 | **Web-Lokalisierung (JavaScript & Hilfen):** `open-list.js` und `dialogs.js` mit `MailhelpI18n` verbinden. Einstellungs-Hilfetexte in `setting_help.py` übersetzen. |
| **L6** | 7.5.7 | **CLI, Gesamtabnahme & Dokumentation:** CLI-Meldungen lokalisieren, vollständige Python-Prüfung (`devtools.check full`) und Playwright-Browsersuite für beide Sprachen ausführen. 100 % Zeilen- und Branch-Coverage. |

---

## 6. Tests und Abnahmekriterien

### 6.1 Automatisierte Python-Tests
* **Vollständigkeitstest:** `test_i18n_completeness.py` stellt sicher, dass kein Schlüssel in `de` fehlt, wenn er in `en` existiert (und umgekehrt), sowie alle Formatparameter exakt übereinstimmen.
* **Formatierungstests:** Prüfung deutscher und englischer Datumsangaben, Zeitspannen, Ganztagsmarkierungen und Zahlenformate.
* **Kontext-Tests:** Korrekte Sprachauflösung über Session-Cookie, `Accept-Language`, `config.yaml` und Fallback auf `de`.
* **Coverage-Pflicht:** 100 % Zeilen- und Branch-Abdeckung für alle neuen und berührten Codepfade.

### 6.2 Browser- und UI-Tests
* Prüfung der Weboberfläche auf Deutsch und Englisch:
  * Umschalten der Sprache ändert sofort Navigation, Spaltenköpfe, Schaltflächen und Badges.
  * Wischgesten auf Mobilgeräten zeigen korrekte englische Texte („Accept“ / „Dismiss“).
  * Kein Layout-Bruch durch längere oder kürzere englische Texte.
  * No-JS-Kompatibilität bleibt in beiden Sprachen vollständig gewährleistet.

### 6.3 Bestätigung der Abgrenzung
* Nachweis, dass bei englischer Spracheinstellung die Modellprompts (`prompts.yaml`),
  die Tokenkostenberechnung und die Verarbeitungspipeline unverändert auf Deutsch ablaufen.
