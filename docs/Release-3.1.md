# Mailhelp 3.1 – Mehrere Postfächer

Stand: 14. Oktober 2026. Version 3.1.0. Planung und Entscheidungen: [Planung 3.1](Planung-3.1.md).
Einstellungen je Postfach (eigene Ziele, Ignorierlisten, Themen) folgen mit [Planung 3.2](Planung-3.2.md).

## Was sich ändert

Eine Mailhelp-Instanz verarbeitet bis zu zehn IMAP-Postfächer derselben Person mit gemeinsamer
Weboberfläche, gemeinsamem Telegram-Chat, gemeinsamen Themen, Prompts, Zielen und
Benachrichtigungsregeln.

- **Abruf:** ein schreibfreier Reader je aktiviertem Postfach. Ein nicht erreichbares Postfach hält die
  anderen nicht auf. Die Auswahl eines Laufs erfolgt über alle Postfächer nach Empfangszeitpunkt;
  `batch_size` und `--max-mails` gelten gemeinsam. Bearbeitet wird Postfach für Postfach.
- **Duplikate:** Dieselbe Mail in zwei Postfächern wird nur einmal analysiert.
- **Antwortentwürfe:** nur im Entwurfsordner des Postfachs, aus dem die Mail stammt, mit dessen
  Benutzernamen als Absender. Ist dieses Postfach nicht mehr aktiviert, wird nicht gespeichert.
- **Tätigkeitsberichte:** gehören zu genau einem Postfach; Auswahl im Formular.
- **Lernmodus und Decision-Test:** bei mehreren aktivierten Postfächern `--mailbox <Nummer>` für ein
  Postfach oder `--mailbox alle` für alle angeben. Mit „alle“ sind es die `N` neuesten Mails über alle
  Postfächer zusammen, z. B. `mailhelp --learn 50 --mailbox alle`.
- **Anzeige:** Maildetail, Archiv (mit Filter „Postfach“) und Telegram-Karten nennen das Postfach,
  sobald mehr als eines aktiviert ist. Web-Push bleibt neutral.
- **Diagnose:** `/diagnose` → `imap` prüft alle aktivierten Postfächer lesend.

## Einrichten

Ohne Änderung läuft eine bestehende Installation unverändert weiter: Der bisherige `imap`-Abschnitt ist
Postfach 1, `IMAP_USERNAME`/`IMAP_PASSWORD` bleiben gültig.

Für mehrere Postfächer `config.yaml` umstellen (Dienst vorher stoppen, Datei sichern):

```yaml
imap:
  batch_size: 25
  global_newest_first: true
  mailboxes:
  - id: 1                 # bisheriges Postfach: Nummer 1 behalten
    label: Privat
    host: imap.web.de
    port: 993
    connection_mode: ssl
    historical_start: '2026-09-15T00:00:00+02:00'
    folders: [INBOX, Sent]
    drafts_folder: Entwürfe
  - id: 2
    label: Arbeit
    host: imap.example.org
    port: 993
    folders: [INBOX]
    drafts_folder: Drafts
```

Zugangsdaten in `.env` oder der Prozessumgebung:

```text
IMAP_2_USERNAME=…
IMAP_2_PASSWORD=…
```

Postfach 1 darf weiterhin `IMAP_USERNAME`/`IMAP_PASSWORD` verwenden; gesetzte `IMAP_1_…`-Variablen
haben Vorrang. Danach `mailhelp --check` und `mailhelp --check-access` ausführen; die Zugangsprüfung
nennt jedes Postfach mit Nummer und Anzeigenamen. Anschließend neu starten.

Regeln:

- `id` ist eine Zahl von 1 bis 99, eindeutig und dauerhaft. Sie bestimmt die Variablennamen. Beim
  Entfernen eines Postfachs die übrigen Nummern **nicht** verschieben.
- Höchstens 10 Postfächer, mindestens eines aktiviert (`enabled: true`). Zwei aktivierte Postfächer mit
  demselben Server, Port und Benutzernamen werden abgelehnt.
- Die alten Postfachfelder direkt unter `imap` und `imap.mailboxes` gleichzeitig sind ungültig.
- Ein neues Postfach ohne `historical_start` beginnt bei UID 1 und liest damit seinen gesamten Bestand.
  Für große Postfächer einen Startzeitpunkt setzen.
- Server, Port oder Benutzername eines bestehenden Postfachs zu ändern, ergibt ein neues technisches
  Konto: Das Postfach wird ab `historical_start` neu eingelesen.

Im Einrichtungsassistenten (`/einrichtung`, Schritt „Postfach“) lassen sich Anzeigename, Aktivierung und
Verbindungsfelder jedes konfigurierten Postfachs bearbeiten. Postfächer hinzufügen oder entfernen erfolgt
in 3.1 in `config.yaml`; die Weboberfläche dafür folgt mit 3.2. Zugangsdaten eines neuen Postfachs werden
beim Start geladen; die Diagnose meldet bis dahin `auth`.

## Laufende Mails und Upgrade

Postfachangaben gehören ab 3.1 nicht mehr zum Analyse-Fingerprint. Beim ersten Start registriert
Mailhelp die Fingerprints bis 3.0 für Postfach 1 als gleichwertig: Mails, die unter 3.0 begonnen haben
oder auf eine Entscheidung warten, laufen weiter – auch wenn gleichzeitig auf `imap.mailboxes`
umgestellt wird, solange Postfach 1 dieselben Werte behält. Ein Postfach ändern, hinzufügen oder
entfernen hält keine laufende Mail zurück.

Mails eines entfernten oder deaktivierten Postfachs bleiben unverändert liegen (Logeintrag
`mailbox_unavailable`); bereits erzeugte Vorschläge bleiben bestätigbar.

Tätigkeitsberichte vor 3.1 gelten als Berichte von Postfach 1.

## Rückkehr zu 3.0

Dienst stoppen, vorherige Paketversion sowie die vor dem Upgrade gesicherte `config.yaml` und
Zustandsablage wiederherstellen. Eine `config.yaml` mit `imap.mailboxes` ist für 3.0 ungültig.
Zustände zusätzlicher Postfächer werden von 3.0 nicht gelesen, aber auch nicht beschädigt. Tätigkeitsberichte
mit dem Feld `mailbox` sind für 3.0 schemawidrig und werden isoliert; vorher sichern. Nie beide
Versionen gleichzeitig starten.

## Datenschutz

Jedes zusätzliche Postfach wird wie das erste verarbeitet: Inhalte relevanter Mails gehen an das
konfigurierte KI-Modell, Zusammenfassungen und Vorschläge an Telegram bzw. die Weboberfläche. Nur
Postfächer eintragen, deren Verarbeitung erlaubt ist (z. B. dienstliche Vorgaben beachten). Logs,
Diagnosebericht und Push-Meldungen enthalten keine Postfach-Zugangsdaten; Logs nennen höchstens die
Postfachnummer und die nicht geheime Konto-ID.
