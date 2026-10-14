# Mailhelp 2.0 – The New Experience & Standalone PWA

> Historischer Versionsstand: Dieses Dokument beschreibt die genannte Version oder
> deren damaligen Plan. Ursprüngliche Ziele und Prüfergebnisse sind kein Nachweis
> des heutigen Umfangs. Aktueller Betrieb: [README](../README.md),
> [Release 3.3](Release-3.3.md) und [Projektspezifikation](../Mailhelp-Projektspezifikation.md).

Mailhelp 2.0.0 macht die Weboberfläche zur eigenständigen App für Smartphone und
Desktop. Alle neuen Funktionen sind optional und standardmäßig ausgeschaltet;
ohne Konfigurationsänderung verhält sich Mailhelp nach dem Upgrade wie 1.6 – mit
der überarbeiteten Weboberfläche.

Grundlage: [Planung-2.0.md](Planung-2.0.md) und
[Konzept-2.0-Redesign-und-Web-Push.md](Konzept-2.0-Redesign-und-Web-Push.md).

## Neu

### Weboberfläche

- **Split-View ab 1024 px:** links die offenen Vorgänge, rechts die Details des
  ausgewählten Vorgangs, ohne Seitenwechsel.
- **Schrittweise Offenlegung:** Auf der Vorschlagsseite sind Quellbeleg (Mail und
  Anhänge), Revisionshistorie und technische Analyse einklappbar. Mit Bildanhängen
  ist der Quellbeleg sofort geöffnet.
- **Schnellfilter** über `/offen`, `/mails` und `/verlauf`: Alle, Termine, Aufgaben,
  Klärung nötig, Mit Anhängen, Duplikate. Der Filter steht in der Adresse
  (`?filter=events`) und funktioniert auch ohne JavaScript.
- **Daumenzone auf dem Smartphone:** Aktionsleiste am unteren Rand, Schaltflächen
  mindestens 48 px hoch, Verwerfen links, Bestätigen rechts.
- **Tastenkürzel am Desktop:** `J`/`↓` nächster, `K`/`↑` vorheriger Vorgang,
  `C`/`Enter` bestätigen, `E` bearbeiten, `X`/`D` verwerfen, `?` Hilfe. In
  Eingabefeldern sind sie inaktiv.
- **Rückgängig:** Nach Bestätigen oder Verwerfen bleiben 5 Sekunden. Erst danach
  sendet der Browser das normale Formular; der Server prüft wie bisher Sitzung,
  CSRF, Version und Idempotenzschlüssel.
- **Bildanhänge:** Vorschau mit Abmessungen, Größe und erkanntem Text, Vergrößerung
  in einer zoombaren Ansicht. Ausgeliefert werden nur von Mailhelp neu kodierte
  JPEG-Dateien über `GET /mail/<id>/anhang/<index>` mit Sitzungsprüfung, `nosniff`
  und `Content-Security-Policy: default-src 'none'`. SVG wird nie ausgeliefert.
- **Alles erledigt:** Ohne offene Entscheidungen zeigt `/offen` die Ergebnisse des
  Tages und den Zeitpunkt der letzten verarbeiteten Mail.

### Web-Push (`push.enabled`)

Mailhelp erzeugt beim ersten Start ein VAPID-Schlüsselpaar (P-256) und speichert
es im Datenverzeichnis (`web-vapid.json`). Unter **Einstellungen** schaltet jedes
Gerät Push für sich ein oder aus. Benachrichtigungen enthalten nie Betreff,
Absender, Mailtext oder Termintitel, sondern nur „Neue Entscheidungen warten in
Mailhelp.“ oder „Dein Tagesüberblick ist verfügbar.“ Akzeptiert werden nur
Endpunkte bekannter Push-Dienste (Google, Mozilla, Apple, Microsoft) über HTTPS;
Weiterleitungen werden nicht verfolgt. Abgemeldete Geräte und vom Push-Dienst als
erloschen gemeldete Abos werden entfernt.

Voraussetzung ist HTTPS (z. B. Tailscale Serve) oder `localhost`. Auf dem iPhone
muss Mailhelp vorher über „Zum Home-Bildschirm“ installiert sein.

### Antwort-Entwürfe (`smart_reply`)

Auf der Mail- und der Vorschlagsseite stehen immer die Schaltflächen
„Zusagen“, „Absagen“ und „Rückfrage“. Ein Klick lässt das Modell (Prompt
`draft_reply` in `prompts.yaml`) genau einen passenden Entwurf formulieren –
positiv, negativ oder als Rückfrage. Der Entwurf erscheint in einem Textfeld und
kann frei geändert werden. „Abbrechen“ verwirft ihn, ohne das Postfach zu
berühren; „Als Entwurf im Postfach speichern“ legt genau den angezeigten Text
per IMAP `APPEND` mit den Flags `\Draft \Seen` in `imap.drafts_folder` ab – mit
`In-Reply-To`, `References` und `Re:`-Betreff. Im Hintergrund entstehen keine
Entwürfe; LLM-Kosten fallen nur pro Klick an.

Das Modell sieht neben dem Mailtext auch die erkannten Texte aller Anhänge
(PDF, Office, OCR von Bildern und Scans). Unter **Einstellungen → Antworten →
Persönliche Angaben für Antworten** (`personal_info` in `config.yaml`) lassen sich
Name, Rolle, Signatur oder Anrede-Wünsche hinterlegen; das Modell unterschreibt
damit und berücksichtigt die Angaben. Sie gehen nur in Antwort-Entwürfe ein und
wirken sofort, ohne Neustart.

**Mailhelp versendet keine E-Mails.** Es gibt keinen SMTP-Pfad; abgeschickt wird
der Entwurf im eigenen Mailprogramm.

Ist das Ergebnis eines `APPEND` unklar (Verbindungsabbruch), gleicht Mailhelp bei
der nächsten Bestätigung zuerst über die Message-ID mit dem Ordner ab und legt den
Entwurf nur an, wenn er dort nachweislich fehlt. Lehnt der Server eindeutig ab,
bleibt der Entwurf bearbeitbar.

### Tagesüberblick (`daily_briefing`)

Zur eingestellten Uhrzeit (einmal je lokalem Kalendertag, auch nach Neustarts)
liest Mailhelp heutige Termine, fällige Aufgaben und offene Entscheidungen. Fällt
ein Dienst aus, enthält der Überblick die übrigen Daten und einen Hinweis. Telegram
erhält den Text, Web-Push einen neutralen Hinweis; im Web steht er unter
`/briefing`. Ein Kanal wird höchstens einmal je Tag versucht.

### Betrieb ohne Telegram (`telegram.enabled: false`)

Mit `web.enabled: true` lässt sich Mailhelp ohne Telegram betreiben;
`TELEGRAM_BOT_TOKEN` entfällt dann. Kopplungscodes erscheinen ausschließlich im
Konsolenfenster des PCs (bei Docker: `docker compose logs mailhelp`), beim Start
und auf Anforderung über die Anmeldeseite. Codes gelten 10 Minuten und einmalig.
Unklare Relevanzfragen und alle Vorschläge werden dann im Web entschieden.

## Upgrade von 1.6

1. Mailhelp geordnet beenden; Konfiguration und Datenverzeichnis sichern.
2. Paket auf 2.0.0 aktualisieren bzw. das Docker-Image neu bauen. Ein Neubau ist
   nötig, weil `pywebpush` mit seinen Abhängigkeiten neu hinzukommt
   (`requirements.lock`).
3. Optional die neuen Abschnitte aus `config.example.yaml` übernehmen
   (`smart_reply`, `push`, `daily_briefing`, `imap.drafts_folder`,
   `telegram.enabled`) sowie den Prompt `draft_reply` aus `prompts.yaml`. Fehlt der
   Prompt, bleibt `smart_reply` wirkungslos.
4. Für Antwort-Entwürfe muss der Entwurfsordner auf dem Server existieren
   (Gmail z. B. `[Gmail]/Entwürfe`); Umlaute sind erlaubt.

Es ist keine Datenmigration nötig. Die neuen Einstellungen fließen nicht in den
Konfigurations-Fingerprint ein: Mails, die unter 1.x begonnen wurden, laufen ohne
Rückfrage weiter – auch mit eingeschalteten 2.0-Funktionen.

Bildvorschauen entstehen für neu vorbereitete Mails; bereits verarbeitete Mails
behalten die Textanzeige. Vorschauen und Entwurfstexte werden mit dem Mailtext
nach `retention.full_mail_days` gelöscht.

Rollback auf 1.6: Paket bzw. Image zurücksetzen. Die zusätzlichen Zustandsdateien
(`web-vapid`, `push-subscriptions`, `push-decisions`, `draft-*`, `daily-briefing`,
`briefing-latest`, `attachments/`) werden von 1.6 ignoriert und können bleiben.

## Prüfung

```powershell
python -m pytest -q --tb=short
python -m pytest ui_tests --no-cov -p no:cacheprovider -q --tb=short
python -m hatchling build
```

Alle externen Dienste sind simuliert (IMAP, Push-Dienst, Kalender, Todoist,
Telegram); die Testdaten sind synthetisch. Die Browsertests prüfen Split-View,
Tastenkürzel, Rückgängig, Schnellfilter, Lightbox, Entwurfseditor, Push-Einstellung
und Service Worker auf Desktop, Smartphone und schmalem Display sowie jede
Funktion mit ausgeschaltetem JavaScript.

### Lokale Abnahme am 12. Oktober 2026

- 1.613 Python-Tests bestanden; 100 % Zeilen- und Branch-Coverage.
- 86 Browsertests bestanden (Desktop, Smartphone, schmales Display, ohne JavaScript);
  100 % JavaScript-Blockabdeckung für `app.js` und `sw.js`.
- Wheel und Source-Archiv 2.0.0 gebaut.
- Kein lokaler Linux-/Docker-Lauf, da Docker hier nicht verfügbar ist; die
  CI-Matrix (Windows, Linux, Container) steht noch aus.
