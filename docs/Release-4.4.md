# Release 4.4 – Pufferschicht für Web-Eingaben und Bedienung ohne Wartezeit

Version 4.4.0, 7. November 2026. Umsetzung und automatisierte Plattformabnahme abgeschlossen.
Grundlage: [Planung 4.4](Planung-4.4.md), Stufe 15.

## Bedienung

Nach einem Klick auf eine Aktion erscheint sofort wieder die Übersicht. Sie springt zur
betroffenen Karte. Die Karte zeigt „Wird verarbeitet …“ und bietet bis zum Ergebnis
keine weitere Aktion an. Andere Karten bleiben bedienbar, und weitere Aktionen werden
in der Reihenfolge der Annahme ausgeführt.

Erfolge erscheinen als kurze Meldung. Fehler, abgelehnte Versionen und unklare Anlagen
bleiben auf der Karte sichtbar, auch nach dem Neuladen und auf anderen gekoppelten
Geräten, bis „Zur Kenntnis genommen“ gewählt wird. Hat Mailhelp eine frühere Anlage
erkannt, bietet die Karte „Erneut anlegen“ und „Nicht erneut anlegen“ mit denselben
versionsgebundenen Formularen an. Fällt die ursprüngliche Karte durch die Entscheidung
weg, erscheint das Ergebnis als Karte „Deine Aktion“.

Ohne JavaScript lädt sich die Übersicht jede Sekunde neu, solange eine Aktion läuft.
Auf breiten Bildschirmen wählt die Übersicht die Karte der gerade ausgeführten Aktion aus.
Die Seite `/aktion/<id>` bleibt als direkter Link erhalten.

## Annahme und Übernahme

`POST /aktion` prüft Sitzung und CSRF und legt den Befehl ohne Sperre der Zustandsablage
und ohne andere zwischen Threads geteilte Sperre ab:

1. Eine Kapazitätsmarke `commands/capacity/<n>.json` wird per exklusivem Hardlink belegt.
   Höchstens 50 Befehle warten, gezählt über Eingang und Warteschlange zusammen.
2. Die unveränderliche Quittung `commands/receipts/<id>.json` wird ebenfalls exklusiv
   angelegt. Ab hier ist der Befehl quittiert.
3. Die Eingangsdatei `commands/incoming/<sha256>.json` dient als zweite Kopie für die
   Reparatur.

Gleicher Idempotenzschlüssel ergibt dieselbe Aktion. Ein anderer Inhalt unter demselben
Schlüssel wird mit 422 abgewiesen. Ein voller Datenträger beantwortet die Anfrage mit 503
und gibt die Kapazitätsmarke frei; derselbe Versuch kann dann erneut gesendet werden.

Der Bedien-Thread übernimmt die Quittungen vor allen anderen Arbeiten in die bestehende
`command-inbox` und prüft dabei Version, Sitzung und Idempotenz erneut. Die Eingangsdatei
löscht er erst nach dem dauerhaften Speichern. Beschädigte, widersprüchliche oder falsch
benannte Dateien werden isoliert und ohne Inhalt als `command_input_damaged` gemeldet; die
Übersicht zeigt einen Hinweis. Abgebrochene Annahmen, Abstürze nach dem Speichern und
Neustarts führen weder zu verlorenen noch zu doppelten Befehlen.

Sicherheitsregeln bleiben unverändert: Bearbeiten und Speichern autorisieren keine externe
Anlage. Eine zwischen Annahme und Ausführung abgelaufene Sitzung verhindert die Ausführung.
Unklare Schreibresultate werden vor jeder Wiederholung abgeglichen.

## Reaktionszeiten

Zielwerte aus der Planung: Antwort auf `POST /aktion` im Median unter 0,1 s und im Maximum
unter 0,3 s, auch während Mailanalyse, Benachrichtigungen und Telegram-Versand laufen und die
Sperre der Zustandsablage gehalten wird.

Die Lastmessung (`tests/services/test_v44_load.py`) simuliert genau diese Lage:

- eine blockierte Mailanalyse,
- einen blockierten Telegram-Versand,
- eine 5 s gehaltene Ablagesperre,
- fünf gleichzeitig angemeldete Browser.

Gemessen wird jeweils die Antwortzeit inklusive Sitzungs- und CSRF-Prüfung, über mehrere Läufe:

| Umgebung | Median | Maximum |
| --- | --- | --- |
| Windows 11, Python 3.12.10 | 25,7–32,8 ms | 36,3–52,4 ms |
| Ubuntu/WSL, Python 3.12.3 | 24,7–32,0 ms | 28,8–33,7 ms |
| Docker `python:3.12.10-slim`, Benutzer 65532, ohne Netzwerk | 9,2–29,1 ms | 11,6–31,8 ms |
| Chrome über echtes HTTP, Bedien-Thread blockiert (`ui_tests/test_ui_v44.py`), Desktop, Mobil und schmal | Einzelwerte 12,1–26,3 ms | 62,0 ms |

**Ausgangswert 4.3.0:** Derselbe POST wartete bei gehaltener Ablagesperre 5.006 ms; ohne
Konkurrenz brauchte er etwa 12 ms. Der Regressionstest `tests/services/test_v44_admission.py`
schlägt auf 4.3.0 nach 0,3 s fehl und besteht mit 4.4.0.

Die Zielwerte sind damit auf allen Plattformen mit großem Abstand erreicht. `/status` zeigt
Median und Maximum der letzten 20 Annahmen neben der Wartezeit bis zum Ausführungsbeginn.
Die Wartezeit bis zum Beginn hängt von der Arbeit vor dem Befehl ab. Sie ist nicht Teil
der Quittung und blockiert den Browser nicht mehr.

## In der Abnahme gefundene und behobene Fehler

Jeder Fehler hat einen Regressionstest, der vor der Korrektur fehlschlug.

- **Kein Neuladen ohne JavaScript:** Die Weiterleitung enthält die Sprungmarke der Karte.
  Ein Refresh auf dieselbe URL mit Sprungmarke springt nur innerhalb der Seite. Die
  Übersicht blieb deshalb dauerhaft bei „Wird verarbeitet …“. Der Refresh nennt jetzt ein
  Ziel ohne Sprungmarke (`tests/web/test_v44_cards.py`).
- **Ergebnis auf breiten Bildschirmen unsichtbar:** Ohne gespeicherte Auswahl wählte die
  Übersicht den ersten Eintrag statt der Karte der Sprungmarke. Das Ergebnis wurde nur
  vorgelesen (`ui_tests/test_ui_v42.py`, `ui_tests/test_ui_v44.py`, Desktop).
- **Meta-Refresh aus nachgeladenem HTML:** `DOMParser` wandelt `<noscript>`-Inhalte in
  echte Elemente um. `app.js` entfernt sie jetzt vor dem Einfügen, damit kein Refresh in
  die laufende Seite gelangt (axe-Regel `meta-refresh`).
- **Übernahme an der Kapazitätsgrenze:** Quittierte Befehle besitzen bereits eine
  Kapazitätsmarke. Die Übernahme prüft deshalb die Warteschlangengrenze nicht mehr.
- **Doppelte Meldung:** Die Übersicht zeigte ein Ergebnis oben (`?ergebnis=`) und auf der
  Karte, Screenreader lasen es zweimal vor. Es steht jetzt nur auf der Karte, und die
  Weiterleitung von `/aktion/<id>` springt dorthin (`tests/web/test_web_actions.py`).
- **Toast verdeckte Schaltflächen:** Der Toast zeigte den gesamten Kartentext und blieb
  stehen. Auf schmalen Bildschirmen fing er Klicks ab. Er zeigt jetzt nur die
  Ergebnismeldung und verschwindet nach sechs Sekunden (`ui_tests/test_ui_actions.py`).
- **Verlorene POST-Antwort:** Eine noch unbekannte Aktion (404) wurde als
  Verbindungsfehler angezeigt. Jetzt bleibt der Hinweis „Antwort unterbrochen …“ stehen,
  und der Status wird weiter abgefragt (`ui_tests/test_ui_v20.py`).
- **Serie ohne JavaScript:** Das Ergebnis eines Serienmitglieds lag in der zugeklappten
  Seriengruppe. Die Gruppe öffnet sich jetzt, solange ein Mitglied eine Aktion zeigt
  (`tests/web/test_v44_cards.py`).
- **„Zuletzt erledigt“ veraltet:** Die Liste wird jetzt zusammen mit der Karte aktualisiert.
- **Ergebnis in der Desktop-Liste unsichtbar:** Die kompakte Liste blendete alle Hinweise
  aus. Das Ergebnis einer nicht ausgewählten Karte war nur kurz im Toast zu sehen. Jetzt
  steht es auch in der Liste (`ui_tests/test_ui_pending_selection.py`, Desktop).
- **JavaScript-Abdeckung:** Die mit 4.4 neuen Pfade in `app.js` waren im Browser
  ungetestet. Dazu gehören Fortschrittsseite, abgelaufene Sitzung, Polling auf
  Detailseiten, abgelehnte POSTs, Doppelabsendung und Formulare außerhalb von Karten.
  `ui_tests/test_ui_v44_paths.py` deckt sie ab. Pfade, die in einer Navigation enden,
  brechen diese ab, damit die Abdeckung gemessen wird.

Mit dem 4.4-Commit vor dieser Abnahme schlugen 34 von 237 Browsertests fehl. 30 davon
erwarteten noch das Verhalten vor den Ergebniskarten, etwa eine verschwindende Karte oder
die Seite „Nicht mehr aktuell“ für unbekannt neuere Versionen. Andere fragten das
Lesemodell ab, bevor der simulierte Bedien-Thread es veröffentlicht hatte. Diese Tests
prüfen jetzt das Verhalten von 4.4. Außerdem erwartete ein E2E-Test nach einem
simulierten Antwortverlust fälschlich „Angelegt.“. Richtig ist der Hinweis auf die unklare
Anlage, die bis zur Kenntnisnahme sichtbar bleibt.

## Qualitätsnachweise

| Prüfung | Ergebnis |
| --- | --- |
| Windows 11, Python 3.12.10 | 3.634 bestanden, ein POSIX-spezifischer Skip; der 4.2-Lasttest (siehe unten) besteht einzeln |
| Docker (Linux), Benutzer 65532, ohne Netzwerk, mit gebauten Paketen | 3.636 bestanden; 213 s |
| Python-Abdeckung | 24.902 Statements, 7.210 Branches; jeweils 100 % |
| Vollständige Browser-Suite | 268 bestanden; 546 s; 100 % JavaScript-Blöcke in `app.js`, `sw.js`, `setup.js` |
| Ruff / mypy | Keine Befunde in `src`, `tests`, `ui_tests`, `devtools`; mypy prüft 238 Quelldateien |

Der 4.2-Lasttest (`tests/services/test_v42_load.py`) misst die Wartezeit bis zum
Ausführungsbeginn von fünf nacheinander ausgeführten Befehlen (Grenze: Median 0,5 s). Er
besteht einzeln unter Windows (Median 377–431 ms) und Docker. Unter acht parallelen
Testprozessen auf einem Windows-Rechner überschreitet er die Grenze. Das ist eine
Messung unter fremder CPU-Last und betrifft nicht die Annahmezeit.

Die Schritte 15.1 bis 15.8 wurden gemeinsam als 4.4.0 geliefert, nicht als einzelne
Patchversionen. Alle automatisierten Dienste und Daten sind simuliert; es erfolgten keine
echten externen Anlagen oder kostenpflichtigen Modellaufrufe.

## Upgrade

Neue Verzeichnisse unter dem Datenverzeichnis: `commands/capacity`, `commands/receipts`,
`commands/incoming`, `commands/acknowledged` und `commands/quarantine`. Sie gehören zur
dauerhaften Zustandsablage und müssen mit ihr gesichert werden. Beim Start werden bestehende
wartende Befehle aus 4.3 übernommen und erhalten Kapazitätsmarken. Eine Rückkehr zu 4.3
setzt eine Sicherung vor dem Upgrade voraus und sollte erst erfolgen, wenn keine Web-Aktion
mehr wartet.
