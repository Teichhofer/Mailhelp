# Mailhelp 8.3 – Vollständige Bereinigung der Sprachausgabe (Deutsch & Englisch)

**Stand:** 22. November 2026. **Status:** Umgesetzt (Version 8.3.1).

**Zielversion:** 8.3, erste Auslieferung 8.3.1; weitere Commits mit fortlaufenden Patchversionen gemäß [Entwicklungsregeln](../AGENTS.md).

**Grundlagen:** [Entwicklungsregeln](../AGENTS.md), [Planung 7.5](Planung-7.5.md), [Planung 7.8](Planung-7.8.md), [Planung 8.0](Planung-8.0.md), [Planung 8.1](Planung-8.1.md), [Planung 8.2](Planung-8.2.md).

---

## 1. Anlass und Prüfergebnis auf dem Live-Server (8.2.1)

Nach dem Deployment von **Mailhelp 8.2.1** (`mailhelp-production:8.2.1-183649f`) am 21.11.2026 wurden sowohl die Produktivinstanz (`stefan.inboxstride.de`) als auch die Demo-Instanz (`demo.inboxstride.de`) in beiden Sprachen (`/de/` und `/en/`) systematisch geprüft:

- **Live-Demo-Crawl:** 101 Seiten auf Deutsch, 107 Seiten auf Englisch (inklusive Login, Übersicht, Mails, Detailseiten aller 30 Beispielmails, aller 11 Vorschläge, Versionen, Bearbeitung, Verlauf, Abgleich, Lernen, Einstellungen und Status).
- **Live-Produktion:** Anmeldeseite in Deutsch und Englisch.
- **Vollständige App- und Codebase-Prüfung (8.2.1):** 160 authentifizierte Routen inklusive Einrichtung, Zugangsdaten, Web-Passwort, Ersteinrichtungs-Assistent (Schritte 1–5), Onboarding (8.2), gehostete OAuth-Seiten (8.0/8.1/8.2) und mitgelieferte Dokumentation (`/hilfe/dokumentation`) sowie statischer AST-Scan aller unübersetzten Strings in `src/mailhelp/`.

### Zusammenfassung des Befunds

- **Deutsch (`/de/`):** Alle geprüften Seiten der Demo- und Produktivinstanz zeigen korrekte deutsche Texte (keine unbeabsichtigten englischen UI-Texte). Einziger sprachübergreifender Darstellungsfehler: Auf `/mail/<id>` wird in der Liste der erkannten Aktionen der rohe interne Statuswert `pending_confirmation` statt des lesbaren Labels ausgegeben (`archive_pages.py:383`).
- **Englisch (`/en/`):** Der Großteil der Oberfläche und der 30 englischen Demo-Mails (`standard-en-v1`) ist sauber übersetzt. Es wurden jedoch **konkrete deutsche Resttexte auf englischen Seiten** sowie eine **systematische Python-`str`-Subklassen-Falle** bei `msg(...)` festgestellt, die in **8.3** vollständig behoben werden.

---

## 2. Vollständige Befundliste

### 2.1 Direkt auf dem Live-Server (Produktion & Demo) beobachtete Fehler

| Nr. | Bereich / URL (EN) | Aktuelle Anzeige auf `/en/` | Erwartete Anzeige (EN) | Ursache im Code |
| :--- | :--- | :--- | :--- | :--- |
| **B1** | Produktion `/anmelden` (Browser-`<title>`) | `Anmelden · Mailhelp` | `Sign in · Mailhelp` | `src/mailhelp/web/pages.py:291` übergibt unübersetztes `"Anmelden"` an `layout(...)`. |
| **B2** | Demo `/mail/<id>` & `/vorschlag/<mail>/<id>` (40×) | `Decision-Modell: typisierte Relevanz- und Themenentscheidung.` | `Decision model: typed relevance and topic decision.` | Hartkodierter deutscher String in `src/mailhelp/llm/decisions.py:257` (sowie `:259, :261, :274`), im englischen Demo-Datensatz `src/mailhelp/defaults/demo/standard-en-v1/state/*.json` gespeichert und in `src/mailhelp/web/archive_pages.py:379,401` ohne `stored()` gerendert. |
| **B3** | Demo `/mail/<id>` (3 Mails mit Frist ohne Aufgabe) | Überschrift `Prüfhinweise`, Hinweistext `Die Zusammenfassung nennt eine Frist, zu der es keinen Aufgabenvorschlag gibt. Bitte prüfen, ob ein eigener Auftrag dahintersteht; eine Frist allein ist keine Aufgabe.`, Beleg `Evidence: Zusammenfassung: 2026-12-09, 16:00–17:30` | `Review hints`, englischer Hinweistext, `Evidence: Summary: 2026-12-09, 16:00–17:30` | `src/mailhelp/web/archive_pages.py:426` (`<h3>Prüfhinweise</h3>`), `src/mailhelp/review/consistency.py:47-95` (alle Hinweistexte und Belegpräfixe unübersetzt) und fehlendes `stored()` in `archive_pages.py:421-422`. |
| **B4** | Demo `/vorschlag/<mail>/<id>` (11×) | `Quellenmail` (und Fallback `Zeit nicht mehr gespeichert`) | `Source email` (`Time no longer stored`) | `src/mailhelp/web/reconciliation_pages.py:61-62` ohne `tr()`/`msg()`. |
| **B5** | Demo `/abgleich` (6×) & `/status` | `Version 1 · Target: Google Kalender · primary` | `Version 1 · Target: Google Calendar · primary` | `CALENDAR_LABELS`, `TASK_LABELS`, `provider_services()` in `src/mailhelp/external/providers.py:46-56` sowie Dienstnamen in `src/mailhelp/support/metrics.py` und `src/mailhelp/support/connection_health.py` sind normale deutsche Strings statt `msg(...)`. |
| **B6** | Demo `/mail/<id>` (DE & EN, 28×) | `· pending_confirmation` | DE: `· Wartet auf Bestätigung` / EN: `· Pending confirmation` | `src/mailhelp/web/archive_pages.py:383` rendert `p.status.value` statt `STATUS_LABELS[p.status]`. |

### 2.2 Auf weiteren authentifizierten Seiten & im Codebase-Audit gefundene Fehler

| Nr. | Bereich / URL (EN) | Aktuelle Anzeige auf `/en/` | Ursache im Code |
| :--- | :--- | :--- | :--- |
| **B7** | `/einstellungen/web-passwort` & Login-Fehlerseiten | Komplette Seite auf Deutsch (`Web-Passwort`, `Web-Passwort ändern`, `Neues Passwort (mindestens 12 Zeichen)`, `Passwort speichern`, Fehlerseiten `Anmeldung fehlgeschlagen`, `Passwort nicht gespeichert`, `Code nicht gesendet`, `Bitte später erneut versuchen`, `Lokalen Code anfordern`) | `src/mailhelp/web/login_site.py:77-142` nutzt weder `tr()` noch `msg()`. |
| **B8** | `/einrichtung` (Einrichtung) & `/einrichtung/schritt/1..5` (Ersteinrichtung) | Seitentitel `Ersteinrichtung · Mailhelp`; `Änderungsliste`, `Neustart erforderlich` / `sofort`; Secret-Status `fehlt` / `vorhanden`; `noch nicht geprüft` in der Ordnerliste | `src/mailhelp/web/initial_pages.py:258`, `src/mailhelp/web/setup_site.py:237-246,291,294`, `src/mailhelp/app/setup_runtime.py:112-120`. Zusätzlich **Python-`str`-Subklassen-Falle**: `"; ".join(parts)` ruft bei `Message("noch nicht geprüft")` nicht `Message.__str__()` auf. |
| **B9** | `/einstellungen/zugangsdaten` | `Postfach 1`, `KI-Anbieter`, `Zielprofil 1`, `IMAP-Passwort`, `OpenRouter API-Schlüssel`, `Google OAuth Client-Schlüssel` usw. | `src/mailhelp/runtime/credentials.py:24-33,99-109` ohne `msg()`/`tr()`. |
| **B10** | `/status` (vollständige Instanz) | `IMAP-Postfach`, `Jev (Relevanz)`, `Google Kalender`, `Google-Anmeldung`, `Microsoft-Anmeldung` | `src/mailhelp/support/metrics.py:136-145,205,228-229,302` und `src/mailhelp/support/connection_health.py:29-36`. |
| **B11** | `/hilfe/dokumentation` | Browser-`<title>` `Hilfe · Mailhelp` (und `<h1>Hilfe</h1>` in Fehlerfällen) | `src/mailhelp/web/help_site.py:56-57,81,91` ohne `tr()`. |
| **B12** | `/lernen/vorschlaege` | `Ohne Thema`, `Absender entfernt`, Hinweissätze zu Absendern und Lernlauf | `src/mailhelp/review/proposal_evaluation.py:147,204,373,512,546,606` und `src/mailhelp/web/proposal_evaluation_pages.py:268`. |
| **B13** | Weitere unübersetzte UI-Labels in `web/` | `Ausstehende Themenänderungen` (`topic_site.py:141`), `Ausschließen` (`activity_pages.py:389`), `Abbrechen` (`experience.py:218`), `Filteränderung` (`mailbox_draft.py:44`, `mailbox_site.py:368`), `Profiländerung vormerken` (`mailbox_profiles.py:80`), `geändert`/`unverändert` (`rule_compare.py:58,68`), `Unbekanntes Gerät` (`auth.py:110`), `Weboberfläche` (`settings_pages.py:506,509`), `Eigenes Postfach-Briefing` / `Kein relevantes Thema für dieses Postfach` (`prefilter_stats.py:34,36`). | Fehlende `tr()`/`msg()`-Aufrufe in den jeweiligen Web-Modulen. |
| **B14** | Laufzeit-, Diagnose-, Prüf- und Onboarding-Meldungen | Meldungen aus `setup_messages.py`, `diagnostics.py`, `onboarding.py` (Dry-Run-Vorschau & Fehlermeldungen), `demo_answers.py`, `demo_visitors.py`, `error_reporting.py`, `verification_texts.py`, `removal.py`, `series.py` | Werden als reine deutsche Strings erzeugt und teils ohne `stored()` oder ohne passenden Katalogeintrag in `i18n/en.py` angezeigt. |
| **B15** | Mobile Tabellen-Labels (`data-label`) & EN-Feinschliff | In `src/mailhelp/i18n/en.py` stehen in einer EN-Vorlage noch deutsche `data-label`-Attribute (`Geltungsbereich`, `Beispiele / Ausschlüsse`, `Beschreibung`), die auf schmalen Displays sichtbar sind. Zudem uneinheitliches großgeschriebenes `Mails` statt `emails` in einzelnen EN-Strings (`Only Mails that Mailhelp...`, `Search Mails stored by Mailhelp.`, `What happened to proposals and Mails.`). | `src/mailhelp/i18n/en.py` (Katalogeinträge). |
| **B16** | Englische Dokumentation (`docs/en/*.md`) | Einzelne deutsche Reste in `docs/en/Web-Einstellungen.md` (`Errors are in Deutsch`, `TT.MM.JJJJ`, `JJJJ-MM-TT`) und `docs/en/Ziele-einrichten.md` (`Frist: 12.05.2026, 18:00 Uhr`). | Übersetzungsreste in `docs/en/`. |

---

## 3. Technische Ursache: Die `Message(str)`-Falle

Die Klasse `Message(str)` in `src/mailhelp/i18n/__init__.py` überschreibt `__str__()`, damit `msg("...")` zur Laufzeit in der aktiven Sprache gerendert wird. In CPython greifen C-implementierte `str`-Methoden wie `"; ".join(parts)` oder `html.escape(value)` jedoch **direkt auf den internen String-Puffer** zu, ohne `__str__()` aufzurufen!

**Folge:** `e("; ".join(parts))` in `setup_site.py:246` gab trotz `msg("noch nicht geprüft")` auf Englisch wörtlich `noch nicht geprüft` aus.

**Lösung in 8.3:**
1. Die zentrale HTML-Escape-Funktion `e(value)` in `src/mailhelp/web/pages.py` ruft explizit `html.escape(str(value), quote=True)` auf (für `Message` wird damit garantiert `Message.__str__()` ausgewertet).
2. Alle `join(...)`-Stellen, die `Message`-Objekte enthalten können, wandeln Elemente explizit per `str(item)` um oder verwenden direkt `tr(...)` zur Renderzeit.
3. Ein statischer Prüftest erkennt künftig unübersetzte Strings in `layout(...)`-Titeln, HTML-Templates und `msg()`-Verwendungen.

---

## 4. Umsetzungsplan in 5 Arbeitspaketen

### Paket 1: Live-sichtbare Hauptfehler & Kern-Infrastruktur (B1–B6, `Message`-Falle)
1. **`pages.py` (`e()` und `login_page()`):**
   - `e(value)` sicherstellen, dass `str(value)` vor `html.escape` ausgewertet wird.
   - `layout(tr("Anmelden"), ...)` in `pages.py:291`, `layout(tr("Ersteinrichtung"), ...)` in `initial_pages.py:258`, `layout(tr("Hilfe"), ...)` in `help_site.py:56,81,91`.
2. **`archive_pages.py` & `consistency.py` (B2, B3, B6):**
   - `archive_pages.py:383`: `e(str(STATUS_LABELS[p.status]))` statt `e(p.status.value)`.
   - `archive_pages.py:379,401`: `stored(...)` auf `relevance.get("reason")` und `step.model_reason` anwenden, damit systemgenerierte Begründungen wie `"Decision-Modell: typisierte Relevanz- und Themenentscheidung."` in Englisch übersetzt werden (freie LLM-Texte bleiben durch `stored()` unverändert).
   - `archive_pages.py:421-422,426`: `<h3>{tr("Prüfhinweise")}</h3>` sowie `e(stored(hint.text))` und `e(stored(hint.evidence))`.
   - `consistency.py`: Alle deterministischen Hinweistexte und Belegpräfixe (`Zusammenfassung: {p0}`, `Termin „{p0}“`, `Vorschlag „{p0}“`, `Anhang „{p0}“`, `Router und Extraktion`, `Gespeicherter Verarbeitungsfehler`, `Mailtext`, `Anhänge`) über `de(...)` markieren und im EN-Katalog `src/mailhelp/i18n/en.py` hinterlegen.
   - `llm/decisions.py:257-274`: Die vier festen System-Begründungen über `de(...)` markieren und in `en.py` übersetzen.
3. **`reconciliation_pages.py` & `providers.py` & `metrics.py` & `connection_health.py` (B4, B5):**
   - `reconciliation_pages.py:61-62`: `tr("Quellenmail")` und `tr("Zeit nicht mehr gespeichert")`.
   - `providers.py:46-56`: `CALENDAR_LABELS`, `TASK_LABELS` und `provider_services()` mit `msg(...)` auszeichnen (oder beim Rendern in `reconciliation_pages.py`, `status_pages.py`, `status_accounts.py` über `stored()`/`tr()` übersetzen, ohne bestehende interne Logik/Tests zu brechen).
   - `metrics.py` und `connection_health.py`: Dienst- und Statusnamen (`IMAP-Postfach`, `Jev (Relevanz)`, `Google Kalender`, `Google-Anmeldung`, `Microsoft-Anmeldung`, `IServ-Anmeldung fehlgeschlagen`) über `stored()` beim Rendern in der Weboberfläche übersetzen und in `en.py` pflegen.
4. **Englischer Demo-Datensatz (`standard-en-v1`):**
   - Prüfen, ob neben der `stored()`-Übersetzung der `Decision-Modell`-Begründung noch weitere deutsche Texte in `src/mailhelp/defaults/demo/standard-en-v1/` stehen, und diese ggf. bereinigen.

### Paket 2: Web-Passwort, Einrichtung, Zugangsdaten & Lernen (B7–B12)
1. **`login_site.py` (B7):** Alle Titel, Formulare und Fehlerseiten in `password()`, `password_settings()`, `save_password()`, `request_code()`, `pair()` auf `tr()` umstellen und in `en.py` eintragen.
2. **`setup_site.py` & `setup_runtime.py` (B8):**
   - `setup_site.py:237-246`: `str(...)` bei `parts` sicherstellen.
   - `setup_site.py:291,294`: `tr("<h2>Änderungsliste</h2><ul>")`, `tr("sofort")`, `tr("Neustart erforderlich")`.
   - `setup_runtime.py:112-120`: `msg("vorhanden")` / `msg("fehlt")` (bzw. `stored(status)` beim Rendern in `setup_site.py:261`).
3. **`credentials.py` (B9):** Gruppen- und Zugangslabels in `src/mailhelp/runtime/credentials.py` übersetzbar machen (`msg()` / `de()` + `stored()` in `secrets_site.py` / `settings_pages.py`).
4. **`proposal_evaluation.py` & `proposal_evaluation_pages.py` (B12):** `Ohne Thema`, `Absender entfernt` sowie die Absender- und Lernlauf-Hinweise über `de()`/`tr()` übersetzen.

### Paket 3: Restliche Web-Module, Laufzeitmeldungen & Onboarding (B13–B14)
1. Alle übrigen unübersetzten UI-Strings in `topic_site.py`, `activity_pages.py`, `experience.py`, `mailbox_draft.py`, `mailbox_profiles.py`, `mailbox_site.py`, `rule_compare.py`, `auth.py`, `prefilter_stats.py`, `settings_pages.py` auf `tr()`/`msg()` umstellen.
2. Laufzeit- und Prüf-Meldungen in `setup_messages.py`, `diagnostics.py`, `onboarding.py` (inklusive Dry-Run-Beispielvorschlag), `demo_answers.py`, `demo_visitors.py`, `error_reporting.py`, `verification_texts.py`, `removal.py`, `series.py` über `de()` markieren, in `en.py` vollständig übersetzen und an den Renderstellen mit `stored()` ausgeben.

### Paket 4: Katalog-Feinschliff & Englische Dokumentation (B15–B16)
1. In `src/mailhelp/i18n/en.py` die deutschen `data-label`-Attribute (`Scope`, `Examples / exclusions`, `Description`) korrigieren und uneinheitliches `Mails` in betroffenen EN-UI-Strings an `emails` angleichen.
2. In `docs/en/Web-Einstellungen.md` und `docs/en/Ziele-einrichten.md` die gefundenen deutschen Reste (`Errors are in Deutsch`, `TT.MM.JJJJ`, `JJJJ-MM-TT`, `Frist: ... Uhr`) korrigieren und das mitgelieferte Help-Dokumentationspaket prüfen.

### Paket 5: Automatisierte Regressionstests & Vollprüfung
Gemäß [AGENTS.md](../AGENTS.md) gilt für jeden Bugfix:
1. **Regressionstests vor dem Fix schreiben (rot -> grün):**
   - **Live-ähnlicher EN/DE-Sprach-Audit-Test** (`tests/i18n/test_english_completeness_audit.py`):
     - Rendert den kompletten Demo-Bestand (`standard-en-v1` in EN, `standard-v1` in DE) über alle relevanten Routen (`/anmelden`, `/`, `/offen`, `/mails`, `/mail/<id>`, `/vorschlag/<mail>/<id>`, `/abgleich`, `/verlauf`, `/lernen`, `/lernen/vorschlaege`, `/einstellungen`, `/status`, `/status/vorschlaege`).
     - Rendert zusätzlich `/einstellungen/web-passwort`, `/einstellungen/zugangsdaten`, `/einrichtung`, `/einrichtung/schritt/1..5`, `/onboarding`, `/hilfe/dokumentation` in EN.
     - Prüft automatisiert, dass:
       - `<html lang="en">` bzw. `<html lang="de">` stimmt,
       - keiner der behobenen deutschen Resttexte (`Anmelden · Mailhelp`, `Ersteinrichtung · Mailhelp`, `Hilfe · Mailhelp`, `Web-Passwort`, `Quellenmail`, `Prüfhinweise`, `Google Kalender`, `Decision-Modell:`, `Änderungsliste`, `noch nicht geprüft`, `Ohne Thema`, `pending_confirmation`) auf EN-Seiten erscheint,
       - `Message(str)` in `e("; ".join([...]))` korrekt übersetzt wird.
   - Bestehende i18n-Vollständigkeitstests erweitern, sodass auch `de(...)`-Aufrufe und `layout(title, ...)`-Titel geprüft werden.
2. **Qualitätsabnahme (100 % Zeilen- & Branch-Abdeckung):**
   - `python -m devtools.check full --workers 12` (muss mit 100 % Zeilen- und 100 % Branch-Abdeckung, 0 Ruff- und 0 Mypy-Fehlern bestehen).
   - Anschließend getrennt: `python -m pytest ui_tests -n 6 --dist worksteal --no-cov` (100 % JS-Abdeckung).
3. **Versions- & Dokumentationspflege bei Umsetzung:**
   - Patch-Version auf `8.3.1` in `pyproject.toml` und `src/mailhelp/__init__.py`, Eintrag in `CHANGELOG.md`, Aktualisierung von `README.md` und `docs/Release-8.3.md`.
   - Nach erneutem Server-Update: Verifikation auf `stefan.inboxstride.de` und `demo.inboxstride.de` sowie Aktualisierung von `docs/Serverhandbuch.md`, `docs/Betrieb.md` und `/opt/mailhelp/server-docs`.
