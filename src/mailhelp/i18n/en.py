"""7.5: English texts of the human interface, keyed by their German reference text.

Placeholders (``{count}``) must be the same as in the German text; the completeness test checks
this and that every literal ``tr()`` call of the code has an entry here.
"""
from __future__ import annotations

EN: dict[str, str] = {
    # Page frame and navigation (7.5.1)
    "Zum Inhalt springen": "Skip to content",
    "Hauptnavigation": "Main navigation",
    "Schnellnavigation": "Quick navigation",
    "Mehr": "More",
    "Offen": "Open",
    "Mails": "Mails",
    "Verlauf": "History",
    "Status": "Status",
    "Auswertung": "Statistics",
    "Berichte": "Reports",
    "Einstellungen": "Settings",
    "Geräte": "Devices",
    "Vorschlagsabgleich": "Proposal review",
    "Abgleich": "Review",
    "Lernen": "Learning",
    "Arbeitsbereich": "Workspace",
    "Einblicke": "Insights",
    "Verwaltung": "Administration",
    "offene Entscheidung": "open decision",
    "offene Entscheidungen": "open decisions",
    "Hilfschat öffnen": "Open help chat",
    "Sprache": "Language",
    "English": "English",
    "Deutsch": "Deutsch",
    "unbekannt ({value})": "unknown ({value})",
    # Dates, times and durations (7.5.2)
    "{n} Min.": "{n} min",
    "{n} Std.": "{n} h",
    "{n} Tag": "{n} day",
    "{n} Tage": "{n} days",
    "ganztägig": "all-day",
    "höchstens {duration}": "at most {duration}",
    "Ende angenommen: Standarddauer {minutes} Min.": "Assumed end: default duration {minutes} min",
    # Telegram cards, buttons and prompts (7.5.3)
    "Manuell prüfen": "Check manually",
    "Verwerfen": "Dismiss",
    "Klären": "Clarify",
    "Ändern": "Edit",
    "Simulieren": "Simulate",
    "Termin absagen": "Cancel event",
    "Termin aktualisieren": "Update event",
    "Im Kalender anlegen": "Add to calendar",
    "Als Aufgabe anlegen": "Add as task",
    "✓ Schon erledigt": "✓ Already done",
    "Termin {number} meinen": "I mean event {number}",
    "📧 Original-Mail öffnen": "📧 Open original email",
    "Auf Zielprofil {name} umstellen": "Switch to target profile {name}",
    "Zu diesem Eintrag hinzufügen": "Add to this entry",
    "Als eigenen Vorschlag behalten": "Keep as a separate proposal",
    "übernehmen": "take",
    "behalten": "keep",
    "❌ Termin im Kalender stornieren: Der bestehende Eintrag wird nach Bestätigung abgesagt":
        "❌ Cancel the calendar event: the existing entry is cancelled after confirmation",
    "🔄 Terminänderung gegenüber Kalender:": "🔄 Change against the calendar:",
    "- {field}: bisher {before} → neu {after}": "- {field}: was {before} → now {after}",
    "🔄 Terminänderung gegenüber Kalender": "🔄 Change against the calendar",
    "📅 Passende Kalendertermine:": "📅 Matching calendar events:",
    "⚠️ Widerspruch: {field} – welcher Wert soll gelten?": "⚠️ Conflict: {field} – which value applies?",
    "Version {number}": "Version {number}",
    "📅 Termin": "📅 Event",
    "✅ Aufgabe": "✅ Task",
    "🕒 Fällig: {due}": "🕒 Due: {due}",
    "Zuständig: {value}": "Responsible: {value}",
    "Sicherheit: {value}": "Certainty: {value}",
    "Einordnung: {value}": "Classification: {value}",
    "⚠️ Kann nicht automatisch angelegt werden – bitte manuell prüfen.":
        "⚠️ Cannot be created automatically – please check manually.",
    "🧪 Testmodus: Der Eintrag wird nur simuliert, nicht extern angelegt.":
        "🧪 Test mode: the entry is only simulated, not created externally.",
    "❓ Offen:": "❓ Open:",
    "Beleg: „{evidence}“": "Evidence: “{evidence}”",
    "📧 Original-Mail (Apple Mail): {link}": "📧 Original email (Apple Mail): {link}",
    "✏️ Was soll an „{title}“ geändert werden?": "✏️ What should be changed in “{title}”?",
    "„Titel: Elternabend“ oder „Ort: Raum 3“": "“Title: Parents' evening” or “Location: Room 3”",
    "fällig {date}": "due {date}",
    "z. B. {example} · ": "e.g. {example} · ",
    "/abbrechen beendet die Bearbeitung": "/abbrechen ends the editing",
    "Übernommen – keine sichtbare Änderung.": "Applied – no visible change.",
    "Übernommen": "Applied",
    "Neu offen:": "Newly open:",
    # Card labels and displayed questions (review/cards.py)
    "„16:00“ oder „nach 2 Stunden“": "“16:00” or “after 2 hours”",
    "„21.10.2026 14:00“": "“21.10.2026 14:00”",
    "„ja“ oder „nein“": "“yes” or “no”",
    "„Raum 3“": "“Room 3”",
    "Du": "You",
    "Andere Person": "Someone else",
    "Noch unklar": "Not yet clear",
    "Eindeutig": "Certain",
    "Unsicher": "Uncertain",
    "Widersprüchlich": "Contradictory",
    "Neu": "New",
    "Unverbindlicher Hinweis": "Non-binding note",
    "Bereits erledigt": "Already done",
    "Änderung eines bestehenden Eintrags": "Change of an existing entry",
    "Absage": "Cancellation",
    "Wiederkehrend": "Recurring",
    "Bist du dafür zuständig?": "Are you responsible for this?",
    "Stimmen die Angaben so?": "Are these details correct?",
    "Ist nur ein Hinweis – trotzdem anlegen?": "This is only a note – create it anyway?",
    "Wann beginnt der Termin?": "When does the event start?",
    "Wann endet der Termin?": "When does the event end?",
    "Welches Datum ist gemeint?": "Which date is meant?",
    # Statuses, events, sources and kinds (web/labels.py)
    "Als irrelevant eingestuft": "Rated as irrelevant",
    "Als relevant eingestuft": "Rated as relevant",
    "Als schon erledigt erfasst": "Recorded as already done",
    "Altbestand": "Earlier record",
    "Altbestand – Ablauf nicht vollständig erfasst": "Earlier record – history not complete",
    "Angelegt": "Created",
    "Angelegter Eintrag wieder entfernt": "Created entry removed again",
    "Anlage fehlgeschlagen": "Creation failed",
    "Aufgabe": "Task",
    "Bereits vorhanden": "Already exists",
    "Bestätigt": "Confirmed",
    "Bestätigt – wird angelegt": "Confirmed – being created",
    "Eintrag beim Anbieter geprüft": "Entry checked with the provider",
    "Erneut versucht": "Retried",
    "Erneuter Versuch angefordert": "Retry requested",
    "Felder bearbeitet": "Fields edited",
    "Gespeichert – Eintrag wird geprüft": "Saved – entry being verified",
    "Grund der Ablehnung gespeichert": "Reason for rejection saved",
    "Kalendereintrag gewählt": "Calendar entry chosen",
    "Klärung abgebrochen": "Clarification cancelled",
    "Klärung begonnen": "Clarification started",
    "Klärung nötig": "Needs clarification",
    "Mail erneut geprüft": "Mail checked again",
    "Mailhelp": "Mailhelp",
    "Nicht verarbeitet – abgelegt": "Not processed – filed",
    "Relevanz entschieden": "Relevance decided",
    "Rückfrage beantwortet": "Question answered",
    "Simuliert (Testmodus)": "Simulated (test mode)",
    "Standardwerte übernommen": "Defaults applied",
    "Status geändert": "Status changed",
    "Telegram": "Telegram",
    "Termin": "Event",
    "Terminserie beantwortet": "Event series answered",
    "Terminserie bestätigt": "Event series confirmed",
    "Trotz möglicher Dublette bestätigt": "Confirmed despite a possible duplicate",
    "Verworfen": "Dismissed",
    "Vorschlag erneut geprüft": "Proposal checked again",
    "Vorschlag wiederhergestellt": "Proposal restored",
    "Vorschläge getrennt": "Proposals separated",
    "Vorschläge zusammengeführt": "Proposals merged",
    "Wartet auf Bestätigung": "Pending confirmation",
    "Weboberfläche": "Web interface",
    "Wert aus einem Konflikt gewählt": "Value chosen from a conflict",
    "Wieder entfernt": "Removed again",
    "Wird abgeglichen": "Being reconciled",
    "Wird angelegt": "Being created",
    "Ziel geändert": "Target changed",
    "Zusammengeführt": "Merged",
    "unbekannt": "unknown",
    # Open decisions, cards, mail view and action forms (7.5.4)
    "Offene Entscheidungen": "Open decisions",
    "Vorschläge prüfen, Rückfragen klären und Entscheidungen treffen.":
        "Review proposals, answer questions and make decisions.",
    "{count} gespeicherte Datensätze sind beschädigt und werden nicht angezeigt. Bitte die Protokolle prüfen.":
        "{count} stored records are damaged and not shown. Please check the logs.",
    "Relevanz klären": "Clarify relevance",
    "Vorschläge": "Proposals",
    "Nichts zu entscheiden. Neue Vorschläge erscheinen hier automatisch.":
        "Nothing to decide. New proposals appear here automatically.",
    "Zuletzt erledigt": "Recently done",
    "Nach rechts wischen: anlegen · nach links: verwerfen": "Swipe right: accept · left: dismiss",
    "Nach rechts wischen: relevant · nach links: irrelevant": "Swipe right: relevant · left: irrelevant",
    "Hinweis schließen": "Close hint",
    "Zeit": "Time",
    "Frist": "Deadline",
    "Aufgabenziel": "Task target",
    "Ort": "Location",
    "Videolink": "Video link",
    "Zuständig": "Responsible",
    "Sicherheit": "Certainty",
    "Einordnung": "Classification",
    "Beschreibung": "Description",
    "Beleg": "Evidence",
    "Fällig: {due}": "Due: {due}",
    "Zielprofil: {profile} · {target}": "Target profile: {profile} · {target}",
    "Aktuell in Telegram": "Current in Telegram",
    "Folgt in Telegram": "Next in Telegram",
    "Kann nicht automatisch angelegt werden – bitte manuell prüfen.":
        "Cannot be created automatically – please check manually.",
    "Testmodus: Der Eintrag wird nur simuliert.": "Test mode: the entry is only simulated.",
    "Offene Fragen ({count})": "Open questions ({count})",
    "Termin im Kalender stornieren: Der bestehende Eintrag wird nach deiner Bestätigung abgesagt.":
        "Cancel event in calendar: the existing entry is cancelled after your confirmation.",
    "Passende Kalendertermine:": "Matching calendar events:",
    "Terminänderung gegenüber dem Kalender:": "Change compared with the calendar:",
    "Beginn": "Start",
    "Ende": "End",
    "🔄 Terminänderung": "🔄 Event change",
    "🚫 Terminabsage": "🚫 Event cancellation",
    "Beschreibung und Beleg": "Description and evidence",
    "Eintrag wieder entfernen": "Remove entry again",
    "Im Kalender öffnen": "Open in calendar",
    "Aufgabe öffnen": "Open task",
    "Details": "Details",
    "❔ Relevanz": "❔ Relevance",
    "Ist diese Mail für dich relevant? Bis zur Antwort wartet die Mailanalyse.":
        "Is this email relevant to you? The analysis waits for your answer.",
    "Serie: {title} ({count} Termine)": "Series: {title} ({count} events)",
    "Serie bearbeiten und bestätigen": "Edit and confirm series",
    "Per Bilderkennung gelesen": "Read by image recognition",
    "Bild ohne lesbaren Text": "Image without readable text",
    "Bilderkennung fehlgeschlagen": "Image recognition failed",
    "Übersprungen (Symbol oder Logo)": "Skipped (icon or logo)",
    "Übersprungen (Bildlimit je Mail)": "Skipped (image limit per email)",
    "Übersprungen (Bild zu groß)": "Skipped (image too large)",
    "Bild nicht lesbar": "Image not readable",
    "Von": "From",
    "Betreff": "Subject",
    "Postfach": "Mailbox",
    "Datum": "Date",
    "{count} Anhang/Anhänge nicht ausgewertet und nicht gespeichert.":
        "{count} attachment(s) not analysed and not stored.",
    "Der Text wurde für die Auswertung gekürzt.": "The text was shortened for the analysis.",
    "Der vollständige Mailtext ist nicht mehr gespeichert (automatische Löschung nach Abschluss und "
    "Aufbewahrungsfrist).":
        "The full email text is no longer stored (deleted automatically after completion and the retention period).",
    "Text extrahiert": "Text extracted",
    "Kein Text gefunden": "No text found",
    "Verschlüsselt / Passwortgeschützt": "Encrypted / password protected",
    "Übersprungen (zu groß)": "Skipped (too large)",
    "Fehler beim Lesen": "Error while reading",
    "Nicht unterstütztes Format": "Unsupported format",
    "Original herunterladen": "Download original",
    "Erkannten Text anzeigen": "Show recognised text",
    "Kein erkannter Text gespeichert.": "No recognised text stored.",
    "{name} vergrößern": "Enlarge {name}",
    "Anhänge ({count}):": "Attachments ({count}):",
    "{count} ICS-Kalenderanhang/-anhänge erkannt": "{count} ICS calendar attachment(s) detected",
    "Mail": "Email",
    "Quellbeleg aus E-Mail / Anhang": "Source evidence from email / attachment",
    "Mail von {name}": "Email from {name}",
    "1 Bild": "1 image",
    "{count} Bilder": "{count} images",
    "Zur Übersicht": "To the overview",
    "übernommen": "applied",
    "Die Auswahl ändert nur den Vorschlag; angelegt wird erst nach deiner Bestätigung. Für einen anderen Wert den "
    "Vorschlag ändern.":
        "The choice only changes the proposal; nothing is created before your confirmation. For another value, edit "
        "the proposal.",
    "Antwort gespeichert – der Vorschlag wird aktualisiert.": "Answer saved – the proposal is being updated.",
    "Die Verarbeitung ist pausiert. Bitte den Betreiber prüfen lassen.":
        "Processing is paused. Please ask the operator to check.",
    "Diesen Termin meinen: {label}": "I mean this event: {label}",
    "Mailhelp hält diesen Vorschlag für möglicherweise dieselbe Sache wie einen anderen. Im Vorschlagsabgleich "
    "entscheidest du: zuordnen oder als eigenen Vorschlag behalten.":
        "Mailhelp thinks this proposal may be the same matter as another one. Decide in the proposal review: assign "
        "it or keep it as a proposal of its own.",
    "Im Vorschlagsabgleich entscheiden": "Decide in the proposal review",
    "Dublettenprüfung wiederholen": "Repeat duplicate check",
    "Bestehenden Termin aktualisieren": "Update existing event",
    "Schon erledigt": "Already done",
    "Bearbeitung beenden": "End editing",
    "Legt den Eintrag beim Anbieter an.": "Creates the entry with the provider.",
    "Lehnt diesen Vorschlag ab; es wird nichts angelegt.": "Rejects this proposal; nothing is created.",
    "Relevant, aber bereits erledigt; es wird kein neuer Eintrag angelegt.":
        "Relevant, but already done; no new entry is created.",
    "Was bedeuten diese Entscheidungen?": "What do these decisions mean?",
    "Diese Aktion ist für diesen Vorgang nicht möglich.": "This action is not possible for this item.",
    "Erst den Widerspruch klären.": "Resolve the conflict first.",
    "Erst die Rückfrage beantworten.": "Answer the question first.",
    "Erst im Vorschlagsabgleich entscheiden.": "Decide in the proposal review first.",
    "Erst die Dublettenprüfung wiederholen.": "Repeat the duplicate check first.",
    "Erst den gemeinten Termin wählen.": "Choose the event you mean first.",
    "Angabe": "Field",
    "Beim Anbieter": "At the provider",
    "Erneut prüfen": "Check again",
    "Liest den Eintrag nur erneut; es wird nichts geändert oder angelegt.":
        "Only reads the entry again; nothing is changed or created.",
    "Was soll geändert werden?": "What should be changed?",
    "z. B. {example}": "e.g. {example}",
    "Ja": "Yes",
    "Nein": "No",
    "Antwort senden": "Send answer",
    "Erneut versuchen": "Try again",
    "Ignorieren": "Ignore",
    "Relevant": "Relevant",
    "Irrelevant": "Irrelevant",
    "Relevant: Mail weiter auswerten. Irrelevant: nicht weiter auswerten. Die Entscheidung kann später zum "
    "Regellernen verwendet werden.":
        "Relevant: keep analysing the email. Irrelevant: stop analysing it. The decision can later be used to learn "
        "rules.",
    "Wird ausgeführt … Danach geht es automatisch zur Übersicht.":
        "Running … You will return to the overview automatically.",
    "Kalender": "Calendar",
    "Aufgabenliste (z. B. Todoist)": "Task list (e.g. Todoist)",
    "Die Anlage im Ziel {target} kann einen Moment dauern.":
        "Creating the entry in the target “{target}” can take a moment.",
    "Aktion läuft": "Action running",
    "„{title}“ wurde schon einmal angelegt.": "“{title}” was already created once.",
    "Erneut anlegen": "Create again",
    "Nicht erneut anlegen": "Do not create again",
    "Ergebnis": "Result",
    "gespeichert: {reason}": "saved: {reason}",
    "Verworfen. Warum?": "Dismissed. Why?",
    "(freiwillig, verbessert künftige Vorschläge)": "(optional, improves future proposals)",
    "Betrifft mich nicht": "Does not concern me",
    "Nur zur Information": "For information only",
    "Werbung oder Rundschreiben": "Advertising or newsletter",
    "Falsch erkannt (Datum, Inhalt)": "Misrecognised (date, content)",
    "Anderer Grund": "Other reason",
    "Aktueller Stand: Version {number} – {state}.": "Current state: version {number} – {state}.",
    "Veraltet": "Outdated",
    "Nicht mehr aktuell": "No longer current",
    "Aktuellen Stand anzeigen": "Show current state",
    "Aufgaben": "Tasks",
    "Der Eintrag wird im Kalender gelöscht. Der Vorschlag bleibt als ‚wieder entfernt‘ im Verlauf.":
        "The entry is deleted from the calendar. The proposal stays in the history as ‘removed again’.",
    "Der Eintrag wird in den Aufgaben gelöscht. Der Vorschlag bleibt als ‚wieder entfernt‘ im Verlauf.":
        "The entry is deleted from the tasks. The proposal stays in the history as ‘removed again’.",
    "Zeit: {value}": "Time: {value}",
    "Eintrag wirklich entfernen": "Really remove entry",
    "Abbrechen": "Cancel",
    "Zurück zum Vorschlag": "Back to the proposal",
    "Ziel: {target}": "Target: {target}",
    "Eintrag entfernen": "Remove entry",
    "Wird verarbeitet …": "Processing …",
    "Zur Kenntnis genommen": "Noted",
    "Ansehen": "View",
    "Deine Aktion": "Your action",
    "Verarbeitung pausiert – bitte Betreiber prüfen lassen": "Processing paused – please ask the operator to check",
    "Antwort gespeichert – wird verarbeitet": "Answer saved – being processed",
    "Rückfrage offen": "Question open",
    "Zielprofil nicht verfügbar – Zugriff prüfen oder Ziel umstellen":
        "Target profile not available – check access or switch the target",
    "Freigabe des Altbestands nicht prüfbar – Anlage gesperrt":
        "Approval of the old record cannot be checked – creation blocked",
    "relevant": "relevant",
    "irrelevant": "irrelevant",
    # Results of actions, stored in German and shown in the reader's language (7.5.4)
    "Diese Mail ist nicht (mehr) vorhanden.": "This email no longer exists.",
    "Diese Mail ist nicht als irrelevant aussortiert.": "This email was not sorted out as irrelevant.",
    "Diese Mail wird bereits erneut geprüft oder wurde inzwischen geändert.":
        "This email is already being checked again or has changed in the meantime.",
    "Diese Mail wird noch verarbeitet.": "This email is still being processed.",
    "Vorschlag verworfen.": "Proposal dismissed.",
    "Eintrag entfernt und geprüft.": "Entry removed and checked.",
    "Als schon erledigt erfasst (Aufgabe bleibt als relevant vermerkt)": "Recorded as already done (kept as relevant)",
    "Bearbeitung gestartet – bitte die Rückfrage beantworten.": "Editing started – please answer the question.",
    "Antwort übernommen – der Vorschlag wird aktualisiert.": "Answer applied – the proposal is being updated.",
    "Bearbeitung beendet; der Vorschlag ist unverändert.": "Editing ended; the proposal is unchanged.",
    "Diese Aktion wurde bereits früher angelegt. Wirklich erneut anlegen?":
        "This action was already created earlier. Really create it again?",
    "Bestätigt; die externe Anlage ist noch unklar und wird abgeglichen.":
        "Confirmed; whether the entry was created is still unclear and is being reconciled.",
    "Bestätigt; die externe Anlage ist fehlgeschlagen.": "Confirmed; creating the entry failed.",
    "Bestätigt; keine externe Anlage ausgeführt.": "Confirmed; no entry was created.",
    "Konfigurationsdienst nicht verfügbar.": "Configuration service not available.",
    "Nicht autorisiert.": "Not authorised.",
    "Vorschlag inzwischen geändert": "Proposal changed in the meantime",
    "Erneut geprüft; separat bestätigen.": "Checked again; confirm separately.",
    "Ziel umgestellt; neue Version separat bestätigen.": "Target switched; confirm the new version separately.",
    "Neue Version gespeichert; bitte separat bestätigen.": "New version saved; please confirm separately.",
    "Vorschlag inzwischen geändert oder nicht gefunden": "Proposal changed in the meantime or not found",
    "Grund gespeichert: {label}.": "Reason saved: {label}.",
    "{label} {value} übernommen; neue Version bitte separat bestätigen.":
        "{label} {value} applied; please confirm the new version separately.",
    "{label} {value} behalten; neue Version bitte separat bestätigen.":
        "{label} {value} kept; please confirm the new version separately.",
    "Zeitraum": "Time range",
    "Endzeit": "End time",
    "Fälligkeit": "Due date",
    "Kalendertermin zugeordnet; separat bestätigen.": "Calendar event assigned; confirm separately.",
    "Vorschlag inzwischen geändert oder entschieden": "Proposal changed or decided in the meantime",
    "Mail als {label} eingestuft.": "Email classified as {label}.",
    "Erneuter Versuch beim nächsten Abruf.": "New attempt at the next fetch.",
    "Mail als nicht verarbeitet abgelegt; sie bleibt im Archiv.":
        "Email filed as not processed; it stays in the archive.",
    "Erneute Prüfung ist in diesem Betrieb nicht verfügbar.": "Checking again is not available in this mode.",
    "Die Mail wird beim nächsten Abruf mit den aktuellen Themen erneut geprüft.":
        "The email is checked again with the current topics at the next fetch.",
    "Vorschlag wurde nicht gefunden": "Proposal not found",
    "Der Vorschlag wurde inzwischen geändert oder entschieden": "The proposal was changed or decided in the meantime",
    "Für diesen Eintrag läuft bereits eine Prüfung oder sie ist abgeschlossen":
        "A check is already running for this entry or has finished",
    "Erneute Prüfung gestartet – Mailhelp liest den Eintrag nur erneut.":
        "Check started again – Mailhelp only reads the entry again.",
    "Eine andere Antwort wird gerade verarbeitet; bitte gleich erneut senden.":
        "Another answer is being processed; please send again shortly.",
    "Antwort nicht übernommen; der Vorschlag ist unverändert.": "Answer not applied; the proposal is unchanged.",
    "Antwort gespeichert – die Auswertung wird automatisch wiederholt.":
        "Answer saved – the analysis is repeated automatically.",
    "Für diesen Vorschlag läuft keine Bearbeitung": "No editing is running for this proposal",
    "Die Eingabe ist ungültig.": "The input is invalid.",
    "Bereits entfernt.": "Already removed.",
    "Simulierte Vorschläge können nicht extern entfernt werden.": "Simulated proposals cannot be removed externally.",
    "Nur angelegte Einträge können wieder entfernt werden.": "Only created entries can be removed again.",
    "Keine externe ID vorhanden.": "No external ID available.",
    "Die Frist zum Entfernen des Eintrags ist abgelaufen (maximal 10 Minuten nach dem Anlegen).":
        "The time for removing the entry has expired (at most 10 minutes after creating it).",
    "Nicht entfernt – Eintrag wurde beim Anbieter geändert.": "Not removed – the entry was changed at the provider.",
    "Entfernt und geprüft.": "Removed and checked.",
    "Entfernen noch nicht bestätigt; Abgleich läuft.": "Removal not yet confirmed; reconciliation running.",
    "Entfernen fehlgeschlagen.": "Removal failed.",
    "Kein Schreibdienst für diesen Vorschlag konfiguriert.": "No writing service configured for this proposal.",
    "{label}: Einträge lassen sich in Mailhelp nicht wieder entfernen; bitte direkt beim Anbieter bearbeiten.":
        "{label}: entries cannot be removed in Mailhelp; please edit them directly at the provider.",
    "Nach einem Neustart abgeglichen; der aktuelle Stand wird angezeigt.":
        "Reconciled after a restart; the current state is shown.",
    "Durch einen Neustart unterbrochen – bitte prüfen und erneut auslösen.":
        "Interrupted by a restart – please check and trigger again.",
    "Mailbefund inzwischen geändert": "Email result changed in the meantime",
    "Mailbefund inzwischen geändert oder wiederhergestellt": "Email result changed or restored in the meantime",
    "Gespeicherten Befund wiederhergestellt.": "Stored result restored.",
    "Quellversion inzwischen geändert": "Source version changed in the meantime",
    "Vorschlag nicht mehr offen": "Proposal no longer open",
    "Standarddauer inzwischen geändert": "Default duration changed in the meantime",
    "Zielversion inzwischen geändert": "Target version changed in the meantime",
    "Vorschlagsversion gespeichert; separat bestätigen.": "Proposal version saved; confirm separately.",
    "Serienschlüssel bereits für eine andere Entscheidung verwendet": "Series key already used for another decision",
    "Serie während der Vorprüfung geändert; Liste erneut prüfen":
        "Series changed during the pre-check; check the list again",
    "Sitzung abgelaufen; verbleibende Serientermine bleiben unverändert.":
        "Session expired; the remaining events of the series stay unchanged.",
    "Zielprofil nicht verfügbar; gesamte Serie bleibt unverändert":
        "Target profile not available; the whole series stays unchanged",
    "Zuordnung geändert; gesamte Serie erneut prüfen": "Assignment changed; check the whole series again",
    "Frühere Anlage gefunden; betroffenen Termin separat prüfen":
        "Earlier creation found; check the affected event separately",
    "Dublettenprüfung geändert; gesamte Serie erneut prüfen": "Duplicate check changed; check the whole series again",
    "Serie geändert; gesamte angezeigte Liste neu prüfen und bestätigen":
        "Series changed; check and confirm the whole list shown again",
    "Die angezeigten Termine gehören nicht zu derselben Serie": "The events shown do not belong to the same series",
    "Zuerst alle offenen Fragen der ausgewählten Termine klären":
        "First answer all open questions of the chosen events",
    "Bitte eine eindeutige Uhrzeit oder ein Zeitintervall angeben": "Please give an unambiguous time or time range",
    "Bereits abgeschlossen.": "Already finished.",
    "Serie während der Anlage geändert; verbleibende Termine neu prüfen und bestätigen.":
        "Series changed while creating it; check and confirm the remaining events again.",
    # Telegram messages, sent in the configured language (7.5.4)
    "Die Aktion ist fehlgeschlagen; Details stehen im Protokoll.": "The action failed; details are in the log.",
    "🌐 Im Web: {message}": "🌐 On the web: {message}",
    "Mailhelp – Befehle\n/offen – aktuelle Entscheidung erneut zeigen\n/status – Zahl verarbeiteter Mails und alle "
    "offenen Vorgänge\n/abbrechen – laufende Rückfrage beenden\n/web – Link und Code für die "
    "Weboberfläche\n/web_abmelden – alle Geräte der Weboberfläche abmelden\n/hilfe – diese Übersicht\n\nVorschläge "
    "kommen einzeln nacheinander. Rückfragen beantwortest du einfach mit einer Nachricht; die nächste offene Frage "
    "folgt automatisch. Angelegt wird erst, wenn du „Im Kalender anlegen“ bzw. „Als Aufgabe anlegen“ drückst.":
        "Mailhelp – commands\n/offen – show the current decision again\n/status – number of processed emails and all "
        "open items\n/abbrechen – end the running question\n/web – link and code for the web interface\n/web_abmelden "
        "– sign out all devices of the web interface\n/hilfe – this overview\n\nProposals come one after another. "
        "Answer questions simply with a message; the next open question follows automatically. Nothing is created "
        "until you press “Add to calendar” or “Add as task”.",
    "👋 Mailhelp gestartet. Befehle: /hilfe": "👋 Mailhelp started. Commands: /hilfe",
    "Unbekannter Befehl. Verfügbare Befehle: /hilfe": "Unknown command. Available commands: /hilfe",
    "📊 Bisher {count} {value} verarbeitet.": "📊 {count} {value} processed so far.",
    "{abandoned} aufgegebene Mails – Handlungsbedarf im Webstatus.":
        "{abandoned} abandoned emails – action needed on the web status page.",
    "Aktuelle Entscheidung: {value}": "Current decision: {value}",
    "{held_back} weitere Vorschläge folgen nacheinander.": "{held_back} more proposals follow one after another.",
    "Zurückgehaltene Nachrichten bis zur Erledigung der aktuellen Entscheidung: {held}":
        "Messages held back until the current decision is done: {held}",
    "Mail ohne Betreff": "Email without subject",
    "Relevanz „{subject}“ · Version {version}": "Relevance “{subject}” · version {version}",
    "Relevanzentscheidung: {subject} · Version {version}": "Relevance decision: {subject} · version {version}",
    "„{title}“ · Version {version}": "“{title}” · version {version}",
    "Noch nicht gesendet – folgt nach Erledigung der aktuellen Entscheidung":
        "Not sent yet – follows once the current decision is done",
    "Verarbeitung pausiert; Betreiber muss den gespeicherten Zustand prüfen":
        "Processing paused; the operator has to check the stored state",
    "Antwort gespeichert; Verarbeitung läuft oder wird automatisch fortgesetzt":
        "Answer saved; processing is running or continues automatically",
    "Antwort gespeichert; Verarbeitung wird automatisch fortgesetzt":
        "Answer saved; processing continues automatically",
    "„{title}“ · Version {version}: {status}": "“{title}” · version {version}: {status}",
    "Warte auf Antwort zur angezeigten Frage": "Waiting for an answer to the question shown",
    "Klärung erforderlich – bitte „Klären“ bzw. „Ändern“ oder „Manuell prüfen“ wählen":
        "Clarification needed – please choose “Clarify”, “Edit” or “Check manually”",
    "Warte auf Bestätigung oder Verwerfen": "Waiting for confirmation or dismissal",
    "Keine offene Telegram-Entscheidung.": "No open Telegram decision.",
    "Die Weboberfläche ist nicht aktiviert.": "The web interface is not enabled.",
    "🔐 Alle Geräte der Weboberfläche wurden abgemeldet ({count}).":
        "🔐 All devices of the web interface were signed out ({count}).",
    "Keine aktive Bearbeitung. Offene Entscheidungen: /offen": "No active editing. Open decisions: /offen",
    "Die Bearbeitung ist nicht mehr aktuell. Offene Entscheidungen: /offen":
        "The editing is no longer current. Open decisions: /offen",
    "Die Antwort ist bereits gespeichert. Die Verarbeitung kann hier nicht abgebrochen werden. Status: /status":
        "The answer is already saved. Processing cannot be cancelled here. Status: /status",
    "Bearbeitung geschlossen. Vorschlag unverändert; bitte erneut auswählen.":
        "Editing closed. Proposal unchanged; please choose it again.",
    "Nicht autorisierte Telegram-Anfrage": "Unauthorised Telegram request",
    "Zuerst müssen die offenen Fragen beantwortet werden": "The open questions have to be answered first",
    "Zielprofil nicht mehr konfiguriert oder nicht verfügbar": "Target profile no longer configured or not available",
    "Offene Entscheidungen haben sich geändert; neue Version prüfen":
        "Open decisions have changed; check the new version",
    "Dublettenprüfung hat den Vorschlag geändert; neue Version prüfen":
        "The duplicate check changed the proposal; check the new version",
    "✅ Doppelanlage-Prüfung wurde entgegengenommen.": "✅ Duplicate creation check received.",
    "Die Doppelanlage-Bestätigung ist veraltet": "The duplicate creation confirmation is outdated",
    "Websitzung vor Ausführung ungültig geworden": "Web session became invalid before execution",
    "✅ Als schon erledigt erfasst (Aufgabe bleibt als relevant vermerkt)":
        "✅ Recorded as already done (kept as relevant)",
    "✅ Vorschlag wurde verworfen.": "✅ Proposal dismissed.",
    "Diese Schaltfläche ist veraltet": "This button is outdated",
    "✏️ Änderungsmodus läuft bereits – bitte die Rückfrage oben beantworten.":
        "✏️ Edit mode is already running – please answer the question above.",
    "Absender: {sender}\nBetreff: {subject}": "Sender: {sender}\nSubject: {subject}",
    "Quellangaben nicht mehr verfügbar.": "Source details no longer available.",
    "Bereits angelegt: {value} „{title}“.": "Already created: {value} “{title}”.",
    "Frühere Quelle (Version {proposal_version}):\n{source_text}":
        "Earlier source (version {proposal_version}):\n{source_text}",
    "Soll die Aktion wirklich ein zweites Mal angelegt bzw. versendet werden?":
        "Should the action really be created or sent a second time?",
    "Nicht erneut": "Not again",
    "⚠️ Vorschlag bestätigt; externe Anlage ist noch unklar.":
        "⚠️ Proposal confirmed; whether the entry was created is still unclear.",
    "❌ Vorschlag bestätigt; externe Anlage fehlgeschlagen.": "❌ Proposal confirmed; creating the entry failed.",
    "⚠️ Vorschlag intern bestätigt; keine externe Anlage ausgeführt.":
        "⚠️ Proposal confirmed internally; no entry was created.",
    "ℹ️ Bereits entschieden oder geändert (z. B. in der Weboberfläche) – diese Schaltfläche ist veraltet. Aktueller "
    "Stand: /offen":
        "ℹ️ Already decided or changed (e.g. in the web interface) – this button is outdated. Current state: /offen",
    "Relevanz bitte bestätigen:": "Please confirm the relevance:",
    "Telegram-Eingabe ist syntaktisch ungültig und wurde verworfen.":
        "Telegram input is syntactically invalid and was discarded.",
    "❌ Eine Telegram-Eingabe konnte nicht verarbeitet werden und wurde verworfen. Bitte /offen öffnen und die Aktion "
    "erneut wählen.":
        "❌ A Telegram input could not be processed and was discarded. Please open /offen and choose the action again.",
    "Freitext ist nicht eindeutig zuordenbar; bitte die Schaltfläche der gewünschten Mail verwenden.":
        "The free text cannot be assigned unambiguously; please use the button of the email you mean.",
    "Aktion wird verarbeitet …": "Processing action …",
    "❌ Nicht autorisierte Aktion.": "❌ Unauthorised action.",
    "❌ Aktion ist syntaktisch ungültig; bitte erneut versuchen.":
        "❌ Action is syntactically invalid; please try again.",
    "Entfernen abgebrochen; der Eintrag bleibt erhalten.": "Removal cancelled; the entry is kept.",
    "❌ Aktion konnte nicht verarbeitet werden. Bitte erneut versuchen.":
        "❌ The action could not be processed. Please try again.",
    "❌ Relevanzantwort ist syntaktisch ungültig; bitte erneut versuchen.":
        "❌ Relevance answer is syntactically invalid; please try again.",
    "Dieser Eintrag wurde inzwischen geändert oder bereits entfernt.":
        "This entry was changed or already removed in the meantime.",
    "Die Frist zum Entfernen des Eintrags ist abgelaufen.": "The time for removing the entry has expired.",
    "Wirklich entfernen: „{title}“?": "Really remove: “{title}”?",
    "Diese Relevanzantwort wurde bereits verarbeitet.": "This relevance answer was already processed.",
    " · {date}, ganztägig": " · {date}, all day",
    "✅ Termin „{title}“ war im Kalender bereits abgesagt oder gelöscht (geprüft); nichts geändert.":
        "✅ Event “{title}” was already cancelled or deleted in the calendar (checked); nothing changed.",
    "✅ Termin „{title}“ im Kalender abgesagt und geprüft.":
        "✅ Event “{title}” cancelled in the calendar and checked.",
    "bestätigte Angaben übernommen": "confirmed details applied",
    "✅ Bestehender Termin „{title}“ geändert und geprüft: {changes}. Titel und Beschreibung bleiben erhalten; die "
    "Änderung ist in der Beschreibung vermerkt.":
        "✅ Existing event “{title}” changed and checked: {changes}. Title and description are kept; the change is "
        "noted in the description.",
    "✅ Bestehender Termin „{title}“ aktualisiert und geprüft: {changes}. Die Änderung ist in der Terminbeschreibung "
    "vermerkt.":
        "✅ Existing event “{title}” updated and checked: {changes}. The change is noted in the event description.",
    "Bereits vorhandener gleicher Termin „{title}“ wurde erkannt; fehlende Informationen wurden ergänzt und geprüft. "
    "Kein neuer Termin wurde angelegt.":
        "An identical existing event “{title}” was recognised; missing details were added and checked. No new event "
        "was created.",
    "Bereits vorhandener gleicher Termin „{title}“ wurde erkannt und frisch geprüft. Kein neuer Termin wurde angelegt.":
        "An identical existing event “{title}” was recognised and checked again. No new event was created.",
    "Wieder entfernen": "Remove again",
    "⚠️ Eintrag vorhanden, Angaben weichen ab: „{title}“ – {differences_text}. Mailhelp ändert den Eintrag nicht "
    "automatisch und legt keinen neuen an.":
        "⚠️ Entry exists, details differ: “{title}” – {differences_text}. Mailhelp does not change the entry "
        "automatically and creates no new one.",
    "⚠️ Eintragung noch nicht bestätigt: „{title}“ wurde gespeichert, aber {reason_text}. Mailhelp legt den Eintrag "
    "nicht erneut an.":
        "⚠️ Entry not yet confirmed: “{title}” was saved, but {reason_text}. Mailhelp does not create the entry again.",
    "Ziel geändert: „{title}“ bleibt gesperrt. Das konfigurierte Ziel stimmt nicht mit dem angezeigten Vorschlagsziel "
    "überein. Ursprüngliches Ziel wiederherstellen oder einen neuen Vorschlag für das neue Ziel ausdrücklich "
    "bestätigen.":
        "Target changed: “{title}” stays blocked. The configured target does not match the target shown in the "
        "proposal. Restore the original target or explicitly confirm a new proposal for the new target.",
    "Anlage blockiert: Freigabe, Vorschlagsversion oder Websitzung ist nicht mehr gültig.":
        "Creation blocked: approval, proposal version or web session is no longer valid.",
    "📎 Kalenderdatei für „{title}“{event_time_details} bereitgestellt – Übernahme in den Kalender nicht prüfbar.":
        "📎 Calendar file for “{title}”{event_time_details} provided – whether it reached the calendar cannot be "
        "checked.",
    "🧪 Testmodus: {kind} „{title}“ bestätigt, aber nicht angelegt (nur simuliert).":
        "🧪 Test mode: {kind} “{title}” confirmed but not created (only simulated).",
    "✅ Termin „{title}“ im Kalender abgesagt.": "✅ Event “{title}” cancelled in the calendar.",
    "✅ Termin „{title}“ war im Kalender bereits abgesagt oder gelöscht; nichts geändert.":
        "✅ Event “{title}” was already cancelled or deleted in the calendar; nothing changed.",
    "✅ Bestehender Termin „{title}“ geändert: {changes}. Titel und Beschreibung bleiben erhalten; die Änderung ist in "
    "der Beschreibung vermerkt.":
        "✅ Existing event “{title}” changed: {changes}. Title and description are kept; the change is noted in the "
        "description.",
    "✅ Bestehender Termin „{title}“ aktualisiert: {changes}. Die Änderung ist in der Terminbeschreibung vermerkt.":
        "✅ Existing event “{title}” updated: {changes}. The change is noted in the event description.",
    "Bereits vorhandener gleicher Termin „{title}“ wurde erkannt; fehlende Informationen wurden ergänzt. Kein neuer "
    "Termin wurde angelegt.":
        "An identical existing event “{title}” was recognised; missing details were added. No new event was created.",
    "Bereits vorhandener gleicher Termin „{title}“ wurde erkannt. Kein neuer Termin wurde angelegt.":
        "An identical existing event “{title}” was recognised. No new event was created.",
    "Unklarer Schreiberfolg bei „{title}“; wird weiter abgeglichen und nicht automatisch wiederholt.":
        "Unclear whether “{title}” was written; reconciliation continues and it is not repeated automatically.",
    "Erstellen von „{title}“ fehlgeschlagen.": "Creating “{title}” failed.",
    "als Aufgabe": "as a task",
    "im Kalender": "in the calendar",
    "✅ Angelegt {where}: „{title}“{details}": "✅ Created {where}: “{title}”{details}",
    "✅ Angelegt und geprüft {where}: „{title}“{details}": "✅ Created and checked {where}: “{title}”{details}",
    "Keine offene Rückfrage. Bitte /offen öffnen und beim gewünschten Vorschlag „Klären“, „Ändern“ oder „Manuell "
    "prüfen“ wählen.":
        "No open question. Please open /offen and choose “Clarify”, “Edit” or “Check manually” on the proposal you "
        "want.",
    "Welche Änderung soll übernommen werden?": "Which change should be applied?",
    "Die Überarbeitung ist derzeit nicht verfügbar; der Vorschlag blieb unverändert.":
        "Revising is currently not available; the proposal stayed unchanged.",
    "Der zugehörige Vorschlag wurde nicht gefunden.": "The related proposal was not found.",
    "Die Rückfrage ist veraltet; es wurde nichts geändert.": "The question is outdated; nothing was changed.",
    "Keine offene Rückfrage. Die vorherige Antwort ist bereits gespeichert.":
        "No open question. The previous answer is already saved.",
    "Die autorisierte Antwort ist bereits sicher gespeichert und wird verarbeitet.":
        "The authorised answer is already stored safely and is being processed.",
    "Die Überarbeitung der gespeicherten Antwort wurde nach mehreren Versuchen pausiert. Die Antwort bleibt erhalten. "
    "Zur Wiederaufnahme muss ein Betreiber den Revisionsstatus auf retry_required setzen und Mailhelp neu starten.":
        "Revising the stored answer was paused after several attempts. The answer is kept. To resume, an operator has "
        "to set the revision status to retry_required and restart Mailhelp.",
    "Die interne Verarbeitung der gespeicherten Antwort ist verzögert.":
        "Internal processing of the stored answer is delayed.",
    "Für alle {count} offenen Termine dieser Serie übernehmen? Antwort: {answer}":
        "Apply to all {count} open events of this series? Answer: {answer}",
    "Nur diesen": "Only this one",
    "Angezeigte Termine und Versionen prüfen. Erst diese Bestätigung autorisiert die Anlage.":
        "Check the events and versions shown. Only this confirmation authorises creating them.",
    "Alle {count} Termine anlegen": "Create all {count} events",
    "{title} · {event_time} · ID {id}, Version {version}": "{title} · {event_time} · ID {id}, version {version}",
    "Ungültige Serienentscheidung": "Invalid series decision",
    "Serienauswahl nicht vorhanden oder nicht autorisiert": "Series choice missing or not authorised",
    "Relevanzverarbeitung ist nicht verfügbar": "Relevance processing is not available",
    "✅ E-Mail wurde als {decision} eingestuft.": "✅ Email classified as {decision}.",
    "Zusätzliche Quelle fehlt; Abgleich prüfen": "Additional source missing; check the review",
    "Eingegangen – wird bearbeitet …": "Received – being processed …",
    # Open-decision tools and web replies (7.5.4)
    "({count} aktiv)": "({count} active)",
    "Aktion nicht möglich": "Action not possible",
    "Alle": "All",
    "Anhang nicht vorhanden.": "Attachment not available.",
    "Anzeigen": "Show",
    "Aussortiert": "Sorted out",
    "Bereit zum Bestätigen": "Ready to confirm",
    "Beschädigte Web-Eingaben wurden isoliert. Bitte die Protokolle prüfen.":
        "Damaged web inputs were isolated. Please check the logs.",
    "Die Aktion ist unvollständig oder ungültig.": "The action is incomplete or invalid.",
    "Die Aktion konnte nicht sicher gespeichert werden. Bitte denselben Versuch erneut senden.":
        "The action could not be saved safely. Please send the same attempt again.",
    "Die Anfrage konnte nicht bestätigt werden. Bitte die Seite neu laden und erneut versuchen.":
        "The request could not be verified. Please reload the page and try again.",
    "Die Mail wurde inzwischen geändert oder verarbeitet.": "The email was changed or processed in the meantime.",
    "Diese Aktion ist nicht (mehr) bekannt.": "This action is not known (any more).",
    "Diese Aktion wurde bereits mit anderen Angaben gesendet.": "This action was already sent with other details.",
    "Diese Relevanzfrage ist bereits beantwortet oder veraltet.":
        "This relevance question is already answered or outdated.",
    "Diese abgeschlossene Aktion ist nicht bekannt.": "This finished action is not known.",
    "Dieser Eintrag kann nicht wieder entfernt werden.": "This entry cannot be removed again.",
    "Dieser Eintrag wird bereits geprüft oder wurde inzwischen geändert.":
        "This entry is already being checked or was changed in the meantime.",
    "Dieser Vorschlag ist nicht (mehr) vorhanden.": "This proposal no longer exists.",
    "Dieser Vorschlag wurde inzwischen geändert oder entschieden.":
        "This proposal was changed or decided in the meantime.",
    "Dieser Vorschlag wurde inzwischen geändert oder ist nicht angelegt.":
        "This proposal was changed in the meantime or is not created.",
    "Dieser Vorschlag wurde inzwischen geändert oder ist nicht verworfen.":
        "This proposal was changed in the meantime or is not dismissed.",
    "Duplikate": "Duplicates",
    "Einstellungen werden gespeichert": "Saving settings",
    "Felder bearbeiten": "Edit fields",
    "Keine passenden Entscheidungen.": "No matching decisions.",
    "Mailhelp hat diese Mail als nicht relevant eingestuft. Nach einer Änderung der Themen kann sie mit der aktuellen "
    "Konfiguration erneut geprüft werden; das Ergebnis erscheint nach dem nächsten Abruf.":
        "Mailhelp classified this email as not relevant. After changing the topics it can be checked again with the "
        "current configuration; the result appears after the next fetch.",
    "Mailhelp ist gerade ausgelastet. Bitte gleich erneut versuchen.":
        "Mailhelp is busy right now. Please try again shortly.",
    "Mailhelp wird beendet; keine neuen Aktionen möglich.": "Mailhelp is shutting down; no new actions possible.",
    "Mehr Filter": "More filters",
    "Mit Anhängen": "With attachments",
    "Nach Bearbeitungsbedarf gruppieren": "Group by what is needed",
    "Neueste Mail zuerst": "Newest email first",
    "Nicht gefunden": "Not found",
    "Nicht möglich": "Not possible",
    "Nur Formulardaten werden angenommen.": "Only form data is accepted.",
    "Nächster Termin / nächste Frist zuerst": "Next event / next deadline first",
    "Original nicht vorhanden.": "Original not available.",
    "Revisionshistorie & Differenzen": "Revision history & differences",
    "Rückfrage nötig": "Question needed",
    "Schnellfilter": "Quick filters",
    "Sicherheitsprüfung fehlgeschlagen": "Security check failed",
    "Sortierung": "Sort order",
    "Suchen": "Search",
    "Suchen und sortieren": "Search and sort",
    "Technische LLM-Analyse & Metriken": "Technical LLM analysis & metrics",
    "Termine": "Events",
    "Titel, Betreff oder Absender": "Title, subject or sender",
    "Ungültige Formulardaten.": "Invalid form data.",
    "Ungültige kanonische Vorschlagsreferenz.": "Invalid canonical proposal reference.",
    "Ungültiger Filter.": "Invalid filter.",
    "Weitere Prüfung nötig": "Further check needed",
    "Wird verarbeitet": "Processing",
    "Zurück": "Back",
    "Zurücksetzen": "Reset",
    "gruppiert": "grouped",
    "{shown} von {total}": "{shown} of {total}",
    "Älteste Mail zuerst": "Oldest email first",
    "Beschreibung vollständig anzeigen": "Show full description",
    "Beleg vollständig anzeigen": "Show full evidence",
    # Sender rules (7.7.3)
    "Absender ignorieren": "Ignore sender",
    "Absender wieder zulassen": "Allow sender again",
    "Absender wird ignoriert": "Sender is ignored",
    "Absender-Regeln": "Sender rules",
    "Absenderverwaltung nicht verfügbar.": "Sender management is not available.",
    "Achtung: Das ist ein großer Mailanbieter; die Regel träfe sehr viele Absender.":
        "Caution: this is a large email provider; the rule would match very many senders.",
    "Als VIP einstufen": "Mark as VIP",
    "Als VIP gelten sie ohne Relevanzprüfung als relevant; jeder Eintrag braucht weiterhin deine Bestätigung.":
        "As VIPs they count as relevant without the relevance check; every entry still needs your confirmation.",
    "Als VIP übernehmen": "Make VIP",
    "Art": "Kind",
    "Ausnahmen": "Exceptions",
    "Ausschalten": "Switch off",
    "Bitte eine gültige E-Mail-Adresse oder Domain angeben, z. B. newsletter@example.com oder example.com.":
        "Please enter a valid email address or domain, e.g. newsletter@example.com or example.com.",
    "Derzeit wird kein Absender ignoriert.": "No sender is ignored at the moment.",
    "Die Mail hat keine gültige Absenderadresse.": "The email has no valid sender address.",
    "Diese Regel gibt es bereits.": "This rule already exists.",
    "Diese Regel gibt es nicht mehr.": "This rule no longer exists.",
    "Diese Regel ist ungültig. Muster dürfen nur * als Platzhalter enthalten, höchstens dreimal.":
        "This rule is invalid. Patterns may only use * as a wildcard, at most three times.",
    "Diese Regel würde {matched} der letzten {total} Mails treffen.":
        "This rule would match {matched} of the last {total} emails.",
    "Diese Regeln entscheiden vor jedem KI-Aufruf. Ein VIP-Absender spart nur die Relevanzprüfung; Termine und "
    "Aufgaben brauchen weiterhin deine Bestätigung.":
        "These rules decide before any AI call. A VIP sender only skips the relevance check; events and tasks still "
        "need your confirmation.",
    "Domain wird ignoriert": "Domain is ignored",
    "Domain {domain} ignorieren": "Ignore domain {domain}",
    "Einschalten": "Switch on",
    "Entfernen": "Remove",
    "Für diesen Absender ist diese Regel nicht möglich.": "This rule is not possible for this sender.",
    "Heben jede Sperre für diesen Absender auf, ohne ihn zum VIP zu machen.":
        "Lift every block for this sender without making it a VIP.",
    "Ignorierte Absender": "Ignored senders",
    "Immer relevant, auch wenn eine Sperre passt.": "Always relevant, even if a block matches.",
    "Keine Absenderadresse erkennbar.": "No sender address recognisable.",
    "Keine Ausnahmen.": "No exceptions.",
    "Neue Mails von {senders} werden dann ohne KI-Aufruf und ohne Benachrichtigung aussortiert.":
        "New emails from {senders} are then sorted out without an AI call and without a notification.",
    "Neue Regel": "New rule",
    "Noch kein VIP-Absender.": "No VIP sender yet.",
    "Notiz": "Note",
    "Nur für Postfach (leer: alle)": "Only for mailbox (empty: all)",
    "Postfach {number}": "Mailbox {number}",
    "Regel ausgeschaltet.": "Rule switched off.",
    "Regel eingeschaltet.": "Rule switched on.",
    "Regel für „{value}“ entfernt.": "Rule for “{value}” removed.",
    "Regel für „{value}“ geändert.": "Rule for “{value}” changed.",
    "Regel nicht geändert: ungültig oder nicht schreibbar.": "Rule not changed: invalid or not writable.",
    "Regel speichern": "Save rule",
    "Regeln verwalten": "Manage rules",
    "Sitzung inzwischen abgelaufen.": "The session has expired in the meantime.",
    "Treffer prüfen": "Check matches",
    "VIP-Absender": "VIP senders",
    "Werden ohne KI-Aufruf und ohne Benachrichtigung aussortiert. Neue Domainregeln umfassen auch Subdomains.":
        "Sorted out without an AI call and without a notification. New domain rules include subdomains.",
    "Wert": "Value",
    "Wird durch eine Regel ignoriert": "Ignored by a rule",
    "Wirkung": "Effect",
    "alle Postfächer": "all mailboxes",
    "alle Postfächer · Treffer: {count} · zuletzt: {when}": "all mailboxes · matches: {count} · last: {when}",
    "aus": "off",
    "hebt nur die Sperre auf": "only lifts the block",
    "nie": "never",
    "z. B. newsletter@shop.de, shop.de, no-reply@* oder einen Betreff":
        "e.g. newsletter@shop.com, shop.com, no-reply@* or a subject",
    "{scope} · Treffer: {count} · zuletzt: {when}": "{scope} · matches: {count} · last: {when}",
    "„{value}“ gilt jetzt als VIP-Absender.": "“{value}” is now a VIP sender.",
    "„{value}“ gilt künftig ohne Relevanzprüfung als relevant.":
        "“{value}” will count as relevant without the relevance check from now on.",
    "„{value}“ wird künftig ohne KI-Aufruf aussortiert.":
        "“{value}” will be sorted out without an AI call from now on.",
    "„{value}“ wird nie vorgefiltert.": "“{value}” is never prefiltered.",
    "Adresse": "Address",
    "Domain": "Domain",
    "Muster": "Pattern",
    "VIP – immer relevant": "VIP – always relevant",
    "Nur Ausnahme": "Exception only",
    "Absender immer ignorieren": "Always ignore sender",
    "Absender {address} wird künftig ignoriert.": "Sender {address} will be ignored from now on.",
    "Die Relevanzfrage ist veraltet oder bereits beantwortet": "The relevance question is outdated or already answered",
    "Rückgängig": "Undo",
}
