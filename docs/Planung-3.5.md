# Mailhelp 3.5 – Übersichtliche Einstellungen und Postfächer wie IServ aktivieren

**Zielversion:** 3.5.0

**Stand:** 17. Oktober 2026

**Status:** Vollständig umgesetzt und abgenommen (siehe Abschnitt 5)
**Grundlage:** [Entwicklungsregeln](../AGENTS.md), [Projektspezifikation](../Mailhelp-Projektspezifikation.md),
[Planung 3.4](Planung-3.4.md), [Release 3.4](Release-3.4.md) (IServ „prüfen und aktivieren“, 3.4.7)

---

## 1. Ziel

1. **Einstellungsseite `/einstellungen` übersichtlich machen.** Bisher standen Modelle, alle
   Zugangsdaten, 16 Einstellungsgruppen, Push-Steuerung und acht Linkbuttons auf einer einzigen
   Seite. Künftig: eine Übersicht mit Kacheln, thematische Bereiche und eine Suche.
2. **Postfach hinzufügen wie IServ-Konten (3.4.7).** Ein Formular mit Server, Verbindungsart,
   Zugangsdaten, Ordnern und Startgrenze; „Verbindung prüfen und Postfach aktivieren“ meldet sich
   an, prüft die Ordner, speichert erst danach `config.yaml` und `.env` und startet den Abruf im
   nächsten sicheren Mailzyklus ohne Neustart. Der bisherige Entwurfsablauf bleibt als
   eingeklappte Alternative erhalten.

Nicht Teil von 3.5: Ändern oder Entfernen laufender Postfächer ohne Neustart (nur Hinzufügen wird
nachgeladen), Erststart ohne Konfiguration, OAuth im Browser.

## 2. Einstellungsseite

- `/einstellungen` (ohne Parameter): **Übersicht** mit Suchfeld und Kachelgruppen
  - Konten und Verbindungen: Postfächer (Anzahl), IServ-Konten (Anzahl), Zielprofile,
    Zugangsdaten, Einrichtung, Diagnose
  - Allgemeine Einstellungen: je Bereich eine Kachel mit Kurzbeschreibung und Hinweis
    „n Änderungen ausstehend“ (gespeichert, aber noch nicht aktiv)
  - Inhalte und Benachrichtigungen: Themen, Ignorierte Absender, Benachrichtigungsprofil,
    Zustellhistorie
  - System: Geräte, Mailhelp neu starten, Mailhelp beenden
- `/einstellungen?bereich=<schlüssel>`: nur die Gruppen eines Bereichs, Seitennavigation mit
  `aria-current`. Unbekannter Bereich → 404.

  | Schlüssel | Titel | Gruppen (bisherige `SETTING_GROUPS`) | Zusatz |
  | :--- | :--- | :--- | :--- |
  | `abruf` | Mailabruf | Mailabruf und Betrieb, Aufrufbudget und Mailgrenzen, Zeitlimits und Wiederholungen | – |
  | `benachrichtigungen` | Benachrichtigungen | Telegram, Tagesüberblick | Push-Steuerung |
  | `antworten` | Antworten und Termine | Antworten, Termindauern und Vorschlagsabgleich, Ziele | – |
  | `ki` | KI und Auswertung | Bildauswertung, Lernmodus, Tätigkeitsberichte, Kosten und Messung | Modelltabelle |
  | `daten` | Daten und Protokolle | Originalanhänge, Aufbewahrung, Protokollierung | – |
  | `system` | Weboberfläche und System | Weboberfläche | Geräte, Neustart, Beenden |
  | `zugangsdaten` | Zugangsdaten | Abschnitt `credentials_section` | – |

- `/einstellungen?suche=<text>`: alle Einstellungen, deren Bezeichnung, Name, Gruppe oder Bereich
  alle Suchwörter enthält, gruppiert mit Link zum Bereich; sonst Hinweis „Keine Einstellung … gefunden“.
- Speichern, Bestätigung und Warteschlange bleiben unverändert (`/einstellungen/speichern`).
- Nach dem Speichern einer Zugangsangabe führt „Zurück zu Zugangsdaten“ auf
  `/einstellungen?bereich=zugangsdaten` (statt `#settings-credentials`).

## 3. Postfach hinzufügen

- `POST /einstellungen/postfaecher/aktivieren` (CSRF, Sitzung, Entwurfsversion, `config.yaml`-
  und `.env`-Hash, Idempotenzschlüssel – wie IServ).
- Formularfelder: Anzeigename, IMAP-Server, Port (993), Verbindungsart (SSL/TLS, STARTTLS,
  unverschlüsselt), Benutzername, Passwort/App-Passwort (leer = hinterlegte `IMAP_<n>_…` nutzen,
  falls vorhanden), Ordner (kommagetrennt, erster = Posteingang), Entwurfsordner (Drafts),
  „Ältere Mails nicht verarbeiten vor“ (vorbelegt mit dem heutigen Datum, damit nicht der ganze
  Altbestand verarbeitet wird; leer = alle Mails).
- Prüfung vor dem Speichern: Doppelkonto (gleicher Server/Port/Benutzer wie ein anderes
  Postfach), Anmeldung, Ordnerliste (fehlende Ordner werden mit den vorhandenen genannt),
  Lesezugriff. Verständliche Fehlermeldungen ohne Serverantworten oder Geheimnisse; die
  Eingaben (außer Passwort) bleiben im Formular erhalten (Status 422).
- Postfachübersicht zeigt Karten mit Server, Ordnern und Zustand: „aktiv“, „deaktiviert“,
  „Entwurf – noch nicht aktiviert“, „gespeichert – Aktivierung ausstehend“, „Änderungen im Entwurf“.

## 4. Umsetzung

Neue Module:
- `src/mailhelp/connection_activation.py` – `ConnectionActivation` (abstrakte Basis aus dem
  IServ-Ablauf 3.4.7 herausgelöst: Autorisierung, Versions-/Hashprüfung, Idempotenz, Journal,
  atomares `.env`-Schreiben, Rebase des Entwurfs) und `ActivationProblem` (anzeigbare Meldung).
- `src/mailhelp/connection_runtime.py` – `PendingConnections` (Basis für „zwischen Mailzyklen
  nachladen“).
- `src/mailhelp/mailbox_activation.py` – `MailboxActivation` (Patch `imap.mailboxes`, wandelt das
  Format vor 3.1 um, Doppelkonto- und Ordnerprüfung).
- `src/mailhelp/mailbox_runtime.py` – `MailboxRuntime`: baut `ImapReader` für neue Postfächer,
  ergänzt `app.sources`, Orchestrator-Zuordnung, Metriken, Postfachlabels und die gemeinsamen
  Zugangsdaten; laufende Postfächer bleiben unberührt; Fehler → erneuter Versuch im nächsten Zyklus.
- `src/mailhelp/web/mailbox_add_site.py` – Formular und Handler.

Geänderte Module:
- `iserv_activation.py`, `iserv_runtime.py` – nutzen die neuen Basisklassen.
- `application.py` – Feld `mailbox_runtime`; `_cycle` lädt Postfächer und IServ-Konten nach.
- `composition.py` – erzeugt `MailboxRuntime` bei aktivierter Weboberfläche.
- `experience.py` – `ExperienceRuntime.add_mailboxes` (Antwortentwürfe, Postfachfilter).
- `web/mailbox_site.py` – neue Postfachübersicht; `index(…, problem, values)`.
- `web/iserv_site.py` – `reason(exc, names)` mit Feldnamen-Parameter.
- `web/settings_pages.py` – `AREAS`, `AREA_KEYS`, Übersicht, Bereiche, Suche;
  `settings_page(…, area, query, push)`.
- `web/settings_site.py` – liest `bereich`/`suche`, 404 bei unbekanntem Bereich.
- `web/site.py` – registriert `MailboxAddSite` als `site.mailbox_add`.
- `web/static/app.css` – Kacheln, Suche, aktiver Navigationspunkt, `fieldset`.
- `tests/web/test_iserv_activation.py` – Monkeypatch-Pfade auf `connection_activation`;
  `tests/web/test_credentials_settings.py` – auf `?bereich=zugangsdaten` umgestellt.

`ruff` und `mypy` sind sauber.

## 5. Abnahme

- Bestehende Web-, Service-, YAML- und Ende-zu-Ende-Tests verwenden die jeweiligen
  Einstellungsbereiche. Die Bestätigungs- und Warteschlangenverträge bleiben geprüft.
- `tests/web/test_settings_areas.py`: Übersicht, Kontenzahlen, alle Bereiche, Navigation,
  Mehrwortsuche, Escaping, keine Treffer, 404 und nicht verfügbare Konfiguration.
- `tests/web/test_mailbox_activation.py`: Erfolg, Idempotenz und Doppelklick, Neustart,
  CSRF, erneute Autorisierung, Entwurfs-/Dateikonflikte, Doppelkonten (auch deaktiviert
  und nur in `.env` hinterlegt), Ordnerfehler, Netzwerk-/Anmeldefehler, Prozessvariablen,
  Schreibfehler, Postfachlimit, gespeicherte Zugangsdaten und das Format vor 3.1.
- `tests/services/test_mailbox_reload.py`: Nachladen am Zyklusanfang, unveränderte
  laufende Reader, Ressourcenfreigabe, Wiederholung nach Fehler, gemeinsame Zugangsdaten,
  Zuordnungen, Metriken, Antwortentwürfe und Filter.
- `ui_tests/test_ui_settings35.py`: Übersicht, Bereich, Suche und Aktivierungsformular
  auf Desktop, Mobil und schmalem Bildschirm; Barrierefreiheit, 48-px-Tippflächen,
  Screenshots, Fehlereingaben und erfolgreiche Aktivierung. Bestehende Browserfälle
  einschließlich Bedienung ohne JavaScript sind angepasst.
- Regressionen vor dem Fix nachgewiesen: deaktivierte Doppelkonten wurden zugelassen;
  Postfachtitel hatten auf Mobilgeräten zu kleine Tippflächen. Beide sind korrigiert.
- README, CHANGELOG, Web-Anleitung, Projektspezifikation, Konfigurationsbeispiel und
  [Release 3.5](Release-3.5.md) sind aktualisiert; Versionsnummern stehen auf 3.5.0.
- Wheel und Quellpaket werden für die aktuelle Version neu gebaut. Der zuvor offene
  Pakettest verglich gegen veraltete Artefakte; neue Module und Dokumente sind im
  Paketvertrag aufgenommen.

| Prüfung | Ergebnis |
| --- | --- |
| Vollständige Python-Suite | 2.694 Tests bestanden |
| Zeilenabdeckung | 100 % – 21.524 von 21.524 Zeilen |
| Branch-Abdeckung | 100 % – 6.214 von 6.214 Branches |
| Ruff | Keine Befunde |
| mypy | Keine Befunde in 202 Quelldateien |
| Isoliert installiertes Wheel / Paketvertrag | 2 Tests bestanden |
| Vollständige Browser-Suite | 202 Tests bestanden, Desktop / Mobil / schmal |
| JavaScript-Abdeckung | 100 % der Blöcke in `app.js` und `sw.js` |

Die Python-Prüfung lief unter Linux/WSL ohne Root-Rechte, damit Schreibschutz real wirksam ist.
Eine Cachewarnung auf dem Windows-Mount betrifft nur den optionalen pytest-Cache.
Alle externen Dienste sind simuliert; Produktivkonfiguration und Zugangsdaten bleiben unberührt.
Der Coverage-Bericht enthält keine fehlenden Zeilen oder Branches; die 100-%-Schranke bleibt aktiv.

## 6. Bewusste Abgrenzung

Für bestehende Postfächer wird kein Austausch laufender Reader eingeführt. Änderungen,
Entfernen und Ersetzen von Zugangsdaten benötigen weiterhin Entwurfsübernahme und Neustart.
Eine entsprechende Erweiterung wäre eine spätere Planung.
