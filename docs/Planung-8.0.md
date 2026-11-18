# Mailhelp 8.0 – Google-Konten über Inboxstride verbinden und verwalten

**Zielversion:** 8.0, erste Auslieferung 8.0.1; weitere Commits mit fortlaufenden Patchversionen.

**Stand:** 18. November 2026.

**Status:** Geplant. Beschreibt Anforderungen, Architektur, Umsetzung und Abnahme;
kein Auftrag zur Implementierung, Bereitstellung oder Änderung produktiver Konten.

**Grundlagen:** [Entwicklungsregeln](../AGENTS.md), [Spezifikation](../Mailhelp-Projektspezifikation.md),
[Planung 7.9](Planung-7.9.md), [Google-Webserver-OAuth](https://developers.google.com/identity/protocols/oauth2/web-server),
[Google-Kalenderberechtigungen](https://developers.google.com/workspace/calendar/api/auth),
[Google-Nutzerdatenrichtlinie](https://developers.google.com/terms/api-services-user-data-policy).

## 1. Ziel und Umfang

Nutzer einer freigeschalteten Inboxstride-Instanz verbinden ihren Google-Kalender
über „Mit Google verbinden“. Sie wählen bei Google ihr Konto und erlauben die
benötigten Berechtigungen. Anschließend wählen sie in ihrer Instanz einen Kalender,
prüfen die Verbindung und übernehmen sie ausdrücklich. Client-ID, Client-Secret und
Refresh-Token müssen Nutzer weder erzeugen noch kopieren oder in `.env` eintragen.

Derselbe Ablauf funktioniert in der Ersteinrichtung, beim Hinzufügen weiterer
Zielprofile, bei erneuter Autorisierung und beim Wechsel des Google-Kontos oder
Zielkalenders. Alle Google-Anmeldungen des gehosteten Angebots kehren zu
`https://auth.inboxstride.de/auth/google/callback` zurück. Danach gelangt der Nutzer
ausschließlich zur ursprünglich gebundenen Instanz, beispielsweise seiner Subdomain.

„Zugang anlegen“ bedeutet hier eine Google-Kontoverbindung innerhalb einer bereits
berechtigt eingerichteten Nutzerinstanz. Eine Registrierung neuer Inboxstride-Nutzer,
Google als Login für Inboxstride, Abrechnung und das Anlegen von Google-Konten sind
nicht Bestandteil dieser Version. Das Onboarding einer Instanz darf auf die neue
Google-Verbindung aufbauen, benötigt aber weiterhin eine eigene autorisierte Sitzung.

### Abnahme aus Nutzersicht

1. Eine berechtigt gekoppelte frische Instanz ohne fertige `config.yaml` bietet im
   Einrichtungsschritt „Kalender und Aufgaben“ die Google-Verbindung an.
2. Der Nutzer meldet sich bei Google an, wählt einen zugänglichen Kalender und
   übernimmt ihn nach erfolgreicher rein lesender Prüfung. Danach kann die Einrichtung
   ohne manuelle OAuth-Geheimnisse abgeschlossen werden.
3. Ein bestehendes Konto lässt sich erneut autorisieren oder ersetzen. Ein Abbruch
   oder Fehler erhält die bisherige Verbindung; ein neuer Zugang wird erst nach Prüfung übernommen.
4. Eine zweite Nutzerinstanz kann gleichzeitig einen anderen Zugang verbinden.
   Aufträge, Tokens, Kalenderauswahl und Sitzungen bleiben sicher voneinander getrennt.
5. Im laufenden Betrieb werden Access-Tokens automatisch erneuert. Ein ungültiger
   Refresh-Zugang erzeugt die Warnung aus 7.9 und führt gezielt zu „Google erneut verbinden“.
6. Die Verbindung selbst erzeugt keine Kalender- oder Aufgabenaktion. Jede solche
   Schreibaktion benötigt weiterhin eine ausdrückliche, versionsbezogene Bestätigung.

## 2. Ausgangsstand und Abgrenzung zu 7.9

| Vorhandener Baustein | Lücke für 8.0 |
| --- | --- |
| `runtime/oauth_web.py` mit State, PKCE und dauerhaften OAuth-Aufträgen | Kennt nur lokale Clientdaten, lokale Sitzungen und Tokenablage in der Instanz |
| `web/oauth_site.py` mit Start, Callback, Status und Kalenderauswahl | Callback erwartet das Sitzungscookie derselben Instanz; funktioniert nicht als zentraler Mehrnutzer-Callback |
| `runtime/initial_setup.py`, `web/initial_site.py`, `web/initial_pages.py` | Entwurfszustand, Zielprofil und neue Verbindung müssen auch vor fertiger Konfiguration stabil gebunden werden |
| `external/oauth.py::GoogleOAuthTokenProvider` | Erneuert Tokens mit lokalem Client-Secret und Refresh-Token; benötigt einen zusätzlichen zentralen Tokenprovider |
| `external/providers.py` und Google-Kalenderauswahl | Verbindungsmodus, Profil und Generation müssen einheitlich bis zum API-Aufruf durchgereicht werden |
| Bestehende Geräte-/Sitzungskopplung und CSRF-Schutz | Erhalten, auch beim Abschluss über zwei verschiedene Hosts |
| 7.9: Kalenderergänzungen und Authentifizierungswarnungen | Bleiben eigenständige 7.9-Ziele; Warnungen verlinken ab 8.0 auf den neuen Wiederverbindungsablauf |

Die Architekturentscheidung aus Abschnitt 4.6 der Planung 7.9 wird hier verbindlich
ausgearbeitet und in 8.0 umgesetzt. Der zentrale Auth-Dienst ist keine Voraussetzung
für die Auslieferung der beiden ursprünglichen 7.9-Fehlerbehebungen.

### Vorhandene Google-Konfiguration

- Neues Projekt und Webanwendungsclient unter der Marke Inboxstride wurden vom Nutzer angelegt.
- Vereinbarter produktiver Redirect: `https://auth.inboxstride.de/auth/google/callback`.
- Vereinbarte Berechtigungen: `calendar.events`, `calendar.calendars.readonly`,
  `calendar.calendarlist.readonly`, jeweils unter `https://www.googleapis.com/auth/`.
- Clientdatei ist lokal außerhalb der Git-Erfassung abgelegt. Ihr Speicherort steht
  in der ebenfalls ignorierten `SERVERZUGANG.local.md`; keine Clientgeheimnisse in diesen Plan aufnehmen.
- Veröffentlichung, tatsächliche Scopes, Verifizierung, DNS, TLS und Erreichbarkeit
  vor Inbetriebnahme erneut prüfen. Die Console-Konfiguration allein implementiert den Ablauf nicht.

8.0 fordert für den gehosteten Standardmodus nur diese Kalenderberechtigungen an.
Gmail, Drive, Identitäts-Scopes und Google Tasks werden nicht vorsorglich ergänzt.
Eine Google-Tasks-Verbindung bleibt im bisherigen expliziten Selbstbetreibermodus,
bis ein gesondert konfigurierter und geprüfter zentraler Umfang dafür freigegeben ist.
Kalendernamen sind keine verifizierte Google-Kontoidentität; ohne Identitäts-Scopes
keine vermeintlich geprüfte E-Mail-Adresse oder Kontoinhaberschaft anzeigen.

## 3. Architekturentscheidung: zentraler OAuth-Dienst

Der zentrale Dienst übernimmt Autorisierungscode-Tausch, sichere Speicherung der
Google-Refresh-Tokens und deren spätere Erneuerung. Die Nutzerinstanz hält eine
undurchsichtige Verbindungsreferenz und erhält über eine geschützte interne API
kurzlebige Access-Tokens für genau diese Verbindung. Kalender-API-Aufrufe erfolgen
weiterhin durch die Nutzerinstanz. Der zentrale Dienst benötigt keine Mailinhalte
und führt selbst keine Kalender- oder Aufgabenaktionen aus.

Damit bleibt das gemeinsame Google-Client-Secret im zentralen Dienst. Würde nur der
Callback zentralisiert und der Refresh-Token an jede Instanz verteilt, müsste dort
zusätzlich das gemeinsame Client-Secret für die Erneuerung verfügbar sein. Diese
Verteilung ist für den gehosteten Modus nicht vorgesehen.

### Vertrauensgrenzen und Speicherorte

| Ort | Gespeicherte beziehungsweise zulässige Daten |
| --- | --- |
| Zentraler Dienst | Registrierte Instanzen, Clientrevisionen, OAuth-Aufträge, Bindungen und Zustände als lesbares JSON; separate JSONL-Ereignisse |
| Zentraler Geheimnisspeicher | Client-Secret, Refresh-Tokens und notwendige vorübergehende Geheimnisse, verschlüsselt beziehungsweise in einem etablierten Secret-Store; Schlüssel außerhalb der Zustandsdateien |
| Nutzerinstanz | Lokale Sitzung, Einrichtungsentwurf, Profil, Verbindungs-ID, Generation, Kalenderziel und sicherer Verbindungsstatus |
| Arbeitsspeicher der Nutzerinstanz | Kurzlebiger Access-Token mit Ablaufzeit, weder HTML-Ausgabe noch dauerhafter Klartextzustand |
| Browser | Google-Anmeldung und kurzlebiger Abschlussbeleg; kein Client-Secret oder Refresh-/Access-Token von Inboxstride |

Bestehende, geprüfte Bibliotheken für OAuth und Verschlüsselung verwenden; kein
eigenes kryptografisches Verfahren entwickeln. Ein Dateisystem-Backup allein darf
keine Entschlüsselung der zentralen Tokens ermöglichen. Secret-Store- und
Schlüsselwiederherstellung gehören zusammen mit der Löschung zum Betriebsnachweis.

### Interne Kommunikation

- Pro Nutzerinstanz eine eigene stabile Instanz-ID und widerrufbare interne Identität.
  Die interne API verwendet TLS mit gegenseitiger Zertifikatsprüfung (mTLS).
  Zertifikatsrotation, Sperrung und vertrauenswürdige CA dokumentieren und testen.
- Instanzen werden durch den Betreiber registriert; kein öffentlicher API-Aufruf
  darf beliebige Mandanten, Rücksprungadressen oder fremde Profile registrieren.
- Die interne Identität begrenzt alle Zugriffe auf die zugeordnete Instanz.
  Eine Verbindungs-ID ist keine alleinige Autorisierung. Profil, Auftrags-ID,
  Revision und erlaubte Operation müssen zusätzlich passen.
- Interne Routen sind nicht über den öffentlichen nginx erreichbar. Öffentliche
  Routen sind auf den erforderlichen Google-Callback und inhaltsfreie Zustandsseiten begrenzt.
- Erlaubte Rücksprungziele stammen aus dem registrierten Instanzverzeichnis.
  Keine Freigabe beliebiger URLs durch Hostheader, Benutzernamen oder URL-Parameter;
  reservierte Subdomains wie `auth`, `demo` und `www` erhalten keine Nutzerzuordnung.
- Der lokale Selbstbetrieb unter Windows 11 und Docker/Linux bleibt ohne zentralen
  Dienst möglich. mTLS betrifft die gehostete Integration, nicht alle lokalen Installationen.

## 4. Ablauf und dauerhafte Zustände

### 4.1 Start, Google-Rückkehr und Abschluss

1. Ein POST in der Nutzerinstanz prüft aktive lokale Sitzung, CSRF, Profil-/Entwurfsrevision
   und Idempotenzschlüssel. Bei der Ersteinrichtung wird eine stabile Entwurfs-ID
   statt einer vermeintlich fertigen Zielkonfiguration gebunden.
2. Die Instanz registriert den Auftrag intern beim zentralen Dienst. Dieser bindet
   ihn an Instanz, lokale Sitzungsreferenz, Zielprofil oder Entwurfs-ID, Operation
   (`connect`, `reauthorize`, `replace`), Clientrevision, Scopes und Rücksprungziel.
3. Der zentrale Dienst erzeugt zufälligen OAuth-State und PKCE-Verifier/-Challenge.
   Die Autorisierungsanfrage verwendet Offline-Zugriff, erforderliche Zustimmung und
   den exakt registrierten zentralen Redirect. Ein Kontowechsel muss eine bewusste
   Google-Kontoauswahl ermöglichen, statt still ein vorheriges Konto zu übernehmen.
4. Google kehrt zum zentralen Callback zurück. Dieser prüft eindeutige Parameter,
   State-Bindung, Provider, Laufzeit und Auftragsstatus. Ein Providerfehler ist ein
   kontrollierter Abbruch; ein unbekannter oder wiederverwendeter State wird abgewiesen.
5. Der Code wird einmalig getauscht, das Ergebnis strikt validiert und als vorläufiger
   Zugang gespeichert. Fehlende erforderliche Scopes oder ein beim neuen Client fehlender
   Refresh-Token führen nicht zu einer angeblich erfolgreichen dauerhaften Verbindung.
6. Der Browser wird ausschließlich zur gebundenen Nutzerinstanz zurückgeleitet.
   Die URL enthält höchstens einen kurzlebigen einmaligen Abschlussbeleg, niemals den
   Google-Code oder einen Google-Token. Belege serverseitig nur als Hash referenzieren
   und nach Gebrauch entfernen; sie ersetzen nicht die lokale Sitzung.
7. Die Instanz prüft die ursprüngliche Sitzung und Revision erneut. Da hostgebundene
   `SameSite=Strict`-Cookies auf der Rückkehr fehlen können, eine neutrale Abschlussseite
   anbieten. Erst ein geschützter same-origin POST schließt den Auftrag ab.
   Keine Cookies für die gemeinsame Domain `.inboxstride.de` einführen.
8. Intern wird der gebundene vorläufige Zugang für Kalenderauswahl und rein lesende
   Berechtigungsprüfung nutzbar. Nach Auswahl zeigt die Instanz Zielprofil, Kalender
   und Konsequenzen eines Wechsels. Ein weiterer geschützter POST übernimmt den Zugang
   mit Versionsprüfung. Die Vorschau selbst verändert keine aktive Verbindung.

### 4.2 Zustandsmodell und Wiederaufnahme

Mindestens `registered → awaiting_google → exchanging → candidate_ready →
awaiting_local_confirmation → activating → active` sowie `cancelled`, `expired`,
`failed`, `blocked` und `reconnect_required` unterscheiden. Übergänge sind dauerhaft,
versionsgeprüft und nachvollziehbar; Kandidaten und aktive Verbindungen nicht vermischen.

- Autorisierungsaufträge laufen standardmäßig nach 10 Minuten ab, Abschlussbelege
  spätestens nach 2 Minuten und spätestens mit ihrem Auftrag. Kalenderauswahl und
  Übernahme müssen innerhalb der Auftragslaufzeit erfolgen; danach neu starten.
- Zeiten als absolute UTC-Zeitpunkte speichern. Neustart darf keine Laufzeit verlängern;
  eine monotone Prozessuhr allein ist kein persistierbares Ablaufdatum.
- Ein Code-Tausch mit unklarem Ergebnis wird nicht blind wiederholt. Wenn kein
  sicher gespeichertes Ergebnis vorliegt, eine neue Anmeldung verlangen und die alte
  aktive Verbindung erhalten. Vorläufig erhaltene Tokens bei Abbruch sicher bereinigen.
- Aktivierung zwischen Instanz und zentralem Dienst mit dauerhaftem Journal,
  Idempotenzschlüssel und Verbindungs-Generation ausführen. Nach Absturz ein bereits
  bestätigtes Aktivierungsergebnis abgleichen; keine halb umgestellte Verbindung nutzen.
- Ändert sich Sitzung, Entwurf, Profil, Client oder Konfiguration während des Ablaufs,
  darf der alte Auftrag nichts übernehmen. Ein fremder oder neuer Browser kann einen
  alten Abschlussbeleg nicht als Ersatz für die ursprüngliche Sitzung verwenden.
- Mehrere Tabs und parallele Anmeldungen dürfen denselben Profilstand nicht gegeneinander
  überschreiben. Neue bewusst gestartete Abläufe invalidieren veraltete Kandidaten dieses Profils.

## 5. Bedienabläufe

| Situation | Verbindliches Verhalten |
| --- | --- |
| Ersteinrichtung | „Mit Google verbinden“, Kalenderwahl, lesende Prüfung und bewusste Übernahme direkt im Assistenten; Rückkehr zum richtigen Schritt |
| Noch kein Client-/Zentraldienst eingerichtet | Verständlicher Hinweis für den Betreiber; nicht ein endloser Google-Login oder eine angeblich erfolgreiche Verbindung |
| Weitere Zielprofile | Eigenständiger Ablauf pro Profil; bestehende Profile unverändert |
| Erneut autorisieren | Bei Fehler aus 7.9 zur betroffenen Verbindung führen; alten Fehler erst nach erfolgreicher aktueller Prüfung zurücksetzen |
| Anderes Konto verbinden | Neuen Kandidaten getrennt vom aktiven Zugang halten, Kalender neu wählen, Wechsel sichtbar bestätigen |
| Nur Kalender ändern | Mit vorhandenem Zugang verfügbare Kalender lesen; Zielwechsel separat bestätigen, ohne unnötigen erneuten Google-Login |
| Abbruch oder unzureichende Berechtigungen | Ausgangsverbindung und Einrichtungseingaben erhalten; konkrete Abhilfe und neuen Versuch anbieten |
| Verbindung trennen | Geschützter bestätigter POST, Referenz deaktivieren, lokale Token-Caches invalidieren und weiteres Verwenden verhindern |
| Ablauf der Websitzung | Keine Übernahme; neu anmelden und neuen Verbindungsvorgang starten, sofern alter Auftrag nicht mehr gültig gebunden ist |

### Ersteinrichtung ohne fertige Konfiguration

- Einrichtungsentwurf, Sitzungsreferenz und Kandidaten-ID dauerhaft vorhalten;
  Einrichtung darf nicht erst eine gültige Altverbindung oder fertige `config.yaml` verlangen.
- Die Kandidatenprüfung verwendet den neuen Zugang, nicht versehentlich alte
  Prozessumgebungsvariablen oder einen geerbten Google-Zugang aus einem anderen Profil.
- Beim Speichern den Entwurf atomar in das richtige Zielprofil überführen. Offene
  Aufträge beim Zurücksetzen oder Abbrechen der Einrichtung invalidieren und bereinigen.
- Google kann übersprungen werden, wenn ein unterstützter anderer Kalenderanbieter
  gewählt ist. Erst gewählte Funktionen dürfen notwendige Einrichtungsbedingungen erzeugen.
- Die im Hosting vom Betreiber vorgegebene Auth-Konfiguration ist für Endnutzer
  nicht als frei bearbeitbares Client-Secret-/Redirect-Formular darzustellen.

### Folgen eines Zielwechsels

Ein Kalenderwechsel darf bestehende Vorschläge, Bestätigungen oder unklare Schreibaufträge
nicht auf das neue Ziel umlenken. Verbindung, Profil, Kalender und Generation an
Schreibauftrag und Idempotenzschlüssel binden. Vor Ausführung erneut prüfen.
Betroffene noch offene Bestätigungen invalidieren und eine neue prüfbare Vorschlagsversion
anbieten. Bereits geschriebene Einträge und deren Nachweise behalten ihre ursprüngliche
Zielbindung. Unklare frühere Schreibresultate ausschließlich gegen das ursprüngliche
Ziel abgleichen; ein verlorener Altzugang verlangt Klärung, keinen Ersatzschreibzugriff.

## 6. Token-Erneuerung, Störungen und Trennung

- Eine gemeinsame Tokenprovider-Schnittstelle für direkten lokalen OAuth und den
  zentralen Modus einführen; Kalenderadapter und lesende Auswahlprüfungen verwenden sie.
- Der zentrale Dienst erneuert Access-Tokens bei Bedarf mit Sicherheitsabstand,
  bündelt gleichzeitige Erneuerungen je Verbindung und validiert Typ, Ablauf und Scopes.
  Eine erfolgreiche normale Erneuerung erzeugt keine Warnung und keinen Nutzerprompt.
- Refresh-Tokens mit optionaler Rotation sicher und atomar übernehmen; das Fehlen
  eines neuen Refresh-Tokens in einer normalen Refresh-Antwort löscht den bisherigen nicht.
- `invalid_grant`, ungültiger Client, fehlende Berechtigung, Netzwerkfehler und
  Rate Limits unterscheiden. Wiederholungen nur für geeignete temporäre Fehler,
  mit Grenzen, Backoff und Beachtung von `Retry-After`.
- Ein ungültiger Refresh-Zugang wird `reconnect_required`; 7.9 zeigt den betroffenen
  Dienst/das Profil mit „Google erneut verbinden“. Kein automatischer neuer Login
  und keine Behauptung, einen abgelaufenen Refresh-Token ohne Nutzerzustimmung zu ersetzen.
- Zentrale Ausfälle dürfen IMAP, Todoist, andere Kalender oder fremde Instanzen nicht
  blockieren. Google-Aktionen bleiben kontrolliert offen/fehlgeschlagen; keine Ersatzanlage.
- Trennung stoppt Tokenausgabe und lokale Nutzung. Hintergrundarbeiten prüfen aktive
  Verbindungsbindung/Generation; Trennung ist keine Löschung schon erstellter Kalendereinträge.
- Einen Google-weiten Grant nicht ungefragt widerrufen: Ein Widerruf kann weitere
  Verbindungen desselben Google-Kontos/Clients betreffen. Lokales Trennen und expliziten
  Google-Widerruf unterscheiden, Auswirkungen erklären und Profile nicht gegenseitig beschädigen.

## 7. Sicherheit, Protokollierung und Datenschutz

- State und PKCE schützen den Google-Ablauf; Sitzung, CSRF, Version und Idempotenz
  schützen Start, Übernahme, Zielwechsel und Trennung. Keine dieser Schichten ersetzt die andere.
- Der öffentlich erreichbare zentrale Callback benötigt keine Sitzung einer beliebigen
  Nutzerinstanz; er darf selbst keine lokale Sitzungsberechtigung erfinden oder aktive
  Kontobindung ohne den abschließenden lokalen Nachweis ändern.
- Keine Analytics, Drittinhalte oder Service-Worker-Caches auf Auth-/Abschlussseiten.
  `Cache-Control: no-store`, restriktive Referrer-Policy und passende CSP setzen.
  Auth-Querystrings in nginx-, Fehler-, Monitoring- und Anwendungslogs unterdrücken.
- Unvertrauenswürdige Providerantworten mit Größenlimits und Schema validieren;
  Codes, Tokens, Verifier, Client-Secret und interne private Schlüssel niemals protokollieren.
- Nur Zustandswechsel, sichere Fehlercodes, Dauer und erforderliche interne Referenzen
  in getrennten JSONL-Logs erfassen. Keine Mailinhalte oder Kalenderdetails im zentralen Dienst.
- Abgelaufene Aufträge und einmalige Belege zeitnah bereinigen. Nicht mehr benötigte
  Kandidatengeheimnisse sofort löschen. Trennung, Benutzerlöschung und Vertragsende
  erfassen auch zentrale Verbindungen und Geheimnisse; die bestätigte 14-Tage-Frist
  nach Vertragsende und gesetzliche Ausnahmen gelten auch für diese neuen Komponenten.
- Ein gelöschtes Konto darf durch Wiederherstellung eines Backups nicht wieder einen
  nutzbaren Google-Zugang erhalten. Lösch-/Sperrnachweise und Schlüssel-/Backupverfahren testen.
- Datenschutz und Nutzungsbedingungen auf inboxstride.de um die tatsächliche zentrale
  Tokenverwaltung ergänzen. Hosting bei centron in Deutschland bedeutet nicht, dass
  die zusätzliche Google- und OpenRouter-Verarbeitung ausschließlich in Deutschland erfolgt.

## 8. Konfiguration, Betrieb und Migration

### Konfiguration und Paketierung

- Anwendungsoptionen in `config.yaml` beziehungsweise Paketdefaults aufnehmen:
  OAuth-Modus (`direct`/`hosted`), zentrale interne Dienstadresse, Instanz-ID und
  Verbindungsreferenzen pro Profil. Sichere Defaults und strikte Validierung verwenden.
- Client-/mTLS-/Verschlüsselungsgeheimnisse ausschließlich als serverseitige Secrets
  beziehungsweise geschützte Dateien; keine Schlüsselwerte in YAML-Beispielen oder Git.
- Zentralen Dienst als getrennte Python-Komponente mit Docker-Betrieb und Healthchecks
  paketieren. Öffentlichen Callback und interne mTLS-Schnittstelle getrennt binden.
  Health-Antworten nennen keine Nutzer, Verbindungen, Tokens oder Clientdaten.
- DNS und HTTPS für `auth.inboxstride.de` einrichten; nginx-Konfiguration, Rate Limits,
  Zertifikatserneuerung, interne Firewallregeln und registrierte Rücksprungziele dokumentieren.
- Für gehostete Instanzen keine stille Rückkehr zu alten `.env`-Zugängen zulassen.
  Direkter Selbstbetrieb mit eigenen Clients und Desktop-Loopback bleibt ausdrücklich unterstützt.

### Wechsel vom bisherigen produktiven Google-Client

1. Aktuellen Quell-/Serverstand, neue Console-Konfiguration und erforderliche
   Verifizierung prüfen; neue Clientdaten aus der ignorierten lokalen Ablage sicher bereitstellen.
2. Zentraldienst und Pilotinstanz getrennt vorbereiten und mit simulierten Diensten testen.
   Den vorhandenen funktionierenden Produktivzugang unverändert erhalten.
3. Gezielte Pilot-Neuanmeldung mit dem neuen Client durchführen. Ein alter Refresh-Token
   ist nicht auf den neuen Client übertragbar; keine automatische Übernahme behaupten.
4. Kalender prüfen und Übergang erst nach erfolgreichem Abschluss bestätigen. Alte
   Credentials danach nicht mehr als Rückfall verwenden, nicht voreilig global widerrufen.
5. Rückkehr zur vorherigen Anwendungsversion und Zuordnung vorbereiten. Durch Google
   bereits widerrufene Tokens lassen sich durch ein Dateibackup nicht wieder gültig machen.
6. Weitere Nutzerinstanzen nach erfolgreicher Pilotabnahme registrieren. Infrastruktur-
   Bereitstellung und reale Nutzerautorisierung getrennt behandeln und nachvollziehen.

Neue Konfigurations-/Zustandsfelder benötigen Schemafassungen, lesbare Migrationen
und Tests mit bestehenden 7.x-Zuständen. Bereits bestätigte Kalenderaktionen werden
weder migriert ausgeführt noch durch einen neu verbundenen Zugang automatisch freigegeben.

### Versioniertes Serverhandbuch und Konfigurationsvorlagen

**Pflichtlieferumfang von 8.0:** `docs/Serverhandbuch.md` als maßgebliche,
gepflegte Anleitung sowie `ops/server/` mit geheimnisfreien Konfigurationsvorlagen.
Beide gehören in Git und müssen einen Neuaufbau aus einem frischen Checkout und
einer getrennten privaten Sicherung ermöglichen. Das Handbuch beschreibt den
nachgewiesenen Istzustand; geplante oder noch ungeprüfte Teile sind klar gekennzeichnet.
Es umfasst die gesamte Inboxstride-Installation, nicht nur den neuen Auth-Dienst.

| Teil des Handbuchs | Verbindlicher Inhalt |
| --- | --- |
| Inventar und Architektur | Hoster centron, Deutschland; tatsächlich ermittelte OS-/Paket-/Imageversionen, Dienste, Domains, Ports, Netze und Abhängigkeiten; Produktionsinstanz, Demo, Landingpage/Formulardienst und zentraler OAuth-Dienst getrennt aufführen |
| Frischer Server | Voraussetzungen und Installationsreihenfolge, Administrator-/Dienstbenutzer, SSH-Zugang, Betriebssystempakete, Docker/Compose, nginx, Firewall und notwendige Rechte; keine aus Vermutungen abgeleiteten Versionsangaben |
| Verzeichnisse und Rechte | Anwendung, Releases, aktive Verknüpfungen, Runtime, Daten, Logs, Secrets, Backups und Zertifikate; Eigentümer/Modi und Bind-Mounts; Code von veränderlichen Daten trennen |
| DNS und HTTPS | Hauptdomain, www, Demo, Auth und Nutzer-Subdomains; benötigte Records, nginx-Zuordnung, Zertifikatsausstellung/-erneuerung, Prüfungen und Reparatur bei Ausfall |
| Dienste und Ressourcen | Produktive Compose-Projekte, Container-/Dienstnamen, systemd-Units, Netztrennung der Demo, interne Ports, Limits, Start-/Stopp-/Neustartreihenfolge und erwartete Healthchecks |
| OAuth und Instanzzuordnung | Google-Projekt/Clienttyp und genehmigter Umfang ohne Geheimwerte, Callback, Instanzregister, mTLS-Identitäten, Zertifikatsrotation und Zugriffsprüfung; Desktop-/Selbstbetrieb abgrenzen |
| Update und Rückkehr | Versionierte Quellen und Images, Releaseverzeichnis, atomarer Wechsel, Vorabprüfung, Datenmigration, Rückkehrbedingungen und Nachprüfung; veraltete Backups nicht über neuere Schreibnachweise legen |
| Sicherung | Konsistenter Sicherungspunkt, sämtliche erforderlichen Daten und Secrets, verschlüsselte externe Sicherung, Zeitplan, tatsächliche Aufbewahrung, Schlüsselzugang und Verantwortlichkeit; Backup auf demselben VPS ist kein Schutz vor Serververlust |
| Wiederherstellung | Neuaufbau auf leerem Ersatzsystem, Wiederherstellung der passenden Daten-/Codeversion, Rechte, Secrets und Zertifikate, Prüfung vor Freigabe; nie zwei aktive Instanzen mit demselben Datenbestand betreiben |
| Fehlerbehebung | Konkrete Symptome, rein lesende Diagnosebefehle, erwartete Ergebnisse und begrenzte Reparaturschritte für DNS/TLS, nginx, Container/systemd, Mounts/Rechte, OAuth, Firewall, Speicherplatz und Formulardienst |
| Datenschutz und Löschung | Umsetzung der 14-Tage-Frist nach Vertragsende einschließlich zentraler Tokens, Logs, Exporte und Sicherungen; gesetzliche Ausnahmen; Wiederherstellung darf gelöschte Zugänge nicht reaktivieren |
| Prüfung und Änderungshistorie | Letztes Prüfdatum, Quell-/Releaseversion, Prüfergebnisse, bekannte Lücken sowie nachvollziehbare erfolgreich übernommene Betriebsänderungen und Rückkehrmaßnahmen |

#### Vorlagen und reproduzierbare Quellen

- Unter `ops/server/` logisch getrennte Vorlagen für nginx, Compose, systemd,
  Firewallregeln, Zertifikatserneuerung, Backup-/Restore-Abläufe, Verzeichnisrechte
  und die private Konfigurations-/Secretbereitstellung ablegen. Benötigte Werte
  eindeutig als Platzhalter dokumentieren; keine realen Tokens, privaten Schlüssel,
  Kundendaten, produktiven `.env`-Inhalte oder Kundeninstanzregister übernehmen.
- Zu jeder Vorlage Zielpfad, Voraussetzungen, eingesetzte Version, erforderliche
  Variablen, Validierungsbefehl, Übernahme/Neuladen und Rückkehrverfahren nennen.
  Die wirksame Serverkonfiguration gegen die aufgelöste Vorlage vergleichen und
  bewusste Abweichungen dokumentieren. Kein blindes Überschreiben fremder Konfigurationen.
- Bestehende Dateien und Skripte zunächst lesend inventarisieren. Nachvollziehbar
  erfolgreiche Schritte aus lokalen Deploymentdateien und Releaseberichten übernehmen;
  ein historischer Bericht allein beweist nicht den gegenwärtigen Serverzustand.
- Die Landingpage liegt derzeit außerhalb des Mailhelp-Repositorys und hat kein
  eigenes Git-Repository. Ihre Quellen und Betriebsdateien in einem eigenen
  Git-Repository versionieren; im Serverhandbuch Repository, freigegebenen Commit,
  Build-/Paketierverfahren und Deploymentmanifest referenzieren. Auch diese Quelle
  muss gesichert und nach frischem Checkout verfügbar sein. Temporäre lokale Ordner
  oder ausschließlich auf dem Server vorhandene Releases reichen nicht.
- Git-Quellen, benötigte Binärartefakte, Runtime-Sicherungen und private Secrets
  getrennt ausweisen. Ein Quellcode-Checkout stellt weder Kundendaten noch private
  Schlüssel oder bei Google widerrufene Tokens wieder her.
- Selbst geschriebene Automatisierung erhält Tests für Erfolg, Fehler, Wiederholung,
  Abbruch und Rückkehr und unterliegt der vollständigen Coverage-Vorgabe. Destruktive
  Schritte klar kennzeichnen und auf überprüfte Zielpfade begrenzen. Einen geeigneten
  Vorschau-/Prüfmodus anbieten; keinen produktiven Restore als automatisierten Test ausführen.

#### Pflegepflicht nach erfolgreichen Serveränderungen

Die Regel aus `AGENTS.md` gilt ab sofort für Arbeiten an der bestehenden Installation,
auch wenn das vollständige Handbuch erst mit 8.0 entsteht. Bis dahin den belegten
Stand in `docs/Betrieb.md` nachführen und später ins Handbuch übernehmen.

1. Vor Änderungen den bestätigten Ausgangsstand und die Rückkehrmöglichkeit festhalten.
2. Nach der Änderung passende Konfigurations-, Dienst-, HTTPS- und Funktionsprüfungen
   ausführen. Bloßes Kopieren einer Datei oder ein erfolgreicher Neustart allein
   belegt nicht die Funktionsfähigkeit der geänderten Einrichtung.
3. Erst nach nachgewiesenem Erfolg Handbuch, Vorlagen, Betriebsinventar und gegebenenfalls
   Releasebericht auf den neuen Stand bringen. Datum, Anlass, betroffene Komponenten,
   Versionen, reproduzierbare Schritte, Ergebnis und Rückkehrverfahren festhalten.
4. Fehlgeschlagene, zurückgenommene und nur geplante Änderungen getrennt kennzeichnen;
   sie dürfen den gültigen Istzustand nicht ersetzen. Nach Rückkehr den tatsächlich
   wiederhergestellten, geprüften Stand dokumentieren.
5. Die Arbeit erst nach dieser Aktualisierung als abgeschlossen melden. Dokumentation
   und Vorlagen im zugehörigen Repository versionierbar vorbereiten. Ohne expliziten
   Commit-/Push-Auftrag nicht eigenmächtig veröffentlichen; klar nennen, wenn die
   Änderungen noch nicht committed beziehungsweise noch nicht extern gesichert sind.

#### Nachweis von Neuaufbau und Reparierbarkeit

Eine vom Produktivsystem getrennte Neuaufbau-/Wiederherstellungsprobe mit synthetischen
Daten ist Freigabekriterium für 8.0. Sie startet mit frischem Git-Checkout und
definierter Test-Sicherung, verwendet ausschließlich die dokumentierten Schritte
und benötigt keine nur auf dem alten Server oder im Gedächtnis vorhandenen Dateien.
Externe Dienste simulieren; keine echten Mails, Tokens oder Kalenderaktionen verwenden.

Zusätzlich mindestens eine nginx-/Portfehlkonfiguration und einen Dateirechte-/Mountfehler
gezielt im Testsystem einführen, anhand der Anleitung diagnostizieren und reparieren.
Backup-Restore, fehlendes/defektes Backup, fehlender Entschlüsselungsschlüssel,
Versionskonflikt und Rückkehr nach gescheiterter Bereitstellung prüfen.
Nachweise mit Versionsstand, Dauer, Ergebnissen und verbleibenden Grenzen im
Releasebericht festhalten. Erst danach den jeweiligen Ablauf als geprüft markieren.

## 9. Tests und Abnahme

Automatisierte Tests verwenden ausschließlich simulierte Google-/Zentraldienste,
synthetische Nutzer, Beispielhosts und künstliche Geheimnisse. Jede Codeänderung
erhält passende Tests. Jeder Bugfix wird vor dem Fix durch einen roten und danach
durch denselben grünen Regressionstest nachgewiesen.

| Bereich | Verbindliche Nachweise |
| --- | --- |
| Frische Ersteinrichtung | Ohne `config.yaml`/Google-Token verbinden, Kalender auswählen, prüfen, übernehmen, Assistent fortsetzen; Zurück, Abbruch, Reset und Neustart |
| Laufende Instanz | Neues Profil, Reautorisierung, anderes Konto, anderer Kalender; alte Verbindung bis zur erfolgreichen Übernahme erhalten |
| Zwei Nutzerinstanzen | Parallele Aufträge; vertauschter State, fremde Verbindungs-ID, Profil, Sitzung oder mTLS-Identität erlauben keinen Zugriff |
| Google-Protokoll | PKCE/State, Ablehnung, fehlender oder doppelter Parameter, falscher Provider, fehlende Scopes, fehlender Refresh-Token, ungültiger Tokentyp |
| Browsergrenzen | Hostgebundene Cookies, Strict-SameSite-Rückkehr, gültiger Abschluss-POST, CSRF, Fremdorigin, offene Weiterleitung und fremder Browser |
| Dauerhaftigkeit | Neustart bei jedem Übergang, verlorene Antworten, Token-Tausch unklar, doppelte Callbacks und Abschlussbelege, atomare Aktivierung, CAS-Konflikt |
| Ablauf und Konkurrenz | Auftrags-/Belegablauf, Zeitverhalten nach Neustart, parallele Tabs, geänderte Entwürfe/Profile/Clientrevisionen, widerrufene Sitzung |
| Tokenprovider | Cache, gleichzeitiger Refresh, Fehlerklassen, Backoff, Rotation, zentrale Nichterreichbarkeit, Verbindung getrennt und alte Generation |
| Kalenderprüfung | Zugängliche Liste, leerer Zugriff, fehlendes Ziel, Leser ohne Schreibrecht, Kalender während Auswahl entfernt; Prüfung legt nichts an |
| Bestätigungsbindung | Kontowechsel lenkt keinen Altauftrag um; Sitzung bei Ausführung erneut gültig; alte Versionen abgewiesen; keine Doppelanlage |
| Trennung/Widerruf | Eigene Verbindung deaktiviert, weitere Profile intakt, grantweiter Widerruf nicht automatisch ausgelöst, kein Löschen bestehender Termine |
| Secrets/Logs | Keine Geheimnisse in HTML, URLs, Logs, Tracebacks, PWA-Cache oder öffentlichen Healthchecks; gesicherter Secret-Store und mTLS-Rotation |
| Löschung | Kandidatenablauf, Kontolöschung, Vertragsende, zentrale Speicher/Backups und Schutz gegen Reaktivierung gelöschter Verbindungen |
| Kompatibilität | Windows-Selbstbetrieb, Linux/Docker, direkte lokale OAuth-Modi, neue und alte Profile, 7.x-Zustandsmigrationen, andere Kalender-/Aufgabenanbieter |
| Serverhandbuch und Vorlagen | Frischer Checkout, synthetischer Neuaufbau und Restore ohne versteckte Dateien; nginx/Ports und Rechte/Mounts anhand der Anleitung reparieren; Vorlagenvalidierung, fehlende Secrets/Schlüssel, defekte Sicherung, Versionskonflikt und Rückkehr |
| Oberfläche | Deutsche/englische Ersteinrichtung und Einstellungen, Mobil/PWA, Tastatur, Fehlermeldungen, Wiederverbinden aus 7.9-Warnung |

Bestehende OAuth-, Setup-, Zielprofil-, Credential-, Kalenderauswahl-, Upgrade-,
Web- und Browsersuites erweitern. Neue zentrale Protokoll-/Tokenprovider-Tests
einschließlich Instanz-Autorisierung und Secret-Lebenszyklus hinzufügen.

Zwei durchgängige Browserfälle sind Pflicht: Erstverbindung aus einer leeren
Einrichtung sowie Ersatz einer bestehenden Verbindung. Beide müssen mit simuliertem
Google, zentralem Callback und mindestens zwei voneinander getrennten Instanzhosts laufen.
Ein Happy-Path-Test allein ersetzt die Fehler- und Mandantentrennungstests nicht.

Verbindliche vollständige Prüfungen, nacheinander:

```powershell
python -m devtools.check full --workers 12
python -m pytest ui_tests -n 6 --dist worksteal --no-cov
```

Die Prüfung muss sämtlichen eigenen Anwendungscode einschließlich der neuen
zentralen Komponente erfassen und bei weniger als 100 % Zeilen- oder 100 %
Branch-Abdeckung scheitern. Keine Coverage-Ausnahmen oder wirkungslosen Tests.
Python- und Browsersuite nie gleichzeitig ausführen. Notwendige zusätzliche
Paket-/Container-/mTLS-Prüfungen in das Prüfwerkzeug aufnehmen.

## 10. Arbeitspakete und Freigabe

1. **Verträge und Modelle:** Ausgangsstand prüfen, Instanzregister, Zustände,
   Generationsbindung, interne mTLS-API, Secret-Store und Migrationsregeln konkretisieren.
2. **Zentraldienst:** Registrierung, Google-Callback, Kandidaten, einmalige Belege,
   Secret-Lebenszyklus, Refresh und dauerhafte Aktivierung implementieren und testen.
3. **Instanzintegration:** Tokenprovider, Zielprofile, Kalenderauswahl, atomare
   Übernahme und Bindung laufender Schreibaufträge integrieren.
4. **Ersteinrichtung und Verwaltung:** Einheitlichen Ablauf für leere Einrichtung,
   Hinzufügen, Reautorisierung, Wechsel, Trennung und Rückkehr aus Warnungen umsetzen.
5. **Betrieb, Serverhandbuch und Migration:** Gesamten tatsächlichen Serverbestand
   inventarisieren, `docs/Serverhandbuch.md` und `ops/server/` mit Neuaufbau, Reparatur,
   Backup/Restore und Rückkehr erstellen; Landingpage-Quellen versionieren. DNS/TLS/nginx,
   mTLS, Docker, Backup-/Löschkonzept und Clientwechsel nachvollziehbar abbilden.
   Isolierte Wiederherstellungs-/Reparaturprobe durchführen und belegen.
6. **Dokumentation und Prüfung:** Spezifikation, Konfigurationsbeispiele, Paketdefaults,
   Bedienung, Hilfe DE/EN, README, Changelog und öffentliche Datenschutztexte aktualisieren.
   Ergebnisse beider vollständiger Prüfungen sowie Regressionsnachweise in
   `docs/Release-8.0.md` dokumentieren.
7. **Auslieferung:** Erste Zielversion 8.0.1; pro Commit auf `main`/`beta` die geltende
   Patchversionsregel anwenden. `pyproject.toml` und `src/mailhelp/__init__.py` synchron
   erhöhen und Changelog/README mitführen. Keine Versionsänderung allein durch diesen Plan.

Freigabe erst, wenn Erstverbindung und Zugangsaustausch ohne manuelle Tokeneingabe
funktionieren, beide synthetischen Mandanten nachweislich getrennt bleiben,
automatischer Refresh und Wiederverbindung funktionieren und alle vollständigen
Prüfungen bestehen. Öffentliches DNS/TLS, die richtige Google-Clientkonfiguration
und gegebenenfalls erforderliche Google-Verifizierung vor realem Kundenbetrieb bestätigen.
Versioniertes Serverhandbuch und Vorlagen müssen den erfolgreichen Neuaufbau,
Restore und die beschriebenen Reparaturfälle belegen. Alle bei der Bereitstellung
erfolgreich übernommenen Serveränderungen sind vor Abschluss nachzuführen.
Ein manueller Pilot testet Anmeldung, Kalenderliste und Zugriff ausschließlich lesend;
eine spätere Kalender-Schreibprüfung braucht ihre eigene konkrete Vorschlagsfreigabe.
