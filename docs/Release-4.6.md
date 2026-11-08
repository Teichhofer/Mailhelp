# Release 4.6 – Terminänderungen, Verschiebungen und Absagen im Kalender

Versionen 4.6.0 bis 4.6.7, 8. November 2026. Grundlage: [Planung 4.6](Planung-4.6.md), Stufe 17.

## Anlass

Wurde ein Termin verschoben, suchte der Dublettenabgleich nur am neuen Tag. Mailhelp
legte dann einen zweiten Termin an, der alte blieb stehen. Absagen und Änderungen blieben
mit der Rückfrage „Welcher bestehende Eintrag soll geändert werden?“ offen, auch wenn der
Eintrag eindeutig war. Eine Mail mit abgesagtem Kalenderanhang ließ die Verarbeitung
sogar scheitern.

## Was sich ändert

| Version | Schritt | Inhalt |
| --- | --- | --- |
| 4.6.0 | 17.1 | Titelsuche `search_events` für Google, CalDAV und Outlook; der Titel wird nur lokal verglichen. |
| 4.6.1 | 17.2 | Die Terminextraktion liefert bei Verschiebungen das frühere Datum (`original_date_text`), der Vorschlag `original_date`. |
| 4.6.2 | 17.3 | Änderungen und Absagen finden ihren Kalendereintrag (±1 Tag um das frühere bzw. abgesagte Datum, sonst Titelsuche ±92 Tage). Genau ein Treffer wird Ziel, fehlende Zeiten kommen aus dem Eintrag; kein oder mehrere Treffer führen zu einer konkreten Rückfrage. |
| 4.6.3 | 17.4 | Web: alter Wert durchgestrichen, neuer fett, Absage als roter Hinweis. Telegram: „bisher … → neu …“. Mehrere Treffer sind per Schaltfläche wählbar. |
| 4.6.4 | 17.5 | Eine Änderung schreibt nur Zeiten und Ort; Titel und Beschreibung bleiben, eine Notiz vermerkt die Änderung. Ein gelöschter Eintrag wird nie neu angelegt. |
| 4.6.5 | 17.6 | Eine Absage ändert nur den Status. Eine unklare Absage wird über den Zieleintrag abgeglichen und nie wiederholt. |
| 4.6.6 | 17.7 | Vier synthetische Korpusfälle (Verschiebung, späterer Beginn, neuer Raum, Absage); 38 Fälle insgesamt. |
| 4.6.7 | 17.8 | Abnahme, End-to-End-Test und Schärfung des Aktionsrouters für Absagen. |

## Fehlerbehebungen unterwegs

- **Abgesagter Kalenderanhang (4.6.2):** Der Builder setzte `is_cancellation` ohne
  Zieleintrag; der Vorschlag war ungültig und die Mail scheiterte.
- **CalDAV-Serie (4.6.4):** Ein Serientermin galt beim Lesen als „nicht vorhanden“; eine
  Absage wäre fälschlich als erledigt gemeldet worden.
- **Absagen im Aktionsrouter (4.6.7):** Das echte Modell antwortete bei „Die
  Teambesprechung ist abgesagt“ mit `none`; es entstand kein Vorschlag. Der Router zählt
  die Absage eines bestimmten Termins jetzt als Terminkandidat.

## Sicherheit

Jede Änderung und Absage bleibt an eine ausdrückliche, versionsgebundene Bestätigung
gebunden. Gewählt werden kann nur ein angebotener Kalendereintrag; vor dem Schreiben wird
er erneut gelesen. Unklare Schreibresultate werden über den Schlüssel der bestätigten
Version oder den Zieleintrag abgeglichen und nie automatisch wiederholt. Der Suchtext
verlässt Mailhelp nicht.

## Abnahmekriterien

| Kriterium | Nachweis |
| --- | --- |
| Keine Dateileichen bei Verschiebungen | `tests/e2e/test_v467_change_and_cancellation.py`: der Eintrag wird verschoben, nicht dupliziert |
| Eindeutiges Matching | zwei mögliche Einträge: Rückfrage mit Kandidaten, kein Schreibzugriff |
| Sichere Stornierung | Absage erst nach Bestätigung; zweite Bestätigung schreibt nicht erneut |
| Unveränderte Schreibsicherheit | Versionsbindung, Sitzungsprüfung, Idempotenzschlüssel und Abgleich unklarer Ergebnisse gelten auch für Änderung und Absage |
| 100 % Abdeckung | siehe Qualitätsnachweise |

## Reale Auswertung

Mit `mailhelp-evaluate` über OpenRouter (Freigabe vom 8. November 2026) für die Änderungs-
und Absagefälle 09, 10 und 35–38.

| Lauf | Aufrufe | Kosten | Ergebnis |
| --- | --- | --- | --- |
| vor der Router-Schärfung (6 Fälle) | 22 | 0,014 $ | Verschiebungen 09 und 35 vollständig bestanden; bei 36 und 37 stimmen Termin und früheres Datum. Absagen 10 und 38: Router `none`, kein Vorschlag. |
| nach der Router-Schärfung (09, 10, 35, 38) | 16 | 0,009 $ | Router 4/4, Terminextraktion 4/4; 09, 10 und 35 vollständig bestanden. |

Offen, ohne Änderung in 4.6: Die Relevanzprüfung stuft den Raumwechsel eines
Elternabends (37) und die Absage einer Förderverein-Versammlung (38) als irrelevant ein,
weil sie zu keinem konfigurierten Thema passen. Das ist eine Frage der Themen in
`topics.yaml`. Bei 36 enthält die Fristliste zusätzlich einen Eintrag ohne Datum.

## Qualitätsnachweise

| Prüfung | Ergebnis |
| --- | --- |
| Windows 11, Python 3.12.10 | 3.761 bestanden; 100 % Zeilen- und Branch-Abdeckung (25.471 Statements, 7.364 Branches). Der 4.4.1-Lasttest scheiterte nur unter acht parallelen Prozessen bei gleichzeitigem Docker-Lauf; einzeln besteht er (Median 338 ms). |
| Docker `python:3.12.10-slim`, Benutzer 65532, ohne Netzwerk, gebaute Pakete | 3.763 bestanden; 100 % Abdeckung; Lasttest 4.4.1 Median 222 ms |
| Offline-Prompt-Gate | 38 von 38 Fällen |
| Ruff / mypy | ohne Befunde |

## Upgrade

Keine Migration nötig: Die neuen Felder (`original_date`, `calendar_candidates`,
`original_date_text`) haben Standardwerte, Vorschlags-IDs bestehender Extraktionen bleiben
gleich. Bereits verarbeitete Mails werden nicht neu bewertet.
