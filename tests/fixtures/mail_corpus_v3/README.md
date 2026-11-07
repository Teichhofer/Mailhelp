# Release-Korpus Version 3

Enthält die 20 synthetischen Fälle aus Version 2 mit unveränderten Erwartungen
und zusätzlich einen synthetischen Kurzlink-Köder. Dieser muss vor der
Modellentscheidung als unklar markiert werden und darf keine Aktion erzeugen.
Seit 4.1.0 (Planung 4.1, Schritt 9.1) kommen fünf Fälle für die Themen
`jimdo-anfragen-und-nachrichten` und `camping-und-stellplatzbuchungen` hinzu: eine
Kontaktformular-Anfrage über Jimdo, eine Buchungsbestätigung und eine Stornierung mit
Anreise und Abreise sowie je ein Jimdo- und ein Roadsurfer-Werbenewsletter, die
irrelevant bleiben müssen. Seit 4.1.10 deckt ein Einsatzplan mit zwei eigenen Terminen
das Thema `persoenliche-termine-und-terminhinweise` ab; eine Werbemail mit Frist muss
irrelevant bleiben. Die Themen sind wortgleich aus `topics.yaml` übernommen.
Links werden nicht aufgerufen. Es werden keine persönlichen Mails verwendet.

Version 4.3 ergänzt eine Einladung mit erforderlicher Anmeldung und optionalen
Weiterleitungs-/Downloadfloskeln, reine Marketingangebote ohne Aufgabe sowie zehn
gleichnamige Sitzungstermine und eine getrennte Haushaltsklausur. Der Korpus enthält
damit 31 Fälle. Die Offline-Prüfung nutzt simulierte Modellantworten; sie belegt
Schema-, Routing- und Normalisierungsverträge, keine reale Modell-Erkennungsrate.

Die Standardprüfung nutzt Jev mit dem produktiven Rückfall bei `unclear` sowie
die generativen Folgestufen. Die stufenweise Messung prüft Extraktion zusätzlich
auch für irrelevante Mails; sie ersetzt keinen Telegram-/Schreibdiensttest.
Zusammenfassung, Titel, Beschreibung und Evidenz werden zusätzlich manuell bewertet.
