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

Version 4.5 ergänzt drei synthetische Notizen an die eigene Adresse
(`own_addresses`): „Ich bin angemeldet und nehme teil“ mit einem Einladungsfoto, dessen
erkannter Text unter `vision` steht, eine weitergeleitete Einladung mit „Bitte
eintragen“ und eine eigene Aufgabe mit Frist. Der Korpus enthält damit 34 Fälle.

Version 4.6 ergänzt vier Änderungen und Absagen bestehender Termine: eine Verschiebung
um eine Woche, einen späteren Beginn am selben Tag, einen neuen Raum und eine ersatzlose
Absage. Bei Änderungen nennt die Erwartung das frühere Datum in `original_date_text`;
die Auswertung vergleicht den Tag, den es bezeichnet. Der Korpus enthält damit 38 Fälle.

Die Standardprüfung nutzt Jev mit dem produktiven Rückfall bei `unclear` sowie
die generativen Folgestufen. Die stufenweise Messung prüft Extraktion zusätzlich
auch für irrelevante Mails; sie ersetzt keinen Telegram-/Schreibdiensttest.
Zusammenfassung, Titel, Beschreibung und Evidenz werden zusätzlich manuell bewertet.
