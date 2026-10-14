# Mailhelp 3.2 – Einstellungen je Postfach

> Historischer Versionsstand: Dieses Dokument beschreibt die genannte Version oder
> deren damaligen Plan. Ursprüngliche Ziele und Prüfergebnisse sind kein Nachweis
> des heutigen Umfangs. Aktueller Betrieb: [README](../README.md),
> [Release 3.3](Release-3.3.md) und [Projektspezifikation](../Mailhelp-Projektspezifikation.md).

Die Umsetzung erweitert 3.1 um vererbte Postfacheinstellungen und getrennte Kalender-/Aufgabenziele.
Die bisherige Einzelpostfachkonfiguration bleibt gültig. Die [Planung](Planung-3.2.md) beschreibt den Umfang.

## Einrichten und übernehmen

Unter **Einstellungen → Postfächer** lassen sich Postfächer hinzufügen und entfernen. Die stabile Nummer
bleibt die Verbindung zu gespeicherten Mails und Geheimnissen. Ein neues Postfach benötigt
`IMAP_<id>_USERNAME` und `IMAP_<id>_PASSWORD` in `.env` oder der Prozessumgebung.

Die Tabs **Ziele**, **Filter**, **Themen**, **Antworten** und **Benachrichtigungen** zeigen globale Vererbung
und eigene Werte. **Zurücksetzen auf global** entfernt die lokale Überschreibung. Einstellungen werden
zunächst im gemeinsamen Einrichtungsentwurf gespeichert. Vor der Übernahme zeigt die Vorschau die
betroffenen laufenden Mails. Ein anderer Themen- oder Filterentwurf muss vorher übernommen oder verworfen
werden. Änderungen an Verbindungen und Zieladaptern benötigen erfolgreiche aktuelle Diagnosen und einen
Dienstneustart. Operative Überschreibungen bestehender Postfächer gelten am nächsten Verarbeitungspunkt.

## Zielprofile und Geheimnisse

`targets` ist Profil 1. `target_profiles` enthält Profile 2–99 mit den gleichen Zielfeldern und einem
Anzeigenamen. `imap.mailboxes[].target_profile` wählt das Ziel für zukünftige Vorschläge.

```yaml
target_profiles:
  - id: 2
    label: Arbeit
    calendar_provider: outlook
    task_provider: microsoft_todo
    outlook_calendar: default
    microsoft_todo_list: default
imap:
  mailboxes:
    - id: 1
      label: Privat
      host: imap.private.example
      port: 993
      folders: [INBOX]
    - id: 2
      label: Arbeit
      host: imap.work.example
      port: 993
      folders: [INBOX]
      target_profile: 2
      personal_info: 'Arbeitsrolle und Signatur'
      smart_reply: false
      activity_report_folder: Projekte
      daily_briefing: true
      retention:
        full_mail_days: 7
      event_defaults:
        video_duration_minutes: 60
      notifications:
        quiet_hours:
          enabled: true
          start: '18:00'
          end: '08:00'
        categories:
          decisions: [telegram]
```

Profil 2 verwendet beispielsweise `MICROSOFT_2_CLIENT_ID`, `MICROSOFT_2_REFRESH_TOKEN`,
`GOOGLE_OAUTH_2_REFRESH_TOKEN`, `TODOIST_2_TOKEN` oder `CALDAV_2_PASSWORD`. OAuth-Client-ID und
Client-Secret dürfen vom Standardprofil geerbt werden. Refresh- und Zugriffstokens werden niemals geteilt.
Nur aktivierten Postfächern zugeordnete Profile verlangen ihre Providergeheimnisse.

Microsoft: `mailhelp --microsoft-login --profile 2` speichert die Anmeldung in `microsoft-token-2.json`.
Google: `mailhelp --google-auth --profile 2` öffnet den Browser, prüft State und PKCE über einen zeitlich
begrenzten Rückruf an `127.0.0.1` und speichert ausschließlich den nummerierten Refresh-Token atomar in
`.env`. Dafür eine Google-OAuth-App vom Typ **Desktop-App** und die Kalenderberechtigungen
`calendar.events` und `calendar.calendars.readonly` verwenden. Bei Docker diese erstmalige Browseranmeldung
auf dem Host ausführen und die geschützte `.env` einbinden. Tokens erscheinen nicht im Terminal.

Jeder Vorschlag behält sein ursprüngliches Profil. **Auf Zielprofil … umstellen** in Web oder Telegram
erzeugt eine neue, unbestätigte Version. Erst eine neue versionsbezogene Bestätigung erlaubt den externen
Schreibzugriff. Profile mit offenen Vorschlägen oder Postfachverweisen können nicht über die Oberfläche
entfernt werden. Nach manueller Entfernung bleibt der Vorschlag sichtbar und gesperrt.

Duplikatprüfung, unsichere Schreibresultate und Tagesüberblick verwenden den zugehörigen Adapter.
Offene Vorschläge unterschiedlicher Profile werden nicht zusammengeführt. Bei identischen Mailkopien
über mehrere Postfächer gilt die zuerst verarbeitete Mail; die andere Kopie erhält einen Hinweis.
Ein Profilfehler blockiert die übrigen Profile nicht.

## Themen, Filter und operative Regeln

Ein Thema ohne `mailboxes` gilt global. `mailboxes: [2]` begrenzt es auf Postfach 2;
`mailboxes: []` deaktiviert seinen Geltungsbereich. Das gilt auch für ausgeschlossene Themen.
Lernen bietet standardmäßig das Ursprungspostfach und zusätzlich die Auswahl für alle Postfächer.
Decision-Test und normale Verarbeitung verwenden die wirksamen Themen und Absenderfilter.

`irrelevant-senders.json` Schema 2 enthält globale `addresses`/`domains` und optional `mailboxes` mit
`addresses`, `domains` und `allow`. Exakte lokale `allow`-Adressen nehmen globale Sperren aus.
Schema 1 wird beim Lesen nicht verändert. Erst das nächste Speichern erstellt atomar Schema 2 und die
Sicherung `irrelevant-senders.json.v1`.

Antwortentwürfe bleiben im Ursprungspostfach und verwenden dessen persönliche Angaben. Ruhezeiten
und Kategoriekanäle gelten je Benachrichtigung; Bündel bleiben nach Postfach getrennt. Tagesüberblicke
zeigen die eingeschlossenen Postfächer als Abschnitte. Tätigkeitsberichte nutzen lokale persönliche
Angaben, den Standardordner und die wirksamen Filter. Lokale Volltextaufbewahrung darf nur kürzer sein
als die globale Aufbewahrung.

Sämtliche Ziele einschließlich `google_calendar`, `todoist_project`, Provider und Profilzuordnung
bleiben außerhalb des Analyse-Fingerprints. Beim Upgrade werden die bisherigen Fingerprints und
Themenrichtlinien der unveränderten Analysekonfiguration als gleichwertig registriert. Offene
Entscheidungen laufen dadurch auch nach einem Neustart weiter; gespeicherte Vorschläge behalten
ihr bisheriges Ziel und ihre Bestätigungspflicht. Die neuen Hashes müssen nicht bitgleich zu 3.1 sein.
Nur betroffene Postfächer werden bei einer analyserelevanten Änderung zurückgehalten.
Themenbeschränkungen lassen auch migrierte Mails in Postfächern mit unveränderten wirksamen Themen
weiterlaufen; der Abgleich prüft dafür den gespeicherten Themenstand und die Analyse-Richtlinie.
Globale Standarddauern gehören zum separaten Vorschlagskontext; lokale Dauerüberschreibungen werden
zusätzlich in den Postfach-Fingerprint aufgenommen.

## Upgrade und Rückkehr

1. Dienst stoppen und Konfiguration, `.env`, Token-Dateien sowie sämtliche Zustandsverzeichnisse sichern.
2. Paket aktualisieren und `mailhelp --check` ausführen. Zunächst ohne neue Felder starten.
3. Bestehende Vorschläge werden atomar und wiederholbar von Schema 2 auf Schema 3 mit Profil 1 migriert.
   Die Fingerprints bis einschließlich 3.1 werden bei unveränderter Analysekonfiguration automatisch
   als gleichwertig registriert. Nach dieser Registrierung beeinflussen auch spätere Zieländerungen
   die laufenden Mails nicht. Deshalb zunächst mit den bisherigen Zielen starten.
   Alte Filter bleiben bis zum nächsten Schreibzugriff unverändert. Benachrichtigungsmarker verhindern
   erneuten Versand bereits übermittelter oder unklarer Tagesüberblicke.
4. Neue Profile und Überschreibungen einrichten, lesende Diagnosen prüfen, Entwurf übernehmen und
   bei Verbindungs-/Zieländerungen neu starten. Testmodus vor echten Schreibaktionen verwenden.

Eine Rückkehr zu 3.1 benötigt die vorherige Sicherung von Konfiguration und Zuständen. Schema-3-Vorschläge
und Filter Schema 2 sind für 3.1 nicht vorgesehen. Den Dienst vor der Wiederherstellung stoppen;
neuere Zustände separat sichern und keine extern möglicherweise erfolgreichen Aktionen erneut freigeben.

Die empfohlenen Entscheidungen der Planung gelten: kein Übernehmen einer Duplikatkopie in ein anderes
Profil, Lernen standardmäßig im Ursprungspostfach, keine lokalen Relevanzschwellen und keine Entwürfe
in einem anderen Postfach.

## Abnahme

Windows und WSL: jeweils 2.357 Python-Tests mit 100 % Zeilen- und Branch-Abdeckung. Browser:
je 146 Tests über Desktop, Mobil und schmale Telefonansichten, einschließlich Zielumstellung ohne
externe Anlage; vollständige JavaScript-Abdeckung. Ruff/Mypy, installierte Pakete und frische
Docker-Smokes für Verarbeitung und Lernen einschließlich Neustart sind erfolgreich geprüft.
