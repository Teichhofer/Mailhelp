# Release 4.5 – Eigene Mails, Notizen an sich selbst und Weiterleitungen

Versionen 4.5.0 bis 4.5.5, 8. November 2026. Grundlage: [Planung 4.5](Planung-4.5.md), Stufe 16.

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
**Noch nicht durchgeführt:** die Auswertung mit einem echten Modell über
`mailhelp-evaluate` (Schritt 16.6). Sie verursacht Kosten beim LLM-Anbieter und braucht
deshalb eine ausdrückliche Freigabe.

## Upgrade

Keine Migration nötig: Die neuen Felder in `MailState` haben Standardwerte. Bereits
verarbeitete Mails werden nicht neu bewertet. Weitere eigene Absenderadressen lassen sich
unter `imap.mailboxes[].own_addresses` eintragen.
