# Release 4.8 – Antwortentwürfe direkt im Postfach

Versionen 4.8.0 bis 4.8.6, 8. November 2026. Grundlage: [Planung 4.8](Planung-4.8.md), Stufe 19.

## Verhalten

Mailhelp erkennt schriftlichen Antwortbedarf unabhängig von Aufgaben und Terminen.
Mit `smart_reply: true`, `auto_draft: true` und `drafts.enabled: true` erzeugt die
Pipeline einen Antwortentwurf und legt ihn mit `\Draft \Seen` per IMAP APPEND ab.
Mailhelp verwendet keinen SMTP-Versand. Offene Entscheidungen bleiben Platzhalter;
die nutzende Person prüft, bearbeitet und versendet die Antwort im eigenen Mailprogramm.

| Version | Schritt | Ergebnis |
| --- | --- | --- |
| 4.8.0 | 19.1 | SPECIAL-USE- und Namens-Fallback für den Entwurfsordner |
| 4.8.1 | 19.2 | Genau ein Re:-Präfix, Reply-To und sichere Threading-Header |
| 4.8.2 | 19.3 | `reply_needed` und `reply_reason` im Aktionsrouter |
| 4.8.3 | 19.4 | Automatische Entwurfsablage mit dauerhafter Message-ID und Abgleich |
| 4.8.4 | 19.5 | Lesbare und kopierbare Webvorschau; Telegram im Benachrichtigungsprofil |
| 4.8.5 | 19.6 | Hauptschalter, optionale globale Ordnerwahl und Webeinstellungen |
| 4.8.6 | 19.7 | End-to-End-Abnahme und Release-Bericht |

## Einstellungen und Upgrade

```yaml
smart_reply: true
auto_draft: false
drafts:
  enabled: true
  folder: null
```

`drafts.enabled` ist standardmäßig an. Die vorhandenen zusätzlichen Schalter
`smart_reply` und `auto_draft` bleiben standardmäßig aus; das Update aktiviert keine
automatischen Ablagen. `auto_draft` und `smart_reply` sind je Postfach überschreibbar.
`drafts.folder` wählt optional einen globalen IMAP-Ordner; `null` nutzt die vorhandene
Postfachvorgabe, danach SPECIAL-USE und übliche Ordnernamen. Mailhelp legt keine Ordner an.

Unter Einstellungen → Antworten lassen sich `drafts.enabled`, `drafts.folder` und
`auto_draft` ohne Neustart ändern. Der Schalter wird unmittelbar vor APPEND erneut
geprüft. Bereits abgelegte Entwürfe werden durch Deaktivieren nicht gelöscht oder verschoben.
Nach dem Softwareupdate ist ein Neustart nötig. Die Antwortfunktion wird wie bisher
über die aktivierte Weboberfläche zusammengesetzt; ohne sie findet keine automatische
Entwurfsablage statt. Es gibt keine neue Zustandsmigration.

## Nachweise

| Kriterium | Automatisierter Nachweis |
| --- | --- |
| Ausschließlich Entwurf, kein Versand | End-to-End-Test sperrt SMTP und prüft IMAP-Flags; keine Aufgaben-/Kalenderschreibversuche |
| Empfänger, Betreff, Threading, Signatur | MIME-Parsing prüft From, Reply-To als To, Re:, In-Reply-To, References und vollständigen Text |
| Keine Doppelentwürfe | Wiederholung, Neustart und Prozessabbruch direkt nach APPEND; Suche nach derselben Message-ID |
| Ordnerwechsel bei unklarem Resultat | Vor APPEND dauerhaft gebundener tatsächlicher Ordner; kein Abgleich oder Fallback in einen anderen Ordner |
| Voller Ordner und getrennter Verbindungsabbruch | Offline-IMAP verweigert APPEND oder bricht vor/nach Annahme ab; Mailverarbeitung endet und Text bleibt erhalten |
| Vorschau und Kopieren | Browsertests auf Desktop, Mobilansicht und 320-Pixel-Ansicht, einschließlich verweigerter und fehlender Zwischenablage |
| Berechtigungen und Einstellungen | Sitzung, CSRF, Versions-/Dateistand, Replay, Live-Übernahme und Deaktivierung an der Schreibgrenze |
| Benachrichtigungen | Referenzbasierte Warteschlange, neutraler Inhaltsmodus, Zusammenfassung und Wiederanlauf ohne erneute Zustellung |

Die sechs neuen Pipeline-Abnahmeszenarien stehen in
`tests/e2e/test_v486_reply_drafts_end_to_end.py`; drei Regressionstests in
`tests/services/test_v486_draft_recovery.py` sichern die Bindung an den ursprünglichen Ordner.
Externe Dienste und Mails sind in
sämtlichen automatisierten Tests simuliert beziehungsweise synthetisch.

## Qualitätsnachweise

| Prüfung | Ergebnis |
| --- | --- |
| Windows 11, Python 3.12.10, Funktionssuite | 3.889 Funktionstests geprüft, ein POSIX-Berechtigungstest unter Windows übersprungen. Im Gesamtlauf bestanden 3.888 Tests; ein Abgleich der Hilfe mit der Dokumentation wurde anschließend korrigiert und mit 18 einschlägigen Tests erfolgreich nachgeprüft. Danach wurde kein Anwendungscode mehr geändert. |
| Zeilenabdeckung | 25.686 von 25.686 ausführbaren Zeilen, **100 %**, keine fehlenden Zeilen |
| Branch-Abdeckung | 7.428 von 7.428 Branches, **100 %**, keine fehlenden oder partiellen Branches |
| Browser-Gesamtsuite | **277 bestanden**, **100 % JavaScript-Blockabdeckung** in `app.js`, `sw.js`, `setup.js` |
| Abschließende Browser-Nachprüfung | 12 bestanden: Vorschau, Kopieren, Statusanzeige und Speichern der neuen Einstellungen auf drei Bildschirmgrößen |
| Ruff / mypy | Ohne Befunde; 247 Quelldateien typgeprüft |

Alle im Plan geforderten Ablage-, Fehler-, Wiederholungs-, Neustart- und
Autorisierungsszenarien bestehen. Es wurden keine neuen Coverage-Ausschlüsse eingeführt;
das automatische 100-%-Gate bleibt unverändert.

Die zwei zeitkritischen Lasttests werden getrennt von parallelen Tests und ohne
Coverage-Messaufwand ausgeführt; ihre Grenzen bleiben unverändert. Beide bestehen:
4.2 (fünf Browser) Median Warteschlange **329,5 ms**, Maximum **496,5 ms**;
4.4.1 (2.000 Mails) Median Antwortzeit **329,8 ms**, Maximum **340,4 ms**.
Unter gleichzeitig laufenden Testprozessen überschritt die ältere 4.4.1-Messung
ihre Laufzeitgrenze. Deshalb werden Funktionsabdeckung und Laufzeit getrennt gemessen.

```powershell
python -m pytest tests/services/test_v42_load.py tests/services/test_v441_load.py --no-cov -q -s
python -m pytest -n 4 --dist loadgroup -q --ignore=tests/services/test_v42_load.py --ignore=tests/services/test_v441_load.py --cov-report=term-missing --cov-report=json:.test-tmp/coverage-v48.json
python -m pytest ui_tests --no-cov -q
python -m ruff check src tests ui_tests devtools
python -m mypy
```

## Grenzen

Die Abnahme belegt die Verarbeitung und das Protokollverhalten mit Offline-IMAP.
Eine neue Prüfung an echten IMAP-Servern, in Docker/Linux oder der Antwortqualität
mit einem echten Modell wurde für diesen Abschluss nicht durchgeführt. Die überprüfte
Konfigurations-Baseline enthält die bereits autorisierte Themenergänzung;
`model_quality_proven` bleibt ausdrücklich `false`.
