# Inboxstride landing page

Seit Mailhelp 7.9.7 liegen die Quellen im Mailhelp-Repository unter `landing/`
(übernommen aus dem Release `brand-legal-20261118T210536Z`, alle Dateien per SHA-256 gegen
das Release-Manifest geprüft). Dieses Verzeichnis entspricht dem Release-Verzeichnis auf dem
Server; Tests und Werkzeuge liegen in den Mailhelp-Ordnern (siehe „Entwicklung und Prüfung“).
`deployment-manifest.json` stammt aus einem früheren Release und wird beim nächsten Release ersetzt.

Deutsch und Englisch unter `https://inboxstride.de/` und `/en/`.
`https://www.inboxstride.de/` leitet auf die Hauptadresse um.

## Aufbau

- Statische HTML-Seiten, CSS, JavaScript, Bilder und lokal gespeicherte Schrift in `public/`.
- `lead_service.py` verarbeitet ausschließlich das Formular und verwaltet private Interessentendaten.
- Python-Standardbibliothek, keine Laufzeitpakete, kein Node-Prozess und kein zusätzlicher Container.
- Der bestehende nginx liefert die Dateien und übernimmt TLS, Kompression, Caching und Anfragelimits.
- Ein systemd-Dienst startet den Formularprozess mit 64 MB Speicherobergrenze und 20 % CPU-Limit.
- Impressum und Datenschutz verwenden die vom Betreiber übermittelten Angaben der Hartmann GbR mit Stefan Hartmann als vertretungsberechtigter Person.

## Interessenten

Der Dienst speichert je normalisierter E-Mail-Adresse eine private JSON-Datei in
`/var/lib/inboxstride/leads/`. Sie enthält E-Mail-Adresse, UTC-Zeitpunkt, Sprache,
Fassung und Wortlaut der Einwilligung. Bestehende Einträge werden bei Wiederholungen
nicht verdoppelt. Ein atomarer Dateiaustausch verhindert unvollständige Datensätze.
Dateinamen bestehen aus einem SHA-256-Hash. Dateirechte sind auf den Dienstbenutzer begrenzt.

Der laufende Dienst prüft einmal täglich die Aufbewahrung. Einträge über 365 Tage
werden gelöscht. Diese Frist ist auch in beiden Datenschutzerklärungen dokumentiert.
Eine E-Mail-Bestätigung oder ein automatischer Newsletter-Versand ist nicht eingerichtet.
`address_verified: false` kennzeichnet, dass die Adresse nicht per E-Mail bestätigt wurde.
Die Einträge sind Interessentenanfragen für die Kontaktaufnahme zum Start.

Export auf dem Server über SSH, beispielsweise in eine private JSONL-Datei

```sh
umask 077
sudo -u inboxstride /usr/bin/python3 /opt/inboxstride/current/lead_service.py export --data-dir /var/lib/inboxstride/leads > interested.jsonl
```

Löschung auf Wunsch einer Person

```sh
sudo -u inboxstride /usr/bin/python3 /opt/inboxstride/current/lead_service.py delete --data-dir /var/lib/inboxstride/leads --email 'person@example.org'
```

Zugriffsprotokolle der Landingpage sind deaktiviert. Formulardaten werden nicht protokolliert.
Eine externe Origin wird zurückgewiesen. Honeypot, kleine Anfragelimits und nginx-Rate-Limits
begrenzen automatisierte Einträge. Die Vormerkseite speichert die Cookie-Auswahl für höchstens 180 Tage. Google Tag Manager
und Analytics werden ausschließlich nach Statistik-Einwilligung geladen. Schrift, Bilder
und Video bleiben lokal; das Formular überträgt keine Kontaktadresse an Analytics.

## Betrieb

```sh
systemctl status inboxstride
journalctl -u inboxstride --since today
systemctl show inboxstride -p MemoryCurrent -p CPUUsageNSec
curl -H 'Accept: application/json' http://127.0.0.1:8877/health
```

`ops/` enthält Dienst- und nginx-Konfigurationen. Der interne Port ist 8877, gebunden
an `127.0.0.1`. TLS verwendet den vorhandenen kurzzeitig gestarteten Certbot-Container.
Die Zertifikatserneuerung für die Landingpage wird über einen eigenen Cronjob ausgelöst.
Bestehende Mailhelp-Konfiguration und deren Container werden für diese Website nicht angepasst.

Updates werden in ein neues Verzeichnis unter `/opt/inboxstride/releases/` übertragen.
`/opt/inboxstride/current` zeigt auf das aktive Release. Interessentendaten liegen außerhalb
des Release-Verzeichnisses. Vor dem Wechsel wird die bisherige Verknüpfung gesichert.
Die Installation übernimmt `python3 -m devtools.landing_install <archiv> <manifest>` aus dem
Mailhelp-Repository (bis 7.9.6 `ops/install_server.py` in diesem Ordner).

## Entwicklung und Prüfung

Die Website-Quellen liegen in diesem Ordner. Der mitgelieferte Build erzeugt beide
Sprachversionen und Dateinamen mit Inhaltsprüfsummen für langfristiges Browser-Caching.
Die Bildmotive und Schriftdateien werden dabei lokal wiederverwendet.

```sh
python landing/build_site.py
python -m pytest tests/landing
```

Die Tests in `tests/landing/` laufen in der vollständigen Mailhelp-Prüfung
(`python -m devtools.check full`) mit 100 % Zeilen- und Branch-Abdeckung für `landing/`
und `devtools/landing_install.py`. `test_landing_build.py` baut die Seite in einer Kopie neu
und verlangt, dass alle ausgelieferten Dateien Byte für Byte entstehen; eine Änderung an den
Quellen braucht also auch den neu gebauten Stand in `public/`. Der Produktionsdienst benötigt
ausschließlich Python. Backend-Tests verwenden synthetische Adressen unter Beispieldomains. Vor der
Bereitstellung wurden Formularablauf, Tastaturbedienung, beide Sprachen, responsive Ansichten,
Fehlerfälle, Wiederholungen und dauerhafte Speicherung geprüft.

Bildherkunft, verwendete Prompts und Dateipfade stehen in `ASSETS.md`. Die lokal
eingebundene Schrift DM Sans steht unter der SIL Open Font License in
`public/assets/DM-Sans-OFL.txt`.

## Recherche und Positionierung

Die qualitative Forenrecherche vom 15. November 2026, Quellen, Funktionsabgleich und offene Wünsche stehen in [RESEARCH.md](RESEARCH.md). Die deutsche und englische Landingpage betonen konkrete Alltagssituationen und kennzeichnen das noch nicht gestartete gehostete Angebot. Nicht vorhandene Funktionen werden nicht als Leistung beworben.

## Video und Analytics (16. November 2026)

- Das bereitgestellte MP4 liegt unter `public/assets/inboxstride-film.mp4`, mit
  Faststart und ohne erneute Video-/Audiokodierung; native Steuerung, kein Autoplay,
  `preload="none"`, kleines lokales Poster. Zum Build werden Inhaltsprüfsummen ergänzt.
- `consent.js` lädt GTM-55C4ZT5N erst nach ausdrücklicher Zustimmung. Der öffentliche
  Container enthält GA4 G-ZQP60GV6NS. Ohne Auswahl, nach Ablehnung und ohne JavaScript
  gibt es keine Google-Anfragen. Werbe- und Nutzerdatenfreigaben bleiben abgelehnt.
- Gleichwertige Zustimmen-/Ablehnen-Schaltflächen; Widerruf über Cookie-Einstellungen,
  lokale GA-Cookies löschen und Seite neu laden. Zustimmung/Ablehnung werden über ein
  notwendiges Cookie 180 Tage gemerkt. Keine Cookie-Auswahlwerte im Interessentendatensatz.
- Google-Cookie-Laufzeit wird auf 180 Tage ohne Aktualisierung angefordert. Die
  **GA4-Property-Aufbewahrung ist im Administrationsbereich noch zu prüfen** (empfohlen:
  2 Monate), ebenso Auftragsverarbeitungsbedingungen und Zugriff auf die Property.
  Die Datenschutzhinweise benennen den noch ungeprüften Aufbewahrungsstand ausdrücklich.
- Im vorhandenen öffentlichen Container sind automatische Ereignisse und Erkennung
  nutzerbereitgestellter Daten konfiguriert. Unsere Einbindung setzt `user_data` leer,
  verweigert `ad_user_data`/Werbung und übergibt keine Formularadresse. Im Google-Konto
  zusätzlich automatische Nutzerdatenerfassung/Enhanced Conversions abschalten und
  bei künftigen Containeränderungen erneut prüfen. Keine neuen Ads-/Remarketing-Tags
  unter derselben reinen Statistik-Einwilligung veröffentlichen.
- CSP erlaubt nur die nötigen Google-Tag-/Analytics-Ziele und lokale Medien, kein
  `unsafe-inline` oder `unsafe-eval`. Die nginx-Konfiguration muss zusammen mit der
  Seite aktualisiert werden; geänderte Container können zusätzliche Prüfungen erfordern.

Zusätzliche Browserprüfung (GTM simuliert, keine Analytics-Sendungen):

```sh
python ui_tests/landing/landing_browser_check.py
python ui_tests/landing/landing_consent_video_check.py
```

Beide Skripte benötigen Playwright mit Chrome und WebKit und legen Bildschirmfotos unter
`landing/.checks/` ab (nicht in Git).

Rechtliche Grundlagen und technische Referenzen:
[§ 25 TDDDG](https://www.gesetze-im-internet.de/ttdsg/__25.html),
[Google Basic Consent Mode](https://developers.google.com/tag-platform/security/guides/consent?consentmode=basic),
[Datenschutzeinstellungen](https://developers.google.com/tag-platform/security/guides/privacy),
[GA4-Cookies](https://support.google.com/analytics/answer/11397207?hl=en-GB),
[GA4-Aufbewahrung](https://support.google.com/analytics/answer/7667196),
[Datenübermittlungen](https://policies.google.com/privacy/frameworks?hl=de).

## Live-Demo (16. November 2026)

`https://demo.inboxstride.de/` ist als Hauptaktion im Hero, im Header und in einem eigenen hervorgehobenen Abschnitt auf Deutsch und Englisch verlinkt. Der gehostete Dienst für echte Postfächer bleibt als in Vorbereitung gekennzeichnet. Die Demo zeigt 30 synthetische Mails, simulierte Aktionen und getrennte zweistündige Besucherbereiche. Die Demo-Oberfläche ist derzeit deutschsprachig. Die Datenschutzhinweise beschreiben die notwendigen Demo-Cookies und die Trennung von Analytics.
