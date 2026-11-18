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

**Noch nicht enthalten:** HTTP- und mTLS-Schicht, Anbindung der Mailhelp-Instanz (Tokenprovider,
Einrichtung, Zielprofile), Serverhandbuch und Vorlagen, Betrieb. Der Dienst läuft noch nirgends.
