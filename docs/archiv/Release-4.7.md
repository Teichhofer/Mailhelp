# Release 4.7 – Links zur Original-Mail in Kalender und Aufgaben

Versionen 4.7.0 bis 4.7.5, 8. November 2026. Grundlage: [Planung 4.7](Planung-4.7.md), Stufe 18.

## Anlass

Wer in Todoist oder im Kalender eine von Mailhelp angelegte Aufgabe oder einen Termin
bearbeitete, musste die zugehörige Mail im Mailprogramm von Hand suchen. Neue Aufgaben
und Termine enthalten jetzt einen Link, der die Original-Mail öffnet.

## Was sich ändert

| Version | Schritt | Inhalt |
| --- | --- | --- |
| 4.7.0 | 18.1 | `domain/deep_links.py`: bereinigt die Message-ID und bildet `message://%3C…%3E` (Apple Mail). |
| 4.7.1 | 18.2 | Gmail im Browser (`rfc822msgid:`-Suche), Outlook im Browser (Suche nach der Message-ID), Wahl nach IMAP-Server. |
| 4.7.2 | 18.3 | Der Builder hängt den Link an die Beschreibung: in Aufgaben als Markdown-Link, in Terminen als Link; `Proposal.mail_link`. |
| 4.7.3 | 18.4 | „📧 Original-Mail öffnen“ auf Web-Karten; Telegram-Schaltfläche für Gmail/Outlook, Apple-Mail-Link als Text. |
| 4.7.4 | 18.5 | `imap.mailboxes[].mail_client` (`auto`, `apple_mail`, `gmail_web`, `outlook_web`, `none`), auch in der Weboberfläche. |
| 4.7.5 | 18.6 | Abnahme mit End-to-End-Test bis Todoist und Google Kalender. |

## Welcher Link entsteht

| Postfach | `mail_client: auto` ergibt |
| --- | --- |
| `imap.gmail.com`, `imap.googlemail.com` | Gmail im Browser, Suche nach genau dieser Message-ID |
| jeder andere Server | Apple Mail (`message://`), öffnet die Mail auf Mac und iPhone; unter Windows nur mit einem registrierten Programm für `message://` |

Outlook im Browser bietet keinen dokumentierten Link über die Message-ID. `outlook_web`
öffnet deshalb die Outlook-Suche nach der Message-ID und wird nie automatisch gewählt.
**Nicht mit einem echten Konto geprüft:** ob Outlook die Suche über diesen Link ausführt
und ob Google Kalender `message://`-Links klickbar darstellt. Gmail- und Todoist-Links sind
Standardfunktionen der Dienste, aber ebenfalls nur mit simulierten Diensten getestet.

## Sicherheit und Stabilität

- Die Message-ID ist nicht vertrauenswürdig. Sie wird auf genau einen Wert
  `id@host` reduziert und vollständig prozentkodiert; `Proposal.mail_link` lässt nur die
  drei Formen von Mailhelp zu. Ohne gültige Message-ID entsteht kein Link.
- Vorschlags-IDs bleiben gleich. Das Ledger zählt den Link wie Absender und Betreff zur
  Herkunft; dieselbe Aufgabe aus einer anderen Mail wird weiter als Dublette erkannt.
- Mails, die vor 4.7 vorbereitet wurden, erhalten keinen Link; ihre Beschreibungen
  bleiben unverändert.

## Abnahmekriterien

| Kriterium | Nachweis |
| --- | --- |
| Funktionierende Links | `tests/e2e/test_v475_mail_links_end_to_end.py`: Todoist erhält den Markdown-Link, Google Kalender den Link |
| Stabile Idempotenz | `tests/services/test_v472_mail_link_builder.py`: gleiche Vorschlags-IDs und Ledger-Identität mit und ohne Link |
| Robuste Zeichenbehandlung | `+ / = & # { }` in der Message-ID werden kodiert; unzulässige Links werden abgelehnt |
| Fehlertoleranz | ohne Message-ID kein Link und kein Fehler |
| 100 % Abdeckung | siehe Qualitätsnachweise |

## Qualitätsnachweise

| Prüfung | Ergebnis |
| --- | --- |
| Windows 11, Python 3.12.10 | 3.816 bestanden; 100 % Zeilen- und Branch-Abdeckung (25.527 Statements, 7.380 Branches). Der 4.2-Lasttest scheitert wie seit 4.4.0 nur unter acht parallelen Prozessen und besteht einzeln. |
| Docker `python:3.12.10-slim`, Benutzer 65532, ohne Netzwerk, gebaute Pakete | 3.818 bestanden; 100 % Abdeckung; Lasttest 4.4.1 Median 239 ms |
| Ruff / mypy | ohne Befunde |

4.7 ändert keine Prompts; eine Auswertung mit einem echten Modell ist nicht nötig.

## Upgrade

Keine Migration nötig. `mail_client` ist optional (Standard `auto`) und wird ohne Neustart
übernommen. Nach dem Update muss Mailhelp neu gestartet werden; erst danach vorbereitete
Mails erhalten den Link.
