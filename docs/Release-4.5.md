# Release 4.5 – Eigene Mails, Notizen an sich selbst und Weiterleitungen

Versionen 4.5.0 bis 4.5.7, 8. November 2026. Grundlage: [Planung 4.5](Planung-4.5.md), Stufe 16.

## Anlass

Ein vom iPhone an die eigene Adresse geschicktes Foto einer Einladung mit dem Satz
„Ich bin angemeldet und nehme teil“ erzeugte keinen Termin. Der Aktionsrouter hielt die
Fotos für eine ältere, an jemand anderen gerichtete Nachricht und antwortete `none`.
Mailhelp ging davon aus, dass jede Mail von einer dritten Person stammt.

## Was sich ändert

| Version | Schritt | Inhalt |
| --- | --- | --- |
| 4.5.0 | 16.1 | Mails von einer eigenen Adresse gelten als eigene Notiz (`self_mail`, `user_note`). Eigene Adressen sind der IMAP-Benutzername, die neuen Aliase `imap.mailboxes[].own_addresses` und die Adressen in `personal_info`. |
| 4.5.1 | 16.2 | Weiterleitungen werden erkannt (`WG:`/`Fwd:` und die Trennzeilen von Apple Mail, Outlook, Gmail und Thunderbird). Die Notiz wird vom Original getrennt, die Kopfzeilen des Originals stehen in `forwarded_headers`. |
| 4.5.2 | 16.3 | Der Aktionsrouter erhält das von der Anwendung gesetzte Feld `perspective` und kehrt die Perspektive um: Teilnahme- oder Eintragungsnotiz mit Termin ergibt einen eigenen Termin, eine eigene Anweisung eine Aufgabe. |
| 4.5.3 | 16.4 | Aufgaben- und Terminextraktion erhalten dieselbe Perspektive. Die Fakten stammen aus Anhang oder Original, nicht aus der Notiz. |
| 4.5.4 | 16.5 | Korpus v3 enthält drei synthetische eigene Notizen. `mailhelp-evaluate` bestimmt die Perspektive mit demselben Modul wie die Verarbeitung. |
| 4.5.5 | 16.6/16.7 | Offline-Prompt-Gate für alle 34 Fälle und End-to-End-Regressionstest der Landesversammlung (synthetisiert). |
| 4.5.6 | 16.6 | Eigene Notizen und eigene Weiterleitungen gelten ohne Relevanzaufruf als relevant. Die Auswertung vergleicht Daten ohne vorangestellten Wochentag. Reale Auswertung mit echtem Modell. |
| 4.5.7 | Fristen | Zusammenfassung: `deadlines` ist im Antwortschema Pflicht; keine Kopfzeilendaten und keine Anmeldefrist bei bestehender Anmeldung; Vorlage `defaults/prompts.yaml` wieder identisch. Siehe [Planung Fristen](Planung-Fristen-Zusammenfassung.md). |

Für Mails Dritter ohne Weiterleitung ändert sich die Modelleingabe nicht.

## Sicherheit

Der From-Kopf einer Mail ist fälschbar. `self_mail` ändert deshalb nur die Lesart und
autorisiert keine Anlage; jede Anlage bleibt an eine ausdrückliche, versionsgebundene
Bestätigung gebunden. Anzeigenamen zählen nie als Absender, und mehrere Absender
schließen eine eigene Mail aus. Das Feld `perspective` setzt die Anwendung, es wird nicht
gespeichert. Die Prompts verbieten, Anweisungen an das Modell aus einer Notiz zu
befolgen. Die eigenen Adressen gehen nicht in den Konfigurations-Fingerabdruck ein
(keine Neuanalyse bestehender Mails) und werden nicht protokolliert.

## Regressionstest Landesversammlung

`tests/e2e/test_v45_landesversammlung.py` bildet die Mail mit synthetischen Inhalten nach:
eigene Notiz, drei Fotos und deren erkannter Text. Das simulierte Modell antwortet so, wie
es die geschärften Prompts verlangen. Ohne Perspektive antwortet es wie 2026 beobachtet.

- Von der eigenen Adresse entsteht ein Terminvorschlag für die nutzende Person:
  „Landesversammlung“, 05.12.2026, 9:30 Uhr, Gasthof Krone, Hauptstraße 1, Hohenstadt.
- Von einer unbekannten Adresse entsteht wie bisher kein Vorschlag.

**Offen:** Der Vorschlag fragt noch „Wann endet der Termin?“. Die Standarddauer setzt
Mailhelp nur ein, wenn die Art des Treffens erkennbar ist (etwa „Raum“, „vor Ort“ oder ein
Videolink). Eine bloße Adresse wie „Gasthof Krone, Hauptstraße 1“ zählt bisher nicht dazu.
Diese Regel stammt aus einer früheren Version und ist hier unverändert.

## Qualitätsnachweise

| Prüfung | Ergebnis |
| --- | --- |
| Windows 11, Python 3.12.10 | 3.677 bestanden; 100 % Zeilen- und Branch-Abdeckung (25.131 Statements, 7.254 Branches). Der 4.2-Lasttest scheitert wie seit 4.4.0 nur unter acht parallelen Prozessen und besteht einzeln. |
| Docker `python:3.12.10-slim`, Benutzer 65532, ohne Netzwerk, gebaute Pakete | 3.680 bestanden; 100 % Abdeckung; Lasttest 4.4.1 Median 228 ms |
| Browser-Suite | nicht erneut ausgeführt; 4.5 ändert weder Seiten noch Skripte |
| Offline-Prompt-Gate (`tests/evaluation/test_prompt_gate.py`) | 34 von 34 Fällen, alle Stufen |
| Ruff / mypy | ohne Befunde |

Die Prompt-Baseline ist bei jedem Schritt als geprüfter Konfigurationsvertrag
fortgeschrieben worden (`model_quality_proven: false`). Simulierte Antworten belegen
Schema, Routing und Normalisierung, aber nicht die Erkennungsrate eines echten Modells.

## Reale Auswertung (16.6)

Am 8. November 2026 mit `mailhelp-evaluate` über OpenRouter, freigegeben mit einer
Grenze von 100 Aufrufen. Die Fälle liefen in einer Prioritätsreihenfolge: zuerst die
drei eigenen Notizen, dann externe Einladungen und Termine. Nach 100 Aufrufen waren 25
von 34 Fällen geprüft; die Fälle 21 bis 29 (Jimdo, Buchungen, Werbung) liefen nicht.
Gemeldete Kosten: 0,07 $ bei rund 270.000 Tokens.

| Stufe | bestanden (Lauf 1, 4.5.5) |
| --- | --- |
| Aktionsrouter | 25 / 25 |
| Aufgabenextraktion | 25 / 25 |
| Terminextraktion | 22 / 25 |
| Relevanz | 22 / 25 |
| Zusammenfassung | 14 / 25 |

- **Router:** Alle drei eigenen Notizen und alle externen Einladungen sind richtig
  geroutet. Der Perspektivenwechsel aus 16.3 wirkt beim echten Modell.
- **Terminextraktion:** Bei der Landesversammlung und dem Elternabend stimmten Datum,
  Zeit, Ort und Zuständigkeit. Gewertet wurde „abweichend“ nur, weil das Modell den
  Wochentag voranstellte. Seit 4.5.6 vergleicht die Auswertung ohne Wochentag.
- **Relevanz:** Die weitergeleitete Einladung „Bitte eintragen“ wurde als irrelevant
  eingestuft. In der Verarbeitung wäre dadurch kein Vorschlag entstanden. Seit 4.5.6
  gelten eigene Notizen ohne Themenentscheidung als relevant.
- **Zusammenfassung:** In 11 Fällen blieb die Fristliste leer, obwohl das Datum im Satz
  steht. Das betrifft keine Änderung von 4.5 und ist in
  [Planung Fristen in der Zusammenfassung](Planung-Fristen-Zusammenfassung.md) beschrieben.
- **Ratssitzungsreihe (30):** Die Termine wurden als sichere eigene Termine
  zurückgegeben, erwartet war „unklar“. Fälle 08 und 20 erhielten ein zusätzliches Thema.

**Nachprüfung nach 4.5.6:** Die drei Notiz-Fälle liefen erneut (9 Aufrufe, 0,006 $).
Relevanz, Router, Aufgaben- und Terminextraktion bestehen in allen drei Fällen. Der
Aufgaben-Fall besteht vollständig. Bei den beiden Termin-Fällen weicht nur die
Fristliste der Zusammenfassung ab.

**Abnahme nach 4.5.7:** vollständiger realer Lauf über alle 34 Fälle (126 Aufrufe,
0,07 $): Zusammenfassung 31/34, Router 33/34, Aufgaben 34/34, Termine 31/34, Relevanz
29/34. Alle drei eigenen Notizen bestehen vollständig. Einzelheiten und verbliebene
Abweichungen: [Planung Fristen](Planung-Fristen-Zusammenfassung.md), Abschnitt 8.

Die Berichte enthalten nur Ausgaben zum synthetischen Korpus und liegen nicht im
Repository.

## Upgrade

Keine Migration nötig: Die neuen Felder in `MailState` haben Standardwerte. Bereits
verarbeitete Mails werden nicht neu bewertet. Weitere eigene Absenderadressen lassen sich
unter `imap.mailboxes[].own_addresses` eintragen.
