# Mailhelp 6.1 – Prüfen in der Ersteinrichtung und Dauer jedes Verarbeitungsschritts

**Zielversion:** 6.1.0, Umsetzung in Patchversionen 6.1.1 bis 6.1.9

**Stand:** 13. November 2026

**Status:** Umgesetzt und abgenommen (siehe Release-Bericht)

**Ausgangsstand:** 6.0.x (Ersteinrichtung `/einrichtung/…` aus `web/initial_site.py`, `web/initial_pages.py`,
`runtime/initial_setup.py`, `runtime/setup_checks.py`)

**Vorgänger:** [Planung 6.0](Planung-6.0.md)

**Grundlage:** [Entwicklungsregeln](../AGENTS.md), [Projektspezifikation](../Mailhelp-Projektspezifikation.md),
[Ersteinrichtung](Ersteinrichtung.md)

---

## 0. Bestandsaufnahme

Die Ersteinrichtung im Browser hat fünf Schritte (`TITLES` in `initial_pages.py`):

| Schritt | Inhalt | Heute prüfbar? |
| :--- | :--- | :--- |
| 1 Web-Zugang und Zeitzone | Zeitzone, Web-Passwort | **nein** – nur Formatprüfung beim Speichern |
| 2 Postfach | IMAP-Server, Port, Verschlüsselung, Posteingang, Entwurfsordner, Benutzer, Passwort | ja: „Verbindung jetzt prüfen“ |
| 3 KI-Anbieter | OpenRouter-Schlüssel oder Ollama-Adresse, Modell | ja |
| 4 Kalender und Aufgaben | Google, Todoist, CalDAV, Microsoft; Ziele | ja |
| 5 Abschluss | erneute Prüfung aller Verbindungen, Aktivierung | prüft, zeigt Fehler aber nicht an |

Befunde im Code:

- **Eine einzige Fehlermeldung für alles.** `InitialSite.save` und `InitialSite.probe` fangen jede
  Ausnahme ab und zeigen immer dieselbe Seite „Einrichtung nicht gespeichert – Eingaben und
  Verbindungsdaten prüfen …“ (HTTP 409). Ob der Server nicht erreichbar, das Passwort falsch, der
  Port verwechselt oder ein Modell nicht verfügbar ist, erfährt man nicht. Der Grund ist richtig
  (Anbieterantworten können Zugangsdaten enthalten), die Folge aber, dass man raten muss.
- **Eingaben gehen verloren.** Die Fehlerseite ersetzt das Formular; alle Felder müssen neu
  eingegeben werden.
- **Prüfen speichert.** `probe` ruft `InitialSetup.save(..., probe=True)` auf. Bei Erfolg werden die
  eingegebenen Zugangsdaten sofort in `.env` geschrieben und der Schritt gilt als erledigt. Eine
  reine Prüfung ohne Übernahme gibt es nicht.
- **Erfolg ist schwer lesbar.** Das Ergebnis erscheint als rohe Liste `folders: [...]`,
  `balance: 3.2`, `ready: True`.
- **Schritt 1 und der Abschluss** prüfen gar nicht beziehungsweise melden einen Fehler nur allgemein.
- **Vorhanden und wiederverwendbar:** `SetupChecks` (lesende, zeitbegrenzte Prüfungen),
  `ImapReader.list_folders`/`check_access`, `check_access()` aller Zielanbieter und
  `runtime/diagnostics.error_code` mit groben Codes (`network`, `tls`, `auth`, `permission`,
  `configuration`, `service`, `timeout`) samt Hilfetexten (`HELP`) für `/diagnose`.

Befunde zur Zeitmessung der Verarbeitung:

- **Gemessen werden nur KI-Aufrufe.** Das Metrik-Journal (`runtime/metrics.py`, `AttemptRecord`)
  speichert je Versuch eines KI-Aufrufs Dauer, Schritt, Modell und Kosten. Alles andere – Abruf
  und Aufbereitung der Mail, Anhänge und Bilderkennung, Normalisierung, Vorschlagserstellung,
  Dublettenprüfung, Telegram-Versand, Abschluss – hat keine Dauer.
- **Die Auswertung kann deshalb nur Teile zeigen.** Der Ablaufplan aus 5.9.8 markiert diese Schritte
  als „lokal · nicht gemessen“; die summierte Aufrufdauer ist ausdrücklich „keine Durchlaufzeit“.
  Wie lange eine Mail vom Abruf bis zum Vorschlag braucht und wo die Zeit außerhalb der KI bleibt,
  ist nicht sichtbar.
- **Die Schritte sind im Code eindeutig markiert.** `processing/mail_pipeline.py` setzt
  `run.stage = ProcessingStage.…` beim Wechsel in jeden Schritt, `orchestrator.py` den Abschluss.
  `MetricsRecorder._track_state` kennt den laufenden Schritt bereits für die Statusseite, speichert
  aber keine Dauer.

---

## 1. Ziel

1. **Jeder Schritt hat eine Schaltfläche „Prüfen“**, auch Schritt 1, und der Abschluss zeigt das
   Ergebnis jeder Teilprüfung.
2. **Prüfen ändert nichts.** Es testet die eingegebenen Werte (zusammen mit bereits gespeicherten
   Zugangsdaten, wenn ein Passwortfeld leer bleibt) und speichert weder `.env` noch den Entwurf.
   „Speichern und weiter“ bleibt der einzige schreibende Weg.
3. **Aussagekräftige Meldungen.** Bei einem Fehler nennt die Seite *was* nicht stimmt, *welches Feld*
   betroffen ist und *was zu tun ist* – ohne Zugangsdaten oder Anbieterantworten wiederzugeben.
4. **Eingaben bleiben stehen.** Das Ergebnis erscheint auf derselben Seite über dem Formular; alle
   Felder außer Passwörtern behalten ihren Wert.
5. **Erfolg verständlich darstellen**, etwa „Verbunden mit imap.example.org (SSL, Port 993).
   Posteingang ‚INBOX‘ lesbar, 14 Ordner gefunden, Entwurfsordner ‚Entwürfe‘ erkannt.“
6. **Jeder Verarbeitungsschritt wird gemessen.** Für jede Mail und jeden Schritt aus
   `ProcessingStage` entsteht ein inhaltsfreier Eintrag mit Beginn, Dauer, Ergebnis und dem Anteil,
   der auf KI-Aufrufe entfiel. Dazu kommt die **Durchlaufzeit** je Mail vom Abruf bis zum Abschluss.
7. **Die Auswertung zeigt diese Daten:** echte Dauern im Ablaufplan statt „lokal · nicht gemessen“,
   eine Rangliste der Schritte nach Wanduhrzeit, die Durchlaufzeit je Mail im Zeitverlauf und eine
   Liste der langsamsten Mails je Schritt.

**Nicht Teil von 6.1:** neue Einstellungen in `config.yaml`, Schreibtests bei Kalender oder
Aufgaben (es bleibt bei lesenden Prüfungen), Änderungen an Prompts. Die Einrichtung im
Normalbetrieb (`/einrichtung` aus `setup_site.py`) und `/diagnose` nutzen den neuen Meldungskatalog
mit (Entscheidung E2), bekommen aber keine neue Oberfläche.

---

## 2. Spezifikation

### 2.1 Prüfergebnis

```python
class CheckFinding(BaseModel):
    code: str            # stabiler Schlüssel, z. B. "imap.auth_failed"
    field: str | None    # betroffenes Formularfeld, z. B. "imap.port" oder "IMAP_PASSWORD"
    severity: Literal["error", "warning", "ok"]

class CheckResult(BaseModel):
    step: int
    ok: bool
    summary: str                  # ein Satz, aus festen Texten zusammengesetzt
    findings: list[CheckFinding]  # Reihenfolge = Anzeige
    facts: dict[str, str]         # geprüfte, unkritische Fakten (Servername, Port, Ordnerzahl, Modellnamen)
    checked_at: datetime
```

- Texte stehen in einem **Meldungskatalog** (`runtime/setup_messages.py`): je `code` eine Ursache und
  ein bis drei konkrete Schritte zur Lösung. Angezeigt werden nur Katalogtexte und `facts`. Freitext
  aus Ausnahmen oder Anbieterantworten erreicht den Browser nie.
- `facts` enthalten nur Werte, die der Nutzer selbst eingegeben hat oder die unkritisch sind
  (Ordnernamen, Modellnamen, Guthaben). Benutzernamen werden maskiert (`m***@example.org`).
- Das letzte Ergebnis je Schritt liegt im Einrichtungsentwurf (`InitialDraft.checks[step]`) ohne
  Zugangsdaten, damit es nach Neuladen sichtbar bleibt. Es verfällt, sobald sich ein Feld des
  Schritts oder `.env` ändert (Fingerabdruck der geprüften Werte ohne Geheimnisse).

### 2.2 Prüfungen und Meldungen je Schritt

Die Prüfungen sind lesend und auf 15 Sekunden je Teilprüfung begrenzt (wie heute). Die Tabelle
nennt die wichtigsten Fälle; der Katalog wird im Test vollständig gegen die Ausnahmen der Adapter
geprüft.

**Schritt 1 – Web-Zugang und Zeitzone** (ohne Netzwerk)

| Fall | `code` | Feld | Meldung (gekürzt) |
| :--- | :--- | :--- | :--- |
| Zeitzone unbekannt | `zone.unknown` | `timezone` | „‚Europa/Berlin‘ ist keine bekannte Zeitzone. Schreibweise wie ‚Europe/Berlin‘ verwenden.“ Vorschlag der Browserzeitzone. |
| Passwort zu kurz/leer | `password.too_short` | `password` | „Mindestens 12 Zeichen.“ |
| Passwort mit Steuerzeichen | `password.invalid` | `password` | „Keine Tabulatoren oder Zeilenumbrüche.“ |
| Gespeichertes Passwort vorhanden, Feld leer | `password.kept` (ok) | – | „Das gespeicherte Passwort bleibt erhalten.“ |
| Zugriff über unsicheres HTTP von außen | `web.insecure` (Warnung) | – | Hinweis auf HTTPS/Reverse Proxy, falls nicht `localhost`. |

**Schritt 2 – Postfach** (Reihenfolge: Eingaben → DNS → TCP → TLS → Anmeldung → Ordner)

| Fall | `code` | Feld | Lösungshinweis |
| :--- | :--- | :--- | :--- |
| Pflichtfeld leer | `imap.missing` | jeweiliges Feld | Feld ausfüllen. |
| Servername unbekannt (DNS) | `imap.host_unknown` | `imap.host` | Schreibweise prüfen, z. B. `imap.gmx.net`; keine `https://`-Adresse. |
| Verbindung abgelehnt/Zeitlimit | `imap.unreachable` | `imap.port` | Port und Firewall prüfen; übliche Paare 993/SSL, 143/STARTTLS. |
| Port und Verschlüsselung passen nicht (TLS-Handshake auf 143, Klartext auf 993) | `imap.tls_mismatch` | `imap.connection_mode` | „Port 993 erwartet ‚SSL‘, Port 143 ‚STARTTLS‘.“ |
| Zertifikat ungültig/abgelaufen | `imap.certificate` | `imap.host` | Servernamen exakt wie im Zertifikat; Systemzeit prüfen. |
| Anmeldung abgelehnt | `imap.auth_failed` | `IMAP_PASSWORD` | Benutzername meist die volle Adresse; bei Gmail, Outlook, iCloud ein **App-Passwort** nötig; IMAP im Webmail aktivieren. |
| Konto gesperrt/zu viele Versuche | `imap.locked` | – | Einige Minuten warten, Webmail-Hinweise lesen. |
| Posteingang nicht vorhanden | `imap.folder_missing` | `imap.primary_folder` | Liste der gefundenen Ordner mit Auswahl; typische Namen „INBOX“. |
| Entwurfsordner nicht gefunden | `imap.drafts_missing` (Warnung) | `imap.drafts_folder` | Erkannten Entwurfsordner vorschlagen; ohne ihn keine Antwortentwürfe. |
| Erfolg | `imap.ok` | – | Server, Verschlüsselung, Ordnerzahl, erkannter Posteingang/Entwurfsordner. |

**Schritt 3 – KI-Anbieter**

| Fall | `code` | Feld | Lösungshinweis |
| :--- | :--- | :--- | :--- |
| OpenRouter-Schlüssel fehlt | `llm.key_missing` | `OPENROUTER_API_KEY` | Schlüssel unter openrouter.ai/keys anlegen. |
| Schlüssel ungültig (401/403) | `llm.key_invalid` | `OPENROUTER_API_KEY` | Vollständig kopieren (beginnt mit `sk-or-`), nicht widerrufen. |
| Kein Guthaben (402) / Schlüssellimit erschöpft | `llm.no_credit` | – | Guthaben aufladen oder Limit erhöhen; Betrag wird genannt. |
| Modell nicht verfügbar | `llm.model_missing` | – | Nennt die fehlenden Modellnamen aus `prompts.yaml`. |
| Anbieter überlastet (429/5xx) | `llm.service` | – | Später erneut prüfen. |
| Ollama nicht erreichbar | `llm.ollama_unreachable` | `llm.ollama_address` | Läuft `ollama serve`? Adresse `http://host:11434`; im Docker-Betrieb `host.docker.internal`. |
| Ollama ohne Modelle | `llm.ollama_empty` | `model` | `ollama pull <modell>` ausführen. |
| Gewähltes Ollama-Modell fehlt | `llm.ollama_model_missing` | `model` | Auswahl aus den installierten Modellen. |
| Erfolg | `llm.ok` | – | Anbieter, geprüfte Modelle, Guthaben bzw. installierte Modelle. |

**Schritt 4 – Kalender und Aufgaben** (je Ziel eine Teilprüfung, Ergebnisse getrennt)

| Fall | `code` | Feld | Lösungshinweis |
| :--- | :--- | :--- | :--- |
| Zugangsdaten fehlen | `target.secret_missing` | jeweiliges Feld | Nennt das fehlende Feld (nicht dessen Wert). |
| Google: Refresh-Token ungültig/abgelaufen (`invalid_grant`) | `google.token_expired` | `GOOGLE_OAUTH_REFRESH_TOKEN` | „Google verbinden“ erneut ausführen; im Testmodus laufen Tokens nach 7 Tagen ab. |
| Google: Client-ID/Secret falsch | `google.client_invalid` | `GOOGLE_OAUTH_CLIENT_ID` | Daten aus der Cloud Console; Weiterleitungs-URI prüfen. |
| Google: Kalender nicht gefunden/keine Berechtigung | `google.calendar_missing` | `targets.google_calendar` | „Google-Kalender auswählen“ nutzen. |
| Todoist: Token ungültig | `todoist.token_invalid` | `TODOIST_TOKEN` | Token unter Einstellungen → Integrationen → Entwickler. |
| Todoist: Projekt nicht gefunden | `todoist.project_missing` | `targets.todoist_project` | Vorhandene Projekte zur Auswahl anzeigen. |
| CalDAV: 401 / 404 | `caldav.auth_failed` / `caldav.not_found` | Benutzer/URL | Vollständige Kalender-URL, App-Passwort. |
| Microsoft: Token/Mandant/Liste | `microsoft.*` | jeweiliges Feld | analog |
| Netzwerk/TLS/Zeitlimit | `target.network` usw. | – | aus den allgemeinen Codes |
| Erfolg | `target.ok` | – | Je Ziel: Anbieter und ausgewählter Kalender bzw. Projekt. |

**Schritt 5 – Abschluss:** „Alles prüfen“ führt die Prüfungen 1–4 nacheinander aus und zeigt sie in
einer Übersicht (✓/✗ mit Link „Zu Schritt 2“). „Speichern und starten“ bleibt gesperrt, bis alle
Prüfungen erfolgreich sind; Warnungen blockieren nicht.

### 2.3 Oberfläche

- Jeder Schritt hat zwei Schaltflächen: **Prüfen** (sekundär) und **Speichern und weiter** (primär).
  Beide senden dasselbe Formular; Prüfen geht an `POST /einrichtung/pruefen` und speichert nichts.
- Das Ergebnis steht in einem Kasten über dem Formular (`role="status"`, bei Fehlern
  `role="alert"`): grün „Geprüft – alles in Ordnung“, gelb bei Warnungen, rot bei Fehlern. Jede
  Meldung verlinkt ihr Feld (`#feld-imap-port`); das Feld bekommt `aria-invalid="true"` und
  `aria-describedby` auf die Meldung, und der Fokus springt auf den Kasten.
- Felder behalten ihre Werte; Passwortfelder bleiben leer mit dem Hinweis „gespeicherten Wert
  verwenden“ beziehungsweise „eingegebener Wert wurde geprüft, aber noch nicht gespeichert“.
- Ohne JavaScript funktioniert alles über normale Formulare. Mit JavaScript zeigt `setup.js` während
  der Prüfung „Wird geprüft …“ und sperrt doppeltes Absenden.
- Speichern ohne vorherige erfolgreiche Prüfung bleibt möglich (für Schritte, deren Dienst gerade
  ausfällt), zeigt aber den Hinweis „Noch nicht geprüft“.

### 2.4 Sicherheit

- `POST /einrichtung/pruefen` braucht eine gültige Einrichtungssitzung und CSRF-Token; die Sitzung
  wird vor der Prüfung und vor dem Anzeigen erneut geprüft.
- **Begrenzung:** höchstens 10 Prüfungen je Minute und Sitzung (Schutz vor Passwortraten über die
  IMAP-Anmeldung und vor Sperren durch den Mailanbieter); darüber `429` mit verständlicher Meldung.
- Prüfen schreibt weder `.env` noch `config.yaml`. Die gesendeten Geheimnisse leben nur für die
  Dauer der Prüfung im Speicher.
- Ausnahmen werden über ihren **Typ** und strukturierte Merkmale (HTTP-Status, `socket.gaierror`,
  `ssl.SSLError`-Unterart, IMAP-Antwortcode) eingeordnet, nie über den Meldungstext einer Antwort.
  Das Protokoll erhält Code, Schritt und Dauer, keine Werte.
- Nicht zuordenbare Fehler zeigen `unknown` mit „Unerwarteter Fehler; Details stehen im Protokoll
  unter Kennung …“ (Korrelations-ID, keine Inhalte).

### 2.5 Erweitertes Logging der Schrittdauer

**Messpunkt.** Ein Kontextmanager `stage_timer(run, stage)` in `processing/` umschließt jeden
Schritt der Pipeline dort, wo heute `run.stage` gesetzt wird. Er misst mit `time.monotonic()`
(unabhängig von Uhrumstellungen) und meldet am Ende das Ereignis `stage_finished` an den Logger;
`MetricsRecorder` schreibt daraus eine Zeile. So bleibt die Verarbeitung frei von Dateizugriffen,
und Prozesse ohne aktivierte Metriken (`metrics.enabled: false`) messen nichts.

**Eintrag** (eigenes JSONL neben dem KI-Journal, umgesetzt als `<Metrikdatei>-stages.jsonl`, wie in
AGENTS.md für Logs verlangt):

```python
class StageRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str                      # zufällig, 32 Hex-Zeichen; schützt vor doppeltem Zählen
    mail_id: str | None          # wie im KI-Journal; Vergleichsläufe ohne Mail
    run_id: str
    mode: str                    # standard, local, decision_test
    stage: str                   # ProcessingStage-Wert
    started_at: AwareDatetime
    duration_ms: FiniteFloat     # Wanduhrzeit des Schritts
    llm_ms: FiniteFloat          # Summe der KI-Aufrufe innerhalb des Schritts (aus call_id-Zuordnung)
    outcome: Literal["completed", "failed", "deferred"]   # ein abgebrochener Schritt hat keine Zeile
    analysis_round: int          # erneute Analyse derselben Mail
    resumed: bool                # nach Neustart fortgesetzt
```

- **Durchlaufzeit je Mail:** Beim Abschluss (`completion`) entsteht zusätzlich ein Eintrag
  `stage="total"` mit der Zeit vom Beginn der Aufbereitung bis zum Abschluss. Wartezeit auf eine
  Relevanzentscheidung des Nutzers wird **herausgerechnet** und getrennt als `waiting_ms` geführt,
  damit eine Nachtpause nicht als Verarbeitungszeit erscheint (Entscheidung E5).
- **Aufbereitung genauer:** Der Schritt `preparation` erhält Unterzeiten für Zerlegen der Mail,
  Anhänge (Vorschauen) und Bilderkennung (`parts: dict[str, float]`), weil hier bei großen Anhängen
  die meiste lokale Zeit vermutet wird. Umsetzung 6.1.6: Der Abruf vom Server läuft gebündelt vor der
  Verarbeitung je Postfach und gehört deshalb nicht zum Schritt einer einzelnen Mail.
- **Neustart:** Ein durch Neustart abgebrochener Schritt hat keine Endzeit; der fortgesetzte Schritt
  trägt `resumed: true`, die verlorene Teilzeit wird nicht geschätzt.
- **Inhaltsfrei:** keine Betreffzeilen, Absender, Texte oder Fehlermeldungen; Fehler nur über
  `outcome` und den Fehlercode des Zustands.
- **Aufbewahrung und Verdichtung wie beim KI-Journal:** Einzelzeilen bleiben
  `metrics.retention_days` (Standard 90 Tage), ältere werden je Tag, Modus und Schritt zu Anzahl,
  Summe, Median und 95-%-Wert verdichtet (`stage-daily.json`). Keine neue Einstellung.
- **Aufwand:** höchstens eine Zeile je Schritt und Mail (rund 13 Zeilen je Mail); das Schreiben
  erfolgt gepuffert am Ende jeder Mail und darf die Verarbeitung nicht blockieren. Ein
  Schreibfehler zählt als Erfassungsfehler und unterbricht die Verarbeitung nie.

### 2.6 Auswertung der Schrittdauern

Alle Ansichten nutzen die bestehenden Filter (Zeitraum, Erfassung, Schritt, Von/Bis) und
funktionieren ohne JavaScript; Diagramme bleiben Server-SVG mit Wertetabelle (wie seit 3.3.9).

1. **Ablaufplan mit echten Zeiten.** Jeder Knoten zeigt Median je Mail, Anteil an der
   Durchlaufzeit und – bei KI-Schritten – den KI-Anteil („2,4 s, davon KI 2,1 s“). „lokal · nicht
   gemessen“ erscheint nur noch für Zeiträume ohne Schrittdaten (Altbestand vor 6.1). Der
   Flaschenhals richtet sich nach der Wanduhrzeit, nicht mehr nur nach der KI-Zeit.
2. **Rangliste „Zeit je Verarbeitungsschritt“** nach Wanduhrzeit, je Balken Anteil und Dauer, die
   bisherige KI-Rangliste bleibt als zweite Ansicht erhalten. Wertetabelle: Anzahl, Median, 95 %,
   Maximum, Summe, Fehler, davon KI.
3. **Durchlaufzeit je Mail** als neue Kennzahl in der Faktentabelle (Median / 95 % / Maximum) und als
   Diagramm im Zeitverlauf (Median je Tag bzw. Stunde, Punktwolke wie bei der Aufrufdauer). Der
   Hinweis „Die summierte Aufrufdauer ist keine Durchlaufzeit“ verweist auf diese Kennzahl.
4. **Aufbereitung im Detail:** Aufteilung in Abruf, Zerlegen, Anhänge und Bilderkennung als
   gestapelter Balken.
5. **Langsamste Mails je Schritt:** Ein Klick auf einen Schritt (Rangliste, Ablaufplan oder
   Kennzahl) öffnet `/auswertung/schritte?stage=…`, die langsamsten Durchläufe dieses Schritts mit
   Zeit, Dauer, KI-Anteil, Ergebnis und Link zur Mail – aufgebaut wie die Aufrufliste aus 5.9.10
   (Sortierung, 100 Zeilen je Seite, 422 bei unbekannten Werten, nur lesend, nur mit Anmeldung).
6. **Status-Seite:** Der laufende Schritt nennt zusätzlich, wie lange er schon dauert, und den
   Median dieses Schritts („Bilderkennung seit 41 s, üblich 6 s“).

---

## 3. Architektur

| Modul | Änderung |
| :--- | :--- |
| `runtime/setup_messages.py` (neu) | Meldungskatalog `code → (Ursache, Lösungsschritte, Feld)`; Einordnung von Ausnahmen in Codes |
| `runtime/setup_checks.py` | Prüfungen liefern `CheckResult` statt roher Dicts; Einzelschritte (DNS, TCP, TLS, Login, Ordner) einzeln einordnen; Schritt-1-Prüfung |
| `runtime/initial_setup.py` | `check(actor, form)` ohne Schreibzugriff; `InitialDraft.checks`; Abschluss prüft alles und liefert die Übersicht |
| `web/initial_site.py` | Route `POST /einrichtung/pruefen`; Fehler beim Speichern zeigen Feldmeldungen statt der Sammelseite |
| `web/initial_pages.py` | Ergebniskasten, Feld-IDs, `aria-invalid`, Prüfen-Schaltfläche in jedem Schritt, Abschlussübersicht |
| `web/static/setup.js` | „Wird geprüft …“, Doppelklickschutz, Fokus auf Ergebnis |
| `runtime/diagnostics.py` | nutzt die feineren Codes des Katalogs, wo vorhanden (E2) |
| `processing/stage_timing.py` (neu) | `stage_timer`, Unterzeiten der Aufbereitung, Zuordnung der KI-Aufrufe zum Schritt |
| `processing/mail_pipeline.py`, `orchestrator.py` | jeder Schritt läuft im `stage_timer`; Durchlaufzeit beim Abschluss |
| `runtime/stage_metrics.py` (neu) | `StageRecord`, JSONL-Journal, Verdichtung, Abfragen (Median, 95 %, je Tag) |
| `web/pipeline.py`, `web/charts.py` | Ablaufplan und Rangliste mit Wanduhrzeit; Durchlaufzeit-Diagramm; Aufbereitung im Detail |
| `web/stage_page.py` (neu), `web/history_site.py` | Route `/auswertung/schritte`, Faktentabelle um Durchlaufzeit ergänzt |
| `web/status_pages.py` | Dauer des laufenden Schritts mit üblichem Median |

---

## 4. Umsetzungsschritte

| Schritt | Patch | Inhalt | Tests |
| :--- | :--- | :--- | :--- |
| P1 | 6.1.1 | Ergebnismodell, Meldungskatalog, Einordnung der Ausnahmen | Jeder Code hat Text und Lösung; jede bekannte Ausnahmeart der Adapter wird zugeordnet; kein Ausnahmetext erreicht die Ausgabe (Regression mit Passwort im Fehlertext) |
| P2 | 6.1.2 | Prüfen ohne Speichern, Schritt 1, Route, Begrenzung | Prüfen schreibt weder `.env` noch Entwurf; CSRF, abgelaufene Sitzung, 429 nach 10 Versuchen; Wiederholung |
| P3 | 6.1.3 | Postfach-Prüfung fein aufgeschlüsselt | Simulierter IMAP-Server: DNS-Fehler, abgelehnt, Zeitlimit, Port/Verschlüsselung vertauscht, Zertifikat, Anmeldung, Ordner fehlt, Erfolg |
| P4 | 6.1.4 | KI-Anbieter und Ziele fein aufgeschlüsselt | Simulierte HTTP-Antworten 401/402/403/404/429/5xx, `invalid_grant`, fehlende Modelle, Ollama ohne Modelle |
| P5 | 6.1.5 | Oberfläche: Ergebniskasten, Feldbezug, Eingaben bleiben, Abschlussübersicht | Browsertests Desktop/Mobil/schmal, ohne JavaScript, Tastatur und Screenreader-Attribute, axe; Regression „Eingaben gehen nach Fehler verloren“ |
| P6 | 6.1.6 | Schrittzeiten erfassen (2.5) | Jeder `ProcessingStage` erzeugt genau einen Eintrag; Ergebnisarten completed/skipped/failed/deferred; Neustart mitten im Schritt (`resumed`); erneute Analyse; Wartezeit auf Relevanzentscheidung herausgerechnet; KI-Anteil passt zum KI-Journal; Metriken aus → keine Messung; Schreibfehler unterbricht nichts; keine Inhalte im Journal |
| P7 | 6.1.7 | Verdichtung und Abfragen | Aufbewahrungsgrenze, Tagesverdichtung ohne Doppelzählung nach Neustart, beschädigte Zeilen, Median/95 % mit 0, 1 und vielen Werten |
| P8 | 6.1.8 | Auswertung (2.6) | Ablaufplan mit echten Zeiten und Altbestand ohne Schrittdaten; Rangliste; Durchlaufzeit-Kennzahl und -Diagramm; Aufbereitung im Detail; `/auswertung/schritte` (Anmeldung, 422, Sortierung, Seiten, Mail-Links); Statusseite; Browsertests Desktop/Mobil/Breitbild, ohne JavaScript, axe |
| P9 | 6.1.9 | Doku, Abnahme, Release | README, CHANGELOG, Bedienung/Ersteinrichtung (mit Tabelle häufiger Meldungen), Bedienung „Auswertung lesen“, Spezifikation, `docs/Release-6.1.md` |

Jeder Schritt hält 100 % Zeilen- und Branch-Abdeckung; jeder Bugfix (Sammelmeldung, verlorene
Eingaben, Prüfen speichert) bekommt einen Regressionstest, der vor dem Fix scheitert. Externe
Dienste sind in Tests simuliert, Daten synthetisch.

---

## 5. Abnahmekriterien

| Kriterium | Prüfung | Erwartung |
| :--- | :--- | :--- |
| Prüfen in jedem Schritt | Schritte 1–5 öffnen | Jeder Schritt hat „Prüfen“; der Abschluss zeigt alle Teilergebnisse |
| Prüfen ändert nichts | Prüfen mit neuen Zugangsdaten | `.env`, `config.yaml` und Entwurf unverändert |
| Falsches IMAP-Passwort | simulierte Anmeldung abgelehnt | Meldung „Anmeldung abgelehnt“ am Passwortfeld mit App-Passwort-Hinweis; Passwort nirgends im HTML oder Protokoll |
| Port/Verschlüsselung vertauscht | 993 mit STARTTLS | Meldung nennt die passenden Paare und markiert „Verschlüsselung“ |
| Ungültiger KI-Schlüssel / kein Guthaben | 401 bzw. 402 | jeweils eigene Meldung mit Lösung |
| Google-Token abgelaufen | `invalid_grant` | Hinweis „Google verbinden“ erneut ausführen |
| Eingaben bleiben | Fehler in Schritt 2 | alle Nicht-Passwort-Felder behalten ihren Wert |
| Kein Geheimnis in Ausgaben | Fehlertexte mit eingebetteten Zugangsdaten | weder in HTML, noch in Protokoll, noch im Entwurf |
| Begrenzung | 11 Prüfungen in einer Minute | 11. Antwort 429 mit Erklärung |
| Barrierefreiheit | axe, Tastatur | Ergebniskasten wird angesagt, Links springen ins Feld |
| Schrittzeiten vollständig | synthetische Mail durch alle Schritte | je Schritt ein Eintrag; Summe der Schritte ≈ Durchlaufzeit (Abweichung unter 5 %) |
| Durchlaufzeit ohne Wartezeit | Mail wartet 8 Std. auf Relevanzentscheidung | Durchlaufzeit ohne die 8 Std.; Wartezeit getrennt ausgewiesen |
| Ablaufplan mit Zeiten | `/auswertung` mit Schrittdaten | kein „lokal · nicht gemessen“ mehr; Flaschenhals nach Wanduhrzeit |
| Langsamste Mails | Klick auf einen Schritt | `/auswertung/schritte` mit passender Voreinstellung und Links zu den Mails |
| Altbestand | Zeitraum nur vor 6.1 | Auswertung wie in 5.9, ohne Fehler |
| Datenschutz der Schrittzeiten | Journal durchsuchen | keine Betreffzeilen, Absender, Texte oder Fehlermeldungen |
| Abdeckung | `pytest` | 100 % Zeilen und Branches |

---

## 6. Entscheidungen

Am 13.11.2026 ohne Gegenvorschlag mit dem jeweiligen **Vorschlag** übernommen:

1. **E1 – Prüfen speichert nicht.** Heute übernimmt „Verbindung jetzt prüfen“ bei Erfolg die Werte.
   Vorschlag: Prüfen speichert nie; nur „Speichern und weiter“ schreibt. Alternative: „Prüfen und
   speichern“ als eine Schaltfläche.
2. **E2 – Reichweite.** Vorschlag: Der Meldungskatalog wird auch von `/diagnose` und der Einrichtung im
   Normalbetrieb genutzt (feinere Hinweise dort ohne neue Oberfläche). Alternative: nur die
   Ersteinrichtung.
3. **E3 – Abschluss nur nach erfolgreicher Prüfung.** Vorschlag: „Speichern und starten“ erst, wenn
   alle Prüfungen bestanden sind. Alternative: Start mit Warnung erlauben (etwa wenn ein Ziel
   vorübergehend nicht erreichbar ist).
4. **E4 – Telegram.** Die Ersteinrichtung fragt heute keine Telegram-Daten ab. Soll ein optionaler
   Schritt „Benachrichtigungen“ mit Testnachricht dazukommen, oder bleibt das bei der Einrichtung im
   Normalbetrieb?
5. **E5 – Wartezeit in der Durchlaufzeit.** Vorschlag: Die Zeit, in der eine Mail auf deine
   Relevanzentscheidung wartet, zählt nicht zur Durchlaufzeit und wird getrennt gezeigt.
   Alternative: Durchlaufzeit als reine Zeit vom Abruf bis zum fertigen Vorschlag.
6. **E6 – Feinheit der Aufbereitung.** Vorschlag: Unterzeiten für Abruf, Zerlegen, Anhänge und
   Bilderkennung. Alternative: nur die Gesamtzeit des Schritts (weniger Code, weniger Einblick).
7. **E7 – Vergleichsläufe.** Vorschlag: Schrittzeiten der Decision-Tests landen wie die KI-Aufrufe in
   einem getrennten Journal und erscheinen nur unter der Erfassung „Vergleichsläufe“.
