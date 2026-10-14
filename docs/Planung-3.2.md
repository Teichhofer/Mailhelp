# Mailhelp 3.2 – Einstellungen je Postfach

**Zielversion:** 3.2.1

**Stand:** 14. Oktober 2026

**Status:** Umsetzung und lokale Abnahme abgeschlossen (3.2.1); baut auf [Planung 3.1](Planung-3.1.md) auf; Nachfolge-Release: [Planung 3.3](Planung-3.3.md) (Architektur-Refactoring & Konsolidierung)
**Grundlage:** [Planung 3.1](Planung-3.1.md), [Planung 3.0](Planung-3.0.md), [Projektspezifikation](../Mailhelp-Projektspezifikation.md), [Entwicklungsregeln](../AGENTS.md)

## 1. Ziel und Umfang

3.1 verarbeitet mehrere Postfächer mit **einer gemeinsamen** Konfiguration. 3.2 erlaubt, dass sich
Postfächer fachlich unterscheiden, zum Beispiel:

- Arbeitsmails erzeugen Termine im Outlook-Kalender und Aufgaben in Microsoft To Do,
  private Mails weiterhin in Google Kalender und Todoist.
- Ein Newsletter-Absender wird nur im privaten Postfach ignoriert, im Arbeitspostfach nicht.
- Das Thema „Gemeinderat“ ist nur im privaten Postfach relevant, „Projekt X“ nur im Arbeitspostfach.
- Antwortentwürfe aus dem Arbeitspostfach tragen Arbeitssignatur und -rolle.
- Für das Arbeitspostfach gelten abends Ruhezeiten, für das private nicht.

Das Prinzip: **Überschreiben statt kopieren.** Alles bleibt global konfiguriert; ein Postfach
überschreibt nur, was bei ihm abweicht. Ohne Überschreibungen verhält sich 3.2 wie 3.1;
die bisherigen Analyse-Fingerprints werden beim Upgrade als gleichwertig registriert.

**Nicht Teil dieses Plans:** Mehrbenutzerbetrieb, eigene Telegram-Chats oder Bots je Postfach,
getrennte Weboberflächen/Anmeldungen je Postfach, eigene Prompts oder Modelle je Postfach,
automatisches Verschieben von Mails zwischen Postfächern, SMTP-Versand.

## 2. Verbindliche Grundsätze

- Rückwärtskompatibel: eine 3.1-Konfiguration bleibt gültig und unverändert wirksam.
- Die stabile Postfachnummer `id` aus 3.1 ist der einzige Bezug; Labels sind reine Anzeige.
- **Wirksame Einstellungen einer Mail** = globale Einstellungen + Überschreibungen ihres Postfachs
  zum Zeitpunkt der Verarbeitung. Sie werden deterministisch berechnet und nie aus Mailinhalten abgeleitet.
- Vorschläge bleiben an das beim Erzeugen festgelegte Ziel gebunden. Eine spätere Zieländerung
  am Postfach verschiebt keinen bestehenden Vorschlag und erteilt keine Freigabe.
- Externe Schreibzugriffe erfordern unverändert eine ausdrückliche, versionsbezogene Bestätigung.
- Geheimnisse bleiben in `.env`/Prozessumgebung, nummeriert nach dem Muster aus 3.1.
- Analyse-Fingerprints ändern sich nur für die Postfächer, deren analyserelevante Überschreibungen sich ändern.

## 3. Zielprofile (Kalender und Aufgaben)

### 3.1 Konfiguration

Der bestehende Block `targets` bleibt das **Standardprofil**. Zusätzliche Profile werden nummeriert;
ein Postfach verweist auf ein Profil.

```yaml
targets:                       # Standardprofil (unverändert)
  calendar_provider: google
  task_provider: todoist
  google_calendar: primary
  todoist_project: '1234567890'
target_profiles:
  - id: 2                      # Ganzzahl 2–99, stabil; 1 ist das Standardprofil
    label: Arbeit
    calendar_provider: outlook
    task_provider: microsoft_todo
    outlook_calendar: default
    microsoft_todo_list: default
    microsoft_tenant: contoso.onmicrosoft.com
imap:
  mailboxes:
    - id: 1
      label: Privat
      # ohne target_profile → Standardprofil
    - id: 2
      label: Arbeit
      target_profile: 2
```

- Ein Profil enthält dieselben Felder und Validierungen wie `targets`.
- Ein Verweis auf ein nicht vorhandenes Profil ist ein Konfigurationsfehler mit Schlüsselpfad.

### 3.2 Geheimnisse

| Profil | Variablen |
| :--- | :--- |
| Standard (1) | unverändert: `TODOIST_TOKEN`, `GOOGLE_OAUTH_…`, `MICROSOFT_…`, `CALDAV_USERNAME/PASSWORD` |
| `id: <n>` | gleiche Namen mit Nummer: `TODOIST_<n>_TOKEN`, `GOOGLE_OAUTH_<n>_REFRESH_TOKEN`, `MICROSOFT_<n>_REFRESH_TOKEN`, `CALDAV_<n>_PASSWORD` … |

- Client-ID/-Secret einer OAuth-App (Google, Microsoft, Todoist) dürfen profilübergreifend gemeinsam
  genutzt werden: Fehlt `…_<n>_CLIENT_ID`, gilt der Wert des Standardprofils. Tokens werden nie geteilt.
- Benötigt werden nur Geheimnisse von Profilen, auf die ein aktiviertes Postfach verweist.
- Die OAuth-Einrichtungsabläufe (`--google-auth`, Microsoft-Gerätecode) erhalten `--profile <n>`.

### 3.3 Verarbeitung

- Der Proposal-Builder setzt `target` und neu `target_profile` aus dem Profil des Postfachs der Mail.
  Vorschlagsschema +1; Migration setzt bestehende Vorschläge auf Profil 1.
- `TargetWriter`, Duplikatprüfung im Ziel, Bestandsvorschau (2.4) und Tagesüberblick verwenden je
  Vorschlag den Adapter seines Profils. Adapter werden je Profil einmal aufgebaut und geschlossen.
- **Abgleich offener Vorschläge (2.4):** Kandidaten werden nur innerhalb desselben Zielprofils gesucht.
  Vorgänge mit unterschiedlichen Profilen werden nie zusammengeführt, auch wenn sie inhaltlich gleich sind.
- **Kontoübergreifende Duplikate (3.1):** Erreicht dieselbe Mail zwei Postfächer mit unterschiedlichen
  Profilen, gilt die zuerst verarbeitete Mail. Die Oberfläche zeigt, dass die Kopie im anderen Postfach
  als Duplikat erkannt wurde. Optional: „Für Profil X übernehmen“ erzeugt einen neuen, unbestätigten
  Vorschlag mit eigenem Ziel (offene Entscheidung §10).
- Ein Profil, das ausgefallen ist oder entfernt wurde, blockiert nur Schreibzugriffe seiner Vorschläge.
  Nach Entfernung bleibt der Vorschlag sichtbar, ist aber nicht mehr bestätigbar („Ziel nicht mehr konfiguriert“).
- Ändert der Nutzer das Profil eines Postfachs, gilt das nur für neu erzeugte Vorschläge. Bestehende
  offene Vorschläge können in Web/Telegram ausdrücklich „auf neues Ziel umstellen“ – das erzeugt eine
  neue Version, die erneut bestätigt werden muss.
- Sämtliche Ziele sind nicht Teil des Analyse-Fingerprints, einschließlich der bisher enthaltenen
  Standardfelder `google_calendar` und `todoist_project`.

## 4. Ignorierlisten und Absenderfilter

### 4.1 Absenderfilter (`irrelevant-senders.json`)

Schema 2 mit globalem Teil und optionalen Postfachteilen:

```json
{
  "schema_version": 2,
  "addresses": ["newsletter@example.org"],
  "domains": ["werbung.example"],
  "mailboxes": {
    "2": {"addresses": ["intern-digest@firma.example"], "domains": [], "allow": ["chef@werbung.example"]}
  }
}
```

- Wirksamer Filter eines Postfachs = global ∪ Postfachteil, abzüglich postfachbezogener `allow`-Einträge.
  `allow` ermöglicht, einen global gesperrten Absender für ein Postfach zuzulassen.
- Schema 1 wird beim Laden als Schema 2 ohne Postfachteile gelesen und erst beim nächsten Schreiben
  atomar umgestellt (Sicherung `irrelevant-senders.json.v1`).
- Der Lernmodus fragt bei einer abgelehnten Kategorie: „Für alle Postfächer“ oder „Nur Postfach X“
  (Standard: nur das Postfach, aus dem die Mails stammen). Die Web-Einstellungen bieten beide Ebenen.
- Der Absenderfilter ist bereits heute nicht Teil des Fingerprints; das bleibt so.

### 4.2 Themen und ausgeschlossene Themen

- `topics.yaml` und `irrelevant_topics.yaml`: optionales Feld `mailboxes: [1, 2]` je Thema.
  Fehlt es, gilt das Thema für alle Postfächer (heutiges Verhalten).
- Die Relevanzprüfung erhält nur die für das Postfach der Mail wirksamen Themen.
- Der Lernmodus ordnet neu bestätigte Themen standardmäßig dem Ursprungspostfach zu und bietet „für alle“ an.

## 5. Weitere Überschreibungen je Postfach

| Einstellung | Überschreibung am Postfach | Fingerprint-relevant |
| :--- | :--- | :--- |
| Antwortentwürfe | `personal_info` (Signatur, Rolle, Anrede); `smart_reply: false` schaltet Entwürfe für dieses Postfach ab | nein |
| Benachrichtigungen | `notifications.quiet_hours` und Kategorie-Kanäle; nicht überschriebene Felder erben global | nein |
| Tagesüberblick | Postfach ein-/ausschließen; Abschnitt je Postfach | nein |
| Tätigkeitsberichte | Standardordner je Postfach | nein |
| Aufbewahrung | `retention.full_mail_days` je Postfach (nur kürzer als global) | nein |
| Standarddauern (2.4) | `event_defaults` je Postfach | ja (wie heute global) |
| Themen | über `mailboxes` am Thema (§4.2) | ja |

Bewusst **nicht** je Postfach: Prompts, Modelle, LLM-Budget, Relevanzschwelle, Telegram-Chat, Webzugang.

Benachrichtigungen mit Überschreibung: Die gemeinsame Queue aus 3.0 bleibt eine Queue. Jedes Ereignis
trägt seine Postfachnummer; Richtlinie (Ruhezeit, Kanal, Bündelung) wird je Ereignis aus den wirksamen
Einstellungen berechnet. Bündel werden nicht über Postfächer mit unterschiedlicher Richtlinie gemischt.

## 6. Fingerprint

- Wirksamer Analyse-Fingerprint einer Mail = Hash aus globaler Analysekonfiguration, den für ihr Postfach
  wirksamen Themen und den analyserelevanten Überschreibungen (§5).
- **Gleichwertigkeitsregel (Nutzerentscheidung):** Alle Ziele werden aus dem Hash entfernt. Die bisherigen
  Fingerprints und Themenrichtlinien werden beim Upgrade für dieselbe Analysekonfiguration als gleichwertig
  registriert. Bitgleichheit zu 3.1 ist nicht erforderlich. Pflichttest mit synthetischem 3.1-Zustand,
  offener Entscheidung und Neustart; bestehende Vorschläge behalten ihre Zielbindung.
- Ändert sich nur die Themenzuordnung von Postfach 2, werden nur noch nicht abgeschlossene Mails von
  Postfach 2 mit `configuration_changed` zurückgehalten.

## 7. Weboberfläche und Telegram

Aus 3.1 übernommen: Postfächer im Web hinzufügen und entfernen (bis dahin `config.yaml`), Postfach-Label
auf den Karten der Entscheidungsübersicht und im Tagesüberblick, Telegram `/status` je Postfach,
Betriebsproblem-Meldungen mit Postfach-Label und gegebenenfalls Diagnosekomponenten je Postfach.

- **Einstellungen → Postfächer → <Label>:** Tabs „Ziele“, „Filter“, „Themen“, „Antworten“,
  „Benachrichtigungen“. Jedes Feld zeigt „erbt global“ oder den überschriebenen Wert mit „Zurücksetzen“.
- **Zielprofile:** eigene Seite unter Einstellungen; Anlegen, Bearbeiten, Entfernen (nur wenn kein
  Postfach und kein offener Vorschlag darauf verweist, sonst Liste der Verweise).
- Änderungen laufen über den Einrichtungsentwurf aus 3.0 (Sitzung, CSRF, Dateihash, Entwurfsversion,
  Idempotenz, erneute Prüfung bei Ausführung). Fingerprint-relevante Änderungen zeigen vor der
  Übernahme, wie viele laufende Mails welcher Postfächer dadurch zurückgehalten werden.
- **Diagnose:** Komponenten je Zielprofil (`calendar:<n>`, `tasks:<n>`), lesend wie in 3.0.
- **Vorschläge** in Web und Telegram nennen Zielprofil-Label und Ziel („Termin → Outlook · Arbeit“).
- Telegram `/status` zeigt Profile und deren Zustand.

## 8. Umsetzungsphasen

| Phase | Schwerpunkt | Fertig, wenn … |
| :--- | :--- | :--- |
| 1 | Verträge | Schema für Profile, Überschreibungen, Filter Schema 2, Themenfeld; Fingerprint-Gleichwertigkeit getestet; Spezifikation und `config.example.yaml` aktualisiert |
| 2 | Zielprofile | Geheimnisse, Adapter je Profil, Proposal-Schema + Migration, Writer/Abgleich/Bestandsvorschau profilbezogen, OAuth-Abläufe mit `--profile` |
| 3 | Filter und Themen | wirksame Filter/Themen je Postfach in Relevanz, Lernmodus und Decision-Test |
| 4 | Operative Überschreibungen | Entwürfe, Benachrichtigungen, Tagesüberblick, Berichte, Aufbewahrung |
| 5 | Web und Telegram | Postfach-Einstellungen, Profilverwaltung, Diagnose je Profil, Anzeige |
| 6 | Abnahme | Upgrade aus 3.1-Zuständen, Plattformmatrix, Playwright, Dokumentation, Release-Notizen |

## 9. Teststrategie

- 100 % Zeilen- und Branch-Abdeckung, keine Ausschlüsse; Regressionstest je Bugfix.
- Simulierte Kalender-/Aufgabendienste je Profil; synthetische Mails in zwei Postfächern.
- **Ziele:** Vorschlag aus Postfach 2 schreibt nur in Profil 2; Profilwechsel betrifft nur neue Vorschläge;
  entferntes Profil sperrt Bestätigung; Ausfall von Profil 2 lässt Profil 1 schreiben; unklare
  Schreibresultate werden im richtigen Profil abgeglichen.
- **Abgleich:** gleiche Einladung in beiden Postfächern mit unterschiedlichen Profilen wird nicht zusammengeführt.
- **Filter:** globale Sperre, Postfachsperre, `allow`-Ausnahme, Schema-1-Migration, beschädigte Datei je Ebene.
- **Themen/Fingerprint:** Gleichwertigkeitsregel, Änderung nur an Postfach 2 hält nur Postfach-2-Mails zurück.
- **Benachrichtigungen:** Ruhezeit nur für Postfach 2; Bündel mischen keine Richtlinien; Neustart in Ruhezeit.
- **Autorisierung:** alle neuen Webänderungen ohne Sitzung, mit falschem CSRF, veralteter Version,
  wiederholtem Schlüssel und widerrufener Sitzung bei Ausführung; „auf neues Ziel umstellen“ erteilt keine Freigabe.
- **Datenschutz:** keine Tokens, Profilziele-URLs mit Zugangsdaten oder Adressen in Logs und Diagnosebericht.

## 10. Upgrade, Rollback und offene Entscheidungen

**Upgrade:** 3.1-Konfiguration bleibt gültig. Proposal-Migration auf Schema mit `target_profile = 1`
ist atomar und wiederholbar; Sicherung vorher. Absenderfilter wird erst beim nächsten Schreiben umgestellt.

**Rollback auf 3.1:** Nur ohne genutzte 3.2-Felder. Migrierte Vorschläge und Filter Schema 2 sind
für 3.1 nicht lesbar; Release-3.2.md beschreibt die Wiederherstellung aus der Sicherung.

**Offene Entscheidungen:**

1. Kontoübergreifende Duplikate mit unterschiedlichen Zielprofilen: nur Hinweis (empfohlen) oder
   zusätzlich Aktion „Für Profil X übernehmen“.
2. Lernmodus-Standard für neue Absender/Themen: nur Ursprungspostfach (empfohlen) oder global.
3. Sollen Postfächer auch eigene Relevanzschwellen (Jev) erhalten? Empfehlung: nein, erst bei konkretem Bedarf.
4. Zielprofile auch für Antwortentwürfe nutzbar machen (Entwurf in anderem Postfach ablegen)? Empfehlung: nein.

## 11. Umsetzung und Abnahme

Alle sechs Phasen sind umgesetzt. Es gelten die vier empfohlenen Entscheidungen aus §10.
Bedienung, Konfiguration, OAuth, Sicherung und Rückkehr sind in [Release 3.2](Release-3.2.md) beschrieben.

Die ausdrückliche Nutzerentscheidung präzisiert §3.3/§6: Sämtliche Ziele einschließlich der bisher
enthaltenen Standardfelder `google_calendar` und `todoist_project` sind aus dem Analyse-Hash entfernt.
Die bisherigen Fingerprints und Themenrichtlinien bis einschließlich 3.1 werden beim Upgrade als
gleichwertig registriert. Diese Gleichwertigkeit übersteht Neustarts und spätere Zieländerungen;
gespeicherte Vorschläge werden dabei nicht umgestellt. Globale Dauern liegen im Vorschlagskontext;
lokale Dauerregeln ergänzen den Postfach-Hash.

Abnahme mit synthetischen Daten und simulierten externen Diensten am 14. Oktober 2026:

| Prüfung | Ergebnis |
| --- | --- |
| Windows, Python 3.12.10 | 2.357 Tests bestanden; 100 % Zeilen- und 100 % Branch-Abdeckung |
| WSL/Linux, Python 3.12.10, ohne Root-Rechte | 2.357 Tests bestanden; 100 % Zeilen- und 100 % Branch-Abdeckung |
| Chrome/Playwright, Windows und WSL | Je 146 Tests bestanden; Desktop, Mobil und 320-px-Ansicht; JavaScript-Abdeckung vollständig |
| Ruff und Mypy | Erfolgreich; 169 Anwendungsmodule geprüft |
| Wheel/Quellpaket und installiertes Paket | Je zwei Paketprüfungen unter Windows und Linux bestanden; Profilmodule und Release-Dateien enthalten |
| Docker/Linux, UID 65532 | Frischer Build, Konfigurationsprüfung, Verarbeitung/Neustart sowie Lernen/Neustart bestanden |

Regressionen prüfen unter anderem die Ablehnung eingebetteter CalDAV-Benutzernamen, das Erhalten von
YAML-Kommentaren, die Trennung der Zielprofile, neue Bestätigung nach Zielumstellung, lokale Filter und
Aufbewahrung sowie das Verwerfen bereits eingereihter Tagesabschnitte nach Ausschluss eines Postfachs.
Weitere Regressionen prüfen sämtliche Ziele außerhalb des Analyse-Hashs, die Gleichwertigkeitsmigration
offener 3.1-Mails mit und ohne JEV sowie die Einstellungs-Vorschau für migrierte laufende Mails.
Neue Themenbeschränkungen halten auch bei diesen migrierten Mails nur tatsächlich betroffene Postfächer zurück.
