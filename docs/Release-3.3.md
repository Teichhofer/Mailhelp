# Mailhelp 3.3 – Konsolidierung und Weboberfläche

Stand: 14. Oktober 2026. Aktueller Repository-Stand: 3.3.10.
Die technische Konsolidierung wurde mit 3.3.0 abgeschlossen. Das nachfolgende
Facelift ist seit 3.3.1 enthalten; sein ursprünglicher Commit
verwendete vor der anschließenden Versionskorrektur die Nummer 3.3.2.

## Weboberfläche

Ab 1200 Pixeln Breite gliedert eine feste Seitenleiste die Navigation in
Arbeitsbereich, Einblicke und Verwaltung. Kleinere Bildschirme verwenden eine
horizontal wischbare Navigation. Auf dem Handy scrollt die Kopfleiste mit der Seite.
Ein Tastatur-Sprunglink führt zum Inhalt. Die Seitenüberschrift steht vor den Filtern.

Die Übersicht zeigt eine kompakte Arbeitsliste; ab 1024 Pixeln stehen Details daneben.
Status, Zeiten, Ziele, Warnungen und offene Fragen bleiben sichtbar. Beschreibung
und Beleg lassen sich in den Übersichtskarten aufklappen. In der Detailansicht sind
sie direkt zugänglich. Globale Einstellungen besitzen Bereichslinks und eine
aufklappbare Übersicht der verwendeten KI-Modelle. Helles und dunkles Design werden
unterstützt.

Der Service Worker erneuert den Shell-Cache. Er speichert keine Mailinhalte,
Vorschläge oder Aktionen offline. Ein Bearbeiten oder Aufklappen erteilt weiterhin
keine externe Schreibfreigabe; Sitzung, CSRF, Vorschlagsversion und Idempotenz
werden bei bestätigten Aktionen geprüft.

## Technische Konsolidierung

Persistenz liegt im Paket `mailhelp.persistence`, Konfiguration in `mailhelp.config`.
Die deterministische Zeitauflösung ist von Telegram entkoppelt. `ServiceCoordinator`
steuert die Laufzeitdienste. Web-Routing und HTML-Erzeugung sind getrennt; `ArchiveSite`
hält gemeinsame Dienste statt alle Seiten selbst zu bearbeiten.

ruff begrenzt die McCabe-Komplexität auf 15. mypy prüft alle Funktionsrümpfe und
wendet auf die in `pyproject.toml` genannten Kernmodule strikte Typregeln an.
Eine vollständig strikte Webschicht und die weitere Bündelung der Wurzelmodule
sind weiterhin offene Architekturarbeiten, keine bereits zugesagten Funktionen.

## Aktualisieren und prüfen

Dienst stoppen, Konfiguration, Geheimnisse, Token-Dateien und den vollständigen
Zustandsordner sichern. Danach Paket beziehungsweise Docker-Image aktualisieren,
`mailhelp --check` ausführen und neu starten. Diese UI- und Refactoring-Änderungen
erfordern keine neuen Konfigurationsfelder und ändern den Analyse-Fingerprint nicht.
Die Migrationsregeln für Zielprofile bleiben in [Release 3.2](Release-3.2.md) beschrieben.
Eine Rückkehr verwendet die zusammengehörige Sicherung der vorherigen Version;
externe Schreibresultate und Idempotenznachweise müssen erhalten bleiben.

Die lokale Facelift-Abnahme umfasst 2.363 Python-Tests unter Windows sowie die
WSL-Suite mit 100 % Zeilen- und Branch-Abdeckung. Auf beiden Plattformen bestanden
je 158 Browsertests mit vollständiger JavaScript-Blockabdeckung. Paketinstallation,
statische Prüfungen und synthetische Docker-Wiederanläufe wurden ebenfalls geprüft.
Diese Messwerte beziehen sich auf den Facelift-Stand vom 14. Oktober 2026 und
ersetzen keine aktuelle CI oder manuelle Prüfung realer Modellantworten.
