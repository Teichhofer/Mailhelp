"""Shared explanations for the web settings and the checked documentation table."""

from __future__ import annotations

from .pages import e

SETTING_HELP = {
    "event_defaults.video_duration_minutes": "Standarddauer Videokonferenz: 1–1440 Minuten; Standard 60. Ergänzt ein fehlendes Ende nur bei eindeutigem Beginn und belegter Online-Teilnahme. Explizite Endzeiten und Dauern haben Vorrang. Bestehende Vorschläge werden nicht automatisch umgerechnet; Speichern autorisiert keine Kalenderaktion.",
    "event_defaults.in_person_duration_minutes": "Standarddauer Präsenztermin: 1–1440 Minuten; Standard 180. Ergänzt ein fehlendes Ende bei belegter Präsenz und eindeutigem Beginn. Eine Anschrift in der Signatur belegt keine Präsenz. Explizite Zeitangaben haben Vorrang; die Annahme wird im Vorschlag angezeigt.",
    "proposal_reconciliation.max_semantic_candidates": "1–50 mögliche offene Vorschläge je semantischem KI-Vergleich; Standard 8. Weitere plausible Treffer blockieren die automatische Zuordnung, statt als fehlende Dublette zu gelten. Ein fehlender Vergleichsprompt erfordert bei unklaren Fällen eine manuelle Zuordnung.",
    "poll_interval_seconds": "Abstand zwischen Mailabrufen: 5–86400 Sekunden. 60 prüft etwa jede Minute, 300 etwa alle fünf Minuten. Kleinere Werte erkennen neue Mails früher, größere entlasten den Mailserver. Ein laufender Durchlauf kann den nächsten Abruf verzögern.",
    "timezone": "Zeitzone für lokale Datums- und Zeitangaben, z. B. Europe/Berlin mit automatischer Sommerzeit oder UTC ohne Zeitumstellung. Verwende einen gültigen IANA-Zeitzonennamen. Eine andere Zone verändert die Interpretation lokaler Terminzeiten und deren Anzeige.",
    "test_mode": "ja (true) aktiviert den Trockenlauf: bestätigte Kalender- und Todoist-Aktionen werden simuliert; Testdaten werden getrennt gespeichert. nein (false) aktiviert echte Schreibaktionen nach ausdrücklicher Bestätigung. Der Trockenlauf verhindert nicht sämtliche Netzwerkzugriffe, etwa Mailabruf und KI-Aufrufe.",
    "personal_info": "Bis zu 2000 Zeichen, z. B. Name, Rolle, Signatur oder gewünschte Anrede. Diese Angaben erhält das KI-Modell beim Erstellen eines Antwort-Entwurfs. Leer bedeutet keine persönlichen Zusatzangaben. Mehr Kontext kann Ton und Inhalt des Entwurfs verändern; die Angaben werden nicht für die Mailanalyse verwendet.",
    "targets.todoist_project": "ID des Todoist-Projekts für neue Aufgabenvorschläge, nicht dessen Anzeigename. Eine andere ID lenkt neue Vorschläge in ein anderes Projekt; bestehende Aufgaben werden nicht verschoben. Nicht leer, höchstens 500 Zeichen. Die Anlage erfordert weiterhin deine ausdrückliche Bestätigung.",
    "targets.google_calendar": "ID des Zielkalenders für neue Terminvorschläge. primary bezeichnet den Hauptkalender; eine konkrete Kalender-ID wählt einen anderen zugänglichen Kalender. Bestehende Termine werden nicht verschoben. Nicht leer, höchstens 500 Zeichen. Die Anlage erfordert weiterhin deine ausdrückliche Bestätigung.",
    "limits.llm_calls_per_minute": "Budget von 1–600 KI-Aufrufen pro Minute. Ein kleinerer Wert bremst die Verarbeitung und reduziert Lastspitzen; ein größerer erlaubt mehr Aufrufe, soweit Anbieter und übrige Grenzen dies zulassen. Dies ist keine feste Geld- oder Tageskostengrenze.",
    "limits.max_mail_bytes": "Größengrenze für die Mailverarbeitung: 1024–100000000 Bytes. 1000000 entspricht ungefähr 1 MB. Größere Werte erlauben größere Mails und erhöhen den Ressourcenbedarf; kleinere können zur Ablehnung zu großer Inhalte führen. Anhänge und weitere MIME-Grenzen werden zusätzlich geprüft.",
    "limits.max_llm_payload_bytes": "Größengrenze für aufbereitete Maildaten an die KI: 1–100000000 Bytes, keine Tokenzahl. Größere Werte erlauben mehr Inhalt und können Kosten und Laufzeit erhöhen. Zu große aufbereitete Inhalte werden abgewiesen; ein kleinerer Wert ist keine automatische Zusammenfassung.",
    "logging.console.level": "Mindeststufe der Konsolenmeldungen: DEBUG zeigt auch Diagnoseangaben, INFO den normalen Ablauf, WARNING nur Warnungen und schwerere Meldungen, ERROR Fehler und CRITICAL nur schwerste Fehler. Höhere Stufen reduzieren die Ausgabe und erschweren die Fehlersuche. Inhaltsprotokolle werden separat gesteuert.",
    "logging.file.level": "Mindeststufe der allgemeinen Logdatei: DEBUG enthält Diagnoseangaben, INFO den normalen Ablauf, WARNING Warnungen und schwerere Meldungen, ERROR Fehler und CRITICAL nur schwerste Fehler. Höhere Stufen reduzieren die Datenmenge. Separate KI-Inhaltslogs werden damit nicht aktiviert oder deaktiviert.",
    "logging.llm.include_requests": "ja (true) erlaubt vollständige KI-Anfragen im separaten KI-Log, sofern dieses aktiviert ist. Das kann Prompts und private Mailinhalte speichern und benötigt mehr Speicher. nein (false) lässt die vollständigen Anfrageinhalte weg. Bereits geschriebene Logs werden dadurch nicht gelöscht.",
    "logging.llm.include_responses": "ja (true) erlaubt vollständige KI-Antworten im separaten KI-Log, sofern dieses aktiviert ist. Das hilft bei der Fehlersuche, kann aber private Inhalte speichern. nein (false) lässt vollständige Antwortinhalte weg. Bereits geschriebene Logs werden dadurch nicht gelöscht.",
    "metrics.enabled": "ja (true) erfasst Messwerte zu KI-Aufrufen, Laufzeiten und Kosten ohne Mailinhalte. nein (false) stoppt neue Messungen; bereits erfasste Werte bleiben bis zur Bereinigung vorhanden. Diese Einstellung schaltet weder KI-Aufrufe noch die allgemeinen Logs ab.",
    "metrics.retention_days": "Aufbewahrung einzelner Messungen: 1–3650 Tage. 30 hält ungefähr einen Monat, 90 ungefähr drei Monate vor. Kürzere Fristen sparen Speicher, schränken aber rückblickende Auswertungen ein. Ältere Messungen werden bereinigt; disabled und unlimited sind hier nicht erlaubt.",
    "metrics.usd_per_eur": "US-Dollar je Euro, größer als 0: Bei 1.1 werden 11 USD als 10 EUR angezeigt. Ein höherer Kurs ergibt für denselben Dollarbetrag weniger Euro. null deaktiviert die Euro-Umrechnung; dann muss auch das Kursdatum null sein. Der Kurs wird manuell gepflegt, nicht automatisch abgerufen.",
    "metrics.exchange_rate_date": "Bezugsdatum des manuell gepflegten Wechselkurses im Format JJJJ-MM-TT, z. B. 2026-10-12. null lässt das Datum offen. Es kennzeichnet die Aktualität des Kurses und verändert den Umrechnungsfaktor nicht. Ein Datum ist nur mit gesetztem Wechselkurs erlaubt.",
    "metrics.ollama_power_watts": "Angenommene Leistungsaufnahme während lokaler KI-Aufrufe: 0–100000 Watt. 300 steht für 300 W; doppelte Leistung ergibt bei gleicher Dauer doppelte geschätzte Stromkosten. 0 ergibt keine geschätzten Stromkosten. Dies misst oder begrenzt die tatsächliche Hardwareleistung nicht.",
    "metrics.electricity_eur_per_kwh": "Strompreis für lokale KI-Kostenschätzungen: 0–100 EUR/kWh. 0.30 bedeutet 30 Cent je kWh. Ein höherer Preis erhöht die Schätzung proportional; 0 ergibt keine geschätzten Stromkosten. Der Wert beeinflusst weder Cloudpreise noch den Stromverbrauch.",
}

_RETENTION = (" 1–3650 bedeutet volle Tage seit der letzten Aktualisierung des abgeschlossenen Vorgangs. "
              "Kleinere Werte entfernen Inhalte früher. disabled entfernt sie beim nächsten Bereinigungslauf, "
              "unlimited bewahrt sie ohne Frist auf. Offene Vorgänge bleiben geschätzt. Entfernte Inhalte "
              "lassen sich durch späteres Verlängern der Frist nicht wiederherstellen.")
for _name, _text in {
    "full_mail_days": "Aufbewahrung gespeicherter Mailtexte, Bildvorschauen und lokaler Entwurfstexte; die Originalmail im Postfach wird nicht gelöscht.",
    "debug_llm_days": "Aufbewahrung von KI-Diagnosedaten im Vorgang, etwa Zusammenfassung und Validierungsfehlern; separate JSONL-Logdateien haben eigene Fristen.",
    "analysis_days": "Aufbewahrung archivierter Analysen. null übernimmt die Frist für KI-Diagnosedaten (debug_llm_days).",
    "history_days": "Aufbewahrung des Vorgangsverlaufs und der Inhalte historischer Vorschlagsversionen; Kennungen zum Schutz vor Doppelanlagen bleiben erhalten.",
}.items():
    SETTING_HELP["retention." + _name] = _text + _RETENTION

SETTING_HELP.update({
    "targets.calendar_provider": "Dienst für neue Terminvorschläge: google (Google Kalender), caldav (z. B. Nextcloud, iCloud, mailbox.org) oder outlook (Outlook / Microsoft 365). Der Wechsel wirkt nach einem Neustart; bereits bestätigte Vorschläge für das bisherige Ziel werden nicht in das neue geschrieben. Zuerst das passende Ziel eintragen, dann den Dienst wechseln. Zugangsdaten unter Einstellungen → Zugangsdaten oder in der .env-Datei eintragen.",
    "targets.task_provider": "Dienst für neue Aufgabenvorschläge: todoist, microsoft_todo (Microsoft To Do), caldav (Aufgabenliste mit VTODO, z. B. Nextcloud Tasks) oder apple_reminders (iCloud-Erinnerungen über CalDAV; auf die neuen iCloud-Erinnerungen aktualisierte Listen sind dort nicht erreichbar). Der Wechsel wirkt nach einem Neustart. Zuerst das passende Ziel eintragen, dann den Dienst wechseln.",
    "targets.caldav_calendar_url": "Vollständige https-Adresse der CalDAV-Kalendersammlung, z. B. https://cloud.example.org/remote.php/dav/calendars/anna/personal/. Nur bei Kalenderdienst caldav benötigt; Anmeldung mit CALDAV_USERNAME und App-Passwort CALDAV_PASSWORD. Bestehende Einträge werden nicht verschoben. Die Anlage erfordert weiterhin deine ausdrückliche Bestätigung.",
    "targets.caldav_task_url": "Vollständige https-Adresse der CalDAV-Aufgabenliste (VTODO), z. B. https://cloud.example.org/remote.php/dav/calendars/anna/tasks/. Bei Apple Erinnerungen eine Adresse unter https://caldav.icloud.com. Bestehende Einträge werden nicht verschoben. Die Anlage erfordert weiterhin deine ausdrückliche Bestätigung.",
    "targets.outlook_calendar": "ID des Outlook-Kalenders oder default für den Standardkalender des angemeldeten Microsoft-Kontos. Nur bei Kalenderdienst outlook benötigt. Bestehende Einträge werden nicht verschoben. Die Anlage erfordert weiterhin deine ausdrückliche Bestätigung.",
    "targets.microsoft_todo_list": "ID der Microsoft-To-Do-Liste oder default für die Standardliste „Aufgaben“. Nur bei Aufgabendienst microsoft_todo benötigt. Bestehende Einträge werden nicht verschoben. Die Anlage erfordert weiterhin deine ausdrückliche Bestätigung.",
    "targets.microsoft_tenant": "Microsoft-Mandant für die Anmeldung: common (private und geschäftliche Konten), consumers, organizations oder die Mandanten-ID. Gilt für Outlook-Kalender und Microsoft To Do.",
    "attachments.store_originals": "ja (true) speichert Originaldokumente (PDF, Word, Excel, OpenDocument, Text, Bilder) neu verarbeiteter Mails zum Herunterladen in der Weboberfläche. nein (false) speichert nur Bildvorschauen. Gespeicherte Originale werden mit der Aufbewahrungsfrist für Mailinhalte gelöscht.",
    "attachments.max_original_bytes": "Größte Datei, die als Original gespeichert wird: 1024–104857600 Bytes (Standard 25 MB). Größere Anhänge bleiben nur im Postfach.",
    "attachments.max_total_bytes": "Höchstens so viele Bytes an Originalen je Mail: 1024–524288000 (Standard 50 MB). Weitere Anhänge derselben Mail werden nicht gespeichert.",
})

# 3.3.12 (Planung 3.4): further operational settings.
SETTING_HELP.update({
    "imap.batch_size": "Höchstens so viele neue Mails nimmt ein Abrufdurchlauf über alle Postfächer auf: 1–1000; Standard 25. Größere Werte arbeiten Rückstände schneller ab, verlängern aber einen einzelnen Durchlauf; kleinere verteilen die Arbeit auf mehr Durchläufe. --max-mails ersetzt den Wert für einen einzelnen Lauf.",
    "imap.global_newest_first": "ja (true) wählt je Durchlauf die neuesten Mails über alle Postfächer und Ordner nach Empfangszeit. nein (false) arbeitet Postfach für Postfach und Ordner für Ordner in der konfigurierten Reihenfolge. Die Einstellung bestimmt nur die Reihenfolge, nicht welche Mails verarbeitet werden.",
    "telegram.user_id": "Numerische Telegram-ID des einzigen Kontos, dessen Eingaben Mailhelp annimmt; größer als 0. Nachrichten anderer Konten werden ignoriert. Eine falsche ID sperrt die Bedienung über Telegram aus; die Weboberfläche bleibt nutzbar.",
    "telegram.chat_id": "Numerische ID des Chats, in den Mailhelp schreibt; bei einem Privatchat meist gleich der Benutzer-ID. Eine falsche ID führt zu Zustellfehlern; Diagnose und --check-access melden sie und nennen gefundene Chats.",
    "telegram.sequential_questions": "ja (true) zeigt jeweils nur die aktuelle Entscheidung mit Schaltflächen; weitere folgen nacheinander. nein (false) sendet alle offenen Vorschläge sofort. Nacheinander verhindert verwechselte Antworten, wenn viele Fragen gleichzeitig offen sind.",
    "smart_reply": "ja (true) bietet in der Weboberfläche KI-Antwortentwürfe an; sie werden nur nach ausdrücklichem Speichern im Entwurfsordner des Postfachs abgelegt, Mailhelp versendet nie selbst. nein (false) blendet die Funktion aus. Postfächer können den Wert einzeln überschreiben; benötigt den Schritt draft_reply in prompts.yaml.",
    "vision.enabled": "ja (true) lässt Bildanhänge und gescannte PDFs vom KI-Modell lesen (Schritt vision_ocr in prompts.yaml), damit Termine und Aufgaben darin erkannt werden; die Bilder werden dafür übertragen und verursachen Kosten. nein (false) wertet nur Text aus.",
    "vision.max_images_per_mail": "Höchstens so viele Bilder je Mail werden ausgewertet: 1–10; Standard 3. Mehr Bilder erfassen umfangreiche Scans vollständiger und erhöhen Kosten und Laufzeit.",
    "vision.max_image_bytes": "Größere Bilder werden nicht ausgewertet: 10240–50000000 Bytes; Standard 10485760 (10 MB). Größere Werte erlauben hochaufgelöste Scans und erhöhen Speicher- und Übertragungsbedarf.",
    "vision.max_edge_pixels": "Bilder werden vor der Übertragung auf diese längste Kante verkleinert: 512–4096 Pixel; Standard 1600. Größere Werte erhalten feine Schrift besser und erhöhen Datenmenge und Kosten.",
    "daily_briefing.include_calendar": "ja (true) nimmt die heutigen Termine des Zielkalenders in den Tagesüberblick auf. nein (false) lässt sie weg. Wirkt nur bei aktiviertem Tagesüberblick.",
    "daily_briefing.include_tasks": "ja (true) nimmt fällige Aufgaben der Aufgabenliste in den Tagesüberblick auf. nein (false) lässt sie weg. Wirkt nur bei aktiviertem Tagesüberblick.",
    "daily_briefing.include_open": "ja (true) nennt im Tagesüberblick die offenen Vorschläge und Rückfragen. nein (false) lässt sie weg. Wirkt nur bei aktiviertem Tagesüberblick.",
    "activity_report.enabled": "ja (true) erlaubt Tätigkeitsberichte in der Weboberfläche: ein reiner Lesedurchlauf durch ein Postfach zu einem Thema mit XLSX-Export; benötigt die Schritte activity_relevance und activity_events in prompts.yaml. nein (false) blendet die Funktion aus.",
    "activity_report.max_mails": "Ein Bericht pausiert nach so vielen gelesenen Mails: 1–20000; Standard 2000. Größere Werte erfassen längere Zeiträume und erhöhen Laufzeit und KI-Kosten.",
    "activity_report.max_llm_calls": "Ein Bericht pausiert nach so vielen KI-Aufrufen: 1–50000; Standard 3000. Die Grenze schützt vor unerwartet hohen Kosten; ein pausierter Bericht lässt sich fortsetzen.",
    "activity_report.max_share_of_llm_budget": "Anteil von limits.llm_calls_per_minute, den ein laufender Bericht nutzen darf: größer als 0 bis 1; Standard 0.5. Kleinere Werte lassen der normalen Mailverarbeitung mehr Spielraum und verlangsamen den Bericht.",
    "activity_report.max_fulltext_chars": "Volltexte im Export werden auf so viele Zeichen gekürzt: 1000–32000; Standard 30000, passend zur Zellgrenze von Excel.",
    "activity_report.export_mails_without_events": "ja (true) exportiert auch relevante Mails ohne erkannte Termine. nein (false) exportiert nur Mails mit erkannten Terminen.",
    "learning.parallel_llm_calls": "Gleichzeitige KI-Aufrufe im Lernmodus (--learn): 1–100; Standard 4. Mehr parallele Aufrufe beschleunigen das Lernen und erhöhen Lastspitzen; das Minutenbudget limits.llm_calls_per_minute gilt weiterhin.",
    "web.session_days": "So lange bleibt ein gekoppeltes Gerät angemeldet, bevor es neu gekoppelt werden muss: 1–365 Tage; Standard 30. Kürzere Werte verringern das Risiko verlorener Geräte, längere ersparen Kopplungen.",
    "web.lan_access": "ja (true) macht die Weboberfläche im eigenen WLAN unter der privaten IP-Adresse des PCs erreichbar (unverschlüsseltes HTTP); erfordert web.host 0.0.0.0, sonst wird die Änderung abgelehnt. nein (false) beschränkt den Zugriff auf diesen PC und die freigegebenen Adressen.",
    "logging.console.enabled": "ja (true) schreibt Meldungen ins Terminal bzw. in das Containerprotokoll. nein (false) unterdrückt die Konsolenausgabe; die Logdatei bleibt davon unberührt.",
    "logging.file.enabled": "ja (true) schreibt die allgemeine Logdatei im Logverzeichnis. nein (false) schreibt keine allgemeine Logdatei; die Fehlersuche wird dadurch erschwert.",
    "logging.llm.enabled": "ja (true) schreibt das separate KI-Log mit Aufrufmetadaten; vollständige Inhalte nur, wenn zusätzlich Anfragen oder Antworten freigegeben sind. nein (false) schreibt kein KI-Log.",
    "logging.llm.level": "Mindeststufe des KI-Logs: DEBUG enthält Diagnoseangaben, INFO den normalen Ablauf, WARNING Warnungen und schwerere Meldungen, ERROR Fehler und CRITICAL nur schwerste Fehler. Höhere Stufen reduzieren die Datenmenge.",
    "logging.telegram.enabled": "ja (true) schreibt ein separates Prüfprotokoll der Telegram-Nachrichten einschließlich Inhalten. nein (false) verzichtet darauf; Zustellungen bleiben im allgemeinen Log ohne Inhalte sichtbar.",
    "logging.telegram.level": "Mindeststufe des Telegram-Logs: DEBUG enthält Diagnoseangaben, INFO den normalen Ablauf, WARNING Warnungen und schwerere Meldungen, ERROR Fehler und CRITICAL nur schwerste Fehler.",
})
SETTING_HELP["retention.activity_report_days"] = "Aufbewahrung gespeicherter Tätigkeitsberichte und ihrer Exporte; das Postfach bleibt unverändert." + _RETENTION

for _service, _label in {"imap": "IMAP", "telegram": "Telegram", "openrouter": "OpenRouter", "ollama": "Ollama",
                         "todoist": "Todoist", "google_calendar": "Google Kalender", "caldav": "CalDAV",
                         "microsoft": "Microsoft 365"}.items():
    _maximum = 1800 if _service == "ollama" else 300
    for _name, _text in {
        "timeout_seconds": f"Zeitlimit eines Aufrufversuchs: 1–{_maximum} Sekunden. Kleine Werte erkennen nicht antwortende Dienste schneller, können aber langsame Antworten abbrechen. Große Werte geben dem Dienst mehr Zeit und verlängern mögliche Wartezeiten.",
        "retries": "Zusätzliche Wiederholungen bei wiederholbaren Dienstfehlern: 0–10. 0 bedeutet nur den ersten Versuch, 2 erlaubt bis zu drei Versuche insgesamt. Mehr Wiederholungen können vorübergehende Fehler überbrücken, erhöhen aber Laufzeit und gegebenenfalls Kosten. Unklare externe Schreibresultate werden vor einer erneuten Anlage abgeglichen.",
        "initial_backoff_seconds": "Erste Wartezeit vor einem Wiederholungsversuch: 0–30 Sekunden. 0 wartet zunächst nicht; größere Werte lassen dem Dienst mehr Erholungszeit. Weitere Wartezeiten steigen bis zur längsten Wartezeit. Ohne Wiederholungen hat dieser Wert keine Wirkung.",
        "max_backoff_seconds": "Obergrenze der Wartezeit zwischen Wiederholungsversuchen: 0–60 Sekunden und mindestens so groß wie die erste Wartezeit. Größere Werte erlauben längere Pausen, kleinere begrenzen die Verzögerung. Ohne Wiederholungen hat dieser Wert keine Wirkung.",
    }.items():
        SETTING_HELP[f"timeouts.{_service}.{_name}"] = f"{_label}: {_text}"

for _step, _label in {"interpretation": "Verstehen einer Telegram-Antwort", "revision": "Überarbeiten eines Vorschlags"}.items():
    SETTING_HELP[f"retries.{_step}_attempts"] = (
        f"Gesamtzahl der Versuche beim { _label}: 1–20, einschließlich des ersten Versuchs. "
        "1 erlaubt keinen erneuten Versuch; 3 erlaubt bis zu drei Versuche. Höhere Werte können vorübergehende "
        "KI-Fehler auffangen, verlängern aber die Verarbeitung und können mehr KI-Aufrufe verursachen.")
    SETTING_HELP[f"retries.{_step}_backoff_seconds"] = (
        f"Wartezeit vor einem erneuten Versuch beim {_label}: 1–86400 Sekunden. 60 bedeutet eine Minute, "
        "300 fünf Minuten. Größere Werte geben dem Dienst mehr Erholungszeit und verzögern die Fortsetzung. "
        "Wenn nur ein Versuch erlaubt ist, entsteht keine Wiederholung.")

EXTRA_HELP = {
    "models": "Die Tabelle zeigt die tatsächlich verwendeten KI-Modelle, Parameter und deren Quelle. Andere Modelle können Qualität, Geschwindigkeit und Kosten verändern. Parameter und Modelle werden in prompts.yaml gepflegt; ein Start mit --ollama kann die Modellwahl ersetzen. Hier ist die Anzeige nur lesbar.",
    "push": "Push aktivieren meldet diesen Browser für inhaltsneutrale Hinweise an; Mailbetreff und Mailtext werden nicht übertragen. Push deaktivieren beendet das Abonnement dieses Browsers. Andere Geräte bleiben unverändert. Die Funktion benötigt serverseitig aktiviertes Web-Push und deine Browserfreigabe; HTTPS oder localhost ist erforderlich.",
}


def help_bubble(name: str, label: str, text: str) -> str:
    """A focusable, touch-sized trigger, with escaped content and a stable description."""
    identity = "help-" + name.replace(".", "-")
    return (f'<span class="setting-help"><button type="button" class="info-trigger" '
            f'aria-label="Info zu {e(label)}" aria-describedby="{e(identity)}">'
            '<span aria-hidden="true">i</span></button>'
            f'<span class="setting-tooltip" role="tooltip" id="{e(identity)}">{e(text)}</span></span>')
