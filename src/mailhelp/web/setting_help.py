"""Shared explanations for the web settings and the checked documentation table."""
from .pages import e

SETTING_HELP = {
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

for _service, _label in {"imap": "IMAP", "telegram": "Telegram", "openrouter": "OpenRouter", "ollama": "Ollama",
                         "todoist": "Todoist", "google_calendar": "Google Kalender"}.items():
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
