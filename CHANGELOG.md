# Änderungen

## 5.0.0 – Kontrastsichere Design-Tokens (Planung 5.0, Schritt 21.1)

- Neue Farbpalette für hell und dunkel (Slate-Grautöne, Smaragd als Akzent) und eigene
  Farben je Art: Termin, Aufgabe und Antwortentwurf. Alle Text- und Flächenpaare erreichen
  mindestens 4,5:1 (WCAG AA); ein Test berechnet die Kontraste direkt aus `app.css`.
- Die erste Fassung der Planung 5.0 sah hellere Töne vor, die nur 3,6:1 bis 3,8:1
  erreichten; die überarbeitete Planung nutzt die dunkleren 700er-Stufen.
- Die Seitenleiste nutzt Variablen statt fest eingetragener Farben; `theme-color`,
  Offline-Seite und Manifest verwenden dieselbe Akzentfarbe.
- Zahlen in Kennzahlen und Zählern mit gleich breiten Ziffern; weichere Schatten.

## 4.9.7 – Lernmodus in der Weboberfläche startet wieder (Planung Lernen, L.1–L.6)

- Fehlerbehebung: Ein Lernlauf ließ sich nicht starten. Die Schätzung setzte je Mail 17
  bis 69 Millionen Tokens an (die Nutzlastgrenze doppelt für jeden Aufruf und Versuch),
  sodass jedes realistische Budget mit „Budget reicht nicht“ abgelehnt wurde.
  Regressionstest mit den Werten der betroffenen Installation.
- Die Schätzung ist jetzt typisch (vier Aufrufe je Mail zu je 5.000 Tokens); der
  ungünstigste Fall wird getrennt angezeigt. Das Budget schützt weiter hart vor jedem
  Aufruf.
- Jeder Aufruf reserviert nur noch seine Anfragegröße plus `max_tokens` und wird nach
  der Antwort auf den vom Anbieter gemeldeten Verbrauch abgerechnet.
- Abgelehnte Aktionen nennen ihren Grund auf der Seite und im Protokoll; der Startknopf
  erscheint nur, wenn das Budget reicht.
- Ein pausierter Lauf mit geänderter Konfiguration kann durch einen neuen ersetzt werden.

## 4.9.6 – Gesamtabnahme der Postfach-Briefings (Planung 4.9, Schritt 20.7)

- Version 4.9 führt konfigurierbare Postfach-Briefings, dauerhafte Zeitfenster und sichere PWA-Verweise zusammen. Release-Bericht, Paketprüfung sowie Windows-, Linux- und Browserprüfungen dokumentieren die Abnahme.
- Regression behoben: Eigene Briefings im mit abgerufenen Entwurfsordner werden anhand von Konto und gespeichertem Inhaltsabdruck erkannt und erzeugen keine neuen Aufgaben oder LLM-Aufrufe. Betreff und Message-ID allein reichen zum Überspringen nicht aus.

## 4.9.5 – Zeitreisetests für Briefings (Planung 4.9, Schritt 20.6)

- Deterministische Tests mit time-machine prüfen 07:00, 13:00 und 18:00 an Werktagen und Wochenenden mit wieder geöffnetem Zustandsspeicher. Doppelte Herbststunden zählen einmal; fehlende Frühlingszeiten werden um die Zeitlücke verschoben. Verspätete Starts holen nur heutige Slots nach; ausgefallene Tage werden nicht künstlich nacherzeugt.

## 4.9.4 – IMAP-Briefings im Zielpostfach (Planung 4.9, Schritt 20.5)

- Briefings verwenden den gemeinsamen IMAP-Writer mit stabiler Message-ID, festem Inhaltsstand und dauerhaft gebundener Postfach- und Ordnerauswahl. Laufzeit und Testmodus sind unabhängig von Antwortentwürfen; vor APPEND werden die aktuellen Einstellungen erneut geprüft.

## 4.9.3 – HTML- und Text-Briefings (Planung 4.9, Schritt 20.4)

- Briefings enthalten ein responsives HTML-Layout und gleichwertigen Klartext mit offenen Karten, Fristen, Zusammenfassungen und Kennzahlen. HTML-Inhalte werden escaped; Links öffnen ausschließlich die bestehenden authentifizierten Mailhelp-Karten und autorisieren keine Anlage. Große Listen bleiben mit korrekten Gesamtzahlen und Überlaufhinweisen kompakt. Beschädigte Akten erzeugen einen Hinweis statt einer leeren Alles-ruhig-Meldung.

## 4.9.2 – Briefing-Inhalte aggregieren (Planung 4.9, Schritt 20.3)

- Der BriefingAggregator sammelt aktuelle offene Termin-, Aufgaben- und Relevanzkarten aller Postfächer sowie Zusammenfassungen und Fristen aus dem Zeitfenster. Gespeicherte Analysezeitpunkte verhindern erneutes Zählen durch spätere Bearbeitungen. Beschädigte Zustände werden schreibfrei übersprungen und als Hinweis gezählt; entfernte Zusammenfassungen werden nicht wiederhergestellt.

## 4.9.1 – Dauerhafte Briefing-Zeitsteuerung (Planung 4.9, Schritt 20.2)

- Der BriefingScheduler speichert Termine und Wiederholungszeitpunkte in briefing_state.json. Identitäten aus lokalem Datum und Uhrzeit verhindern Doppelläufe nach Neustart, Zielwechsel und rückwärts laufender Uhr. Verpasste heutige Zeiten werden geordnet nachgeholt; Inhaltsfenster beginnen beim letzten erfolgreichen Briefing.

## 4.9.0 – Briefing-Einstellungen (Planung 4.9, Schritt 20.1)

- Neue Postfach-Briefings sind standardmäßig aus; Uhrzeiten, Zielpostfach und Leerlaufverhalten lassen sich unter Einstellungen → Postfach-Briefings versions- und CSRF-geschützt ohne Neustart bearbeiten. Der bestehende Telegram-Tagesüberblick bleibt unabhängig.

## 4.8.6 – Abnahme Antwortentwürfe (Planung 4.8, Schritt 19.7)

- End-to-End-Abnahme mit synthetischer Mail und Offline-IMAP: Antwort ohne Aufgabe oder
  Termin, Threading und Signatur, voller Ordner, Verbindungsabbruch vor und nach APPEND,
  Wiederaufnahme nach einem Prozessabbruch und Schutz vor Doppelentwürfen.
- Release-Bericht `docs/Release-4.8.md` dokumentiert Funktion, Schalter, Tests und Grenzen.
- Regression: Der tatsächliche Entwurfsordner wird vor APPEND dauerhaft gebunden. Ein
  unklares Ergebnis wird auch nach einer Ordneränderung ausschließlich dort abgeglichen;
  ein nicht verfügbarer ursprünglicher Ordner löst keine neue Ablage an anderer Stelle aus.

## 4.8.5 – Einstellungen für Antwortentwürfe (Planung 4.8, Schritt 19.6)

- `drafts.enabled` (Standard an) erlaubt oder sperrt neue Antwortentwürfe global;
  `drafts.folder` überschreibt optional den Entwurfsordner. Beide sind unter Antworten
  ohne Neustart änderbar. `null` verwendet die bisherige Postfach- und SPECIAL-USE-Wahl.
- `auto_draft` ist nun global und je Postfach im Web einstellbar; der bestehende Standard
  bleibt aus. `smart_reply` ist weiterhin Voraussetzung. Bestehende Installationen
  werden nicht auf automatische Ablage umgestellt.
- Regression: Eine während der Generierung oder des IMAP-Abgleichs deaktivierte
  automatische Ablage verhindert APPEND an der Schreibgrenze; der Text bleibt lokal.

## 4.8.4 – Entwurfsvorschau (Planung 4.8, Schritt 19.5)

- Gespeicherte und simulierte Antwortentwürfe bleiben auf der Mail- und Vorschlagsseite
  lesbar. Antworttexte lassen sich kopieren; bei fehlender Zwischenablage oder verweigerter
  Berechtigung erklärt die Seite das manuelle Kopieren.
- Automatische Entwürfe erscheinen als versionsgebundene Aktionsergebnisse im bestehenden
  Benachrichtigungsprofil. Telegram zeigt den Text nur im Inhaltsmodus „Zusammenfassung“;
  Ruhezeiten, Bündelung und der Schutz vor Wiederholungen gelten weiterhin.

## 4.8.3 – Automatischer Antwortentwurf (Planung 4.8, Schritt 19.4)

- Neue Einstellung `auto_draft` (global und je Postfach, Standard aus): Erwartet eine Mail
  eine schriftliche Antwort, legt Mailhelp ohne Klick einen Entwurf im Entwurfsordner ab.
  Voraussetzung ist `smart_reply`. Mailhelp sendet nie selbst.
- Der automatische Entwurf trifft keine Entscheidung für dich: Offene Punkte stehen als
  Platzhalter wie „[Termin vorschlagen]“ im Text.
- Ein begonnener eigener Entwurf wird nie ersetzt, ein fertiger automatischer nicht doppelt
  abgelegt; ein Fehler beim Ablegen stoppt die Mailverarbeitung nicht.

## 4.8.2 – Antwortbedarf im Aktionsrouter (Planung 4.8, Schritt 19.3)

- Der Aktionsrouter erkennt, ob eine Mail eine schriftliche Antwort von dir erwartet
  (`reply_needed`, `reply_reason`), unabhängig von Aufgaben und Terminen.
- Das Schema für das Modell verlangt beide Felder; ältere gespeicherte Routen gelten als
  ohne Antwortbedarf. Korpus v3 und `mailhelp-evaluate` prüfen den Antwortbedarf.
- Prompt-Baseline als geprüfter Konfigurationsvertrag fortgeschrieben (ohne Nachweis der
  Modellqualität; die reale Prüfung folgt in der Abnahme).

## 4.8.1 – Betreff und Threading der Entwürfe (Planung 4.8, Schritt 19.2)

- Antwortentwürfe erhalten genau ein „Re: “: Aus „AW: Angebot“ wird „Re: Angebot“ statt
  „Re: AW: Angebot“. Weiterleitungskennzeichen wie „WG:“ bleiben.
- Threading (`In-Reply-To`, `References`, Reply-To als Empfänger) durch einen eigenen Test
  belegt.

## 4.8.0 – Entwurfsordner per SPECIAL-USE (Planung 4.8, Schritt 19.1)

- Fehlt der konfigurierte Entwurfsordner auf dem Server, legt Mailhelp einen Entwurf im
  vom Server als `\Drafts` markierten Ordner ab, sonst in einem gängigen Ordner wie
  „Entwürfe“. Ohne passenden Ordner wird nichts geschrieben.

## 4.7.5 – Abnahme Links zur Original-Mail (Planung 4.7, Schritt 18.6)

- End-to-End-Test: Der Link kommt in Todoist (Markdown) und im Google Kalender an;
  Sonderzeichen der Message-ID werden kodiert, ohne Message-ID entsteht kein Link.
- Release-Bericht `docs/Release-4.7.md`.

## 4.7.4 – Einstellung für den Mail-Client (Planung 4.7, Schritt 18.5)

- `imap.mailboxes[].mail_client`: `auto` (Standard), `apple_mail`, `gmail_web`,
  `outlook_web` oder `none`. In der Weboberfläche je Postfach im Reiter „Ziele“; wird ohne
  Neustart übernommen. `config.example.yaml` beschreibt die Werte.

## 4.7.3 – „Original-Mail öffnen“ in Web und Telegram (Planung 4.7, Schritt 18.4)

- Web-Karten verlinken die Original-Mail.
- Telegram: Schaltfläche für Gmail und Outlook im Browser; der Apple-Mail-Link steht als
  kopierbarer Text in der Nachricht, weil Telegram-Schaltflächen nur http(s) öffnen.

## 4.7.2 – Link zur Original-Mail in Aufgaben und Terminen (Planung 4.7, Schritt 18.3)

- Neue Aufgaben enden mit „📧 [Original-E-Mail öffnen](…)“ (in Todoist klickbar), neue
  Termine mit „📧 Original-E-Mail öffnen: …“. Gmail-Postfächer öffnen Gmail im Browser,
  alle anderen Apple Mail.
- Ohne Message-ID kein Link. Vorschlags-IDs und die Dublettenerkennung von Aufgaben bleiben
  unverändert; das Ledger zählt den Link zur Herkunft.

## 4.7.1 – Links für Gmail und Outlook im Browser (Planung 4.7, Schritt 18.2)

- Gmail im Browser: Suche nach genau der Message-ID (`rfc822msgid:`). Outlook im Browser:
  Suche nach der Message-ID (Outlook bietet keinen dokumentierten Direktlink).
- Automatische Wahl nach IMAP-Server: Gmail-Server öffnen Gmail im Browser, alle anderen
  Apple Mail. Outlook im Browser nur auf ausdrückliche Wahl.

## 4.7.0 – Message-ID und Apple-Mail-Link (Planung 4.7, Schritt 18.1)

- Neues Modul `domain/deep_links.py`: bereinigt die Message-ID einer Mail und erzeugt
  den Link `message://%3C…%3E`, der die Mail in Apple Mail öffnet. Ohne gültige
  Message-ID entsteht kein Link. Grundlage für die Links in Kalender und Aufgaben.

## 4.6.7 – Abnahme Terminänderungen und Absagen (Planung 4.6, Schritt 17.8)

- Fehlerbehebung: Der Aktionsrouter wertete die Absage eines bestimmten Termins als
  „keine Aktion“ (reale Auswertung, Fälle 10 und 38); es entstand kein Vorschlag. Er zählt
  sie jetzt als Terminkandidaten. Nachprüfung mit echtem Modell: Router 4/4.
- End-to-End-Test von der Mail bis zum verschobenen bzw. abgesagten Kalendereintrag für
  alle Abnahmekriterien aus Planung 4.6.
- Release-Bericht `docs/Release-4.6.md`.

## 4.6.6 – Korpus für Terminänderungen (Planung 4.6, Schritt 17.7)

- Korpus v3 enthält vier synthetische Fälle: Verschiebung um eine Woche, späterer Beginn,
  neuer Raum und ersatzlose Absage (38 Fälle insgesamt).
- `mailhelp-evaluate` vergleicht bei Terminen auch das frühere Datum einer Änderung.
- Prompt-Baseline als geprüfter Konfigurationsvertrag fortgeschrieben, ohne Nachweis der
  Modellqualität.

## 4.6.5 – Unklare Absagen sicher abgleichen (Planung 4.6, Schritt 17.6)

- Eine Absage mit verlorener Antwort wird nach einem Neustart über ihren Zieleintrag
  abgeglichen: abgesagt oder gelöscht heißt erfolgt, noch aktiv heißt weiter unklar. Sie
  wird nie automatisch wiederholt. Bisher blieb sie dauerhaft „unklar“, weil ein
  abgesagter Google-Eintrag in der Schlüsselsuche fehlt.

## 4.6.4 – Bestehende Termine ändern (Planung 4.6, Schritt 17.5)

- Eine bestätigte Änderung liest den Kalendereintrag vor dem Schreiben erneut und ändert
  nur Zeiten und Ort. Titel und Beschreibung des Eintrags bleiben; eine Notiz in der
  Beschreibung hält fest, was sich wann geändert hat. Bisher überschrieb Mailhelp Titel
  und Beschreibung mit den Angaben aus der Mail.
- Ein gelöschter Eintrag wird durch eine Änderung nie neu angelegt (Ergebnis
  „fehlgeschlagen“). Ein unklares Ergebnis wird nach einem Neustart über den Schlüssel der
  bestätigten Version abgeglichen und nicht wiederholt.
- Eine bestätigte Absage ändert nur den Status; ein bereits abgesagter oder gelöschter
  Eintrag braucht keinen zweiten Schreibzugriff.
- Fehlerbehebung: Ein CalDAV-Eintrag, der keine einfache Einzelveranstaltung ist (Serie),
  galt beim Lesen als „nicht vorhanden“; eine Absage wäre fälschlich als erledigt gemeldet
  worden. Er wird jetzt als nicht änderbar abgelehnt.

## 4.6.3 – Darstellung von Änderungen und Terminauswahl (Planung 4.6, Schritt 17.4)

- Web: Änderungen gegenüber dem Kalender mit durchgestrichenem altem und fettem neuem
  Wert; Absagen als roter Hinweis „Termin im Kalender stornieren“.
- Telegram (reiner Text): „Beginn: bisher … → neu …“.
- Mehrere passende Kalendertermine werden nummeriert angezeigt und lassen sich im Web und
  in Telegram auswählen (`choose_calendar_event`, versionsgebunden, nur angebotene
  Einträge). Die Auswahl erzeugt eine neue Version zur gesonderten Bestätigung.

## 4.6.2 – Kalenderabgleich für Änderungen und Absagen (Planung 4.6, Schritt 17.3)

- Änderungen und Absagen finden ihren bestehenden Kalendereintrag: ±1 Tag um das frühere
  bzw. abgesagte Datum, ohne früheres Datum per Titelsuche ±92 Tage um das neue Datum.
- Genau ein Treffer wird zum Ziel; fehlende Zeiten übernimmt Mailhelp aus dem Eintrag
  (alte Uhrzeit und Dauer bei „verschoben auf den 11.12.“, die Zeiten des abgesagten
  Termins). Die Rückfrage nach dem Eintrag entfällt.
- Kein oder mehrere Treffer: konkrete Rückfrage, mehrere Treffer werden als Kandidaten
  gespeichert; nie wird ein Termin geraten. Ein schon verschobener Eintrag ergibt „bereits
  vorhanden“.
- Ein gewähltes Ziel wird bei jeder weiteren Prüfung nur gelesen (`existing_event` für
  Google, CalDAV, Outlook); ist es gelöscht, öffnet sich die Frage erneut.
- Fehlerbehebung: Ein abgesagter Kalenderanhang ließ den Vorschlagsbau scheitern
  („Eine Stornierung erfordert eine Ziel-Event-ID“). Regressionstest ergänzt.

## 4.6.1 – Früheres Datum bei Terminänderungen (Planung 4.6, Schritt 17.2)

- `event_extraction` liefert bei `classification: "change"` zusätzlich
  `original_date_text`, das wörtliche frühere Datum; Datum, Zeit und Ort beschreiben den
  neuen Stand. Bei einer Absage beschreiben sie den abgesagten Termin.
- Der Vorschlag speichert das aufgelöste frühere Datum als `original_date` (nur bei
  Änderungen). `Proposal.calendar_candidates` nimmt später mehrdeutige Kalendertreffer
  auf. Gespeicherte Zustände bleiben ohne Migration gültig; Vorschlags-IDs für
  Extraktionen ohne das neue Feld bleiben gleich.

## 4.6.0 – Titelsuche im Kalender (Planung 4.6, Schritt 17.1)

- Alle Kalenderadapter (Google, CalDAV, Outlook) bieten `search_events(title_query,
  start, end)`: verwandte Termine in einem Zeitraum, Titelvergleich nur lokal
  (`domain/event_titles.py`, auch für zusammengesetzte Wörter). Abgesagte Termine fehlen;
  ein Lesefehler wird gemeldet statt als „kein Termin“ gewertet.
- Grundlage für den Abgleich verschobener und abgesagter Termine in den folgenden Schritten.

## 4.5.7 – Fristen in der Zusammenfassung (Planung Fristen, Schritte F.1 bis F.5)

- Ursache bestätigt (F.1, 11 reale Aufrufe): Das Modell ließ `deadlines` in 6 von 11
  Antworten ganz weg, weil das Schema nur `sentences` verlangte; Mailhelp setzte
  stillschweigend `[]` ein.
- Neues Antwortschema `SummaryAnswer`: `deadlines` ist Pflicht und steht vor
  `sentences`. Eine fehlende Liste ist ein Schemafehler mit Wiederholung. Gespeicherte
  Zusammenfassungen bleiben ohne Migration lesbar.
- Die Zusammenfassung erhält bei eigenen Notizen die Perspektive. Keine Fristen sind
  Kopfzeilendaten weitergeleiteter Nachrichten und eine Anmeldefrist, wenn die nutzende
  Person schon angemeldet ist (Entscheidung vom 8. November 2026).
- Korpus: Fall 30 erwartet die elf genannten Sitzungstermine statt eines kopierten
  Datums aus Fall 03.
- Fehlerbehebung: `src/mailhelp/defaults/prompts.yaml` hatte die Prompt-Änderungen aus
  4.5.2 und 4.5.3 nicht erhalten. Die Vorlage ist wieder identisch; ein Test sichert das.
- Reale Abnahme über alle 34 Fälle (126 Aufrufe, 0,07 $): Zusammenfassung 31 von 34
  (vorher 14 von 25).

## 4.5.6 – Eigene Notizen immer relevant und reale Auswertung (Planung 4.5, Schritt 16.6)

- Eigene Notizen und eigene Weiterleitungen (`self_mail`) gelten ohne Relevanzaufruf als
  relevant (`topic_ids: []`, Begründung „Eigene Notiz: immer relevant“, Quelle
  `self_mail`). Anlass: In der realen Auswertung wurde die weitergeleitete Einladung
  „Bitte eintragen“ als irrelevant eingestuft; es wäre kein Vorschlag entstanden. Ein
  Postfach ohne aktivierte Themen bleibt abgeschaltet, auch für eigene Notizen. Jede
  Anlage bleibt bestätigungspflichtig.
- `mailhelp-evaluate` wendet dieselbe Regel an und vergleicht ein Datum ohne
  vorangestellten Wochentag („Samstag, 5. Dezember 2026“ = „5. Dezember 2026“).
- Reale Auswertung (deepseek-v4.1-flash über OpenRouter): Router 25 von 25, darunter alle
  drei eigenen Notizen. Nachprüfung der Notiz-Fälle nach der Korrektur: Relevanz,
  Routing und Extraktion bestehen; offen sind nur Fristen der Zusammenfassung
  (eigener Plan: `docs/Planung-Fristen-Zusammenfassung.md`).

## 4.5.5 – Abnahme eigene Notizen (Planung 4.5, Schritte 16.6 und 16.7)

- End-to-End-Regressionstest der Landesversammlung, synthetisiert: Eine eigene Notiz
  mit drei Einladungsfotos ergibt einen Terminvorschlag für die nutzende Person.
- Das Offline-Prompt-Gate besteht für alle 34 Fälle. Release-Bericht:
  `docs/Release-4.5.md`. Die Auswertung mit einem echten Modell steht aus.

## 4.5.4 – Korpus für eigene Notizen (Planung 4.5, Schritt 16.5)

- Korpus v3 enthält drei synthetische eigene Notizen (Einladungsfoto mit „Ich nehme
  teil“, weitergeleitete Einladung mit „Bitte eintragen“, Aufgaben-Notiz); insgesamt
  sind es jetzt 34 Fälle.
- `mailhelp-evaluate` übergibt Routing und Extraktion dieselbe Perspektive wie die
  Verarbeitung (gemeinsames Modul `processing.perspective`). Den aus Bildanhängen
  erkannten Text kann ein Korpusfall unter `vision` mitliefern.

## 4.5.3 – Eigene Notizen in der Extraktion (Planung 4.5, Schritt 16.4)

- Aufgaben- und Terminextraktion erhalten wie der Router das Feld `perspective`.
  Eine Teilnahme- oder Eintragungsnotiz macht die Veranstaltung aus Anhang oder
  Weiterleitung zum eigenen Termin (`responsibility: user`). Die Fakten stammen aus
  dem Original, nicht aus der Notiz. Eine Absage erzeugt keinen Termin.
- Die Prompt-Baseline ist als geprüfter Konfigurationsvertrag fortgeschrieben,
  ohne Nachweis der Modellqualität.

## 4.5.2 – Eigene Notizen im Aktionsrouting (Planung 4.5, Schritt 16.3)

- `action_router` erhält bei eigenen Mails und Weiterleitungen das von der Anwendung
  gesetzte Feld `perspective`. Der Prompt kehrt die Perspektive um: „Ich nehme teil“
  oder „Bitte eintragen“ mit einem Termin aus Anhang oder Weiterleitung ist ein
  Termin der nutzenden Person, eine eigene Handlungsanweisung eine Aufgabe. Für
  andere Mails ändert sich die Eingabe nicht.
- Die Prompt-Baseline ist als geprüfter Konfigurationsvertrag fortgeschrieben.
  Die Modellqualität ist damit noch nicht belegt, das folgt in Schritt 16.6.

## 4.5.1 – Weiterleitungen erkennen (Planung 4.5, Schritt 16.2)

- Weiterleitungen werden am Betreff (`WG:`, `Fwd:`, `Fw:`) und an den Trennzeilen von
  Apple Mail, Outlook, Gmail und Thunderbird erkannt (deutsch und englisch).
  `MailState.is_forwarding` und `MailState.forwarded_headers` halten Absender, Datum,
  Betreff und Empfänger des Originals. Bei eigenen Mails ist `user_note` nur die Notiz
  über der Weiterleitung.

## 4.5.0 – Eigene Mails erkennen (Planung 4.5, Schritt 16.1)

- Mails von einer eigenen Adresse des Postfachs gelten als eigene Notiz:
  `MailState.self_mail` und `MailState.user_note`. Eigene Adressen sind der
  IMAP-Benutzername, neue Aliase unter `imap.mailboxes[].own_addresses` und Adressen
  in `personal_info`. Anzeigenamen zählen nicht. Die Markierung autorisiert keine
  Anlage, und gespeicherte Mails bleiben ohne Migration gültig.

## 4.4.1 – Schnelle Web-Aktionen bei großen Datenbeständen

- Fehlerbehebung mit Regressionstest: Der Bedien-Thread speicherte in jedem Durchlauf
  alle aktuellen Vorschläge und ihre Mails erneut, obwohl sich nichts geändert hatte.
  In einer Instanz mit 1.664 Mails waren das 224 Vorschläge etwa alle vier Sekunden.
  Die Reparatur läuft jetzt nur im ersten Durchlauf nach dem Start.
- Fehlerbehebung mit Regressionstest: Jeder Speichervorgang, auch der eines
  Postfachordners, baute die Übersicht aus allen Mails neu auf (rund 1 s bei 1.664
  Mails). Die Übersicht wird jetzt nur nach Änderungen an angezeigten Zuständen neu
  aufgebaut. Sie liest dabei nur geänderte Dateien.
- Fehlerbehebung mit Regressionstest: Identische Zustände werden nicht mehr neu
  geschrieben.
- Relevanzdialoge, Abgleichjournale und bestätigte Anlagen werden pro Durchlauf aus
  einem Verzeichnislauf und zwischengespeicherten Ausschnitten bestimmt. Ein
  Durchlauf dauert bei 2.000 Mails rund 55 ms statt 4,8 s.
- Die Karte fragt ihr Ergebnis in den ersten drei Sekunden alle 0,1 s statt alle
  0,5 s ab.
- Gemessen vom Absenden bis zum sichtbaren Ergebnis: mit 2.000 synthetischen Mails im
  Median 0,33 s statt 6,9 s mit 4.4.0. Mit einer lokalen Kopie der realen Daten
  (1.664 Mails) 0,33–0,35 s statt 2–9 s.

## 4.4.0 – Pufferschicht für Web-Eingaben und Bedienung ohne Wartezeit

- `POST /aktion` nimmt Befehle ohne Ablagesperre und ohne andere zwischen Threads
  geteilte Sperre an. Exklusive Kapazitätsmarken, unveränderliche Quittungen und
  Eingangsdateien sichern jeden quittierten Befehl. Der Bedien-Thread übernimmt sie
  vor allen anderen Arbeiten. Absturz, Doppelklick und Neustart erzeugen weder Verlust
  noch doppelte Ausführung. Beschädigte Dateien werden isoliert und ohne Inhalt gemeldet.
- Nach dem Absenden erscheint sofort die Übersicht. Die Karte zeigt
  „Wird verarbeitet …“, bietet bis zum Ergebnis keine weitere Aktion an und zeigt
  danach das Ergebnis. Fehler, Ablehnungen und unklare Anlagen bleiben auf allen
  gekoppelten Geräten sichtbar, bis „Zur Kenntnis genommen“ gewählt wird.
- Gemessen bei laufender Mailanalyse, blockiertem Telegram-Versand, fünf
  gleichzeitigen Browsern und 5 s gehaltener Ablagesperre: Annahme im Median 9–33 ms,
  im Maximum höchstens 52 ms unter Windows, Linux und Docker; im Browser über HTTP 12–62 ms. Unter 4.3.0 wartete
  dieselbe Annahme 5.006 ms. `/status` zeigt die Annahmezeit der letzten 20 Web-Aktionen.
- Fehlerbehebungen mit Regressionstests:
  - Ohne JavaScript lud sich die Übersicht wegen der Sprungmarke nie neu.
    Der Refresh nennt jetzt ein Ziel ohne Sprungmarke.
  - `app.js` übernimmt keine `<noscript>`-Inhalte mehr aus nachgeladenem HTML.
  - Auf breiten Bildschirmen wählt die Übersicht die Karte der Sprungmarke aus,
    sodass das Ergebnis sichtbar bleibt.
  - Die Übernahme quittierter Befehle wird nicht mehr durch die Warteschlangengrenze
    abgewiesen.
  - Die Übersicht zeigt ein Ergebnis nur noch einmal auf der Karte. Die zusätzliche
    `?ergebnis=`-Meldung oben entfällt. Weiterleitungen von `/aktion/<id>` springen
    zur Karte.
  - Der Toast zeigt nur die Ergebnismeldung statt des ganzen Kartentexts und blendet
    sich nach sechs Sekunden aus. Auf schmalen Bildschirmen verdeckte er die Schaltflächen.
  - Eine noch unbekannte Aktion (404 nach verlorener POST-Antwort) gilt als
    „wird geprüft“ und nicht mehr als Verbindungsfehler.
  - „Zuletzt erledigt“ wird zusammen mit der Karte aktualisiert.
  - Eine Seriengruppe öffnet sich, solange eines ihrer Mitglieder eine Aktion zeigt.
  - Auf breiten Bildschirmen zeigt auch die kompakte Liste das Ergebnis einer Aktion.
    Bisher war es dort ausgeblendet und nur kurz im Toast zu sehen.
  - Die JavaScript-Pfade der Pufferschicht sind vollständig im Browser getestet
    (`ui_tests/test_ui_v44_paths.py`).
- 30 Browsertests aus 4.2 und 4.3 erwarteten noch das Verhalten vor den Ergebniskarten
  oder fragten das Lesemodell ab, bevor es veröffentlicht war. Sie prüfen jetzt das
  Verhalten von 4.4.
- Ein E2E-Test erwartete nach einem simulierten Antwortverlust fälschlich
  „Angelegt.“. Er prüft jetzt den Hinweis auf die unklare Anlage, die bis zur
  Kenntnisnahme sichtbar bleibt.

## 4.3.0 – Aufgaben ohne Mengenfragen und sichere Terminserien

- Router und Aufgabenextraktor schließen werbliche Download-/Leseangebote und
  unverbindliche Höflichkeitsweiterleitungen ausdrücklich aus. Der synthetische
  Qualitätskorpus enthält drei weitere Fälle; Offline-Verträge behaupten keine
  gemessene Qualität kostenpflichtiger Modelle.
- Extraktionszahlen bleiben als Diagnose gespeichert. Positive Ergebnisse
  erhalten keine künstliche Mengenfrage; ein vollständig leerer Befund trotz
  positiver Routerzählung meldet verständlichen Prüfbedarf zur Mail.
- Gleichnamige Termine derselben Quelle erhalten einen stabilen Serienschlüssel
  und bei aufgelöstem Datum unterscheidbare Titel. Abgleich und Aktionsschlüssel
  verwenden weiterhin den Grundtitel. Alte Akten werden ohne neue Version ergänzt.
- Telegram fragt bei einer eindeutigen Zeitantwort nach „Alle“ oder „Nur diesen“.
  Die Weboberfläche gruppiert Serien und erlaubt gemeinsame Uhrzeiten und Ausnahmen,
  auch ohne JavaScript. Gespeicherte Uhrzeiten bleiben als manuelle Fakten geschützt.
- Eine eigene Sammelbestätigung bindet die exakt angezeigten Versionen. Vorprüfungen
  erfolgen für die ganze Liste vor dem ersten Schreiben, ohne Netzaufrufe unter der
  Ablagesperre. Jeder Termin behält seinen eigenen Schlüssel und Wiederanlauf-Abgleich;
  geänderte Versionen oder widerrufene Sitzungen stoppen verbleibende Anlagen.

## 4.2.0 – Reaktionsschnelle Web-Aktionen und „Schon erledigt“

- Web-Befehle werden nach dem Neustart-Abgleich vor Schreib-/Revisionswiederaufnahmen
  und Telegram-Eingaben ausgeführt. Versand hält keine gemeinsame Dialog-/Ablagesperre;
  die dauerhafte Outbox bewahrt gleichzeitig neu eingehende Nachrichten.
- Wartezeit bis zum Beginn sowie Dialog- und Ablagesperrzeiten werden ohne Inhalte
  protokolliert. `/status` zeigt Median und Maximum der letzten 20 gemessenen Web-Aktionen.
- `/api/aktion/<id>` liefert nach erneuter Sitzungsprüfung ausschließlich Status und
  Weiterleitungsziel der eigenen Aktion. JavaScript fragt diesen Endpunkt ab; ohne
  JavaScript bleibt automatisches Neuladen erhalten. Der Hinweis auf eine angeblich
  abzuwartende Mailanalyse entfällt.
- „Schon erledigt“ schließt die genaue Vorschlagsversion lokal als `rejected` mit
  `resolution="already_done"`. Externe Anlagen werden nicht aufgerufen. Das Lernlog
  vermerkt die positive Relevanz; CLI- und Browser-Lernen schützen solche Beispiele
  vor erneuter negativer Kategorisierung. Status und Berichte weisen sie separat aus.
- Der Neustart-Abgleich ordnet „Schon erledigt“ ausschließlich der bestätigten
  Vorschlagsversion und ihrem tatsächlichen Abschlusskennzeichen zu; fremde
  Entscheidungen erzeugen kein positives Lernprotokoll für diese Aktion.
- Ein zufälliger Fehlalarm im PIN-Speichertest ist deterministisch abgesichert:
  erwartete Hashfelder werden feldgenau geprüft, statt kurze Zahlenfolgen auch
  innerhalb sicherer Hashwerte fälschlich als Klartextspeicherung zu bewerten.

## 4.1.11 – Messbare Qualitätsaufgaben und konservativer Prompt-Schutz

- Plattformübergreifende Befehle und VS-Code-Tasks für Schnelltest, vollständige
  Abnahme mit aktuellen Paketen, Browser-Smoke und Prompt-Gate. Der Schnelltest nutzt
  pytest-xdist mit Workstealing und dokumentiert seine Gesamtlaufzeit. Das nach den
  Messungen gemeinsam angepasste 15-Sekunden-Ziel gilt für ausdrücklich ausgewählte
  TDD-Tests (`python -m devtools.check tdd <Testdatei oder Node-ID>`).
- Mutationstests mit festgeschriebenem mutmut 3.8.0 und vollständiger Linux-Abhängigkeitssperre;
  manuell und wöchentlich ausführbarer Workflow mit 90-%-Schranke. Nur getötete Mutanten
  zählen als erkannt, Zeitüberschreitungen und ungetestete Mutanten verbessern den Wert nicht.
- Abschlussaudit: 1.001 von 1.011 Kernmutanten getötet (99,01 %); alle zehn Überlebenden
  einzeln bewertet. Direkte Invarianten prüfen Revisionen, Freigaben, Profilbindung,
  Autorisierung, Wiederaufnahme unklarer Ergebnisse und atomare Speicherung.
  Parallele Volltests führen Prozess- und E2E-Prüfungen gemeinsam sequenziell aus.
- Das Offline-Prompt-Gate verweigert auch Textänderungen gegenüber der geprüften
  Konfigurationsbasis. Simulierte Antworten werden ausdrücklich nicht als Beleg für
  echte Modellqualität gewertet.
- Sicheres YAML-Laden verwendet bei Verfügbarkeit den C-Parser; dieselben Typ- und
  Sicherheitsprüfungen testen den Python-Fallback und den kompilierten Parser.
- Behoben: Die Bereinigung eines erfolgreichen Tests konnte Coverage-Dateien eines
  parallel laufenden Volltests löschen. Volltests verwenden jetzt einen eigenen
  Coverage-Pfad je Aufruf; die Bereinigung berücksichtigt genau diesen Pfad.
  Der Regressionstest wurde gegen die alte und die korrigierte Bereinigung geprüft.
- Automatische Tests erzeugen unkonfigurierte HTTP-Clients mit einem gesperrten
  Simulationstransport. Versehentliche echte Provideraufrufe scheitern sofort;
  ausdrücklich übergebene Simulationstransporte bleiben unverändert wirksam.
- Behoben: Eine Zustandsdatei mit ungültigem UTF-8 umging die Behandlung beschädigter
  JSON-Daten. Schreibfreies Lesen meldet jetzt `CorruptState` ohne Verschieben;
  normales Laden isoliert die ursprünglichen Bytes als `.corrupt`. Der Regressionstest
  scheiterte vor dem Fix mit `UnicodeDecodeError` und besteht danach.

## 4.1.10 – Thema für persönliche Termine und Terminhinweise

- Neues Thema „Persönliche Termine und Terminhinweise“ in `topics.yaml`: Mails, die einen
  konkreten Termin mitteilen, bestätigen, ändern oder absagen, sowie Einsatz-, Dienst-,
  Stunden- oder Blockpläne mit eigenen Einsätzen, auch wenn die Termine nur im Anhang stehen.
  Ein Blockplan mit eigenen Unterrichtsstunden im PDF-Anhang wurde bisher ohne passendes
  Thema als irrelevant eingestuft. Werbung mit Fristen, allgemeine Veranstaltungshinweise
  und Paketankündigungen sind ausgeschlossen.
- Qualitätskorpus v3 um zwei synthetische Fälle erweitert: ein Einsatzplan mit zwei eigenen
  Terminen (relevant, zwei Termine) und eine Werbemail mit Frist (irrelevant). Das
  Evaluierungs-Gate scheitert, wenn das Thema in `topics.yaml` fehlt oder deaktiviert ist.

## 4.1.9 – Browser-Smoke und offline ausgelöste Aktionen

- Planung 4.1, Schritt 9.13: `python -m pytest ui_tests -m smoke --no-cov` prüft in rund
  40 Sekunden Anmeldung, Bestätigen, Übersicht, Offline-Seite, Einrichtung ohne JavaScript und
  Barrierefreiheit. Ein neuer Browsertest belegt, dass eine offline ausgelöste Bestätigung
  weder ausgeführt noch später vom Service Worker wiederholt wird.

## 4.1.8 – Deterministisches Evaluierungs-Gate für Prompts und Themen

- Planung 4.1, Schritt 9.12: Ein deterministisches Gate führt den Qualitätskorpus v3 mit dem
  echten `prompts.yaml` und `topics.yaml` durch den Auswertungspfad von `mailhelp-evaluate`;
  nur die Modellantworten sind simuliert. Fehlende oder umbenannte Stufen, nicht auflösbare
  Routen und entfernte oder deaktivierte Korpusthemen lassen jeden Testlauf scheitern, bevor ein
  bezahlter Aufruf entstünde. Die Wirkung neuer Formulierungen auf echte Modelle misst weiterhin
  `mailhelp-evaluate` mit echtem Anbieter.

## 4.1.7 – Deterministische Zeitreisen mit time-machine

- Planung 4.1, Schritt 9.11: `time-machine` ersetzt die Monkeypatches einzelner Uhrfunktionen
  in den Kalender-, iCalendar- und Telegram-Tests. Neue Tests reisen mit den echten
  Standarduhren durch Ablauf von Web-Sitzungen (30 Tage), Anmeldecodes (10 Minuten) und
  Google-Zugriffstokens (1 Stunde). Ein Kalendertest erwartete wegen seines Patches eine
  UTC-Uhrzeit in der Änderungsnotiz; er prüft jetzt die tatsächlich geschriebene Ortszeit.

## 4.1.6 – Property-Tests für MIME, Datumslogik und LLM-Antworten

- Planung 4.1, Schritt 9.10: Hypothesis prüft feindselige Multipart-Mails mit unpassenden
  Grenzen, Zeichensätzen und Transferkodierungen, Wochentags- und Jahreserkennung von 1900
  bis 2099, eindeutige oder abgewiesene Ortszeiten an Zeitumstellungen gegen ein unabhängiges
  Orakel sowie abgeschnittene, in Markdown gefasste oder falsch geformte LLM-Antworten bis zur
  Schemaprüfung der Analyse. Alle Eigenschaften bestehen ohne Änderung am Anwendungscode.

## 4.1.5 – Test-Factories für Vorschläge, Mailzustände und Einstellungen

- Planung 4.1, Schritt 9.9: `tests/fakes/factories.py` liefert gültige Standardobjekte für
  `Proposal`, `MailState` und `Settings` (minimal und vollständig aus `config.example.yaml`);
  Tests geben nur noch ihre Abweichungen an, verschachtelte Einstellungen werden
  zusammengeführt. Die bisherigen Builder nutzen die Factories, Roh-Dictionaries in den
  Profil- und Laufschleifentests sind ersetzt.

## 4.1.4 – Lastfeste Prozess-Sicherheitstests

- Planung 4.1, Schritt 9.5: `ProcessHarness` wartet nicht mehr starr 20 Sekunden auf den
  Kindprozess. Er wartet, solange der Prozess lebt, bis zu einer großzügigen Obergrenze
  (120 s, einstellbar über `MAILHELP_TEST_PROCESS_SECONDS`), und meldet einen ohne Ergebnis
  beendeten Prozess sofort. Unter hoher I/O-Last auf Windows scheitern gesunde Läufe dadurch
  nicht mehr an der Zeitgrenze.

## 4.1.3 – Testimporte ohne sys.path-Manipulation

- Planung 4.1, Schritt 9.4: Alle Tests importieren gemeinsame Doubles als
  `tests.fakes.<modul>` beziehungsweise `tests.scenarios.<modul>`; die `sys.path`-Schleifen in
  `tests/conftest.py` und `ui_tests/conftest.py` sind entfernt. Zwei Tests luden ein anderes
  Testmodul über `__import__`; sie nutzen jetzt die gemeinsamen Doubles, und der Grenztest
  erkennt solche dynamischen Importe. Der Docker-Smoke setzt `PYTHONPATH=/`.

## 4.1.2 – Testpakete tests.fakes und tests.scenarios

- Planung 4.1, Schritt 9.3: `tests/fakes` und `tests/scenarios` sind reguläre Pakete mit
  beschreibender Gliederung; das Projektverzeichnis steht über `pythonpath` im Importpfad.
  Die Umstellung aller Importe folgt in Schritt 9.4.

## 4.1.1 – Pytest-Marker für schnelle Entwicklungsläufe

- Planung 4.1, Schritt 9.2: Die Marker `slow`, `process` und `e2e` sind in `pyproject.toml`
  registriert und mit `--strict-markers` verbindlich. `pytest -m "not (slow or process or e2e)"
  --no-cov` lässt 130 lange oder prozessstartende Tests aus und braucht unter Windows rund ein
  Drittel der Gesamtlaufzeit. Ein Wächtertest verlangt die Markierung jedes Tests mit
  `ProcessHarness` und jedes Moduls unter `tests/e2e`.

## 4.1.0 – Korpus für Jimdo-Anfragen und Stellplatzbuchungen

- Planung 4.1, Schritt 9.1: Der Release-Korpus v3 enthält fünf neue synthetische Fälle für
  Jimdo-Kontaktanfragen sowie Buchungsbestätigung und Stornierung von Stellplätzen; Werbung
  von Jimdo und Roadsurfer muss irrelevant bleiben. Ein Test weist mit simuliertem Anbieter
  Erkennung, Zeitraum der Buchung und Newsletter-Ausschluss nach.

## 4.0.3 – Planung 4.2

- [Planung 4.2](docs/Planung-4.2.md): Web-Aktionen sollen innerhalb einer Sekunde beginnen,
  auch während Mailanalyse und Telegram-Versand. Grundlage sind die Messungen vom
  5. November 2026; Schritte 10.1–10.6 von der Messung der Wartezeiten bis zur Abnahme.

## 4.0.2 – Thema für Behörden und Auflagen

- Neues Thema „Behörden und Auflagen für Betrieb und Biogasanlage“ in `topics.yaml`:
  Anforderungen von Landratsamt, Gewerbeaufsicht, Immissionsschutz, Baurechtsamt oder
  Landwirtschaftsamt wie Prüfberichte, Schulungsnachweise, Fristen, Kontrollen und
  Auflagen. Solche Mails wurden bisher ohne passendes Thema als irrelevant eingestuft.

## 4.0.1 – Verklemmung von Weboberfläche und Mailabruf behoben

- Behoben: Nach einer Web-Aktion konnten Weboberfläche, Mailabruf und Telegram-Bedienung
  dauerhaft hängen bleiben; nur `/health` und der Telegram-Empfang antworteten noch, bis
  zum Neustart. Ursache war eine umgekehrte Sperrreihenfolge: Die
  Benachrichtigungszustellung hielt die Sperre der Zustandsablage und fragte den
  Befehlseingang beziehungsweise die Push-Abonnements, während eine Webseite deren eigene
  Sperre hielt und auf die Ablage wartete. Befehlseingang und Push-Abonnements nutzen
  jetzt die Sperre der Ablage selbst. Regressionstests stellen beide Verklemmungen mit
  zwei Threads nach.

## 4.0.0 – Browser-First Inbetriebnahme und Web-Lernmodus

Haupt-Release aus den abgenommenen Arbeitsständen 3.6.38, 3.7.19 und 3.8.28.

- Ersteinrichtung ohne vorbereitete `config.yaml` im Browser, geschützt durch einen
  beim Start ausgegebenen Terminal-Code; Übergang in den Normalbetrieb im selben Prozess.
- Anmeldung per Terminal-Code, Telegram-Code oder Web-Passwort; Google- und
  Microsoft-Konten werden im Browser verbunden.
- Web-Lernmodus unter `/lernen` mit Kostenschätzung, Hintergrundlauf, Pause, Abbruch
  und ausdrücklicher gemeinsamer Übernahme von Themen, Ausschlüssen, Absendern und Ordnern.
- `/dienst/neu-laden` ohne Prozessneustart, `/dienst/selbsttest` mit Empfehlungen,
  Monatskosten und letzte Abfrage je Postfach auf `/status`.
- Konkurrierende Bedienung und Prozessabbrüche für sieben Anbieter unter Windows,
  Linux und Docker abgesichert.
- Behoben: Wurde die Systemuhr während der Verarbeitung zurückgestellt (NTP oder
  Zeitabgleich einer VM wie WSL 2), scheiterte die Mail mit `internal_error` oder ihr
  Zustand wurde als `.invalid` isoliert. `updated_at` bewegt sich jetzt beim Speichern
  durch Orchestrator und Vorschlagsablage nie rückwärts, ein neuer Mailzustand liest die
  Uhr nur einmal, und die erneute Prüfung einer aussortierten Mail ist abgesichert.

## 3.8.28 – Gesamtabnahme 3.8

- Gesamtabnahme nach Q4.6 bestanden und im [Releasebericht 3.8](docs/Release-3.8.md)
  dokumentiert: vollständige Suite unter Windows und Linux mit 100 % Zeilen- und
  Branch-Abdeckung, 219 Browsertests mit 100 % JavaScript-Blockabdeckung, installiertes
  Wheel auf beiden Plattformen, Docker-Ablauf mit hartem Abbruch und zwei Neustarts.
- Abschlussbericht mit Szenario, Anbieter/Operation, Plattform, Testreferenz, Ergebnis,
  gefundenen Fehlern (behoben in 3.8.27) und begründeten Einschränkungen.
- Planung 3.8 und Gesamtfahrplan 4.0 auf „abgenommen“ gesetzt; offen ist nur Schritt 8.8
  (Release 4.0.0). Keine Verhaltensänderung.

## 3.8.27 – Lange Vorschlags-IDs entscheidbar

- Behoben: Vorschläge „Nachricht manuell prüfen“ für zu große Anhänge ließen sich
  weder verwerfen noch bestätigen; Web und Telegram meldeten „Die Eingabe ist ungültig.“
  Ihre ID `manual_attachment_<Mail-ID>` hat 42 Zeichen, das interne Entscheidungsmodell
  akzeptierte aber nur 32. Es akzeptiert jetzt wie der Vorschlag selbst 64 Zeichen;
  bereits wartende Vorschläge sind ohne Migration wieder entscheidbar.
- Ein Wächtertest stellt sicher, dass kein Modellfeld mit Vorschlagsbezug strenger
  ist als `Proposal.id`.
- Abgewiesene Prüfbefehle protokollieren das Ereignis `command_refused` mit
  Befehlsart, Status, Fehlerklasse und betroffenen Feldnamen, ohne Feldwerte.

## 3.8.26 – Web-Lernmodus, Laufzeitwechsel und Anbieterabnahme

- Gemeinsamer Lernkern für Terminal und Browser, persistierter Hintergrundjob mit
  Pause, Abbruch, Neustart-Wiederaufnahme und Budgetreservierung vor jedem Modellaufruf.
  Preisobergrenze und Budget werden vor dem ausdrücklichen Start angezeigt.
- Getrennte Laufgenerationen verhindern nach Abbruch und sofortigem neuem Start,
  dass verspätete Ergebnisse, Kostenreservierungen oder Fehler den neuen Job verändern.
- Der Erstzugangscode wird auch bei gepufferter Konsolenausgabe, etwa in Docker,
  sofort ausgegeben. Ein während der Abnahme reproduzierter Fehler ist damit behoben.
- Bearbeitbare Themenkarten mit Belegen, Postfachzuordnung, Ausschlussthemen und
  optionalen Absenderfiltern. Zusätzliche Abrufordner sind auswählbar; Spam und
  Papierkorb bleiben zunächst abgewählt. Erst die gemeinsame bestätigte Übernahme
  schreibt die lokalen Dateien über ein wiederherstellbares Journal.
- `/dienst/neu-laden` bereitet neue Verbindungen vor und wechselt am sicheren
  Mailzyklus. Sitzung und Dateistand werden vor der Aktivierung erneut geprüft;
  alte Verbindungen schließen erst danach. Unfertige Analysen werden zuerst beendet.
- Die Ersteinrichtung aktiviert den Normalbetrieb ohne Austausch des Prozesses.
  Der Lernmodus bleibt neben `--learn` erreichbar.
- Lesender Selbsttest mit Diagnoseempfehlungen; Monatskosten in der konfigurierten
  Zeitzone und letzte Abfrage je Postfach auf der Statusseite.
- Gemeinsame Sicherheitsmatrix über reale Google-, Todoist-, Microsoft-, CalDAV-
  und Apple-Erinnerungen-Adapter mit synthetischem HTTP-Transport; harte Prozessabbrüche
  und zweimaliger Wiederanlauf je Anbieter. CI enthält diese Matrix auch in Docker.
- Die 27 Entwicklungsschritte sind 3.8.0–3.8.26 zugeordnet. Die gesonderte Freigabe
  4.0.0 (Schritt 8.8) wird durch diesen Arbeitsstand nicht veröffentlicht.

## 3.7.19 – Ersteinrichtung und OAuth im Browser

- Ohne `config.yaml` startet ausschließlich der geschützte Einrichtungsserver.
  Ein beim Start automatisch im Terminal ausgegebener Einmalcode öffnet den
  fünfstufigen Assistenten; IMAP-Abruf und Schreibadapter starten erst nach Abschluss.
- Web-Passwörter werden als gesalzene scrypt-Hashes außerhalb der Konfiguration
  gespeichert. Passwort, Terminal-Code und Telegram-Code verwenden dieselben
  widerrufbaren Sitzungen; lokale Passwort-Rücksetzung meldet alle Geräte ab.
- Versionierte Einrichtungsentwürfe, HMAC-geschützte Wiederholungsbelege,
  leere Passwortfelder und erneute Autorisierung nach Verbindungsprüfungen.
  `config.yaml` wird als letzter atomarer Aktivierungsmarker geschrieben;
  unterbrochene Vorbereitungen können wieder aufgenommen werden.
- IMAP-Prüfung mit Ordnerliste und Special-Use-Vorauswahl, OpenRouter-Schlüssel-,
  Guthaben-/Limit- und Modellkatalogprüfung sowie Ollama-Modellauswahl.
  Der gewählte lokale Betrieb bleibt nach dem Neustart aktiv; bisherige
  OpenRouter-Konfigurationen behalten ihren Analyse-Fingerabdruck.
- Kalender- und Aufgabenprüfung bleibt lesend. Todoist benötigt für einen
  persönlichen API-Token keine ungenutzte OAuth-Client-ID oder Client-Secret mehr.
- Google-Playground-Anleitung im Assistenten und in den Zielprofilen; zusätzlich
  Google-Webanmeldung mit registrierter Rückleitung, State, PKCE und Sitzungsbindung.
  Kalenderliste mit Schreibrechten und Pagination, Auswahl als neuer Konfigurationsentwurf.
- Microsoft-Geräteanmeldung im Hintergrund mit dauerhaftem Status, Polling-Abstand,
  Wiederaufnahme nach Neustart und Codeanzeige samt Kopierknopf im Browser.
  Tokens werden nur bei weiterhin gültiger Sitzung und unveränderten Clientdaten gespeichert.
- Eigene Code-, Browser-, Fehler-, Wiederholungs- und Neustartprüfungen ergänzen die
  bisherigen Parallelbedienungs- und Prozessabbruchtests. Neue Persistenzmodelle besitzen
  schema-versionierte JSON-Verträge und Schema-Snapshots.
- Die Zuordnung der 20 Planschritte zu 3.7.0–3.7.19 steht in `docs/Planung-3.7.md`.
  Dieser Arbeitsstand bündelt die Umsetzung; Zwischenreleases wurden hier nicht veröffentlicht.
- Gesamtabnahme: jeweils 2.966 Tests unter Windows und Linux mit 100 % Zeilen- und
  Branch-Abdeckung; 215 Browsertests mit 100 % JavaScript-Blockabdeckung. Zusätzlich
  bestehen 78 Python- und 10 Browsertests gegen das installierte Wheel; `ruff` und
  `mypy` sind ohne Befund. Grenzen der Docker-Prüfung stehen in `docs/Release-3.7.md`.

## 3.6.39 – Feste DeepSeek-Provider: CoreWeave statt Together

- `action_router`, `task_extraction`, `event_extraction`, `mail_question_resolution` und
  `proposal_revision` verwenden jetzt `coreweave` und danach `parasail` statt `together`
  (weiterhin `allow_fallbacks: false`). Grund: Auswertung der LLM-Logs vom 12.10. bis
  04.11.2026 – Together verursachte 49 % der Kosten bei 1,20 USD je Million Ausgabe-Tokens;
  CoreWeave kostet 0,65 USD bei ähnlichem Durchsatz (etwa 270 statt 340 Tokens/s).
- Die Änderung an `prompts.yaml` ändert den Konfigurations-Fingerabdruck: Noch nicht
  abgeschlossene Mails warten wie bei jeder Analyseänderung, statt weiterzulaufen.

## 3.6.38 – Fehlende und beschädigte maßgebliche Akten (Schritt 7.8)

- Upgrade-Absicherung: Alte noch nicht begonnene Freigaben werden nur mit passendem
  ausgeführten Bestätigungsbeleg an die ursprüngliche gültige Websitzung beziehungsweise
  die weiterhin erlaubte Telegram-Identität gebunden.
  Fehlt der Nachweis, bleibt die Anlage sichtbar gesperrt. Lesender Abgleich bleibt möglich;
  die Blockademeldung wird pro Version und Prozess nur einmal ausgegeben.
- Fehlende alte Freigabemetadaten bleiben auch bei unterbrochener Schema-Migration ausdrücklich
  ungeprüft; ein erneuter Start darf daraus keine Telegram-Freigabe ableiten.
- Linux-Abnahme: Der Überblick erkennt extern hinzugefügte oder beschädigte Akten auch
  bei unverändertem Verzeichniszeitstempel; er prüft zusätzlich Dateinamen, Größe und
  Änderungszeit. Nicht sicher serialisierbare Mailkopfzeilen werden vor jedem IMAP-Aufruf
  als Eingabefehler abgewiesen. Deterministische Regressionen ergänzen den Property-Test.
- Regressionen für fehlende, beschädigte und schemawidrige Vorschlags-, Mail-, Ledger-,
  Inbox- und Merge-Akten nach hartem Abbruch und zwei Neustarts. Isolierte Akten bleiben
  sperrend; neue Merge-Revisionen behalten einen Journalverweis und dokumentieren, ob die
  Quelle bereits gespeichert war. Kein stilles Wiederanlegen fehlender Quellen oder Übergehen
  isolierter Journale. Optionale Absenderfilter bleiben rekonstruierbar.
- KI-Revisionsnachfolger dürfen die neuen anwendungseigenen Sitzungsbindungen und
  Journalverweise nicht verändern; zwei Regressionstests sichern diese Grenze ab.
- Eine gültig formatierte Vorschlagsakte unter falschem Dateinamen gilt als beschädigter
  Bestand. Neustarts rekonstruieren daraus keine fehlende maßgebliche Akte und führen nichts aus.
- Abschluss der restlichen 3.6-Implementierung im Arbeitsstand; Patch-Zuordnungen
  3.6.17–3.6.38 dokumentieren die einzelnen Planschritte, keine veröffentlichten Zwischenreleases.

## 3.6.37 – Merge-Abbruch nach beiden Revisionen (Schritt 7.7)

- A7 beendet den Prozess nach der Aliasakte und vor dem Journalabschluss; zwei Neustarts
  vervollständigen das Journal idempotent und erhalten manuell geschützte Werte und Quellen.

## 3.6.36 – Merge-Abbruch vor der Aliasakte (Schritt 7.6)

- A6 prüft harte Beendigung nach der kanonischen Revision, Wiederherstellung der Aliasakte
  sowie Konflikte bei inzwischen geänderter oder fehlender maßgeblicher Akte.

## 3.6.35 – Merge-Abbruch nach dem Journal (Schritt 7.5)

- A5 prüft harte Beendigung direkt nach dem vorbereiteten Merge-Journal; Wiederherstellung
  und zweiter Neustart bewahren beide Quellen und geschützte manuelle Angaben.

## 3.6.34 – Ergebnis vor Ledger-Abschluss (Schritt 7.4)

- A4 beendet den Prozess nach dem maßgeblichen Ergebnis und vor Projektion/Ledger.
  Die lokale Buchführung wird ohne zweiten externen Schreibaufruf repariert.

## 3.6.33 – Antwort vor Ergebnisspeicherung (Schritt 7.3)

- A3 beendet den Prozess vor dem Speichern der erfolgreichen Antwort. Vier Abgleichmodi
  prüfen die sichere Wiederaufnahme ohne erneute Anlage.

## 3.6.32 – Übernommene Anlage ohne Antwort (Schritt 7.2)

- A2 hält die Antwort nach dauerhafter Provider-Übernahme zurück und beendet den Prozess
  hart. Treffer, fehlender Treffer, temporärer Fehler und ungültige Antwort führen zu keiner Doppelanlage.

## 3.6.31 – Gespeicherte Freigabe vor Provider-Aufruf (Schritt 7.1)

- A1 prüft erstmals beginnende Schreibaufträge nach hartem Abbruch, unabhängigen Providerzustand,
  zwei frische Neustarts und weiterhin gültige Autorisierung.

## 3.6.30 – Sichtbare Konflikte in zwei Browserkontexten (Schritt 6.8)

- Zwei unabhängig gekoppelte Browser bearbeiten dieselbe Version. Beide Reihenfolgen prüfen,
  dass die erste Speicherung erhalten bleibt und die zweite sichtbar als Konflikt abgewiesen wird.

## 3.6.29 – Wiederholungen während und nach Ausführung (Schritt 6.7)

- Identische Web-Anfragen liefern trotz inzwischen entschiedenem Vorschlag denselben
  Inbox-Eintrag und sein Ergebnis. Regressionstest für Wiederholung während des Provider-Aufrufs.

## 3.6.28 – Widerruf und Ablauf vor Ausführung (Schritt 6.6)

- Neue Web-Freigaben speichern `confirmed_web_actor`. Sitzung und aktuelle Akte werden nach
  Provider-Vorbereitung und nach Neustarts erneut geprüft. Regressionstests für Widerruf und Ablauf.

## 3.6.27 – Merge gegen Bestätigen (Schritt 6.5)

- Deterministische Tests beider Reihenfolgen prüfen kanonische Version, Aliasakte, Journal,
  Inbox und höchstens eine externe Anlage.

## 3.6.26 – Verwerfen gegen Bestätigen (Schritt 6.4)

- Beide Reihenfolgen prüfen, dass nur eine Entscheidung gewinnt und keine verworfene Version ausgeführt wird.

## 3.6.25 – Bearbeiten gegen Bestätigen (Schritt 6.3)

- Entscheidungen und Bearbeitungen vergleichen vor dem Speichern atomar die aktuelle Akte.
  Regressionstests verhindern, dass eine langsame Vorprüfung eine neuere manuelle Revision überschreibt.

## 3.6.24 – Bestätigen aus zwei Websitzungen (Schritt 6.2)

- Beide Reihenfolgen mit verschiedenen Sitzungsschlüsseln prüfen fachlichen Dublettenschutz,
  persistierte Ergebnisse und eine einzige externe Anlage.

## 3.6.23 – Bestätigen aus Web und Telegram (Schritt 6.1)

- Reale Web- und Telegram-Einstiegspunkte mit gesteuerten Haltepunkten, beiden Reihenfolgen
  und unabhängiger Providerhistorie. CSRF-Matrix für P1–P7 ergänzt.

## 3.6.22 – Unterprozess-Harness (Schritt 1.5)

- Spawn-Prozesse mit echter Betriebssperre, Pipe-Checkpoints, harter Beendigung und begrenztem
  Aufräumen. Coverage wird vor dem Kill gespeichert; ein eigener Test prüft Zeilen und Branch-Arcs.

## 3.6.21 – Persistenter synthetischer Provider (Schritt 1.4)

- Prozessunabhängige JSON-Ablage für Einträge und Aufrufhistorie; Antwort nach Übernahme
  zurückhalten und alle vier Abgleichmodi deterministisch einstellen.

## 3.6.20 – Wiederverwendbare Testbarrieren (Schritt 1.3)

- Event-Haltepunkte mit festen Zeitgrenzen und Aufräumen auch bei fehlgeschlagenen Assertions;
  keine zeitabhängige Synchronisation mit `sleep()`.

## 3.6.19 – Zustandsregeln Schreiben, Ledger und Merge (Schritt 1.2)

- Verbindliche Persistenzgrenzen, Schreibunsicherheit und beide Konfliktreihenfolgen in
  `docs/Zustandsregeln-3.6.md` spezifiziert und mit der Projektspezifikation verknüpft.

## 3.6.18 – Zustandsregeln Review und Inbox (Schritt 1.1)

- Annahme, Ausführungsbeginn, fachlicher Commit, Wiederholung und Neustartabgleich verbindlich dokumentiert.

## 3.6.17 – Protokollierter Antwortzeitnachweis (Schritt 0.6)

- `command_finished` enthält `latency_ms` und `execution_ms`. Der gleichzeitige Betrieb von
  Mailabruf und Bedien-Thread prüft die JSONL-Ereignisse; synthetischer Windows-Messlauf:
  125,102 ms bis Abschluss, während die Analyse weiterhin angehalten war.

## 3.6.16 – Paket `mailhelp.runtime`, Bündelung abgeschlossen (Planung 3.6, Schritt 0.10f)

- Betrieb, Lebenszyklus, Einrichtung, Diagnose, Wartung und Zugangsdaten liegen jetzt im
  Paket `mailhelp.runtime` (`application`, `composition`, `service_coordinator`,
  `operator_thread`, `lifecycle`, `retention`, `metrics`, `diagnostics`, `setup`,
  `setup_runtime`, `standalone`, `experience`, `local_pairing`, `credentials`, `env_file`,
  `yaml_edit`, `google_login`). Damit ist die Bündelung der Wurzelmodule abgeschlossen; im
  Wurzelpaket bleiben `cli`, `models`, `configuration`, `state_names`, `storage`, `logging`,
  `paths`, `formatting`, `german_dates` und `temporal_answers`. Keine Verhaltensänderung;
  der Befehl `mailhelp` und der Neustart nutzen weiterhin `mailhelp.cli`.

## 3.6.15 – Paket `mailhelp.notifications` (Planung 3.6, Schritt 0.10e)

- Benachrichtigungen, Web-Push, Tagesüberblick und Antwortentwürfe liegen jetzt im Paket
  `mailhelp.notifications` (`notifications`, `notification_config`, `notification_context`,
  `notification_runtime`, `webpush`, `briefing`, `drafts`). Importe, Testpfade und
  Dokumentationsverweise sind angepasst; keine Verhaltensänderung.

## 3.6.14 – Paket `mailhelp.llm` (Planung 3.6, Schritt 0.10d)

- Sprachmodell-Clients, Entscheidungsprompts, Lernmodus, Bewertung und
  Konfigurations-Fingerprints liegen jetzt im Paket `mailhelp.llm` (`adapter`, `openrouter`,
  `ollama`, `decisions`, `laya`, `learning`, `evaluation`, `decision_test`, `fingerprints`).
  Der Befehl `mailhelp-evaluate` zeigt auf `mailhelp.llm.evaluation:main`. Importe, Testpfade
  und Dokumentationsverweise sind angepasst; keine Verhaltensänderung.
- Die mitgelieferten Prompt-Vorlagen (`defaults/decisions_prompts.yaml`,
  `defaults/laya_prompts.yaml`) werden vom neuen Ort aus weiterhin im Wurzelpaket gefunden.

## 3.6.13 – Paket `mailhelp.proposals` (Planung 3.6, Schritt 0.10c)

- Vorschläge, Abgleich und Ziele liegen jetzt im Paket `mailhelp.proposals`
  (`proposal_builder`, `proposal_matching`, `proposal_merge`, `proposal_reconciliation`,
  `action_normalization`, `event_defaults`, `precheck`, `profile_binding`, `profile_usage`,
  `target_profiles`, `integrations`). Importe, Testpfade und Dokumentationsverweise sind
  angepasst; keine Verhaltensänderung.

## 3.6.12 – Paket `mailhelp.processing` (Planung 3.6, Schritt 0.10b)

- Die Verarbeitung einer Mail liegt jetzt im Paket `mailhelp.processing` (`orchestrator`,
  `mail_pipeline`, `mail_duplicates`, `mail_questions`, `mail_recheck`, `analysis`,
  `attachment_extractor`, `attachments`, `calendar_parser`, `vision`). Importe, Testpfade und
  Dokumentationsverweise sind angepasst; keine Verhaltensänderung.

## 3.6.11 – Paket `mailhelp.mailbox` (Planung 3.6, Schritt 0.10a)

- Abruf, Postfächer, IServ und die Aktivierung im Betrieb liegen jetzt im Paket
  `mailhelp.mailbox` (`imap`, `mime`, `mailbox_run`, `mailbox_settings`, `mailbox_activation`,
  `mailbox_runtime`, `mailbox_briefing`, `connection_activation`, `connection_runtime`, `iserv`,
  `iserv_activation`, `iserv_runtime`, `sender_filter`). Alle Importe, Testpfade und
  Dokumentationsverweise sind angepasst; keine Verhaltensänderung, Zustandsnamen unverändert.

## 3.6.10 – Zielstruktur der Pakete festgelegt (Planung 3.6, Schritt 0.9)

- `docs/Paketstruktur.md` ordnet alle 78 Module des Wurzelpakets sechs Zielpaketen
  (`mailbox`, `processing`, `proposals`, `llm`, `notifications`, `runtime`) oder dem
  Wurzelpaket zu und legt die Regeln für den Umzug fest: keine Verhaltensänderung, keine
  dauerhaften Alias-Module, `mailhelp.cli` und `mailhelp.models` bleiben. Der Umzug folgt in
  den Schritten 0.10a–0.10f. Keine Verhaltensänderung.

## 3.6.9 – Strikte Typprüfung für die gesamte Weboberfläche (Planung 3.6, Schritt 0.8c)

- `pyproject.toml` stellt `mailhelp.web.*` vollständig unter die strikte mypy-Prüfung.
  Zuletzt wurden Tätigkeitsberichte, Benachrichtigungen und Antwortentwürfe, Absenderfilter,
  Vorschlagsabgleich, Übersicht und `site.py` annotiert; `MailhelpSite` und `ArchiveSite`
  nehmen Konfigurationsdienst, Metriken, Lebenszyklus und Modellübersicht typisiert entgegen.
  Damit ist der in Planung 3.3 offene Punkt erledigt. Keine Verhaltensänderung.

## 3.6.8 – Strikte Typprüfung für Einrichtung, Postfächer und IServ (Planung 3.6, Schritt 0.8b)

- `setup_site`, `mailbox_site`, `mailbox_add_site` und `iserv_site` stehen unter der strikten
  mypy-Prüfung; dazu wurden die lokale Kopplung (`issue`), die Zielprofilauswahl (`choices`)
  und die Verbindungsaktivierung (`ConnectionActivation`) annotiert. Keine Verhaltensänderung.

## 3.6.7 – Strikte Typprüfung weiterer Web-Module (Planung 3.6, Schritt 0.8a)

- Aktionen, Archiv, Verlauf, Vorschlagsbearbeitung, Beenden/Neustart, Zugangsdaten,
  Kontenstatus und Einstellungsseiten stehen unter der strikten mypy-Prüfung.
- Schritt 0.8 wurde wegen 262 Befunden in 0.8a–0.8c geteilt.
- Fehlerbehebung: Das Speichern eines Themas ohne Konfigurationsdienst endete über einen
  abgefangenen `AttributeError` mit 422; es meldet jetzt wie die Themenseite 503
  „Themenverwaltung nicht verfügbar“.

## 3.6.6 – Strikte Typprüfung der Web-Seiten (Planung 3.6, Schritt 0.7)

- `mailhelp.web.pages`, `forms` und alle `*_pages`-Module stehen unter der strikten
  mypy-Prüfung (vollständige Annotationen, parametrisierte Containertypen, keine
  untypisierten Aufrufe). Dafür wurden 32 Typangaben ergänzt; keine Verhaltensänderung.

## 3.6.5 – Nachweis der Entkopplung (Planung 3.6, Schritt 0.6, Tests)

- Neue Tests belegen ohne `sleep()`: Eine im Browser bestätigte Aktion wird ausgeführt und
  genau einmal angelegt, während der Hauptthread mitten in einer Mailanalyse festgehalten
  wird; eine währenddessen gespeicherte Themenänderung wirkt erst beim nächsten Zyklus.
  Die Messung der Antwortzeiten im laufenden Betrieb steht noch aus.

## 3.6.4 – Web-Aktionen warten nicht mehr auf den Mailabruf (Planung 3.6, Schritt 0.5)

- Telegram-Eingaben und Web-Aktionen verarbeitet ein eigener Bedien-Thread sofort bei
  Eingang. Bisher liefen sie erst nach dem kompletten Abrufstapel mit allen KI-Analysen
  (bis zu 25 Mails); der Hauptthread verarbeitet jetzt nur noch Mails.
- Der Telegram-Dialog ist durch eine Sperre serialisiert. Geänderte Live-Einstellungen
  und Themen übernimmt der Hauptthread am Beginn seines nächsten Zyklus, nie während einer
  Mailverarbeitung. Bei einer offenen Relevanzfrage wartet die Mailverarbeitung auf die
  Entscheidung des Bedien-Threads.
- Details und Prüfliste der Schreibpfade: `docs/Entkopplung-Web-und-Abruf.md`.

## 3.6.3 – Analyse zur Entkopplung von Bedienung und Mailabruf (Planung 3.6, Schritt 0.4)

- `docs/Entkopplung-Web-und-Abruf.md` beschreibt, wo Web-Befehle heute auf den Mailabruf
  warten, welche Ressourcen Hauptthread und künftiger Bedien-Thread teilen, welche Sperren
  in welcher Reihenfolge nötig sind und wie Schritt 0.5 umgesetzt und in 0.6 nachgewiesen
  wird. Keine Verhaltensänderung.

## 3.6.2 – „Erneut prüfen“ in der Weboberfläche (Planung 3.6, Schritt 0.3)

- Als irrelevant aussortierte Mails zeigen im Maildetail und in der Archivliste die
  Schaltfläche „Erneut prüfen“. Die Mail wird dann beim nächsten Abruf mit den aktuellen
  Themen neu analysiert, etwa nachdem ein passendes Thema angelegt wurde.
- Die Aktion prüft Sitzung, CSRF-Token, Idempotenzschlüssel und die angezeigte
  Analyserunde (neues Feld `analysis_round` im Mailzustand, ältere Zustände bleiben gültig)
  vor dem Einreihen und erneut bei der Ausführung. Der Verlauf verzeichnet jede
  Neuprüfung; ein durch Neustart unterbrochener Befehl wird anhand der Analyserunde
  abgeglichen und nie doppelt ausgeführt.

## 3.6.1 – Erneute Prüfung aussortierter Mails: Grundlage (Planung 3.6, Schritt 0.2)

- Eine als irrelevant abgeschlossene Mail kann bewusst erneut geprüft werden. Ihr Zustand
  wird dauerhaft auf eine unverarbeitete Mail der aktuellen Konfiguration zurückgesetzt;
  die reguläre Wiederaufnahme holt sie erneut vom Server und analysiert sie vollständig,
  auch wenn die Aufbewahrung Inhalt und Relevanzergebnis bereits entfernt hat.
  Wiederholte Anforderungen sind wirkungslos. Die Bedienung in der Weboberfläche folgt
  in Schritt 0.3.

## 3.6.0 – Klare Meldung bei fehlender Konfiguration (Planung 3.6, Schritt 0.1)

- Fehlerbehebung: Ohne `config.yaml` brach Mailhelp mit `FileNotFoundError` und Traceback
  ab. Fehlt `config.yaml` oder `prompts.yaml`, nennt Mailhelp jetzt die Datei, verweist auf
  `config.example.yaml` und `--config-directory` und endet mit Exitcode 2. Ein
  Regressionstest deckt das ab.

## 3.5.10 – Planung in 3.6, 3.7 und 4.0 aufgeteilt

- Die Planung bis 4.0 ist in drei Teilpläne aufgeteilt: `docs/Planung-3.6.md`
  (Vorarbeiten, Testgrundlage, Parallelbedienung und Prozessabbrüche; 31 Schritte),
  `docs/Planung-3.7.md` (Ersteinrichtung und OAuth im Browser; 18 Schritte) und
  `docs/Planung-4.0.md` (Zielbild, Gesamtfahrplan, Lernmodus, Neuladen, Anbietermatrix und
  Release; 28 Schritte). Schrittnummern bleiben über alle Pläne eindeutig. Keine
  Verhaltensänderung.

## 3.5.9 – Planung 4.0 auf Stand gebracht

- `docs/Planung-4.0.md` beschreibt den Ausgangsstand 3.5.8 je Pfeiler, führt die seit 3.4
  vorhandene Zugangsdatenverwaltung als weitgehend umgesetzt und ersetzt die sechs Phasen
  durch 77 einzeln lieferbare Schritte (S ≤ 1 Tag, M ≤ 2 Tage) in neun Stufen, von den
  Vorarbeiten in 3.6.x bis zum Release. Offene Entscheidungen zum Schutz des Erststarts und
  zum Google-OAuth-Client sind markiert. Keine Verhaltensänderung.

## 3.5.8 – Keine falschen ausstehenden Änderungen

- Fehlerbehebung: Die Einstellungsübersicht zeigte zahlreiche „Änderungen ausstehend“
  (z. B. 8 bei Mailabruf, 15 bei KI und Auswertung), obwohl nichts geändert war. Gezählt
  wurden Einstellungen, die in `config.yaml` fehlen und deshalb mit ihrem Standardwert
  aktiv sind; die Detailseiten nannten sie „Gespeichert: nicht gesetzt · wirkt erst nach
  einem Neustart“. Verglichen wird jetzt mit den Werten, die der nächste Start anwenden
  würde. Eine ungültige `config.yaml` zeigt weiterhin ihre wörtlichen Werte. Ein
  Regressionstest deckt das ab.

## 3.5.7 – Neustart unter Windows

- Fehlerbehebung: „Mailhelp neu starten“ scheiterte unter Windows mit
  `SyntaxError: invalid syntax`, und Mailhelp blieb beendet. `os.execv` setzt unter
  Windows die Argumente ohne Anführungszeichen zusammen, sodass vom Startcode nur
  `from` ankam; zudem verlor der neue Prozess die Konsole. Unter Windows startet der
  ursprüngliche Prozess Mailhelp jetzt als Kindprozess neu und bleibt im Terminal;
  Linux/Docker ersetzt den Prozess weiterhin mit `os.execv`. Ein Regressionstest deckt
  das ab.

## 3.5.6 – Ordnerliste der Postfächer

- Beim ersten Abruf nach jedem Start ruft Mailhelp die Ordnerliste jedes Postfachs ab und
  speichert sie in `mailbox-folders.json`: Name, Rolle (z. B. Spam-Ordner `junk`),
  Flags, ob der Ordner abgerufen wird, und konfigurierte, auf dem Server fehlende Ordner.
  Das Log meldet `folders_listed` je Postfach. Ein Fehlschlag wird einmal als
  `folder_list_failed` gemeldet und beim nächsten Abruf wiederholt; der Mailabruf läuft
  unabhängig davon weiter.

## 3.5.5 – Schnellere Weboberfläche

- Fehlerbehebung: Die Aufbewahrungsbereinigung schrieb bei jedem Abrufzyklus alle bereits
  entfernten Analysen neu (rund 580 Dateien mit `fsync`). Sie blockierte den
  Verarbeitungs-Thread mehrere Sekunden und machte den Archivindex jedes Mal ungültig.
  Bereits entfernte Inhalte werden nicht mehr geschrieben; ein Regressionstest deckt das ab.
- Neue Einstellung `retention.cleanup_interval_minutes` (Standard 60, 0 = jeder Zyklus):
  Die Bereinigung läuft beim Start und danach in diesem Abstand. Web-Aktionen warten
  dadurch nicht mehr bei jedem Zyklus mehrere Sekunden.
- Die Übersicht offener Entscheidungen wird zwischengespeichert und nur nach einer
  Zustandsänderung, Einstellungsübernahme, Änderung des Datenverzeichnisses oder nach
  höchstens 60 Sekunden neu aufgebaut (gemessen: 2 ms statt 0,3–2 s).
- Die Vorschlagsseite liest den Verlauf nur der eigenen Mail statt den gesamten Archivindex
  (gemessen: ca. 10 ms statt bis zu 3 s). Der Archivindex normalisiert Texte schneller.
- Ohne gewählten Anhangsfilter liest die Übersicht die Mails der Karten nicht mehr einzeln.

## 3.5.4 – Dublettenprüfung in der Weboberfläche wiederholen

- Fehlerbehebung: War die Dublettenprüfung eines Vorschlags fehlgeschlagen (z. B. wegen
  einer abgelaufenen Google-Anmeldung), bot die Weboberfläche nur Antworten und Verwerfen an;
  die Neuprüfung war allein unter „Vorschlagsabgleich“ erreichbar. Vorschlagskarte und
  Detailseite zeigen jetzt „Dublettenprüfung wiederholen“. Eine erfolgreiche Prüfung erzeugt
  eine neue, separat zu bestätigende Version; ein Regressionstest deckt den Ablauf ab.

## 3.5.3 – Lernbestand manueller Entscheidungen

- Jede manuelle Entscheidung aus Web oder Telegram (Bestätigen, Verwerfen, Klären,
  Antworten, Bearbeiten, Zusammenführen, Relevanz – auch als Telegram-Freitext) wird als
  ein Datensatz in `data/<Betriebsart>/learning/decisions.jsonl` abgelegt: Mailkopf und
  -inhalt, KI-Ergebnisse mit Aufruf-IDs, erster und entschiedener Vorschlag mit
  Feldänderungen, aktuelles Ergebnis sowie Entscheidung, Quelle und Antworttext.
  Wiederholte oder nach einem Neustart abgeglichene Entscheidungen erscheinen nur einmal.
- Neue Einstellung `retention.decision_learning_days` (Standard `unlimited`; Zahl in Tagen
  oder `disabled`). `learning.decision_llm_content: true` übernimmt zusätzlich vollständige
  KI-Anfragen und -Antworten aus dem KI-Protokoll (Standard `false`).
- Ein Fehler beim Aufzeichnen hält die Entscheidung nicht auf. Die neuen Einstellungen
  ändern den Konfigurationsfingerabdruck nicht; laufende Vorgänge werden nicht neu analysiert.
- Spezifikation, Datenschutzhinweise, README und Beispielkonfiguration aktualisiert.

## 3.5.2 – Weboberfläche mit zusammengeführten Vorschlägen

- Fehlerbehebung: Sobald ein zusammengeführter Vorschlag (Status `merged`) unter „Zuletzt
  erledigt“ stand, endete der Aufruf der Weboberfläche mit „Interner Fehler.“ (HTTP 500,
  `request_failed` / `KeyError`). Für diesen Status fehlte die Badge-Zuordnung. Er wird jetzt
  als „Zusammengeführt“ angezeigt; ein Regressionstest deckt Übersicht und Vorschlagskarte ab.
- `request_failed` der Weboberfläche protokolliert zusätzlich den Pfad (ohne Query-String).

## 3.5.1 – Betriebsproblem-Benachrichtigungen bei fehlgeschlagenen Mails

- Fehlerbehebung: Sobald eine Mail mit einem Verarbeitungsfehler endete (z. B. abgelehnter
  OpenRouter-Schlüssel), brach jeder Benachrichtigungsdurchlauf mit
  `notifications_failed` / `ValidationError` ab. Die Zustellreferenz wurde aus den deutschen
  Anzeigetexten („Zusammenfassung:Dienst lehnt dauerhaft ab“) gebildet und verletzte das
  Referenzformat. Dadurch blieben Betriebsproblem-Meldungen, Dienstfehler und der
  Tagesüberblick aus. Die Referenz verwendet jetzt Verarbeitungsschritt und Fehlercode
  (`<mail_id>:summary:permanent_adapter_error`); ein Regressionstest deckt den Fall ab.

## 3.5.0 – Einstellungsbereiche und Postfächer im Betrieb aktivieren

- Einstellungen zeigen eine Kachelübersicht mit Kontenzahlen, thematischen Bereichen,
  Suchfunktion und Hinweisen auf gespeicherte, noch nicht aktive Änderungen.
  Zugangsdaten, KI-Modelle und Push-Steuerung stehen im jeweiligen Bereich.
- Neue IMAP-Postfächer in einem Formular prüfen und aktivieren: Server, Verbindungsart,
  Anmeldung, Quell- und Entwurfsordner sowie Startgrenze. Erst nach erfolgreicher lesender
  Prüfung werden Konfiguration und Zugangsdaten gespeichert. Der Abruf beginnt im nächsten
  sicheren Mailzyklus ohne Neustart; bestehende Reader und ihre Fortschritte bleiben erhalten.
- Sitzungen werden vor Ausführung und Schreiben erneut geprüft; CSRF, Entwurfs- und
  Dateiversionen sowie Idempotenz sichern den Ablauf. Unterbrochene Schreibvorgänge erfordern
  die Prüfung des gespeicherten Stands. Andere Entwürfe bleiben erhalten.
- Doppelte Konten werden auch bei deaktivierten Postfächern zurückgewiesen.
  Fehler zeigen sichere Meldungen, erhalten die übrigen Eingaben und leeren das Passwortfeld.
- Anleitung, Konfigurationsbeispiel und Paketinhalt aktualisiert:
  [Planung 3.5](docs/Planung-3.5.md), [Betriebsanleitung 3.5](docs/Release-3.5.md).

## 3.4.7 – IServ gemeinsam prüfen und aktivieren

- Auf der IServ-Seite Schuladresse, Startgrenze, Postfach und Zugangsdaten gemeinsam
  eingeben und mit „Verbindung prüfen und Konto aktivieren“ übernehmen. Bereits hinterlegte
  Zugangsdaten können verwendet werden. Fehler bleiben direkt auf der Seite sichtbar.
- Nach erfolgreicher Prüfung wird nur das ausgewählte Konto aktiviert; andere Entwürfe
  bleiben erhalten. Neue Adapter werden im nächsten sicheren Mailzyklus geladen und alte
  Verbindungen geschlossen. Kein manueller Neustart und keine separate Diagnose nötig.
- Aktivierung prüft Sitzung, CSRF, Entwurfs- und Dateiversionen sowie Idempotenz; Zugangsdaten
  bleiben außerhalb von Konfiguration und Journal. Kalender- und Aufgabenfreigaben bleiben separat.

## Noch nicht veröffentlicht – Neustart über die Weboberfläche

- Neben „Mailhelp beenden“ steht „Mailhelp neu starten“ mit eigener Bestätigungsseite.
  Sitzung, CSRF, aktuelle Prozesskennung und aktionsgebundener Idempotenzschlüssel werden geprüft;
  die Sitzung wird nach Auslieferung der Antwort nochmals geprüft.
- Nach kontrolliertem Stopp und Freigabe aller Ressourcen ersetzt sich Mailhelp durch
  denselben Python-Interpreter mit denselben Startoptionen. Code, Konfiguration und
  Zugangsdaten werden unter Windows und Docker neu geladen; offene Vorgänge bleiben erhalten.
- Doppelte Anforderungen lösen keinen zweiten Stopp oder Neustart aus. Veraltete
  Rückrufe können keine zwischenzeitlich neu erteilte Anforderung ausführen.

## Noch nicht veröffentlicht – Große Anhänge manuell prüfen

- Textextraktion und OCR sind standardmäßig auf 5.000.000 Bytes je Anhang begrenzt.
  `limits.max_attachment_bytes` ist unabhängig von der Textgröße der Nachricht.
- Nachrichten mit größeren Anhängen erhalten zuverlässig einen lokalen Vorschlag
  „Nachricht manuell prüfen“, unabhängig von Relevanz und KI-Verfügbarkeit. Wiederholungen
  und Neustarts erzeugen keine weiteren Einträge; externe Aufgaben bleiben bestätigungspflichtig.
- IServ lädt größere Anhänge nur bis zur Erkennung der Überschreitung und verarbeitet
  anschließend die übrigen Elternbriefe weiter. Große Anhänge unterbrechen den Abruf nicht mehr.

## 3.4.6 – Interaktive Diagramme in der Auswertung

- Ein Klick auf ein Diagramm oder „Vergrößern“ öffnet die große Dialogansicht. Auf kleinen
  Bildschirmen lässt sich das vergrößerte Diagramm innerhalb des Dialogs horizontal verschieben.
- Balkendetails erscheinen sofort beim Darüberfahren, bei Tastaturfokus oder beim Antippen:
  Zeitraum bzw. Kategorie, Datenreihe und formatierter Wert mit Einheit.
- Escape und „Schließen“ schließen den Dialog und geben den Fokus zurück. Tabellen und
  SVG-Beschreibungen bleiben ohne JavaScript nutzbar; Inhalte werden nur als Text übernommen.
- Python- und Browserfälle prüfen Daten-Escaping, beide Balkenarten, Maus, Tastatur, Touch,
  Fokuswiederherstellung, eindeutige SVG-IDs, helle/dunkle Ansicht und den Betrieb ohne Skripte.

## 3.4.5 – Diagrammfarben und Stylesheet-Cache der Weboberfläche

- Fehler behoben: In der Auswertung hatten die Balken für erfolgreiche und fehlgeschlagene
  Aufrufe dieselbe schwarze Farbe, die Diagramme erschienen ohne Formatierung. Ursache war der
  Service Worker: Sein Cache-Name blieb seit 3.3.2 gleich, daher lieferte er nach Updates weiter
  das alte Stylesheet ohne Diagrammregeln. Der Cache-Name enthält jetzt einen Hash der
  zwischengespeicherten Dateien und erneuert sich mit jeder Änderung.
- Diagrammbalken, Legende und Achsen tragen zusätzlich eigene Farben und Schriftgröße als
  Rückfall; das Design (hell und dunkel) hat weiterhin Vorrang.
- Regressionstests für Cache-Erneuerung und Balkenfarben; der PWA-Browsertest prüft den
  versionierten Cache-Namen.

## 3.4.4 – Gemeinsamer Stand von Kontenstatus und IServ-Korrekturen

- Die vollständige Kontenübersicht der Statusseite mit den IServ- und Dokumentationsänderungen
  aus beta zusammengeführt. Beide Regressionstestgruppen bleiben erhalten.
- Eine gemeinsame Datumsumwandlung unterstützt `TT.MM.JJJJ [HH:MM]`, `JJJJ-MM-TT` und
  ISO-8601-Zeitpunkte mit Offset. Kopierte IServ-Links und Schuladressen ohne Schema werden
  normalisiert; ungültige Eingaben zeigen weiterhin eine verständliche Ursache im Formular.
- Versionskonflikte werden vor dem erneuten Rendern eines veralteten Entwurfs abgefangen:
  Eine inzwischen geänderte Konfiguration führt zu HTTP 409 und lässt Dateien sowie Entwurf
  unverändert. Ein Regressionstest reproduziert den zuvor erneut ausgelösten Fehler.

## 3.4.3 – Vollständige Kontenübersicht auf der Statusseite

- Die Statusseite zeigt alle konfigurierten IMAP- und IServ-Konten, Kalender und Aufgaben
  je Zielprofil sowie Telegram auch vor dem ersten erfolgreichen Kontakt an.
- Erfolg und Fehler werden je Konto getrennt erfasst; deaktivierte Konten, ungenutzte
  Zielprofile und übernommene Änderungen mit ausstehendem Neustart sind gekennzeichnet.
  Unbestätigte Entwürfe bleiben ausgeschlossen. Der Seitenaufruf prüft keine externen Dienste.
- Konten- und Statuswechsel aktualisieren die Seite, wiederholte erfolgreiche Abrufe allein
  lösen keinen ständigen Neuaufbau aus. Regressionstests prüfen Isolation, Wiederholung,
  Neustart, Fehlerbehebung, HTML-Escaping und die Ansicht in drei Browsergrößen.

## 3.4.3 – beta: Zusammenführung von beta 3.4.2 mit main 3.4.1

- Die Dokumentationsergänzung (beta 3.4.1) und die Korrektur beim Anlegen von IServ-Konten
  (beta 3.4.2) mit den lokalen Web-Korrekturen von main 3.4.1 zusammengeführt: Rückgängig-Sperre
  der Auswahl, Bereich „Zugangsdaten“ in den Einstellungen und die gemeinsame Speicherroute, die
  beide Zugangsdatenformulare unterstützt.
- Die Versionsnummer 3.4.1 wurde auf beiden Zweigen unabhängig vergeben; die beiden Abschnitte
  sind unten als „beta“ und „main“ gekennzeichnet.

## 3.4.2 – main: Datumsangaben für IServ-Konten im Web

- Fehler beim Anlegen und Ändern eines IServ-Kontos mit einer Startgrenze wie
  `01.09.2026` behoben: Das Webformular akzeptiert `TT.MM.JJJJ` und `JJJJ-MM-TT`
  und speichert den Tagesbeginn mit dem Offset der konfigurierten Zeitzone.
  ISO-8601-Zeitpunkte mit explizitem Offset und die leere Postfach-Vererbung bleiben gültig.
- Feldbeschriftung und Hilfe erklären die Eingaben. Regressionstests prüfen Datumsformate,
  Sommer-/Winterzeit, andere Zeitzonen, ungültige Daten, Neustart, Wiederholung,
  Sitzung, CSRF, Version und ausdrückliche Übernahme; der Browsertest füllt die Startgrenze aus.

## 3.4.2 – beta: IServ-Konto anlegen mit kopiertem Link und deutschem Datum

- Fehler behoben: Das Anlegen eines IServ-Kontos scheiterte mit „Entwurf nicht gespeichert;
  Angaben, Version und Sitzung prüfen.“, wenn die Adresse als kopierter IServ-Link (mit Pfad),
  ohne `https://` oder die Startgrenze als `01.10.2026` eingegeben wurde. Die Adresse wird jetzt
  auf die Schuladresse gekürzt, die Startgrenze nimmt `TT.MM.JJJJ [HH:MM]` in der konfigurierten
  Zeitzone an. `http://` und Adressen mit Zugangsdaten bleiben abgelehnt.
- Ungültige Eingaben zeigt die Seite jetzt mit ihrer Ursache an (z. B. „IServ-Adresse: …“ oder
  „Startgrenze: …“) statt der allgemeinen Meldung.
- Regressionstests einschließlich eines Browsertests für Desktop, Telefon und schmale Ansicht.

## 3.4.1 – beta: Dokumentation für IServ, Zugangsdaten und Einstellungen vervollständigt

- Neue [Release-Anleitung 3.4](docs/Release-3.4.md) mit Einrichtung der IServ-Elternbriefe über
  die Weboberfläche und über Dateien, der Zugangsdatenseite, den neuen Einstellungen und den
  Änderungen seit 3.3.2; im Quellarchiv enthalten und in der README verlinkt.
- Einrichtungsanleitung um einen Abschnitt zu IServ-Elternbriefen und die Zugangsdaten im Web
  ergänzt; Web-Einstellungen beschreiben die Seiten IServ-Konten und Zugangsdaten.
- Hilfetext zum Kalenderdienst nennt die Zugangsdatenseite; Planung 4.0 vermerkt die vorgezogene
  Zugangsdatenverwaltung.
- Projektwebsite: IServ-Elternbriefe, Zugangsdaten im Web und weitere Einstellungen auf Start-,
  Einrichtungs-, Konfigurations- und Datenschutzseite.

## 3.4.1 – main: Zusammenführung der lokalen Änderungen mit 3.4.0

- Lokale Korrekturen und den Stand 3.4.0 zusammengeführt; IServ-Elternbriefe,
  Web-Einstellungen und Auswertungsdiagramme bleiben erhalten.
- Die gemeinsame Speicherroute für Zugangsdaten ist eindeutig registriert und
  unterstützt beide Formulararten samt ihrer Bestätigungs- und Versionsprüfungen.
  Die vollständige Kontenübersicht für IServ und neue Konten ist im Bereich verlinkt.
- Prüfung unter WSL: 2532 Python-Tests mit 100 % Zeilen- und Branch-Abdeckung,
  180 Browsertests mit 100 % JavaScript-Blockabdeckung, Ruff und Mypy ohne Befund
  sowie Paketbau und zwei Smoke-Tests des installierten Wheels.

- Eigener Bereich „Zugangsdaten“ in den Einstellungen mit direkter Bearbeitung
  für Postfächer, OpenRouter, Telegram und die eingerichteten Zielprofile.
  Bestehende Werte bleiben verborgen; ein neuer Wert ersetzt nur den gewählten
  Schlüssel in `.env`. Prozessvariablen behalten Vorrang, Änderungen wirken nach Neustart.
- Sitzungs- und CSRF-Prüfung, Versionsabgleich und wiederaufnehmbare,
  idempotente Speichervorgänge. Geheimnisse gelangen weder in die Befehlswarteschlange
  noch in HTML, Logs oder JSON-Belege. Tests verwenden ausschließlich synthetische Werte.

- Während der Rückgängig-Frist von Bestätigen und Verwerfen bleibt die Auswahl
  auch bei Mausklicks gesperrt. Das ursprüngliche Formular bleibt erhalten und
  wird genau einmal gesendet, statt dauerhaft „wird verworfen …“ anzuzeigen.
- Browser-Regressionstests prüfen Bestätigen, Verwerfen, die unveränderte
  Vorschlagszuordnung und die Freigabe der Auswahl nach Rückgängig, ohne dabei
  einen Befehl zu senden. Sie reproduzieren den Fehler vor der Korrektur.

## 3.4.0 – beta: Quellen, Zugangsdaten und Einstellungen im Web (Planung 3.4)

Abschluss von Planung 3.4 (Phasen 1–3 in 3.3.10–3.3.12):

- Postfächer und IServ-Konten lassen sich vollständig über die Weboberfläche anlegen,
  ändern, deaktivieren und entfernen – als geprüfter Entwurf mit Diagnose und ausdrücklicher
  Übernahme.
- Zugangsdaten werden unter Einstellungen → Zugangsdaten nur schreibend gepflegt; gespeicherte
  Werte erscheinen nie in der Oberfläche oder in Protokollen.
- Alle für den Betrieb relevanten Einstellungen sind im Web änderbar; ausgenommen bleiben nur
  Werte, deren Fehlbedienung den Zugang zur Weboberfläche oder die Datenablage gefährdet.
- Gesamtabnahme: 2478 Tests mit 100 % Abdeckung, 167 Browsertests, ruff und mypy ohne Befund.

## 3.3.12 – beta: Weitere Einstellungen in der Weboberfläche (Planung 3.4, Phase 3)

- Unter Einstellungen sind 29 weitere Werte änderbar, jeweils mit Hilfetext: Stapelgröße und
  Reihenfolge des Mailabrufs, Telegram-Benutzer, -Chat und Fragen nacheinander, Antwortentwürfe,
  Bildauswertung, Inhalte des Tagesüberblicks, Tätigkeitsberichte, parallele Aufrufe im
  Lernmodus, Aufbewahrung von Tätigkeitsberichten, Sitzungsdauer, Zugriff im eigenen Netzwerk
  sowie Schalter und Stufen der Protokollierung.
- Die Einrichtung bietet je Postfach die Startgrenze `historical_start` an.
- Bewusst weiterhin nur in `config.yaml`: Datenverzeichnis, Logpfade, Adresse, Port und
  zugelassene Hostnamen der Weboberfläche sowie die Parser-Sicherheitsgrenzen.

## 3.3.11 – beta: Zugangsdaten in der Weboberfläche (Planung 3.4, Phase 2)

- Neu: Einstellungen → Zugangsdaten (`/einstellungen/zugangsdaten`) listet alle Zugangsdaten,
  die die Konfiguration benötigt – je Postfach, je IServ-Konto, OpenRouter, Telegram und die
  Zielanbieter je Zielprofil – und erlaubt, sie einzutragen oder zu ersetzen.
- Nur schreibend: gespeicherte Werte werden nie angezeigt. Speichern braucht eine gültige,
  vor dem Schreiben erneut geprüfte Sitzung, CSRF-Schutz, Idempotenzschlüssel, ausdrückliche
  Bestätigung und den unveränderten Stand von `.env`; nur die betroffene Zeile wird ersetzt.
- Protokolle nennen nur den Namen; neue Werte werden sofort maskiert. `MAILHELP_WEB_SECRET`
  bleibt ausgenommen, weil eine Änderung alle Sitzungen beenden würde.

## 3.3.10 – beta: IServ-Konten in der Weboberfläche (Planung 3.4, Phase 1)

- Neu: Unter Einstellungen → IServ-Konten (`/einstellungen/iserv`) lassen sich IServ-Konten
  hinzufügen, ändern, aktivieren, deaktivieren und entfernen. Jede Änderung ist ein Entwurf,
  der geprüft und erst nach aktueller Diagnose und ausdrücklicher Übernahme in `config.yaml`
  geschrieben wird.
- Fehler behoben: Nach dem Übernehmen eines Einrichtungsentwurfs (etwa eines neuen Postfachs)
  blieb der Entwurf auf dem alten Dateistand stehen; die Postfachseite brach danach ab und
  weitere Änderungen waren blockiert. Übernommene Entwürfe werden jetzt geleert.
- Neue Planung 3.4: Quellen, Zugangsdaten und Einstellungen vollständig im Web.

## 3.3.9 – beta: Diagramme in der Auswertung

- Die Auswertungsseite zeigt für die gewählten Filter Diagramme: KI-Aufrufe je Tag
  (erfolgreich und fehlgeschlagen), gemeldete Cloudkosten je Tag, die Verteilung der
  Aufrufdauer, die summierte Dauer je Verarbeitungsschritt und die Kosten je Modell.
  Bei „Heute“ gilt die Einteilung je Stunde in der konfigurierten Zeitzone.
- Die Diagramme sind serverseitiges SVG ohne Skripte, passen sich hellem und dunklem
  Design an und bieten ihre Werte zusätzlich als aufklappbare Tabelle für Screenreader.

## 3.3.8 – beta: IServ in Einrichtung und Diagnose

- Fehler behoben: Die Zugangsdatenübersicht der Einrichtung nannte die IServ-Zugangsdaten
  nicht. Sie zeigt jetzt je aktivem IServ-Konto `ISERV_<id>_USERNAME/ISERV_<id>_PASSWORD`
  als vorhanden oder fehlend; neu in `.env` eingetragene Werte erscheinen ohne Neustart.
- Die Diagnose hat eine eigene IServ-Prüfung: Anmeldung und Öffnen der Briefübersicht,
  ohne Briefe zu lesen. Eine abgelehnte Anmeldung wird als Zugangsdatenproblem gemeldet.

## 3.3.7 – beta: IServ-Elternbriefe als Quelle

- Neu: Elternbriefe aus dem IServ-Elternbriefmodul werden wie Mails verarbeitet.
  Mailhelp meldet sich mit dem Elternkonto an der IServ-Weboberfläche an, liest neue
  Briefe samt Anhängen und behandelt sie immer als relevant, ohne Modellaufruf und
  ohne Absenderfilter. Zielprofil und Standards folgen dem angegebenen Postfach.
- Konfiguration unter `iserv.accounts`, Zugangsdaten als `ISERV_<id>_USERNAME` und
  `ISERV_<id>_PASSWORD`; der Abschnitt ändert den Analyse-Fingerprint nicht.
- Abruf nur innerhalb der HTTPS-Adresse der Schule, Größengrenzen wie bei Mails,
  keine URLs oder Zugangsdaten in Logs. Unvollständige Briefe werden nach Fehlern
  wiederaufgenommen; Statusseite, `--check-access` und Startprüfung kennen IServ.
- Für Elternbriefe gibt es keine Antwortentwürfe; Mailhelp verändert in IServ nichts.
  Zwei-Faktor-Anmeldung und mehrseitige Übersichten werden noch nicht unterstützt.

## 3.3.6 – beta: Weboberfläche bleibt nach einem Code-Wechsel konsistent

- Fehler behoben: Der Webserver las Stylesheet, Skript, Service Worker und Offline-Seite
  bei jeder Anfrage von der Platte. Wechselte bei laufendem Dienst der Codestand im
  Installationsverzeichnis (Update, Branch-Wechsel einer editierbaren Installation),
  kombinierte ein Neuladen neue Seiten mit altem CSS, und das Layout zerfiel.
  Diese Dateien werden jetzt einmal beim Start geladen und passen bis zum Neustart
  zur laufenden Version.

## 3.3.5 – beta: Verständliche Meldung bei bereits laufender Instanz

- Fehler behoben: Ein zweiter Start mit demselben Datenverzeichnis endete mit einem
  Python-Traceback. Mailhelp meldet jetzt in einer klaren Zeile, dass bereits eine
  Instanz läuft, nennt das Verzeichnis und erklärt, wie die laufende Instanz beendet
  wird; der Exit-Code ist 1. Die Sperre selbst ist unverändert.

## 3.3.4 – beta: IMAP-Abruffehler und sichere UID-Grenzen

- Aktuelle Fehler beim Lesen eines Haupt- oder zusätzlichen Ordners erscheinen auf
  der Statusseite, auch wenn der Durchlauf keine Mail für die Analyse laden konnte.
  Hinweise bleiben je Postfach und Ordner erhalten, bis dieser wieder erfolgreich
  gelesen wird. Provider-Fehlertexte und Zugangsdaten werden nicht im Web angezeigt.
- Regressionstests für leere Durchläufe mit Ordnerfehlern, Status-Aktualisierung,
  erneute Fehler, isolierte Postfächer, erfolgreiche Wiederholung und sichere Darstellung.
- Lokale Ordnernamen und der Entwurfsordner anhand der lesenden IMAP-Liste korrigiert;
  Anleitung und Beispiel weisen auf anbieterspezifische Namen hin.
- Absturz bei Checkpoints behoben: Die IMAP-Suche kann bei `UID Start+1:*` die
  höchste vorhandene UID erneut liefern. Treffer an oder unter der gespeicherten
  Startgrenze werden vor dem Abruf ausgeschlossen. Der Abschluss alter
  Warteschlangeneinträge und separater Wiederaufnahmen verändert diese Grenze nicht.
  Regressionstests prüfen Wiederholungen, neue Mails und dauerhaft lesbare
  Checkpoints nach Neustarts.

## 3.3.3 – beta: Dienststatus sofort nach dem Start

- Fehler behoben: Ein Mailabruf ohne neue Mail ließ das IMAP-Postfach auf der Statusseite
  „unbekannt“, weil der Abruf seit 3.1 über `discover_since` läuft und dessen Ereignis nicht
  als Kontakt zählte. Ebenso zählt jede erfolgreiche Telegram-Abfrage, auch ohne Nachricht.
- Beim Dienststart prüft Mailhelp im Hintergrund lesend OpenRouter bzw. Ollama, Telegram
  (ohne Testnachricht) und die Ziele der aktiven Zielprofile. Die Statusseite zeigt diese
  Dienste damit sofort als erreichbar; die Mailverarbeitung wartet nicht auf die Prüfung.
  Fehlschläge werden nur als Warnung protokolliert.

## 3.3.2 – beta: Dokumentation geprüft und aktualisiert

- README, Changelog, Projektspezifikation, Einrichtungsanleitung, Datenschutzerklärung,
  Nutzungsbedingungen und Projektwebsite auf den Stand 3.3 gebracht: optionale
  Telegram-Nutzung, lokale Webkopplung, mehrere Postfächer und Zielprofile,
  Google-Desktop-OAuth mit Profilnummer, aktivierte Inhaltslogs im Beispiel.
- Neue [Release-Anleitung 3.3](docs/Release-3.3.md) (im Quellarchiv enthalten) und
  [Prüfbericht zur Dokumentation](docs/Pruefung-Dokumentation.md).
- 35 ältere Pläne, Konzepte und Release-Dokumente sind als historisch gekennzeichnet;
  Planung 3.3 trennt umgesetzte Phasen von offenen Architekturzielen.
- Keine Änderung am Anwendungsverhalten.

## 3.3.1 – beta: Entwicklungsregel für README-Aktualisierung

- Entwicklungsregeln in `AGENTS.md` um die Vorgabe ergänzt, bei jeder neuen Version auch die Datei `README.md` zu aktualisieren.
- Weboberfläche mit gruppierter Desktop-Seitenleiste, kompakter Handy-Navigation,
  klarerer Seitenhierarchie, aufklappbaren Vorschlagsbelegen und Einstellungs-Bereichslinks.
  Der Shell-Cache wird beim Update erneuert. Das Facelift wurde zunächst als 3.3.2
  committet; der folgende Versionskorrektur-Commit führt denselben Funktionsstand als 3.3.1.

## 3.3.0 – beta: Technische Konsolidierung (Planung 3.3)

Abschluss von Planung 3.3 (Phasen 1–4 in 3.2.4–3.2.7). Verhalten, CLI, Telegram-Befehle und Web-Routen sind unverändert.

- Strikte Typprüfung zusätzlich für Persistenz, Normalisierung, Zusammenführung, Vorprüfung, Evaluation,
  Konfiguration, Laufschleife, Dienstkoordination, Telegram und Review; `mailhelp.telegram` exportiert eine
  ausdrückliche Namensliste.
- `writer_for`, `retarget`, `profile_references` und `TelegramCommands` sind vollständig annotiert. Die Abbruchlogik
  liest die Dialogreferenz über `TelegramDialogState.reference()`.
- Gesamtabnahme: 2360 Tests mit 100 % Zeilen- und Branch-Abdeckung, 146 Browsertests, ruff und mypy ohne Befund.
- Noch offen sind die Strictness für `mailhelp.web.*` und die Bündelung der Wurzelmodule in Unterpakete
  (siehe Planung 3.3, Abschnitt 5).

## 3.2.7 – beta: Planung 3.3, Phase 4 – Parser und Konfiguration konsolidiert

- `config.py` ist das Paket `mailhelp.config`: Modelle und Validierungsregeln in `config/models.py`,
  Datei- und Umgebungszugriff in `config/loader.py`; alle bisherigen Namen bleiben über `mailhelp.config` importierbar.
- Deutsche Monats- und Wochentagsnamen, Jahreserkennung und Wochentagsprüfung liegen einmalig in
  `mailhelp.german_dates`; die Datumsnormalisierung nutzt sie mit unveränderten Mustern und ist in benannte
  Schritte zerlegt (numerisch, ausgeschrieben, ohne Jahr).
- Telegram-Receiver, Weboberfläche, Erlebnis- und Benachrichtigungslaufzeit starten und stoppen über den neuen
  `ServiceCoordinator`; `Application` führt `lifecycle`, `configuration` und `profile_writers` typisiert statt als `Any`/`object`.
- Verhalten unverändert; der Empfangsoffset wird weiterhin nur für Dialoge mit Telegram-Eingang gelesen (eigener Test).

## 3.2.6 – beta: Planung 3.3, Phase 3 – Weboberfläche entflochten

- `ArchiveSite` ist in fünf Seitenklassen zerlegt (Mailarchiv, Verlauf/Auswertung, Vorschlagsbearbeitung,
  Einstellungen/Themen, Beenden); der verbleibende Knoten hält nur noch gemeinsam genutzte Dienste.
- HTML-Erzeugung und Routing sind getrennt: `archive_pages`, `settings_pages`, `reconciliation_pages`,
  `sender_pages`; gemeinsame Formularbausteine (`post_form`, `field`, `select`) in `web/forms.py`.
- Routen, Seiten und Formulare unverändert; 146 Browsertests und 100 % JavaScript-Abdeckung bestätigt.

## 3.2.5 – beta: Planung 3.3, Phase 2 – Komplexitätsabbau

- Die verschachteltsten Funktionen sind in benannte Schritte zerlegt, ohne Verhaltensänderung:
  `merge_facts` (McCabe 29 → 6), `validate_consistency` (26 → 2, Prüfreihenfolge unverändert),
  Telegram-`overview` (21 → 8) und Schreib-`execute` (19 → 9), Vorschlagskarte (17 → 2),
  Metrikbeobachtung (17 → 2), IMAP-Ermittlung (17 → 3) und Abgleichvorschau (16 → 3).
- ruff prüft die McCabe-Komplexität dauerhaft (`C90`, höchstens 15 je Funktion).
- Zusätzlicher Test: unsichere Quellen behalten ihre offenen Zeitfragen.

## 3.2.4 – beta: Planung 3.3, Phase 1 – Typprüfung und Entkopplung von Telegram

- `mypy --check-untyped-defs` meldet keine Befunde mehr (vorher 18) und ist über `check_untyped_defs`
  dauerhaft Teil der CI-Typprüfung. Dafür u. a. ein `LlmCompleter`-Protokoll für die Evaluation und
  eindeutige Variablen in der Postfachseite.
- Die deterministische Zeitauflösung liegt als `mailhelp.temporal_answers` außerhalb des Telegram-Pakets;
  `analysis` und `mail_questions` importieren sie ohne späten Import. Die Revisionsfehler liegen in
  `mailhelp.domain.revision_errors`; der Importkreis Analyse ↔ Telegram ist aufgelöst.
- `ActionLedger` und `ProposalRepository` liegen in `mailhelp.persistence.ledger` bzw.
  `mailhelp.persistence.proposals`. Ein Architekturtest begrenzt Telegram-Importe außerhalb des Pakets auf
  Anwendung, Komposition, Orchestrator und Prüfdienst.
- Testsuite ohne Warnungen (Pydantic-Serialisierung, Assertion-Rewrite der gemeinsamen Fakes).
- Verhalten unverändert.

## 3.2.3 – beta: Planung 3.3 aktualisiert, Fehler in Antwortentwürfen behoben

- **Fehler behoben:** Ein Betreff mit Zeilenumbrüchen gelangte unverändert in die `Subject`-Kopfzeile
  eines Antwortentwurfs; mit `\r\n` scheiterte das Speichern. Der Betreff wird jetzt auf eine Zeile
  normalisiert (eingeschleuste Kopfzeilen bleiben ausgeschlossen). Eine Antwortadresse ohne Teil vor oder
  nach dem `@` (z. B. `@0`) wird abgelehnt statt als leerer Empfänger übernommen. Gefunden vom
  Eigenschaftstest `test_reply_drafts_never_carry_injected_headers`; Regressionstest
  `test_draft_subject_stays_one_line_and_recipients_need_both_address_parts` scheiterte vor der Korrektur.
- [Planung 3.3](docs/Planung-3.3.md) (technische Konsolidierung, Nachfolger der früheren Planung 2.5) mit
  gemessenen Ausgangswerten: 18 mypy-Befunde unter `--check-untyped-defs`, 8 Funktionen über
  McCabe-Komplexität 15. Planung 4.0 in das Repository aufgenommen.

## 3.2.2 – Überarbeitete README

- README als Produkt- und Betriebsdokumentation neu strukturiert: Funktionen, Installation,
  Konfiguration, Betrieb, Datenschutz und Qualitätssicherung übersichtlich zusammengefasst.
- Direkte Verweise auf Planungs- und Konzeptdokumente entfernt. Weiterführende Anleitungen
  sind nach Anliegen geordnet; Links und dokumentierte Schemaversion wurden geprüft.

## 3.2.1 – Einstellungen je Postfach

- Sparsame Postfachüberschreibungen mit globaler Vererbung für persönliche Angaben, Antwortentwürfe,
  Ruhezeiten/Kategoriekanäle, Tagesüberblick, Berichtsordner, kürzere Volltextaufbewahrung und Termindauern.
- Zielprofile 2–99 mit getrennten Geheimnissen und Adaptern; nur OAuth-App-Zugangsdaten dürfen gemeinsam
  genutzt werden. Google-Browseranmeldung und Microsoft-Gerätecode unterstützen `--profile`.
- Vorschläge Schema 3 binden ihr Profil dauerhaft. Lesender Vorabgleich und Wiederanlauf nach unklarem
  Schreibergebnis verwenden dieses Profil. Zielumstellen in Web/Telegram erzeugt eine neue unbestätigte
  Version; Profilfehler beeinträchtigen andere Profile nicht.
- Themen und ausgeschlossene Themen unterstützen `mailboxes`. Filter Schema 2 kombiniert globale und
  lokale Sperren mit lokalen `allow`-Ausnahmen; Schema 1 wird erst beim Schreiben mit Sicherung migriert.
  Lernen schlägt das Ursprungspostfach vor; Decision-Test und Berichte verwenden die wirksamen Filter.
- Fünf Postfach-Tabs, Profilverwaltung mit Verweisprüfung, versionierte Einrichtungsentwürfe und Vorschau
  betroffener laufender Mails. Profilgebundene Diagnosen und Anzeige in Telegram und Web.
- Postfachbezogene Benachrichtigungsrichtlinien und Tagesabschnitte erhalten Versandmarker beim Upgrade.
  Bereits eingereihte Abschnitte werden verworfen, wenn ihr Postfach inzwischen ausgeschlossen wurde.
- Sämtliche Ziele sind aus dem Analyse-Fingerprint entfernt. Beim Upgrade werden die bisherigen
  Fingerprints und Themenrichtlinien bis 3.1 als gleichwertig registriert; laufende Mails und gebundene
  Vorschlagsziele bleiben erhalten. Details zu Upgrade/Backup/Rollback stehen in
  [Release 3.2](docs/Release-3.2.md).
- Regression: CalDAV-URLs mit eingebetteten Benutzernamen werden abgewiesen. Kleine YAML-Feldänderungen
  behalten Kommentare; Mischentwürfe mit Listen und Benachrichtigungsregeln werden sicher bearbeitet.
  Die Einstellungs-Vorschau berücksichtigt registrierte Alt-Hashes und hält bei reinen Zieländerungen
  keine laufenden Mails zurück.
  Themenbeschränkungen halten auch bei migrierten 3.1-Mails nur Postfächer mit veränderten wirksamen
  Themen zurück.

## 3.1.3 – beta: Telefonansicht, Release-Texte und CI-Actions

- **Fehler behoben:** Auf Telefonen bricht die Navigation auf mehrere Zeilen um; als klebende Kopfleiste
  verdeckte sie einen großen Teil des Bildschirms, und Schaltflächen wie „Relevant“ rutschten beim
  Scrollen darunter. Der Browsertest `test_details_show_the_complete_mail[mobile]` scheiterte deshalb
  in der CI zufällig. Unter 720 px Breite scrollt die Kopfleiste jetzt mit der Seite. Regressionstest
  `test_phone_header_scrolls_away_and_never_covers_actions` scheiterte vor der Korrektur.
- **Fehler behoben:** Jedes GitHub-Release erhielt den Text von Release 1.0. Der Release-Workflow
  erzeugt den Text jetzt aus dem Changelog-Abschnitt der getaggten Version mit absoluten Links und dem
  Verweis auf `docs/Release-X.Y.md`; fehlt der Abschnitt, scheitert die Veröffentlichung. Tests in
  `tests/release/test_release_notes.py`.
- GitHub-Actions auf Node.js 24 umgestellt: `actions/checkout@v6`, `actions/setup-python@v6`,
  `actions/upload-artifact@v6`.

## 3.1.2 – beta: Lernmodus und Decision-Test über alle Postfächer

- `--mailbox alle` (auch `all`) wählt für `--learn` und `--decision-test` alle aktivierten Postfächer:
  `N` begrenzt die neuesten Mails über alle Postfächer zusammen (Reihenfolge wie beim Abruf; ohne
  globale Sortierung Postfach für Postfach). `--mailbox <n>` wählt weiterhin ein einzelnes Postfach;
  bei mehreren aktivierten Postfächern bleibt eine der beiden Angaben Pflicht.
- Der Decision-Test vergleicht identische Rohmails aus mehreren Postfächern nur einmal; der Bericht nennt
  `mailboxes` und bei mehreren Postfächern `historical_start` je Postfach.
- Der Lernmodus ergänzt neue Ordner im Eintrag des jeweiligen Postfachs.
- Spezifikation, Release-Anleitung 3.1, Planung 3.1 und `config.example.yaml` angepasst; neue Tests für
  Auswahl, Reihenfolge, Duplikate und CLI.

## 3.1.1 – Übernahme von beta nach main

- Den committierten beta-Stand mit offenem Vorschlagsabgleich, Standarddauern,
  Einrichtung, Diagnose, Benachrichtigungen und mehreren Postfächern für main vorbereiten.
- Patchversion in Paketmetadaten und Anwendung gemäß den Commit-Regeln erhöhen.
- Die Übernahme erfolgt nach erfolgreicher vollständiger GitHub-CI einschließlich
  Coverage-, Browser-, Paket- und Containerprüfungen.

## 3.1.0 – beta: Mehrere Postfächer

Planung: [docs/Planung-3.1.md](docs/Planung-3.1.md); Einrichtung, Upgrade und Rückkehr:
[docs/Release-3.1.md](docs/Release-3.1.md). Umgesetzt schrittweise in 3.0.1 bis 3.0.5 (Einträge unten).

- Bis zu zehn IMAP-Postfächer (`imap.mailboxes`, Zugangsdaten `IMAP_<n>_USERNAME`/`IMAP_<n>_PASSWORD`);
  das bisherige Format bleibt als Postfach 1 gültig.
- Gemeinsamer Abruf mit globaler Auswahl und gemeinsamem Kontingent, Fehler je Postfach isoliert,
  postfachübergreifende Duplikaterkennung, laufende Mails überstehen Upgrade und Umstellung.
- Entwürfe und Tätigkeitsberichte im jeweiligen Postfach; `--mailbox` für Lernmodus und Decision-Test.
- Postfach-Labels und -Filter in Weboberfläche und Telegram; Diagnose aller Postfächer.
- Release-Anleitung 3.1, Datenschutzhinweis und README ergänzt. Der Release-Tag `v3.1.0` wird erst nach
  erfolgreicher CI-Matrix (Linux, Docker, Paketinstallation) gesetzt.

## 3.0.5 – beta: Planung 3.1, Phase 5 – Weboberfläche, Telegram, bis zu 10 Postfächer

- Bis zu 10 Postfächer; zwei aktivierte Postfächer mit demselben Server, Port und Benutzer werden beim
  Start abgelehnt.
- Maildetail und Archivliste nennen das Postfach, das Archiv filtert nach `postfach=<n>`; Telegram-Karten
  zeigen `✉️ [Label] Absender · Betreff`. Mit einem Postfach bleibt die Darstellung unverändert.
- Diagnose `imap` prüft alle aktivierten Postfächer des Entwurfs; Ordnerauswahl im Einrichtungsschritt je
  Postfach; Anzeigename und Aktivierung sind dort bearbeitbar.
- Verschoben nach 3.2: Postfächer im Web hinzufügen/entfernen, Labels in Entscheidungsübersicht und
  Tagesüberblick, Telegram `/status` je Postfach.
- Abnahme: 2223 Python-Tests mit 100 % Zeilen- und Branch-Abdeckung, 134 Browsertests.

## 3.0.4 – beta: Planung 3.1, Phase 4 – postfachbezogene Funktionen

- Antwortentwürfe gehen nur in den Entwurfsordner des Ursprungspostfachs (eigene Verbindung und
  Absender); ein nicht mehr eingerichtetes Postfach wird abgelehnt, der Text bleibt erhalten.
- Tätigkeitsberichte gehören zu einem Postfach: Auswahl ohne JavaScript, Ordnervorschläge und -prüfung je
  Postfach, Zählen und Lesen nur dort. Schema-Snapshot `ActivityReport` um `mailbox` (Standard 1) ergänzt;
  ältere Berichte bleiben ohne Migration lesbar.
- `--learn` und `--decision-test` lesen genau ein Postfach; bei mehreren aktivierten Postfächern ist
  `--mailbox <n>` Pflicht. Der Lernmodus liest mit dem Reader dieses Postfachs.

## 3.0.3 – beta: Planung 3.1, Phase 3 – Duplikate über Postfächer hinweg

- Der Duplikatindex vergleicht mit den Einträgen aller Postfächer: Dieselbe Mail in zwei konfigurierten
  Postfächern wird nur einmal analysiert und verweist auf die zuerst verarbeitete Mail. Wiederverwendete
  Message-IDs mit anderem Inhalt bleiben auch postfachübergreifend `ambiguous`. Regressionstest
  `test_the_same_message_in_a_second_mailbox_is_skipped` scheiterte vor der Änderung.
- Sortierung offener Vorschläge geprüft: durch die Mail-ID als zweites Kriterium auch bei gleicher UID in
  zwei Postfächern eindeutig; unverändert.

## 3.0.2 – beta: Planung 3.1, Phase 2 – Laufzeitkern für mehrere Postfächer

- Ein Reader je aktiviertem Postfach (`MailboxSource`); ein nicht erreichbares Postfach hält die
  anderen nicht auf. Ordnerfehler werden mit Postfachnummer protokolliert.
- Gemeinsame Auswahl über alle Postfächer nach Empfangszeitpunkt mit gemeinsamem `batch_size`/`--max-mails`;
  ein dauerhafter Run je Postfach, Bearbeitung in Konfigurationsreihenfolge; unfertige Runs werden vor
  jeder neuen Suche fortgesetzt.
- Wiederaufnahme liest über das Postfach der gespeicherten `account_id`; Zustände entfernter oder
  deaktivierter Postfächer bleiben liegen (`mailbox_unavailable`, einmal je Prozess protokolliert).
  Abgeschlossene Wiederaufnahmen schreiben Run und Checkpoint ihres eigenen Kontos fort.
- `--check-access` und Laufzusammenfassung je Postfach. Die Konfiguration bleibt bis Phase 4 auf ein
  Postfach begrenzt.

## 3.0.1 – beta: Planung 3.1, Phase 1 – Postfächer im Konfigurationsvertrag

- `imap.mailboxes` mit stabiler Nummer `id`, Anzeigename `label` und `enabled`; das bisherige Format
  bleibt gültig und gilt als Postfach 1. Beide Schreibweisen zusammen werden abgelehnt.
  Bis Phase 2 wird genau ein Postfach unterstützt.
- Zugangsdaten je Postfach als `IMAP_<id>_USERNAME`/`IMAP_<id>_PASSWORD`; Postfach 1 startet weiterhin
  mit `IMAP_USERNAME`/`IMAP_PASSWORD`. Logs und Vergleichsberichte maskieren jedes IMAP-Passwort.
- `imap` ist nicht mehr Teil des Analyse-Fingerprints. Fingerprints und Themenrichtlinien bis 3.0
  werden für Postfach 1 exakt rekonstruiert und als gleichwertig registriert; laufende Mails werden
  durch das Upgrade oder die Umstellung auf `imap.mailboxes` nicht zurückgehalten (gegen 3.0.0
  nachgerechnet, Regressionstest mit unabhängig nachgebautem 3.0-Algorithmus).
- Kommentarerhaltende YAML-Bearbeitung versteht Listeneinträge (`imap.mailboxes.0.host`), auch beim
  Ergänzen fehlender Schlüssel. Einrichtungsschritt „Postfach“ und Lernmodus arbeiten mit beiden Formaten;
  der Assistent zeigt im Altformat wieder die wirksamen Standardwerte (z. B. `Drafts`, `ssl`).
- Gemeinsame Verbindungsargumente für alle IMAP-Leser (Betrieb, Entwürfe, Berichte, Decision-Test).
- Spezifikation, `config.example.yaml` und `.env.example` ergänzt; neue Tests für Formate, Grenzen,
  Geheimnisnamen, Fingerprint-Gleichwertigkeit, YAML-Listenpfade und den Assistenten.

## 2.3.3 – beta: Abschlussdokumentation zur Planung 2.4

- Umsetzung, Bedienung und Upgrade des offenen Vorschlagsabgleichs sowie der
  Standarddauern in Spezifikation, README und Betriebsanleitung dokumentiert.
- Wiederherstellung fehlender Akten erhält die ursprüngliche Version und den
  Idempotenzschlüssel; bestätigte Altbefunde werden ausschließlich abgeglichen.
- Technische Datenschutzhinweise für Quellen, Vergleichscache und Merge-Journal ergänzt.
- Paketprüfung wählt ausdrücklich die aktuelle Version, auch wenn ältere Builds
  im Distributionsverzeichnis liegen.
- Browserprüfung wartet nach der Gerätenavigation auf die sichtbare Sitzung,
  statt den noch laufenden Dokumentwechsel als Fehler zu werten.

## 2.3.2 – beta: Umsetzung der Planung 2.4

- Termine und Aufgaben werden vor Benachrichtigung auch gegen offene Entscheidungen
  abgeglichen. Kanonische IDs, versionierte Quellen und nicht ausführbare Aliasakten
  verhindern mehrere offene Vorschläge für denselben Vorgang.
- Neue Fakten ergänzen bestehende Vorschläge; ältere Mails ändern konkrete Absprachen
  nicht zurück. Manuelle Werte bleiben geschützt, Widersprüche und mehrere mögliche
  Treffer erfordern Klärung. Ungeprüfte Zusätze lassen sich in Web und Telegram
  zuordnen oder getrennt behalten, ohne externe Anlage.
- Standarddauern für belegte Videokonferenzen (60 Minuten) und Präsenztermine
  (180 Minuten), einstellbar in Einrichtung und Einstellungen. Explizite Zeiten und
  Dauern haben Vorrang; Annahmen sind sichtbar und werden als verstrichene Minuten berechnet.
- Bereits vorhandene Termine werden unabhängig von der Telegram-Zustellung gespeichert.
  Rückmeldeaufgaben zeigen die verknüpfte Sitzung. Fehlende Altakten und Dauerannahmen
  werden unter `/abgleich` nur nach ausdrücklich übernommener Vorschau aktualisiert.
- Wiederaufnehmbares Merge-Journal, versions- und policygebundener Vergleichscache,
  separate Normalisierungspolicy und erneute Sitzungs-/Zielprüfung vor einer Anlage.
  Fehlgeschlagene externe Abgleiche sperren die Anlage und können erneut geprüft werden.
- Synthetische Regressionen für die beobachteten Doppelvorschläge, fehlende Endzeiten
  und die nicht sichtbare bereits vorhandene Beiratssitzung; zusätzliche Konflikt-,
  Wiederanlauf-, Autorisierungs- und Browserprüfungen. Spezifikation und Beispiele ergänzt.

Die beta-Patchnummer folgt `AGENTS.md`; die fachliche Zielversion des Plans bleibt 2.4.
Dieser Commit erstellt keinen Release und keinen Tag.

## 3.0.0 – beta: Einrichtung, Diagnose und Benachrichtigungen

Planung: [docs/Planung-3.0.md](docs/Planung-3.0.md), Betrieb und Upgrade: [docs/Release-3.0.md](docs/Release-3.0.md).
Abnahme auf diesem Stand unter Windows 11: 2173 Python-Tests mit 100 % Zeilen- und Branch-Abdeckung,
134 Browsertests mit 100 % JavaScript-Abdeckung, ruff und mypy ohne Befund. Der Release-Tag `v3.0.0`
wird erst nach erfolgreicher CI-Matrix (Linux, Docker, Paketinstallation) gesetzt.

- Neue Planungen: mehrere Postfächer ([docs/Planung-3.1.md](docs/Planung-3.1.md), Geheimnisse
  `IMAP_<n>_USERNAME`/`IMAP_<n>_PASSWORD`) und Einstellungen je Postfach
  ([docs/Planung-3.2.md](docs/Planung-3.2.md)). Beide gehören nicht zu 3.0.

- Einrichtung unter `/einrichtung`: wiederaufnehmbare Entwürfe, Dateihash und Entwurfsversion,
  getrennte bestätigte Übernahme über die vorhandene, erneut autorisierte Kommando-Warteschlange.
- Unabhängige Diagnosen unter `/diagnose`, sichere Fehlercodes und bereinigter JSON-Export.
  Lesende IMAP-, Kalender- und Todoist-Prüfungen; separate Aktionen für Testnachrichten und synthetische LLM-Tests.
- Lokaler Erstzugang mit `mailhelp --pair`; ohne Telegram erzeugen Webanfragen und Dienststart keine Codes mehr.
- Gemeinsame persistente Benachrichtigungswarteschlange, Kategorie- und Kanalwahl,
  lokale Ruhezeiten einschließlich Zeitumstellung, Bündelung, begrenzter Backoff und sichtbare unklare Zustellungen.
  Pro Push-Gerät gelten Sitzung und Abonnementrevision; Web-Push bleibt neutral.
- Upgrade erhält vorhandene Inhaltsfreigaben und berücksichtigt alte Zustellmarker.
  Neue Profile beginnen mit neutralen Telegram-Hinweisen. Operative Profile ändern keine Analyse-Fingerprints.
- Synthetische Autorisierungs-, Zustell-, Neustart-, Upgrade- und Datenschutztests; neue Schema-Snapshots.
  Die Versionsfreigabe erfolgt nach Abschluss der Plattformmatrix; es wurde kein Release veröffentlicht.
- In der Abnahme abgesichert: unterbrochene alte Outbox-Zustellungen bleiben unklar, eine volle
  Queue wird weiter entleert, endgültige Fehler belegen keine ausstehenden Plätze und Migrationsdaten
  enthalten keine Kopien alter Mailtexte. Die Regressionstests scheiterten vor den jeweiligen Korrekturen.
- Ungültige Unicode-Werte in Kopplungssignaturen und CSRF-Tokens werden mit HTTP 403
  abgewiesen; Regressionstests belegen beide zuvor ausgelösten Serverfehler.

## 2.3.1 – Beta (Branch `beta`), Tätigkeitsberichte in fester Reihenfolge

- **Fehler behoben:** Zwei kurz nacheinander angelegte Tätigkeitsberichte konnten unter Windows denselben
  Anlagezeitpunkt erhalten (Uhrauflösung etwa 15 ms); die Bearbeitungsreihenfolge hing dann von den
  zufälligen Dateinamen ab, und der spätere Bericht konnte vor dem früheren gezählt werden. Berichte tragen
  jetzt eine fortlaufende Nummer (`sequence`, ältere Dateien 0) als zweites Sortierkriterium, danach die
  Kennung. Der Anlagezeitpunkt kommt aus der Uhr des Dienstes.
- Regressionstest `test_reports_created_in_the_same_clock_tick_stay_fifo` friert die Uhr ein und lässt das
  Dateisystem beide Reihenfolgen liefern; er scheiterte vor der Korrektur zuverlässig. Damit ist auch der
  gelegentlich fehlschlagende `test_report_counting_is_fifo` stabil. Schema-Snapshot `ActivityReport`
  um das optionale Feld ergänzt; alte Berichtsdateien bleiben ohne Migration lesbar.

## 2.3.0 – Beta (Branch `beta`), weitere Kalender- und Aufgabendienste, Volltextsuche, Originaldokumente

Planung: [docs/Planung-2.3.md](docs/Planung-2.3.md).

- **Kalender:** zusätzlich CalDAV (Nextcloud, iCloud, mailbox.org, Radicale …) und Outlook /
  Microsoft 365 (`targets.calendar_provider`). Duplikatprüfung, Ergänzung, Zeitänderung und Absage
  laufen für alle Kalender über denselben Ablauf (`TargetWriter`, `CalendarOperations`).
- **Aufgaben:** zusätzlich Microsoft To Do, CalDAV-Aufgabenlisten (VTODO) und Apple Erinnerungen über
  iCloud-CalDAV (`targets.task_provider`). Auf die neuen iCloud-Erinnerungen aktualisierte Listen sind
  über CalDAV nicht erreichbar; die Zugriffsprüfung meldet das.
- **Idempotenz je Anbieter:** CalDAV über einen aus dem Schlüssel abgeleiteten Ressourcennamen mit
  `If-None-Match: *`; Outlook über eine erweiterte Eigenschaft und `transactionId`; To Do über
  `linkedResources.externalId`. Unklare Ergebnisse werden wie bisher nur abgeglichen.
- **Microsoft-Anmeldung:** `mailhelp --microsoft-login` (Gerätecode); rotierte Refresh-Tokens werden in
  `microsoft-token.json` neben `.env` gespeichert.
- **Geheimnisse** werden nur noch für die gewählten Anbieter verlangt; neue Variablen `CALDAV_*`, `MICROSOFT_*`.
- **Volltextsuche** unter `/mails` über Mailtext, Anhangnamen und Anhangtext mit Fundstelle, UND-Verknüpfung,
  Phrasen und Umlaut-Gleichwertigkeit; Auswahl „nur Absender, Betreff und Zusammenfassung“.
- **Originaldokumente** (PDF, Office, OpenDocument, Text, Bilder) neu verarbeiteter Mails zum Herunterladen;
  Allowlist mit Signaturprüfung, Prüfsumme, Download-only-Header, Aufbewahrung wie Mailinhalte
  (`attachments.*`).
- Web-Einstellungen und Einrichtungsschritt „Analyse und Ziele“ bieten Anbieter und Ziele an; neue Zeitlimits
  `timeouts.caldav` und `timeouts.microsoft`. Bestehende Konfigurationen behalten ihren Analyse-Fingerprint.
- Anbieterneutrale Texte: „Als Aufgabe anlegen“, „Angelegt als Aufgabe“, „Aufgabe öffnen“,
  „Terminänderung gegenüber dem Kalender“.
- Tests mit simuliertem CalDAV-Server und simuliertem Microsoft Graph; 100 % Zeilen- und Branch-Abdeckung.

## 2.2.6 – Beta (Branch `beta`), Split-View ohne Flackern

- **Split-View:** Neue Daten ersetzen Liste und Detailbereich ohne Neuladen der Seite; kein Flackern
  mehr, Auswahl und Scrollposition bleiben. Ein laufender Rückgängig-Countdown wird nicht gestört.
  Der in Telegram aktuelle Vorgang ist in der Liste nicht mehr zusätzlich umrandet, nur noch die
  Auswahl. Regressionstests in `ui_tests/test_ui_v20.py` scheiterten vor der Korrektur.
- **Versionierung:** Auch jeder Commit in `beta` erhöht die Patch-Version (AGENTS.md, Spezifikation).
- WSL-Browserabnahme: Der Fehlerpfad der Hintergrundaktualisierung wird vor einer weiteren
  Navigation vermessen, damit seine ausgeführten JavaScript-Blöcke im Coverage-Gate erhalten bleiben.

## 2.2.5 – Beta (Branch `beta`), Entscheidungen aus Planung 2.1 und Testinfrastruktur

- **Web-Push je Gerät (Planung 2.1, 5.3):** Die Idempotenzschlüssel der An- und Abmeldung werden je Gerät begrenzt (500); ein aktives Gerät verdrängt nicht mehr die Schlüssel eines anderen. Test `test_push_operations_are_bounded_per_device`.
- **Tagesüberblick nach spätem Start (Planung 2.1, 5.1):** Entschieden, kein Zeitfenster – der Überblick wird auch nach einem Start lange nach der eingestellten Uhrzeit noch am selben Tag gesendet. Festgehalten mit `test_briefing_is_still_sent_after_a_late_start`.
- **`composition.py` (A4):** Der Aufbau der Anwendung (Logger, Metriken, IMAP, LLM, Telegram, Analyzer, Dialog, Orchestrator, Weboberfläche) liegt in eigenen Fabriken in `composition.py`; `application.py` enthält nur noch die Polling-Schleife und exportiert `build_application` weiter.
- **Tests ohne Querimporte (T1/T2):** Activity-Tests nutzen die gemeinsamen Fakes; ein Architekturtest verbietet Importe aus anderen `test_*`-Modulen.
- **Browsertests (T7):**
  - `axe-core` (WCAG 2.1 A/AA) läuft bei jedem Seiten-Audit, ohne Befund auf allen Seiten; ein Test belegt, dass axe Verstöße tatsächlich meldet.
  - Seitenobjekte `Overview`, `DetailPane`, `SettingsPage` in `ui_tests/pages.py`.
  - Der Test der echten 5-Sekunden-Rückgängig-Frist lud wegen einer Weiterleitung die verkürzte Testfrist und prüfte die 5 Sekunden nicht; er lädt die Seite jetzt selbst und stellt sicher, dass nach 3 Sekunden noch nichts gesendet ist.

## 2.2.4 – Beta (Branch `beta`), statische Prüfung: mypy fehlerfrei und verbindlich

- **mypy (Planung 2.1, A1):** Von 339 Fehlern auf 0, unter Windows und Linux (`--platform linux`). Der CI-Job `static-analysis` bricht jetzt bei jedem ruff- oder mypy-Befund ab (kein `continue-on-error` mehr).
  - `JsonStore.load_model`/`peek_model` liefern mit Default nie `None` (Overloads); `logger.metrics`, Metrics-Vergleich, Orchestrator-Themenpolitik und Review-Konfiguration sind typisiert.
  - Protokolle passen zu ihren Implementierungen: `Completer` mit den tatsächlichen Schlüsselwortparametern, `Decider` für Jev-Entscheidungen, `RelevanceHandler` mit `telegram_offset`, eine gemeinsame `EventLogger`-Definition.
  - pydantic-Plugin für mypy: Konstruktoren nehmen wie zur Laufzeit Strings für Enum-, Literal- und URL-Felder an.
  - `DisabledTelegram` erfüllt den Transportvertrag vollständig (`started_chats`, `answer_callback`).
  - `TelegramDialogState.reference()` liefert Mail, Vorschlag und Version eines offenen Dialogs typisiert.
  - Abweichende Typstubs von `imaplib` (bytes-Ordnernamen, `None` als Zeichensatz) und plattformabhängige Stubs von `fcntl`/`msvcrt` sind an je einer Stelle gekapselt.
- **Klassengröße (A4):** Minutenanteil und harte Aufrufgrenze eines Tätigkeitsberichts liegen in `activity.budget.ReportCalls`; `ActivityRunner` hat damit 19 statt 21 Methoden. Keine Klasse über 20 Methoden, keine Funktion über 80 Zeilen.
- **Bugfix – Telegram-Zeitantworten:** Eine unmögliche Uhrzeit oder ein unmögliches Datum („30“, „heute 25 Uhr“, „31.02.2026“) löste im deterministischen Zeitparser einen `ValueError` aus, statt wie jede freie Antwort an die Interpretation zu gehen. Gefunden durch den Eigenschaftstest; Regressionstest `test_impossible_times_and_dates_are_no_deterministic_answer`.
- **Bugfix – Rückfrage ohne validiertes Datum:** Widersprach eine Antwort auf die Frage nach dem Terminende einem Termin ohne validierte Datumsfakten (etwa aus einer Kalendereinladung), stürzte die Antwortverarbeitung mit `None + 1 Tag` ab, statt nachzufragen. Regressionstest `test_contradictory_end_without_validated_date_gets_a_question`.

## 2.2.3 – Beta (Branch `beta`), statische Prüfung: ruff fehlerfrei

Keine Verhaltensänderung.

- **ruff (Planung 2.1, A1):** Von 236 Befunden auf 0. Zu lange Zeilen von Hand im Stil des Codes umbrochen (Texte als implizit verkettete Literale, sodass Seiten und Meldungen byte-gleich bleiben; der Renderer-Vertragstest bestätigt das). Closures binden ihre Schleifenwerte ausdrücklich; Tests erwarten konkrete Ausnahmen (`ValidationError`, `RetryableError`, `PermanentError`, `UncertainWriteError`) statt `Exception`.
- **Konfiguration:** UP038 ist in ruff selbst veraltet und wird ignoriert; die Kompatibilitätsfassaden `models.py` und `domain/__init__.py` dürfen wie `telegram/_core.py` per Stern importieren.
- Protokollmethoden mit mehrzeiliger Signatur tragen einen Docstring statt `...`.

## 2.2.2 – Beta (Branch `beta`), Anforderungsprüfung 2.2

Behebt die Befunde aus [Pruefung-2.2.md](docs/Pruefung-2.2.md); jede Korrektur hat einen Regressionstest.

- **Korrekturen während der Analyse:** Eine laufende Terminsuche überschrieb danach gespeicherte Nutzerentscheidungen und von Hand ergänzte Termine. Ergebnisse werden jetzt mit dem aktuellen Stand zusammengeführt (`test_live_corrections_survive_the_in_flight_event_analysis`).
- **Harte KI-Grenze:** `max_llm_calls` wurde nur vor jeder Mail geprüft; Relevanz plus Terminsuche, Reparaturversuche und nachgeforderte Terminsuchen konnten sie überschreiten. Die Grenze gilt jetzt vor jedem Provideraufruf (`test_call_limit_stops_between_steps_and_resume_does_not_repeat_relevance`, `test_model_repair_also_consumes_the_hard_call_budget`, `test_requested_extraction_cannot_bypass_the_call_limit`).
- **Zählfehler und UIDVALIDITY:** Ein nicht erreichbares Postfach ließ einen Bericht endlos zählen; jetzt „fehlgeschlagen“ nach drei Versuchen. Eine geänderte UIDVALIDITY ließ den Bericht scheitern; jetzt wird der Ordner neu aufgelistet und Ergebnisse werden über die Message-ID wiederverwendet.
- **Gesendet-Ordner:** Ein ausdrücklich gewählter Gesendet-Ordner prüfte den Absender statt der Empfänger gegen die Ignorierliste.
- **Datumsprüfung:** Ein Modelldatum, das dem Belegzitat widerspricht (Zitat „20. Januar“, Datum 21.01.), wurde übernommen; jetzt verworfen (`test_model_date_must_agree_with_its_quote`).
- **Reihenfolge und Sitzung:** Wartende Berichte in Anlagereihenfolge; vor jedem KI-Aufruf wird die auslösende Sitzung erneut geprüft; Löschen verlangt einen Idempotenzschlüssel; die Ignorierliste wird beim kostenpflichtigen Start gesichert; nur Ordner aus der Serverliste.
- **Neu (Planung 2.2):** Filter, hervorgehobene Belege, Kostenschätzung aus Messwerten, „Mit anderem Thema neu bewerten“, Fortschritt über `/api/stand?bericht=<id>` (ungültige IDs: 404, Regressionstest `test_progress_signal_rejects_malformed_report_ids`).
- **Schema-Verträge:** `ActivityReport` und `ReportMail` sind Teil der Persistenzgrenze und der Schema-Snapshots.
- **Browsertests:** Die JavaScript-Abdeckung las CRLF-Dateien mit verschobenen Offsets und meldete fälschlich Lücken; Messung jetzt auf den ausgelieferten Bytes, auch vor Reload, Zurück und dem Schließen eigener Kontexte.
- **Paket:** Doku 2.1 und 2.2 im sdist.

## 2.2.1 – Beta (Branch `beta`)

- **Bugfix – Ordnervorschlag im Tätigkeitsbericht:** Konfigurierte Ordner, die der Server nicht kennt (z. B. `Trash` und `Sent`, wenn das Postfach `Papierkorb` und `Gesendet` nutzt), wurden vorgeschlagen, weil ihre Rolle unbekannt war, und beim Zählen als „nicht lesbar“ gemeldet. Vorgeschlagen werden jetzt nur vom Server gelistete Ordner; Regressionstest `test_suggested_folders_exist_on_the_server`. Gefunden beim ersten echten Bericht.
- **Bugfix – KI-Fehler im Tätigkeitsbericht:** Eine unbrauchbare KI-Antwort (z. B. Tokenlimit bei der Terminsuche) brach den Hintergrundschritt ab; die Schleife hätte dieselbe kostenpflichtige Anfrage alle fünf Sekunden wiederholt. Unbrauchbare Antworten werden jetzt an der Mail vermerkt (`failed_step`) und nicht wiederholt, die Seite bittet um eigene Entscheidung bzw. Termine von Hand; ein dreimal nicht erreichbarer KI-Dienst pausiert den Bericht, eine fehlschlagende Terminsuche auf Anfrage wird verworfen. Regressionstests `test_unusable_model_answers_are_recorded_once_and_never_retried`, `test_an_unreachable_model_pauses_the_report_after_repeated_failures`, `test_a_failing_requested_extraction_is_dropped_not_repeated`.
- **Prompts:** `max_tokens` für `activity_relevance` (2000) und `activity_events` (8000) angehoben; 2000 reichten dem konfigurierten Modell bei langen Mails nicht. Beim Upgrade die beiden Werte in der eigenen `prompts.yaml` übernehmen.

## 2.2.0 – Beta (Branch `beta`), Tätigkeitsbericht

- **Neu – Tätigkeitsbericht (`/berichte`):** Für ein Thema und einen Zeitraum liest Mailhelp die Mails der gewählten und der gesendeten Ordner schreibfrei, überspringt ignorierte Absender, Duplikate und verdächtige Mails, lässt jede übrige per KI auf das Thema prüfen (`activity_relevance`, mit `personal_info` als Kontext) und extrahiert aus relevanten Mails alle datierten Termine, auch vergangene (`activity_events`, wörtlicher Beleg je Termin). Zählen und kostenpflichtiger Start sind getrennt; Pausieren, Fortsetzen, Abbrechen und Neustart setzen an der nächsten Mail an.
- **Prüfen und korrigieren:** Termine chronologisch mit Quellmail, relevante Mails ohne Termin, „Doch relevant“ für abgelehnte Mails, Termine bearbeiten, ausschließen und ergänzen – mit Sitzungs-, CSRF-, Versions- und Idempotenzprüfung, ohne JavaScript bedienbar.
- **xlsx-Export:** Blätter „Termine“, „Ohne Termin“ und „Bericht“; Mailinhalte werden nie zu Formeln. Neue Abhängigkeit `openpyxl` (gepinnt).
- **Konfiguration:** Abschnitt `activity_report` (standardmäßig aus) und `retention.activity_report_days` (365); neue Prompts in `prompts.yaml`. Kein Analyse-Fingerprint ändert sich.
- **PWA:** Cache-Name `mailhelp-shell-v3`, damit installierte Apps das neue Stylesheet laden.
- Details: [Release-2.2.md](docs/Release-2.2.md).

## 2.1.1 – Beta (Branch `beta`)

- **Testkorrektur:** Der Kerntest prüfte noch die fest eingetragene Version 2.0.3 und brach in 2.1.0 vor seinen übrigen Prüfungen ab (Abdeckung 99,95 %). Er prüft jetzt nur das Format; die Übereinstimmung mit `pyproject.toml` sichert `test_release_package`.

## 2.1.0 – Beta (Branch `beta`), Planung 2.1 Abschluss

- **Modularisierung großer Komponenten (A4, A5, A6):** `MailhelpSite` in spezialisierte Teil-Sites zerlegt (`LoginSite` für Koppelung und Geräte, `ReviewSite` für offene Entscheidungen und Vorschläge, `ArchiveSite` für Archiv und Einstellungen). Seitenaufbau ohne `page.replace("</main>", ...)` über strukturierte Parameter. Modulgrößen gestrafft (Funktionen ≤ 80 Zeilen, Klassen ≤ 20 Methoden).
- **Fehlerbehandlung und Schnittstellen (A7, A8):** Einheitliche Ausnahmehierarchie für externe Dienste (`ExternalServiceError`, `ExternalUnavailable`, `ExternalRefused`, `ExternalUncertain`) in `external/contracts.py`. Neuer Helfer `log_and_continue` für prozessgrenzenübergreifende Fehlerprotokollierung. Zentrales Zeitformatierungsmodul `formatting.py` (`%d.%m.%Y, %H:%M Uhr`).
- **Einheitliche Bilderkennung (A8):** Bildvorschau in `attachments.py` und Texterkennung in `vision.py` nutzen dieselbe Funktion `is_image(filename, content_type)`. Regressionstest `test_raster_cache_matches_image_by_filename_extension` sichert Erkennung über Dateiendungen ab.
- **Bereinigte Client- und Einstellungsattribute (A8):** `getattr`/`hasattr`-Weichen auf Settings und Clients (`primary_folder`, `service_name`, `last_relevance_source`) durch feste Attribute und Protokolle ersetzt.
- **Browsertests & Stabilität (T7):** Automatisches Sammeln der Browser-Coverage vor jeder Navigation über DevTools-Hooks; konfigurierbare Rückgängig-Frist im Testserver via `data-undo-ms`. Alle 98 UI-Browsertests stabil.
- **Statische Analyse (A1):** `ruff` und `mypy --strict` auf dem Kern (`domain/`, `external/contracts.py`, `drafts.py`, `webpush.py`, `briefing.py`, `attachments.py`) fehlerfrei. Durchgängig `from __future__ import annotations`.
- **Qualitätssicherung:** 100 % Zeilen- und Branch-Abdeckung über alle 125 Module (1.721 Tests) verbindlich erreicht. Detaillierte Dokumentation in [Architektur-2.1.md](docs/Architektur-2.1.md) und [Release-2.1.md](docs/Release-2.1.md).

## 2.0.3 – Beta (Branch `beta`), Planung 2.1 Phase 3

- **Bugfix – Kalendereinladungen:** Der ICS-Parser löste Escape-Sequenzen nacheinander auf; ein maskierter Backslash vor `n`/`N` wurde so zum Zeilenumbruch (aus `C:\\new\\Nordsee` in einer Einladung wurde `C:\` + Umbruch + `ew\` + Umbruch + `ordsee`). Jetzt in einem Durchlauf; Regressionstest `test_an_escaped_backslash_before_n_stays_a_backslash`. Gefunden durch die neuen eigenschaftsbasierten Tests.
- **Typisierte vorbereitete Mail (A3):** Lesemodelle `PreparedMail`, `MailHeaders`, `PreparedAttachment`, `ImagePreview` (`domain/prepared.py`) über `MailState.prepared`. Orchestrator, Mail- und Archivansicht, Anhangsdarstellung und Antwortentwürfe lesen typisiert statt über Zeichenkettenschlüssel; die Dict-oder-Objekt-Weiche der Anhangsanreicherung entfällt. Gespeichert und an das Sprachmodell gesendet wird unverändert das bisherige Dict (Dateien und Anfragen byte-gleich). Beschädigte optionale Werte gelten wie bisher als fehlend. Die Duplikatsignatur rechnet bewusst weiter auf dem gespeicherten Dict.
- **Tests über öffentliche Schnittstellen (T3):** Keine Tests mehr über `Application._poll_imap`, `_poll_imap_global`, `_resume_pending`, `_complete_resumed_run_entry` oder `TelegramDialogController._decide`; diese reinen Durchreicher sind entfernt, `MailboxRunService.run_counters` ist öffentlich. Telegram-Befehle laufen in den Usability-Tests über `poll_once()`; nur Tests, die den Zustand zwischen Empfang und Weiterverarbeitung prüfen, nutzen `_handle` mit Begründung. Alle 282 Anweisungsketten mit `;` sind aufgelöst (AST-geprüft unverändert). `test_models_and_config` und der Darstellungstest für Terminänderung/Duplikat sind in benannte Einzeltests geteilt; `test_storage_windows_directory_sync` prüft jetzt ausdrücklich. Offen: 18 weitere Tests über 60 Zeilen.
- **Eigenschaftsbasierte Tests (T6):** `hypothesis` (gepinnt) prüft MIME-Vorbereitung beliebiger Bytes, Payload-Grenzen, Header-Injektion in Antwortentwürfen, zulässige Push-Anbieter, ICS-Escaping und -Faltung als Rundreise, Datumsparser und den Telegram-Zeitparser.

## 2.0.2 – Beta (Branch `beta`), Planung 2.1 Phase 2

Keine Verhaltensänderung für Nutzer; gespeicherte Zustände bleiben byte-gleich lesbar.

- **Speicher-Protokoll (A2):** `StateStore` (`typing.Protocol`) beschreibt, was Dienste vom Zustandsspeicher brauchen. Alle `hasattr`/`getattr`-Weichen auf den Store in `application`, `mailbox_run`, `orchestrator` und `telegram/*` sind entfernt; sie existierten nur für unvollständige Test-Fakes. `drafts` und `webpush` sperren über `store.locked()` statt `store._thread_lock`.
- **Zentrale Zustandsnamen (A2):** Neues Modul `state_names.py` (`mail`, `mail_run`, `draft`, `proposal`, `clarification`, `mail_state_names` …) ersetzt die verstreuten Namensmuster; ein Vertragstest hält die Muster byte-gleich.
- **Telegram-Client:** Die `getattr`-Weiche für Logger ohne `telegram_event` entfällt; das `EventLogger`-Protokoll verlangt die Methode.
- **Gemeinsame Test-Doubles (T2, Beginn):** `tests/fakes/store_fakes.py` (`DelegatingStore`, `InterruptingStore` über einen echten `JsonStore`) und `tests/fakes/log_fakes.py` (`RecordingLogger`, prüft die Log-Stufe wie der echte Logger) ersetzen sieben gleichartige Kopien.
- **Wirkungsloser Test korrigiert:** Der Test „Push-Zustellung hält keine Sperre“ prüfte die re-entrante Store-Sperre im selben Thread und hätte nie scheitern können. Er prüft jetzt aus einem zweiten Thread und schlägt bei gehaltener Sperre nachweislich an.
- **Upgrade-Verträge (T5):** `tests/upgrade/states/` enthält echte Zustände der Releases 1.1–2.0, erzeugt von deren eigenem Ende-zu-Ende-Test aus dem jeweiligen Release-Commit (je vier Szenarien). Geprüft wird: verlustfreies Laden ohne Quarantäne, kein erneuter Schreibzugriff auf Kalender/Todoist und keine erneute Analyse nach einem Neustart. JSON-Schema-Snapshots aller gespeicherten Modelle lassen jede ungeplante Formatänderung scheitern.

## 2.0.1 – Beta (Branch `beta`), Planung 2.1 Phase 1

Keine Verhaltensänderung für Nutzer.

- **Statische Prüfung (A1):** `ruff` und `mypy` sind in `pyproject.toml` konfiguriert (strikter Kern: `domain`, `external.contracts`, `drafts`, `webpush`, `briefing`, `attachments`). Die CI meldet die Befunde in einem eigenen Job, ohne vorerst zu scheitern. Ausgangsbestand: 1.312 ruff-Befunde (Anwendungscode 663) und 490 mypy-Fehler.
- **Abhängigkeiten (T8):** Neuer Test `tests/release/test_dependency_lock.py` prüft, dass die Lock-Dateien die vollständige installierte Abhängigkeitshülle festschreiben. Er fand `colorama` (pytest unter Windows), das bisher ungepinnt installiert wurde; es ist jetzt mit Plattform-Marker gepinnt. Die Werkzeuge für die statische Prüfung stehen in `requirements-lint.lock` und gelangen nicht ins Container-Image.
- **CI (T8):** Laufzeitbericht der 20 langsamsten Tests; wöchentlicher Workflow mit `pip-audit` gegen beide Lock-Dateien.
- **Tests nach Fachgebiet (T1):** Die Testmodule liegen jetzt in `tests/unit`, `services`, `telegram`, `web`, `external`, `evaluation`, `upgrade`, `e2e`, `release` und `scenarios`. Inhaltlich unverändert bis auf repo-relative Pfade; gleiche Testanzahl und 100 % Abdeckung. Pfade in CI, Compose-Smoke-Dateien, README und Architekturdokument angepasst.

## 2.0.0 – Beta (Branch `beta`)

- **Einstellungshilfe:** Alle Web-Konfigurationswerte erhalten Info-Blasen zu Wirkung und Wertewahl, erreichbar per Maus, Tastatur und Antippen. Identische Texte mit Übernahmezeitpunkt stehen in [Web-Einstellungen](docs/Web-Einstellungen.md); Vollständigkeit und Übereinstimmung werden getestet.
- **Auswahl in der Webübersicht (Bugfix):** Automatische und manuelle Aktualisierungen behalten den ausgewählten Vorgang im aktuellen Browser-Verlaufseintrag. Nur wenn er nicht mehr in der Liste vorhanden ist, wird der erste verbleibende Eintrag geöffnet. Regressionstest für wiederholte Hintergrundänderungen, Neuladen und entfernte Vorgänge.
- **Neue Weboberfläche:** Split-View ab 1024 px (Liste links, Details rechts, ohne Seitenwechsel), einklappbare Sektionen für Quellbeleg, Revisionshistorie und technische Analyse, Schnellfilter (`?filter=events|tasks|clarification|attachments|duplicates`) auf `/offen`, `/mails` und `/verlauf`, Daumenzonen-Aktionsleiste mit 48-px-Schaltflächen, Tastenkürzel (`J`/`K`/`C`/`E`/`X`/`?`), 5-Sekunden-Rückgängig vor dem Absenden sowie ein „Alles erledigt“-Zustand mit Tagesbilanz. Alle Funktionen bleiben ohne JavaScript nutzbar.
- **Bildanhänge im Browser:** Neu kodierte JPEG-Vorschauen (max. 1.600 px) unter `GET /mail/<id>/anhang/<index>` mit Sitzungsprüfung, `nosniff` und restriktiver CSP; zoombare Lightbox und erkannter Text. Vorschauen werden mit dem Mailtext gelöscht; ein Vorschaufehler hält die Analyse nie auf.
- **Web-Push (`push.enabled`):** VAPID-Schlüssel im Datenverzeichnis, Opt-in je Gerät unter Einstellungen, nur bekannte Push-Dienste, keine Weiterleitungen, inhaltsneutrale Meldungen für neue Entscheidungen und den Tagesüberblick. Der Versand blockiert weder Weboberfläche noch Mailverarbeitung.
- **Antwort-Entwürfe (`smart_reply`, Prompt `draft_reply`):** Die Mail- und Vorschlagsdetailseite zeigt immer „Zusagen“, „Absagen“ und „Rückfrage“. Ein Klick erzeugt per LLM genau einen passenden Entwurf (positiv, negativ, Rückfrage) in einem bearbeitbaren Textfeld; „Abbrechen“ verwirft ihn lokal, „Als Entwurf im Postfach speichern“ legt genau den angezeigten Text per IMAP `APPEND` mit `\Draft \Seen`, `In-Reply-To` und `References` in `imap.drafts_folder` ab. Keine Entwurfserzeugung im Hintergrund; doppelte Klicks lösen keinen zweiten LLM-Aufruf aus. Das Modell erhält die erkannten Anhangtexte (inklusive OCR) genau einmal und ohne technische Metadaten.
- **Persönliche Angaben für Antworten (`personal_info`):** Neues mehrzeiliges Textfeld unter Einstellungen → Antworten (bis 2.000 Zeichen) für Name, Rolle, Signatur und Anrede-Wünsche. Wird nur dem Prompt `draft_reply` als vertrauenswürdiger Kontext übergeben, wirkt ohne Neustart und ändert keinen Analyse-Fingerprint. Mehrzeilige Werte schreibt der Einstellungseditor als einzeiligen YAML-Wert in `config.yaml`. Kein SMTP-Versand. Unklare Ergebnisse werden über die Message-ID abgeglichen und nur bei nachweislich fehlendem Entwurf wiederholt.
- **Tagesüberblick (`daily_briefing`):** Einmal je lokalem Tag Termine, fällige Aufgaben und offene Entscheidungen, auch bei Teilausfällen; Text an Telegram, neutraler Hinweis per Push, Anzeige unter `/briefing`.
- **Betrieb ohne Telegram (`telegram.enabled: false`):** Nur mit Weboberfläche; Kopplungscodes erscheinen in der Konsole des PCs, `TELEGRAM_BOT_TOKEN` entfällt.
- **Fingerprints (Bugfix):** Die 2.0-Einstellungen gelangten in die Legacy-Fingerprints von 1.1/1.2; Mails aus diesen Versionen wären nach dem Upgrade hängen geblieben. Mit Regressionstest.
- **Abhängigkeiten:** `pywebpush==2.5.0` samt Abhängigkeiten in `requirements.lock`; Docker-Image neu bauen.
- Einrichtung, Upgrade und Rollback: [Release-2.0.md](docs/Release-2.0.md).

## 1.6.0 – Beta (Branch `beta`)

- **Webdarstellung getrennt:** Vorschlags-, Mail- und Review-Seiten bleiben in `web/review_pages.py`; Betriebsstatus und Laufzeitformatierung liegen in `web/status_pages.py`. Bestehende Importe bleiben kompatibel.
- **Eigener Mailbox-Service:** `mailbox_run.py` übernimmt Discovery, globale durable Queue, UID-Checkpoints, Mail-Budgets, Laufzusammenfassung und Wiederaufnahme. `Application` bleibt für Composition und Prozess-/Telegram-/Web-Lifecycle zuständig.
- **Integrationsgrenzen:** OAuth, Google-Kalender, Todoist, ICS-Dateien, HTTP-Transport und bestätigte Schreibausführung sind unter `external/` getrennt. `integrations.py` bleibt die kompatible Fassade für bisherige Importe und Konstruktoren.
- **Telegram-Revisionen entflechtet:** Antwortinterpretation mit eigenen Retries, validierte Nachfolge-Vorschläge und durable/Legacy-Recovery besitzen eigenständige Grenzen. Persistenz, Zustellung und versionsbezogene Autorisierung behalten ihre Reihenfolge.
- **Verhaltensverträge:** Zusätzliche Tests für die kompatiblen Schnittstellen, unabhängige Mailbox-Wiederaufnahme und identische Renderer-Ausgaben gegenüber 1.5. Bestehende JSON-Schemas, CLI-Optionen, Web-Routen, Konfiguration und externe API-Verträge bleiben unverändert.
- **Browsertests korrigiert:** Die Kopplungstesthilfe erkennt den seit 1.5 gültigen vierstelligen Telegram-Code; der Negativtest verwendet garantiert einen abweichenden Code. Die synthetische Hauptschleife wird für unveränderte Renderzustände stabilisiert; produktive Recovery bleibt unverändert.
- Architektur und Upgrade in [Architektur-1.6.md](docs/Architektur-1.6.md) und [Release-1.6.md](docs/Release-1.6.md) dokumentiert.

## 1.5.0 – Beta (Branch `beta`)

- **Schlanke 4-stellige Anmeldeverifizierung:** Reduzierung des Gerätekopplungscodes von 8 auf 4 Ziffern (`0000`–`9999`) für schnelles Eintippen am Smartphone; Telegram-Nachricht und `/web`-Befehl senden den kompakten Code ohne Leerzeichen; Formular-Input auf 4–5 Zeichen angepasst; vollständiger Brute-Force-Schutz durch 3 Versuche (`CODE_ATTEMPTS`) und Rate-Limiting (`PairingLimited`).
- **Standard-Wechselkurs für Euro-Kosten:** Fester Wechselkurs von 1 € = 1,10 $ (`metrics.usd_per_eur = 1.1`) ab Werk hinterlegt; Euro-Kosten werden in der Auswertung ohne manuelle Konfiguration berechnet; Bezugsdatum ist optional.
- **Kosten in $Cent in der Tabellenansicht:** Spalte `<th>$Cent</th>` in der Tabelle „Nach Modell und Schritt“ auf `/auswertung`; Beträge in US-Cent mit 2 Nachkommastellen formatiert; voller USD-Betrag bleibt im `title`-Attribut für Tooltips erhalten.
- **Kompakte Modellnamen:** Modellbezeichner in der Auswertungstabelle werden auf den Namen nach dem letzten Schrägstrich (`/`) gekürzt (z. B. `deepseek` statt `openrouter/deepseek`); voller Modellpfad weiterhin im `title`-Tooltip verfügbar.
- **Sauberes Shutdown-Handling im Telegram-Client (Bugfix):** `RetryInterrupted` während eines Long-Polling-Backoffs wird geordnet als `INFO poll_interrupted` behandelt; kein irreführendes `ERROR`-Log mit 50 Zeilen Stacktrace beim Beenden des Dienstes; inklusive automatisiertem Regressionstest.

## 1.4.0 – Beta (Branch `beta`)

- **Multimodale Bild- und OCR-Texterkennung:** Bildanhänge (`.jpg`, `.png`, `.webp`) sowie gescannte PDFs ohne Textlayer werden automatisch per Vision-LLM (`vision_ocr` in `prompts.yaml`, Standard: `google/gemini-3.5-flash-lite`) ausgewertet.
- **Null externe System-Tools:** Bildaufbereitung und Scan-Seitenextraktion vollständig über Python (`pypdf` + `Pillow`); kein Tesseract, kein PyTorch, keine C-Binaries.
- **Intelligente Bildfilterung & Token-Schutz:** Automatische EXIF-Ausrichtung, Skalierung auf maximal 1.600 Pixel, Dekompressions-Bombenschutz und automatische Verwerfung irrelevanter Logos/Symbole (<150 px oder <10 KB).
- **Konfigurierbare Limits:** Neuer Konfigurationsabschnitt `vision` in `config.yaml` (`enabled`, `max_images_per_mail: 3`, `max_image_bytes: 10485760`, `max_edge_pixels: 1600`).
- **Absender-Management in der Mail-Detailansicht:** Schaltfläche `[🚫 Absender ignorieren]` auf `/mail/<mail_id>` trägt die normalisierte Absenderadresse atomar und idempotent in `irrelevant-senders` ein. Reversibel mit `[Absender wieder zulassen]`.
- **Zentrale Liste ignorierter Absender:** Eigene Verwaltungsseite unter `/einstellungen/ignorierte-absender` zum manuellen Hinzufügen und Entfernen von Adressen und ganzen Domains.
- **Sofortiger Vorfilter im Orchestrator:** Mails blockierter Absender/Domains werden vor jedem KI-Aufruf ohne Benachrichtigung als `irrelevant` aussortiert (0 Cent Kosten).
- **100 % Testabdeckung:** 1.561 synthetische Tests bei 100,00 % Zeilen- und Branch-Coverage.

## 1.3.0 – Beta (Branch `beta`)

- **Intelligente Duplikat-Vorabprüfung (Stufen 1–3):** Vorab-Check gegen Action Ledger, Google Kalender und Todoist vor Benachrichtigung. Exakte Duplikate erhalten den Status `already_exists` und werden auf Telegram und unter `/offen` unterdrückt.
- **Intelligente Terminverschiebung (Reschedule):** Erkennt bestehende Google-Kalender-Termine, berechnet und visualisiert Zeitänderungen in Web und Telegram ("🔄 Terminänderung gegenüber Kalender") und aktualisiert nach Bestätigung per HTTP `PATCH` anstelle eines Neuanlage-`POST`.
- **Lokale Dokumenten-Textextraktion (PDF, Word, Text):** Sichere Extraktion von Textinhalten aus Anhängen (bis 10 MB, max. 20.000 Zeichen) mittels `pypdf` und nativer ZIP/XML-Verarbeitung ohne externe System-Tools; automatische Anreicherung des LLM-Kontexts für Routing und Detail-Extraktion.
- **RFC 5545 Kalenderanhänge (.ics):** Deterministische Übernahme von `VEVENT`-Einladungen und -Absagen ohne LLM-Halluzinationen.
- **Erweiterungen in Web & Telegram:** Diff-Boxen bei Terminänderungen, Duplikat-Badges mit Direktlinks, Anhangs-Statusbadges und kontextbezogene Bestätigungsschaltflächen ("Termin aktualisieren", "Termin absagen").
- Vollständige synthetische Testabdeckung (100 % Zeilen, 100 % Branches) inklusive 3 Regressionstests für Duplikatsunterdrückung, Kalender-PATCH und PDF-Aufgabenextraktion.

## 1.2.0 – Beta (Branch `beta`)

- Weboberfläche mit Mailarchiv (Suche, Filter, Analyse), Entscheidungsverlauf mit
  lesenden Altversionen, erweitertem Betriebsstatus und Kosten-/Zeitauswertung.
- Strukturierte Bearbeitung von Vorschlägen; Speichern erzeugt eine neue Version, die
  separat bestätigt werden muss.
- Einstellungen und Themen im Web, kommentarerhaltend in `config.yaml` gespeichert;
  kontrolliertes Beenden aus dem Web.
- Konfigurations-Fingerprint nur aus analyserelevanten Einstellungen; Vorgänge aus 1.1
  laufen nach dem Upgrade weiter.
- Lernmodus ergänzt IMAP-Ordner ohne Kommentarverlust.
- Bestätigung von Schreibzugriffen über Telegram oder die authentifizierte Weboberfläche.

Einrichtung, Upgrade und Rollback: [Release-Anleitung](docs/Release-1.2.md).

## 1.1.0 – Beta (Branch `beta`)

- Optionale Weboberfläche mit Übersicht, Vorschlagsdetail, Status und Geräteverwaltung,
  bedienbar am PC und als installierbare App (PWA) auf dem iPhone über Tailscale Serve.
- Bestätigen, Doppelanlage, Verwerfen, Antworten (auch Ja/Nein), Bearbeitung beenden
  und Relevanz im Web – versionsgebunden, über eine dauerhafte Befehlswarteschlange,
  idempotent und mit Abgleich nach Neustart.
- Kanalneutrale Review-Schicht; Telegram-Schaltflächen nutzen sie ebenfalls und melden
  im Web entschiedene Vorschläge als veraltet. Neue Befehle `/web` (Link mit
  vorausgefülltem Einmal-Code) und `/web_abmelden`.
- Anmeldung per Telegram-Kopplungscode, gehashte Sitzungen, CSRF, Host-Prüfung,
  strenge Sicherheits-Header; Service Worker speichert nur die App-Hülle.
- `JsonStore` ist zusätzlich thread-sicher (Regressionstest für `os.replace` unter Windows).
- Automatische Browsertests (Desktop und iPhone) mit Screenshots, Bedienbarkeits- und
  Kontrastprüfungen und 100 % JavaScript-Abdeckung; eigener CI-Job.

Einrichtung und Einschränkungen: [Release-Anleitung](docs/Release-1.1.md).

## 1.0.0 – 11. Oktober 2026

- Vollständiger Trockenlauf für Todoist und Google Kalender.
- Konservative Kurzlink-Vorprüfung mit synthetischen Regressionstests.
- Begrenzte Wiederholung vorübergehend blockierter Betriebssystem-Sperren.
- Qualitätsprüfung des produktiven Jev-Pfads mit gemeinsamem Aufrufbudget.
- Semantischer Uhrzeitvergleich, präzisierte Zuständigkeits- und Zusammenfassungsregeln.
- Prüfungen für Sicherungswiederherstellung, Paketinstallation und Release-Artefakte.

Upgrade und Einschränkungen: [Release-Anleitung](docs/Release-1.0.md).

## 0.1.0

Erste Implementierung des persönlichen IMAP-/LLM-/Telegram-Assistenten mit
versionsbezogenen Freigaben, dauerhaften JSON-Zuständen und Duplikatabgleich.
