# Release 8.4 – Automatische Kalendererinnerungen

**Version:** 8.4.1 · **Stand:** 22. November 2026 · **Plan:** [Planung 8.4](Planung-8.4.md)

## Umgesetzte Änderungen

1. **Konfigurationsmodell (`TargetSettings` / `TargetProfileSettings`)**
   - Neue Felder je Zielprofil: `calendar_reminder_enabled` (Standard `true`) und
     `calendar_reminder_minutes` (Standard `5`, Bereich `0`–`1440`, `0` = zum Beginn).
   - Bestehende Konfigurationen übernehmen beim Laden implizit `true` und `5`.
   - Änderungen an den Erinnerungsfeldern fließen über `profile_binding.policy_hash`
     automatisch in die Profilrevision ein.
2. **Gemeinsamer Erinnerungs- und Vorschau-Pfad**
   - Neues Modul `src/mailhelp/external/reminders.py` liefert einheitlich effektiven
     Erinnerungswert, Provider-Payloads, Nachlese-Fakten und lokalisierte Vorschautexte
     (DE & EN).
   - Web-Karten (`CardContent` / `review_pages.py`) und Telegram-Karten
     (`format_proposal` / `ProposalPresenter`) zeigen vor jeder Bestätigung den
     tatsächlichen Erinnerungswert des gebundenen Zielprofils (`Erinnerung: 5 Minuten vor Beginn`,
     `Erinnerung: 1 Minute vor Beginn`, `Erinnerung: zum Beginn`, `Erinnerung: keine`).
   - Ganztägige Termine, Absagen, reine Videolink-Ergänzungen und übersprungene Dubletten
     erhalten keine Erinnerungszusage und keinen minutengenauen Alarm.
3. **Provider-Anbindung & Nachleseprüfung**
   - **Google Kalender**: explizites `reminders` (`useDefault: false`, genau ein `popup`-Override
     bzw. `overrides: []` bei Deaktivierung).
   - **Outlook / Microsoft 365**: `isReminderOn` und `reminderMinutesBeforeStart` in `_graph_body`
     und `$select`.
   - **CalDAV / iCloud**: genau eine `VALARM`-Komponente (`TRIGGER:-PT{minutes}M` bzw. `PT0S`,
     `ACTION:DISPLAY`, `DESCRIPTION:Mailhelp-Erinnerung`), saubere Ersetzung/Entfernung bei
     bestätigten Updates unter Erhalt fremder Eigenschaften und `UID`.
   - **Nachleseprüfung**: `verification.py` und `verification_texts.py` vergleichen das
     `reminder`-Feld gegen den tatsächlichen Providerstand (inkl. Erkennung eines stillen
     `useDefault: true`-Fallbacks als `MISMATCH` ohne blinde Wiederholung).
4. **Weboberfläche & Dokumentation**
   - Zweisprachige Felder und Hilfetexte auf `/einstellungen` (Profil 1) und
     `/einstellungen/zielprofile` (weitere Zielprofile) mit begrenztem Zahlenfeld (`0`–`1440`)
     und Inaktiv-Hinweis, während der vorbereitete Minutenwert speicherbar bleibt.
   - `config.example.yaml`, `docs/Web-Einstellungen.md`, `docs/en/Web-Einstellungen.md` und
     der gebündelte Hilfe-Index aktualisiert.
