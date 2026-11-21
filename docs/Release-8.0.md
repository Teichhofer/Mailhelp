# Mailhelp 8.0 – Google-Konten über Inboxstride verbinden und verwalten

**Stand:** 19. November 2026. **Status:** In Umsetzung. Version 7.9.3 liefert als Vorbereitung die
Grundlage des zentralen Anmeldedienstes; Schnittstellen, Instanzintegration, Einrichtung,
Serverhandbuch und Inbetriebnahme folgen. Plan: [Planung 8.0](Planung-8.0.md).

**Versionsnummer:** Ein Wechsel der Hauptversion verlangt nach Regel K6 eine nachgewiesene Prüfung
aller lebenden Dokumente für 8.0 (`test_every_living_document_names_the_current_major_version`).
Diese Prüfung gehört zum Abschluss von 8.0. Zwischenstände ohne Verhaltensänderung der Anwendung
erscheinen deshalb als 7.9.x; 8.0.1 ist die erste Version mit nutzbarer Google-Verbindung über
Inboxstride und geprüfter Dokumentation.

## Festgelegte Entscheidungen (18. und 19. November 2026)

- **Geheimnisspeicher:** Fernet aus `cryptography`; der Schlüssel liegt als nur für den Eigentümer
  lesbare Datei außerhalb des Zustandsverzeichnisses. Ein Backup des Zustands allein entschlüsselt
  nichts. Mehrere Schlüssel sind möglich (erster verschlüsselt, alle entschlüsseln), mit Rotation.
- **Interne Schnittstelle:** mTLS mit eigener kleiner Inboxstride-CA (folgt).
- **DNS:** Den Eintrag `auth.inboxstride.de` legt der Betreiber an.
- **Landingpage (19. November 2026):** Statt eines eigenen Repositorys liegen ihre Quellen im
  Mailhelp-Repository unter `landing/` (Abweichung von Planung 8.0, Abschnitt 7; seit 7.9.7).
- **Wiederherstellungsprobe (19. November 2026):** entfällt auf Entscheidung des Betreibers. Die
  getrennte Neuaufbau-/Wiederherstellungsprobe aus Planung 8.0 ist damit kein Freigabekriterium
  mehr; das Serverhandbuch beschreibt Neuaufbau und Wiederherstellung trotzdem vollständig, nur ohne
  nachgewiesenen Probelauf.

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

**Server (19. November 2026, mit Freigabe):** Anmeldedienst unter `auth.inboxstride.de`
eingerichtet (Image aus `ops/auth/Dockerfile`, Vorlagen unverändert übernommen), Produktion
und Demo auf 7.9.5 aktualisiert, Produktion als Instanz `stefan` registriert und per mTLS
angebunden; Probe `unknown_connection` aus dem Produktionscontainer bestätigt Zertifikat und
Register. Der bisherige Google-Zugang der Produktion bleibt bis zur Pilotanmeldung aktiv.
Einzelheiten: [Betrieb](Betrieb.md).

## 7.9.7 – Landingpage im Repository

- Quellen der Landingpage unter `landing/`, unverändert aus dem aktiven Server-Release übernommen
  und Datei für Datei gegen dessen Manifest geprüft (58 Dateien gleich; die übrigen stammen
  unverändert aus früheren Releases). Keine Interessentendaten: Diese liegen nur auf dem Server
  unter `/var/lib/inboxstride/leads`.
- `tests/landing/test_landing_build.py` baut die Seite in einer Kopie neu und verlangt alle
  ausgelieferten Dateien Byte für Byte; damit sind die Quellen nachweislich vollständig.
  Die Formulartests laufen jetzt in der Mailhelp-Prüfung; `landing/` steht unter der 100-%-Abdeckung.
- Das einmalige Installationsskript wurde zu `devtools/landing_install.py` mit gleichen Schritten,
  echten Fehlern statt `assert` und Tests für Erfolg, Wiederholung, unsichere Archive, Ausfall des
  Formulardienstes und einen veränderten Mailhelp-Container.
- Die zwei Playwright-Prüfskripte liegen unter `ui_tests/landing/`; die veraltete Erwartung eines
  Demo-Links ohne Sprachpfad wurde an `/de/` und `/en/` angepasst, beide bestehen.
- Ruff und mypy über das ganze Repository wieder ohne Befund (ältere Befunde in Tests und in
  `devtools/server_backup.py` behoben).
- Der Server bleibt unverändert; das nächste Landingpage-Release wird aus `landing/` erzeugt.

## 7.9.8 – Bugfix „Weiter zu Google“

Bei der ersten Pilotanmeldung graute „Weiter zu Google“ nur den Button aus. Der zentrale Dienst
hatte den Auftrag angenommen (`internal_completed` für `/intern/start`), die Instanz antwortete mit
der Weiterleitung zu Google, doch Chromium und WebKit verwarfen sie: Die Sicherheitsrichtlinie
erlaubte mit `form-action 'self'` nur die eigene Adresse, und Browser wenden das auch auf
Weiterleitungen nach dem Absenden an. Die simulierten Tests prüften die Weiterleitung, aber keinen
echten Browser. Jetzt erlaubt nur die Seite „Mit Google verbinden“ zusätzlich
`https://accounts.google.com`. Der Regressionstest
`test_the_connect_page_allows_its_form_to_continue_to_google` schlug vor der Korrektur fehl; ein
Playwright-Probelauf bestätigte Sperre und Korrektur in Chromium und WebKit.

## 7.9.9 – Bugfix „Verbindung übernehmen“

Der zweite Pilotversuch kam bis zur Kalenderwahl; „Verbindung übernehmen“ meldete dann „Die
Verbindung wurde inzwischen geändert oder ist abgelaufen“. Das Log zeigte die erfolgreiche zentrale
Aktivierung (`/intern/activate`) und unmittelbar danach HTTP 409 der Instanz. Eine lesende
Nachstellung im Produktionscontainer ergab `ValueError: Nicht angebotene Einstellung`: Der
Einstellungsentwurf ließ `targets.google_connection` nicht zu. Die Tests hatten das Speichern durch
ein Testdouble ersetzt; der erweiterte Test
`test_the_running_app_binds_target_profiles_and_offers_the_connection` speichert jetzt über den echten
Entwurf für die Profile 1 und 2 und schlug vor der Korrektur mit derselben Meldung fehl.

Außerdem lief die zentrale Aktivierung vor dem lokalen Speichern. Sie ersetzt die bisherige
Verbindung des Ziels und löscht deren Geheimnis; ein danach scheiterndes Speichern hätte ein Profil
mit getrennter Verbindung hinterlassen. Jetzt wird zuerst gespeichert (der Kandidat behält beim
Aktivieren seine Kennung), dann aktiviert. Tests: abgelehntes Speichern aktiviert nichts, ein
Ausfall während der Aktivierung wird durch erneutes Übernehmen nachgeholt, eine abweichende
Antwort des Dienstes wird abgewiesen. Die beim Pilotversuch aktivierte, ungenutzte Verbindung
ersetzt der Dienst bei der nächsten erfolgreichen Übernahme für dasselbe Zielprofil.

## Abgleich und Abschlussarbeit am 20.11.2026

| Bestandteil der Planung | Befund |
| --- | --- |
| Zentraldienst, Secret-Store, mTLS, Kalenderwahl, Wechsel und Trennung | Bereits in 7.9.3–7.9.8 implementiert; die uncommittierte Korrektur 7.9.9 war zu Arbeitsbeginn vorhanden und bleibt erhalten |
| DNS/TLS, Auth-Container, Instanzregistrierung, isolierte Demo | Lesend auf dem Server bestätigt; Produktion/Demo weiterhin 7.9.8, Auth 7.9.5 |
| Landingpage-Quellen | Bereits unter `landing/`, mit Buildvergleich und Formulartests |
| Serverhandbuch | Neu als [Serverhandbuch](Serverhandbuch.md) zusammengeführt; weitere nginx-, Rechte-, Firewall- und TLS-Vorlagen unter `ops/server/` |
| Echte Pilotanmeldung | Betreiber meldet erfolgreichen Abschluss; Serverabgleich zeigt eine aktive zentrale Verbindung, aber noch keine lokale Kalenderreferenz. Nicht automatisch zuordnen |
| Browsernachweise | Neue echte Browserfälle mit simuliertem Google, zentralem Callback und zwei Instanzhosts: Ersteinrichtung ohne config.yaml sowie Verbindungsersatz |
| Dokumentation | Relevante Bedienwege DE/EN, Versionsmarkierungen und Konfigurationsreferenz werden für 8.x nachgeführt |

Die isolierte VPS-Wiederherstellungsprobe entfällt gemäß Entscheidung vom 19.11.2026;
sie wird nicht als durchgeführt ausgewiesen. Ein kompletter produktiver Restore
ist weiterhin ungetestet. Die bestehende Dropbox-Sicherung erfolgt ausdrücklich
unverschlüsselt einschließlich Zugangsdaten auf Betreiberwunsch; abweichende frühere
Planformulierungen zur zusätzlichen Archivverschlüsselung sind damit ersetzt.

**Ausstehende Freigaben:** Vollständige Prüfungen des kombinierten 8.1-Arbeitsstands
und konsistente lokale Übernahme des Pilotzugangs. Der gemeldete Browsererfolg allein
belegt die lokale Zuordnung noch nicht. Keine automatische Migration auf einen
unbekannten oder nur als `primary` bezeichneten Kalender.

## Abschlussprüfung des lokalen Arbeitsstands

Erneuter Abgleich am 20. November 2026: Zentraldienst, mTLS, Secret-Store,
Instanzanbindung, Kalenderverwaltung, Landingpage-Quellen, Serverhandbuch und
geheimnisfreie Vorlagen liegen bereits vor. Der kombinierte Arbeitsstand 8.1.1
wird mit allen vollständigen Prüfungen abgenommen; Ergebnisse stehen im
[Releasebericht 8.1](Release-8.1.md).

Zusätzlich wurden Konfigurationsbeispiele auf den aktuellen Hauptversionsstand
gebracht und echte Browserfälle für Erstverbindung und Austausch beibehalten.
Fünf zusätzliche Regressionen reproduzierten vor der Korrektur parallelen
Code-Tausch, verspätete Token-Erneuerung nach Trennung/Kontowechsel, veraltete
Zugangsprüfung nach Wartezeit sowie verlorene parallele Geheimnisschreibvorgänge.
Auftragsübergänge prüfen nun ihre Vorgängerversion atomar; Secret-/Zustandszugriffe
sind innerhalb des Dienstprozesses gesperrt. Ein Refresh speichert sein Ergebnis
nur bei weiterhin gültiger Verbindung unter derselben Zustandssperre. Die gezielte
Auth-Prüfung besteht mit 86 Tests. Betreiberkommandos auf denselben Dateien erfordern
weiterhin einen gestoppten Auth-Dienst; dafür wurde die Betriebsanleitung präzisiert.
Es wurde in diesem Arbeitsgang weder auf einen Server zugegriffen noch ein
Produktivprofil geändert. Die historische Pilotzuordnung ist deshalb weiterhin
offen. Vollständige Prüfungen des kombinierten Arbeitsstands 8.0–8.2 (Version 8.2.1):
`python -m devtools.check full --workers 12` mit 6 372 bestandenen Tests, 2 bestandenen
Lasttests und 100,00 % Zeilen- und Branch-Abdeckung (41 187 Anweisungen, 11 602 Branches);
Browsersuite mit 998 bestandenen Tests (234 übersprungen) und 100 % JavaScript-Abdeckung.
