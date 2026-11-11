# Release 5.4 – Hilfschat als Fenster in den Einstellungen

Version 5.4.1, 11. November 2026. Grundlage: [Planung 5.4](Planung-5.4.md).
Die Umsetzungsschritte F1–F7 wurden gemeinsam im Arbeitsstand 5.4.0 umgesetzt und mit 5.4.1
abgenommen; die im Plan genannten Patchnummern waren eine vorgesehene Commitfolge.

## Verhalten

Chatsymbol und „Dazu fragen“ öffnen ein kleines, nicht modales Fenster vor der aktuellen
Einstellungsseite. Suche, Bereichswechsel, Eingaben, Bestätigungen und Speichern lassen es
offen. Vollständige HTML-Antworten stellen den Zustand wieder her. Position und Entwurf
werden tabbezogen und sitzungsgebunden erhalten; der Verlauf verwendet den vorhandenen
Chatdienst. Antworten werden ausschließlich im Fenster aktualisiert und laden die
Einstellungsseite nicht neu.

Den Kopf ziehen oder die Richtungsschaltflächen verwenden, um verdeckte Einstellungen
freizugeben. Bestätigungsformulare haben Vorrang. Schließen blendet das Fenster aus;
Leeren verwirft den Inhalt und hält es geöffnet. Quellen erscheinen im Lesebereich des
Fensters. Alte `/hilfe`-Links öffnen das Fenster auf der Einstellungsübersicht.

## Speicherung und Schutz

`sessionStorage` enthält begrenzt Öffnungszustand, Position, Feldbezug und Frageentwurf,
keine Sitzungstoken und keine Kopie des gesamten Gesprächs. Ein nicht authentifizierender
Sitzungsbezug verhindert die Übernahme in eine andere Anmeldung. Bei gesperrtem
Browserspeicher und ohne JavaScript steht ein versionsgeprüfter und idempotenter
JSON-Zustand unter `help-window-<Hash>.json` bereit. Zustandsaktionen benötigen eine gültige
Sitzung und CSRF; vor Speicherung wird die Sitzung erneut geprüft. Inhalte werden spätestens
bei Sitzungsende beziehungsweise nach Ablauf entfernt. Die Abmeldung des eigenen Geräts unter
**Geräte** löscht den lokalen Entwurf bereits beim Absenden (5.4.1).

Ohne JavaScript erfolgen Fragen und Statusprüfung über Formulare. Vor Navigation ist für
einen ungesendeten Text ausdrücklich **Entwurf behalten** nötig. Ein Speicherausfall wird
angezeigt; JavaScript navigiert dann nicht still mit verlorenem Entwurf weiter.

Der Chat erklärt ausschließlich. Modellwahl, Dokumentationsprüfung, Budgets und notwendige
Bestätigungen externer Aktionen verwenden unverändert die bestehenden Fachverträge.

## 5.4.1: Korrekturen bei der Abnahme

- „Chat leeren“ entfernt Fragen und Feldbezüge auch aus gespeicherten Aufträgen; Deaktivierung,
  Sitzung und Chatversion werden vor jedem Modellversuch erneut geprüft.
- Die Suche umfasst Datei-, Einrichtungs-, Postfach-, IServ- und Zielprofileinstellungen.
- Abmeldung unter **Geräte** ließ den Chatentwurf im Browserspeicher zurück (behoben).
- Ein Sprung zu einer Einstellung derselben Seite löste `popstate` und damit ein Neuladen der
  ganzen Seite aus; ungespeicherte Eingaben gingen verloren (behoben).
- Mehrere Browsertests hingen, weil sie Navigationen im Browser abfingen und dabei Seite oder
  DevTools aufriefen. Die Abdeckung vor einer Navigation erfasst jetzt `navigate_collected`,
  das die folgende Seitenantwort serverseitig anhält.

## Upgrade und Rückkehr

Dienst stoppen, Konfiguration und gesamten Zustand sichern, Paket beziehungsweise Image
aktualisieren und neu starten. Eigene Prompts benötigen keine Ergänzung zu 5.3. Der
Hilfebestand ist mit den neuen Benutzeranleitungen reproduzierbar neu erzeugt.
Neue Anwendungs- oder LLM-Schalter sind nicht nötig. Bei Rückkehr zur Vorversion werden
die zusätzlichen `help-window-*`-Dateien ignoriert; vorher gespeicherte Vorschläge und
Freigaben werden dadurch nicht verändert.

## Abnahme

| Prüfung | Ergebnis |
| --- | --- |
| Windows 11, Python 3.12.10 | **4.537 bestanden**, ein POSIX-Berechtigungstest plattformbedingt übersprungen (Lasttests getrennt) |
| Zeilenabdeckung Windows | **29.132 / 29.132, 100 %** |
| Branch-Abdeckung Windows | **8.456 / 8.456, 100 %**, keine partiellen Zweige |
| Browser-Gesamtsuite | **420 bestanden**, 2 übersprungen, auf Desktop, Mobilgerät und 320-Pixel-Ansicht; JavaScript-Blockabdeckung 100 % in `app.js`, `sw.js`, `setup.js` |
| Lasttests | 4.2 (fünf Browser) Median Warteschlange **329,7 ms**, Maximum **488,7 ms**; 4.4.1 (2.000 Mails) Median Antwortzeit **349,5 ms**, Maximum **431,1 ms**; Grenzen unverändert eingehalten |
| Statische Prüfung | Ruff ohne Befunde; mypy ohne Befunde in **272 Quelldateien** |
| Prompt-Qualitätsgate | bestanden |
| Inventur und Hilfebestand | `devtools.inventory --check` und `devtools.help_index --check` ohne Abweichung |
| Paketprüfung | Wheel und sdist 5.4.1 gebaut |
| Linux/Docker | **Nicht durchgeführt**: Docker war auf dem Prüfrechner nicht verfügbar. |

Die Regressionen für Seitenwechsel, Abmeldung und Ankersprung wurden vor dem jeweiligen Fix
reproduziert. Tests verwenden synthetische Daten und simulierte LLMs.

## Grenzen

- Linux/Docker und echte Modellantwortqualität benötigen einen eigenen Nachweis; der lokale
  Windows-Lauf allein belegt diese Plattform beziehungsweise die Modellqualität nicht. Der
  Bericht [help-chat-5.4.1](../quality-reports/help-chat-5.4.1-2026-11-11.json) enthält eine
  Stichprobe von 35 Anfragen an ein echtes Modell; sie ersetzt keine vollständige Bewertung.
- Ohne JavaScript bleibt ein ungesendeter Entwurf nur nach **Entwurf behalten** über
  Seitenwechsel erhalten.

### Reproduzierbare Prüfungen

```powershell
python -m devtools.check full --workers 8
python -m pytest ui_tests --no-cov -q
python -m ruff check src tests ui_tests devtools
python -m mypy
python -m devtools.check prompts
python -m devtools.inventory --check
python -m devtools.help_index --check
```
