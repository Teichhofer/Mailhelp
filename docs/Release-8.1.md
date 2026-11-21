# Mailhelp 8.1 – Umsetzung und Freigabestand

Stand: 20. November 2026. Arbeitsversion 8.1.1, noch in Prüfung, nicht produktiv
bereitgestellt. Grundlage: [Planung 8.1](Planung-8.1.md).

## Implementiert

- Acht lokale Anbietervorlagen mit exakter Domainerkennung, Hinweisen auf
  IMAP-Freischaltung/App-Passwörter und explizitem Laden der Werte ins Formular.
  Ersteinrichtung und Hinzufügen verwenden denselben Katalog. Manuelle Serverwerte
  bleiben möglich; keine E-Mail-Adresse oder Zugangsdaten gehen an einen Suchdienst.
- IMAP-XOAUTH2 mit gebundenen TLS-Servern, abgeschaltetem IMAP-Debugging,
  Token-Erneuerung, Wiederverbindung und bereinigten Fehlermeldungen.
- Getrennte zentrale Anmeldezwecke `calendar`, `gmail` und `microsoft`, zugehörige
  Scopes, verschlüsselte Refresh-Tokens und Zweckprüfung bei Tokenausgabe.
  Microsoft-Clientimport und Freischaltprüfung über mTLS. Alte Kalenderzustände
  werden von Auth-Schema 1 in Schema 2 gelesen; kein automatischer Downgrade.
- Einheitlicher Postfachablauf für Einrichtung und laufende Instanz: Zustimmung,
  lesende Ordnerprüfung, ausdrückliche Übernahme, geschütztes Trennen, Versions-
  und Sitzungsprüfung. Ein Ausfall nach lokaler Speicherung oder unklarer Aktivierung
  erlaubt einen erneuten Abschluss ohne doppelte Speicherung.
- Neue und ersetzte Reader werden zwischen Mailzyklen eingebunden. Fehler beim
  Verbindungsaufbau behalten den alten Reader; gleiche Kontokennung behält Checkpoints.
  Die neuen Auth-Felder verändern keine alten Analysefingerabdrücke.
- Datumsergänzung bei bekannter Uhrzeit korrigiert; auch vollständige Zeitintervalle
  müssen bekannte Uhrzeiten erhalten. `devtools.recover_revision` prüft genau eine
  aktuelle pausierte Antwort vor und setzt sie nur mit `--apply` wieder auf Wiederholung.

## Bisherige Nachweise

- Ursprünglicher Terminfehler: zwei Regressionen vor dem Fix fehlgeschlagen, danach
  bestanden (Winter-/Sommerzeit). Weitere rote/grüne Regressionen für das Verwerfen
  einer bekannten Uhrzeit, alte Fingerabdrücke und ignorierte Reader-Ersetzungen.
- Gezielt: sechs neue Module mit 100 % Zeilen- und Branch-Abdeckung; Postfach-Webablauf
  zuletzt 26 Tests mit 100 % Abdeckung. Bestehende Kalender-/mTLS-Tests wurden mitgeprüft.
- Echter Browser: erster synthetischer Google-Verbindungsfall ohne fertige Konfiguration
  auf dem Desktop bestanden. Alle Geräte und Austauschfälle sowie vollständige Suites folgen.
- Ein erster vollständiger Python-Start scheiterte am gesperrten Standard-Tempverzeichnis.
  Der nächste Lauf mit eigenem Tempverzeichnis wurde unterbrochen und ist kein Erfolgsnachweis.
  Keine Coverage-Ausnahmen oder geänderten Grenzwerte.

## Ergänzender Abgleich am 20. November 2026

Der vorhandene Arbeitsstand enthielt bereits die wesentlichen Anwendungsteile aus
8.0 und 8.1. Die Abschlussprüfung fand veraltete Versionsmarkierungen der beiden
Konfigurationsbeispiele, veraltete HTML-Vergleichsdateien und unzulässige gemeinsame
Testimporte. Diese werden zusammen mit den folgenden Ergänzungen bereinigt:

- Anbietervorlagen enthalten explizit Port, TLS-Modus, Benutzernamensmuster und
  Quellenprüfdatum. iCloud verwendet zunächst den lokalen Benutzernamen; dessen
  Vorschau wurde mit einem zuvor fehlschlagenden Regressionstest korrigiert.
- Ungültige Adressen mit mehreren `@` oder leerem lokalen Teil schlagen keinen
  Anbieter vor; vor der Korrektur schlug der Regressionstest fehl.
- Bekannte Datumsangaben werden auch bei vollständigen UTC-Intervallen in der
  eingestellten Zeitzone verglichen. Zwei rote/grüne Regressionen betreffen
  Mitternachtsgrenzen in Winter- und Sommerzeit.
- Postfachwarnungen bieten eine zweck- und postfachgebundene Wiederverbindung.
  Eine fremde Änderung nach lokalem Speichern sperrt die spätere Aktivierung;
  der Regressionstest reproduzierte zuvor eine unzulässige Weiterleitung mit 303.
- Die Hilfesuche berücksichtigt neben Wortstämmen direkte Wörter und seltene
  Begriffe; bestehende Fachfragen zum Wischen und zu Kontrollabrufen bleiben auffindbar.
- Neue echte Browserfälle verbinden und ersetzen Gmail-/Microsoft-Postfächer
  auf Deutsch und Englisch mit simuliertem Anbieter und echtem lokalen Speichern.
  Alle 18 gezielten Fälle (einschließlich Google-Kalender) bestehen mit echten
  lokalen HTTPS-Weiterleitungen; JavaScript-Abdeckungsmessung bleibt aktiv.
- Revisionswidersprüche melden zusätzlich einen datensparsamen `revision_contract`;
  bekannte Uhrzeit, veränderte/verlorene Zeitfakten und sonstige Widersprüche sind
  ohne Rohantwort oder Mailinhalt unterscheidbar.

Quellenkontrolle am 20.11.2026: die in [Planung 8.1](Planung-8.1.md#8-primärquellen)
verlinkten Anbieterquellen für WEB.DE, GMX, Telekom, IONOS, STRATO, Apple sowie die
Google-/Microsoft-Protokolldokumentation wurden erneut gelesen. Apple nennt für
IMAP zunächst den lokalen Namen und als Alternative die vollständige Adresse.
Dies ist keine Bestätigung einer realen Anmeldung oder Anbieterfreigabe.

## Offene Freigabeschritte und Grenzen

1. Vollständige Python- und Browsersuites getrennt mit allen verbindlichen Grenzwerten:
   am 21.11.2026 im kombinierten Arbeitsstand 8.2.1 erfolgreich abgeschlossen
   (`python -m devtools.check full --workers 12`: 6 372 bestanden, 2 Lasttests bestanden,
   100,00 % Zeilen- und Branch-Abdeckung; `pytest ui_tests`: 998 bestanden, 234 übersprungen,
   100 % JavaScript-Abdeckung nach Ergänzung von `class="button"` am Anbieter-Ladebutton).
2. Anbieterregistrierungen: Laut Betreiber fehlen Google-Gmail-Freigabe und Microsoft-
   Entra-App. Gmail bleibt standardmäßig deaktiviert; ohne Microsoft-Client ist auch
   dieser Anbieter gesperrt. Synthetische Tests ersetzen diese Anbieterfreigaben nicht.
3. Öffentliche Datenschutzhinweise und tatsächlichen Datenfluss vor Mail-OAuth-Freigabe
   abgleichen. Betriebsanleitung: [Postfach-OAuth](../ops/server/OAuth-Postfaecher.md).
4. Der optionale Online-ISPDB-Abgleich ist nicht aktiviert; der vollständige Grundablauf
   verwendet absichtlich lokale Vorlagen und funktioniert ohne Datenbankdienst.
5. Die bestehende zentrale Google-Kalenderverbindung braucht noch ihre geprüfte lokale
   Profilzuordnung, siehe [8.0-Abgleich](Release-8.0.md). Keine automatische Zielannahme.

Serverseitig ausgeführte Änderungen werden erst nach erfolgreicher Prüfung in Handbuch/Vorlagen
und der Kopie unter `/opt/mailhelp/server-docs` als neuer Istzustand dokumentiert.
