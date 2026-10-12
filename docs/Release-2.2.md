# Mailhelp 2.2 – Tätigkeitsbericht

Mailhelp 2.2.0 beantwortet die Frage *„An welchen Terminen war ich im Zeitraum X
für das Thema Y tätig?“* – etwa für den Jahresbericht eines Ehrenamts oder einen
Nachweis. Die Funktion ist optional und standardmäßig ausgeschaltet; ohne
Konfigurationsänderung verhält sich Mailhelp nach dem Upgrade wie 2.1.

Grundlage: [Planung-2.2.md](Planung-2.2.md).

## Ablauf

1. **Berichte → Neuer Bericht:** Titel, Thema (worum es geht, was dazugehört und
   was nicht), Zeitraum (höchstens drei Jahre) und Ordner (einer pro Zeile;
   vorgeschlagen werden die konfigurierten Ordner ohne Papierkorb, Spam und
   Entwürfe). Gesendete Mails sind standardmäßig einbezogen, weil eigene Zusagen
   Tätigkeiten belegen.
2. **Mails zählen:** Mailhelp listet nur die Mails des Zeitraums. Inhalte werden
   noch nicht gelesen, die KI wird noch nicht gefragt.
3. **Bericht kostenpflichtig starten:** Die Seite nennt vorher die Zahl der Mails
   und damit die höchste Zahl der KI-Aufrufe. Nach dem Start liest Mailhelp jede
   Mail schreibfrei (`BODY.PEEK`, keine Flags), überspringt ignorierte Absender,
   Duplikate, zu große, unlesbare und verdächtige Mails und prüft jede übrige per
   KI (Prompt `activity_relevance`) auf das Thema. `personal_info` geht dabei als
   Kontext mit, damit die KI weiß, wer du bist.
4. Aus jeder relevanten Mail nennt ein zweiter Schritt (Prompt `activity_events`)
   alle datierten Termine – **auch vergangene**. Jeder Termin braucht ein wörtliches
   Zitat aus der Mail; erfundene Belege werden verworfen.
5. **Prüfen:** Die Berichtsseite zeigt die Termine chronologisch mit Quellmail,
   die relevanten Mails ohne Termin und eingeklappt die als nicht relevant
   bewerteten Mails („Doch relevant“). Auf der Mailseite lassen sich Termine
   korrigieren, ausschließen oder ergänzen und die Relevanz umstellen. Für eine
   nachträglich relevante Mail sucht Mailhelp die Termine im Hintergrund.
6. **Als xlsx-Liste herunterladen:** Blatt „Termine“ (Termin-Nr., Termin, Datum,
   Uhrzeit, Ort, Mail-Betreff, Absender, Mail-Datum, Volltext; eine Zeile je
   Quellmail, gleiche Termine teilen die Nummer), Blatt „Ohne Termin“ und Blatt
   „Bericht“ mit Thema, Zeitraum und dem Hinweis, ob du die Ergebnisse geprüft hast.

Ein laufender Bericht lässt sich pausieren, fortsetzen und abbrechen. Nach einem
Neustart ist er pausiert und setzt beim Fortsetzen an der nächsten Mail an; keine
Mail wird zweimal bewertet.

## Sicherheit und Datenschutz

- Ein Bericht schreibt nichts in Postfach, Kalender oder Todoist und erzeugt keine
  Vorschläge, Telegram-Nachrichten oder Pushes.
- Mailinhalte und KI-Antworten sind nicht vertrauenswürdig: Schemaprüfung,
  wörtlicher Beleg je Termin, HTML-Escaping, und in der xlsx-Datei wird kein Wert
  zur Formel (führendes `=`, `+`, `-`, `@` erhält ein Apostroph).
- Jede Aktion prüft Sitzung, CSRF-Token, Berichtsversion und Idempotenzschlüssel;
  ein doppelt gesendetes Formular legt keinen zweiten Bericht an.
- Der Download ist `Cache-Control: no-store` und ein Anhang.
- Volltexte und Belegzitate abgeschlossener Berichte werden nach
  `retention.activity_report_days` (Standard 365) entfernt; Termine, Absender und
  Betreffe bleiben. `mailhelp --clear` löscht alle Berichte.

## Einrichtung

In `config.yaml`:

```yaml
activity_report:
  enabled: true
  max_mails: 2000                  # Bericht pausiert bei Erreichen
  max_llm_calls: 3000              # Bericht pausiert bei Erreichen
  max_share_of_llm_budget: 0.5     # Anteil von limits.llm_calls_per_minute
  max_fulltext_chars: 30000
  export_mails_without_events: true
retention:
  activity_report_days: 365
```

`prompts.yaml` braucht die Schritte `activity_relevance` und `activity_events`
(siehe mitgelieferte Datei). Fehlt einer, bleiben Berichte aus und die Seite
„Berichte“ erklärt, was zu tun ist. Die neuen Einstellungen und Prompts verändern
keinen Analyse-Fingerprint; bereits verarbeitete Mails werden nicht neu analysiert.

## Kosten

Je gelesener Mail ein KI-Aufruf für die Relevanz, je relevanter Mail ein weiterer
für die Termine. Ein Bericht nutzt höchstens `max_share_of_llm_budget` des
Minutenbudgets, damit die normale Mailverarbeitung weiterläuft.
