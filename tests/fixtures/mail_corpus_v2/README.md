# Deutscher Mail-Qualitätskorpus, Version 2

`corpus.json` enthält ausschließlich synthetische Nachrichten mit reservierten
`.test`-Adressen. Version 2 ist für reale Modellläufe mit `mailhelp-evaluate`
gedacht und ersetzt Version 1 nicht; `mail_corpus_v1` bleibt Grundlage der
simulierten Standardtests.

Gegenüber Version 1:

- Realistische Mails mit Absender, Anrede, Kontext und Signatur statt Einzelsätzen,
  jeweils mit `received_at` für den Datumskontext wie im Betrieb.
- Aussagekräftige Themenbeschreibungen mit Beispielen und Ausschlüssen.
- Zusammenfassungen erwarten wie der Summary-Prompt alle ausdrücklich genannten
  Fristen und Termine. Verglichen werden nur die darin genannten Kalenderdaten;
  ein Eintrag ohne Datum zählt lediglich als solcher.
- Zuständigkeit bei Terminen folgt der Regel aus Abschnitt 7: Ein in einer an die
  nutzende Person gerichteten Mail angekündigter Termin ist `user`, außer bei
  ausdrücklichen Gegenhinweisen.
- `accept` nennt je Stufe ausdrücklich erlaubte Alternativen für fachliche
  Grenzfälle, zum Beispiel `unclear` statt `event` beim Router der
  Gemeinderatsmail. Alles andere gilt als Abweichung.

Fachliche Änderungen an den Erwartungen erzeugen eine neue Korpusversion.
