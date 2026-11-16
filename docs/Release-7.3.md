# Mailhelp 7.3 – Verwaltung fehlgeschlagener Mails

Geprüft für Mailhelp 7.3.

Umsetzung von [Planung 7.3](Planung-7.3.md). Zwischenstand bis zur Abnahme in 7.3.4.

## 7.3.1 – Ursache und Aktionen in der Fehlerliste (F1, F2)

- **Projektion** (`review/queries.py`): Jede Listenzeile trägt Fehlercode, Stufe, Zahl der
  Fehlversuche, ob ein Versuch angefordert ist, ob ein erneuter Versuch möglich ist (Analyse-Daten
  vorhanden) und die `analysis_round` für die Versionsprüfung.
- **Fehlertexte** (`review/error_reporting.py`): Zeile für die Liste, vollständiger Bericht mit
  Stufe, Ursache, Erklärung, Handlungsempfehlung, Zeiten, Versuchen, Feldpfaden und Modellaufruf-IDs
  sowie kopierbarem Text. Der Bericht enthält nie Mailtext, Adressen, Tokens oder Anbieterantworten.
  Die bisherigen Bezeichnungen für Stufen und Fehler werden weiterverwendet.
- **Fehlerliste** (`/mails?state=failed`): Jede fehlgeschlagene Mail zeigt
  „Fehler: … (Stufe: …, n Fehlversuche)“ und die Knöpfe **Erneut versuchen**, **Ignorieren** und
  **Details** (Link zum Fehlerbericht der Mailseite). Die Aktionen sind normale Formulare mit
  Sitzung, CSRF, Idempotenzschlüssel und `analysis_round`; sie funktionieren ohne JavaScript. Nach
  der Aktion führt der Weg zurück zur Fehlerliste mit dem Ergebnis; der Rücksprung ist ein fester
  Wert (`zurueck=fehlerliste`), nie eine frei übergebene Adresse.
- Die Mailseite nutzt dieselben Formulare; „Ablegen“ heißt jetzt einheitlich **Ignorieren**.

**Abweichung.** Der Plan lässt eine erneut versuchte Mail sofort aus der Fehlerliste
verschwinden. Der gespeicherte Fehler bleibt aber bis zur nächsten Verarbeitung bestehen, und die
Statusseite zählt die Mail weiter als fehlerhaft. Damit Zähler und Liste übereinstimmen, bleibt die
Mail sichtbar, als „Erneuter Versuch angefordert“ gekennzeichnet und ohne zweiten Knopf; nach
erfolgreicher Verarbeitung verschwindet sie, nach einem neuen Fehler erscheint sie mit der neuen
Ursache.

Prüfung 7.3.1: 5 656 Python-Tests mit 100 % Zeilen- und Branch-Abdeckung; danach nennt die
Bedienungsanleitung die frühere Bezeichnung „Ablegen“ mit, damit die Hilfesuche die Frage nach dem
Ablegen weiter beantwortet (Hilfetests bestehen). Browser 941 bestanden; der Zeitmesstest der
Live-Suche scheiterte unter Last und bestand danach einzeln.
