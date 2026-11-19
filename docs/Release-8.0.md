# Mailhelp 8.0 – Google-Konten über Inboxstride verbinden und verwalten

**Stand:** 19. November 2026. **Status:** In Umsetzung. Version 7.9.3 liefert als Vorbereitung die
Grundlage des zentralen Anmeldedienstes; Schnittstellen, Instanzintegration, Einrichtung,
Serverhandbuch und Inbetriebnahme folgen. Plan: [Planung 8.0](Planung-8.0.md).

**Versionsnummer:** Ein Wechsel der Hauptversion verlangt nach Regel K6 eine nachgewiesene Prüfung
aller lebenden Dokumente für 8.0 (`test_every_living_document_names_the_current_major_version`).
Diese Prüfung gehört zum Abschluss von 8.0. Zwischenstände ohne Verhaltensänderung der Anwendung
erscheinen deshalb als 7.9.x; 8.0.1 ist die erste Version mit nutzbarer Google-Verbindung über
Inboxstride und geprüfter Dokumentation.

## Festgelegte Entscheidungen (18. November 2026)

- **Geheimnisspeicher:** Fernet aus `cryptography`; der Schlüssel liegt als nur für den Eigentümer
  lesbare Datei außerhalb des Zustandsverzeichnisses. Ein Backup des Zustands allein entschlüsselt
  nichts. Mehrere Schlüssel sind möglich (erster verschlüsselt, alle entschlüsseln), mit Rotation.
- **Interne Schnittstelle:** mTLS mit eigener kleiner Inboxstride-CA (folgt).
- **DNS:** Den Eintrag `auth.inboxstride.de` legt der Betreiber an.
- **Offen:** getrenntes Testsystem für die Wiederherstellungsprobe und ein eigenes Repository für die
  Landingpage; beides ist Freigabekriterium von 8.0.

## 7.9.3 – Grundlage des zentralen Anmeldedienstes

Neue, eigenständige Komponente `inboxstride_auth` (nicht Teil des Mailhelp-Pakets), mit derselben
verbindlichen 100-%-Abdeckung:

| Baustein | Inhalt |
| --- | --- |
| `models.py` | Lesbarer, versionierter Zustand: registrierte Instanzen (nur Hostname, reservierte Subdomains ausgeschlossen, einziges Rücksprungziel), Anmeldeaufträge mit erlaubten Übergängen nach Abschnitt 4.2, Verbindungen getrennt nach Kandidat und aktivem Zugang, nur absolute UTC-Zeiten (Auftrag 10 Minuten, Beleg 2 Minuten) |
| `secret_store.py` | Verschlüsselte Refresh-Tokens, PKCE-Verifier und Clientgeheimnis; Schlüssel außerhalb des Zustands, Rechteprüfung unter Linux, atomare Schreibvorgänge, Rotation |
| `state_file.py` | Zustandsdatei mit Vergleich der Revision vor jedem Schreiben; Beschädigung wird gemeldet, nie still zurückgesetzt |
| `google.py` | Tokenendpunkt mit Größen- und Schemaprüfung; unterscheidet abgelehnten Zugang, ungültigen Client, vorübergehende Fehler (mit `Retry-After`) und unklaren Code-Tausch |
| `service.py` | Start mit State und PKCE (S256), Offline-Zugriff und bewusster Kontoauswahl; einmaliger Code-Tausch; Rückleitung nur zur gebundenen Instanz mit einmaligem Beleg; Einlösen nur mit der ursprünglichen Sitzung; Aktivierung erst nach lokaler Bestätigung, frühere Verbindung bleibt bis dahin aktiv; Wiederaufnahme nach Absturz; Tokenausgabe mit Cache, Rotation und `reconnect_required`; Trennen ohne Google-weiten Widerruf; Aufräumen abgelaufener Aufträge und Kandidaten |

Die Tests (`tests/auth/`) laufen gegen einen simulierten Google-Endpunkt und zwei synthetische
Instanzen. Sie decken ab: vollständigen Ablauf, Mandantentrennung, Ersatz einer Verbindung,
Erneuerung mit und ohne Rotation, abgelehnten Zugang, unklaren Tausch, fehlenden Refresh-Token,
fehlende Berechtigungen, Abbruch bei Google, abgelaufene Aufträge und Belege, wiederholten Start
und verlorene Schreibvorgänge.

**Prüfung 7.9.3:** `python -m devtools.check full --workers 12` mit 6 151 bestandenen Tests und
100 % Zeilen- und Branch-Abdeckung (einschließlich `inboxstride_auth`); Browsersuite 977 bestanden,
234 übersprungen.

## 7.9.4 – Schnittstellen des Dienstes und Anbindung der Instanz

**Zentraler Dienst:**

- Öffentlicher Callback mit strikter Parameterprüfung (doppelte oder fehlende Parameter → 400) und
  interner mTLS-Schnittstelle. Eine Instanz ist nur über den Fingerabdruck ihres Zertifikats bekannt;
  Sperren im Register widerruft sie sofort.
- Eigene CA (`ca.py`) für Server- und Instanzzertifikate (ECDSA P-256, Server 397 Tage,
  CA 10 Jahre).
- Betreiberkommandos `python -m inboxstride_auth create-key | ca-init | issue | register | disable |
  set-client | sweep | serve`. Pfade kommen aus der Umgebung, Geheimnisse nie aus der Kommandozeile;
  `set-client` liest Googles JSON-Datei und erhöht die Clientrevision.

**Mailhelp-Instanz:**

- `hosted_auth` und `google_connection` (Konfigurationsbeispiel, Referenz, Suchkatalog).
  `HostedTokenProvider` versorgt den Google-Kalender; Google-Geheimnisse in `.env` entfallen.
- „Mit Google verbinden“ in Ersteinrichtung und Zielprofilen; Google-Felder für Client-Daten sind im
  gehosteten Modus ausgeblendet. „Google erneut verbinden“ direkt aus der Warnung von 7.9.2.
- Zielbindung `google-<Verbindung>` für Termin-Vorschläge: Ein Kontowechsel bei gleicher
  Kalender-ID schreibt keine früher bestätigte Version ins neue Konto.
- Fingerabdrücke bestehender Installationen bleiben unverändert (`hosted_auth` und
  `google_connection` beeinflussen keine Analyse).

**Tests:** `tests/web/test_hosted_google_web.py` führt den gesamten Ablauf zwischen Instanz,
zentralem Dienst (echte Anfragebehandlung) und simuliertem Google durch: Erstverbindung, Ersatz
einer Verbindung, Rückkehr ohne Sitzungscookie, fremde Sitzung oder Instanz, Abbruch, fehlende
Berechtigungen, Ausfall des Dienstes, veraltete Entwürfe und abgelaufene Vorgänge.
`tests/auth/test_auth_http.py` startet echte mTLS-Server auf localhost: Ohne Zertifikat und mit
dem Zertifikat einer fremden CA kommt keine Verbindung zustande.

**Prüfung 7.9.4:** `devtools.check full` mit 6 194 bestandenen Tests und 100 % Zeilen- und
Branch-Abdeckung; ein Leitfadentest las eine fett gesetzte Versionsnummer in `docs/Betrieb.md` als
Bedienelement (Formatierung korrigiert, Dokumentationstests danach 136 bestanden). Browsersuite
976 bestanden, 234 übersprungen, ein Zeitausreißer (`test_script_steps_that_end_in_a_navigation`),
der einzeln besteht.

## 7.9.5 – Kalenderwechsel, Trennen und Paketierung

- **Anderen Kalender wählen** (`/google/kalender/wechseln`): liest die Kalender mit Schreibrecht über
  den vorhandenen Zugang, speichert nur `google_calendar` mit Version und Idempotenzschlüssel; kein
  neuer Google-Auftrag.
- **Verbindung trennen** (`POST /google/trennen`, Sitzung, CSRF, Version): zentral `disconnect`, danach
  lehnt jeder `HostedTokenProvider` des Prozesses die Verbindung auch mit noch gültigem Cache ab. Die
  Referenz bleibt im Profil (sonst verlangte die Konfiguration eigene Google-Geheimnisse); weitere
  Profile bleiben aktiv, Termine und der Google-Grant unberührt. Wiederholung ist wirkungslos.
- Zentraler Dienst: gleichzeitige Tokenanfragen derselben Verbindung teilen eine Erneuerung
  (Sperre je Verbindung, danach erneuter Cacheblick).
- Eigenes Image `ops/auth/Dockerfile` mit `ops/auth/requirements.lock`; Tests prüfen, dass die
  Teilmenge genau der Abhängigkeitshülle von `cryptography`, `httpx` und `pydantic` mit den Versionen
  des Hauptlocks entspricht und das Paket nichts außerhalb davon importiert. Ein lokaler Imagebau
  war mangels Docker auf dem Entwicklungsrechner nicht möglich und steht aus.
- Servervorlagen `ops/server/auth.compose.example.yaml` und
  `ops/server/nginx-auth.inboxstride.de.example.conf`, ausdrücklich als geplant gekennzeichnet.

**Prüfung 7.9.5:** `devtools.check full` mit 6 203 bestandenen Tests und 100 % Zeilen- und
Branch-Abdeckung; ein Leitfadentest las „Drittanbieter-Apps“ (Google-Oberfläche) als Mailhelp-
Bedienelement, Formulierung angepasst. Browsersuite 977 bestanden, 234 übersprungen.

**Lesende Serverinventur (19. November 2026):** Ubuntu 26.04.1 LTS, Docker 29.1.3, Compose 2.40.3,
nginx 1.28.3; Zertifikate per certbot-Container v5.10.0 (Webroot) mit Cron-Erneuerung je Domain;
ufw inaktiv; Wurzeldateisystem zu 92 % belegt (alte Images, Build-Cache und Sicherungen). Das
IP-Zertifikat für den direkten Zugriff hatte keine automatische Erneuerung. Mit Freigabe danach
bereinigt und die Erneuerung eingerichtet; siehe [Betrieb](Betrieb.md).

**Offen bis 8.0:** Einrichtung des Dienstes auf dem Server und Pilotanmeldung,
`docs/Serverhandbuch.md`, Wiederherstellungsprobe auf getrenntem Testsystem, Quellen der
Landingpage in Git, Prüfung aller lebenden Dokumente für 8.x.
