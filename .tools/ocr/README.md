# Lokale OCR für raus.life

Dieser getrennte Datenaufbereitungsschritt verändert weder Mailhelp noch die
heruntergeladenen Originaldateien. Die Verarbeitung benötigt keinen Kontozugang
und lädt keine Bilder, Videos oder erkannten Texte zu einem Dienst hoch.

## Ablauf

1. Alle vorhandenen Profil-JSON-Dateien direkt unter
   `downloads/instagram/raus.life` werden den dazugehörigen Bildern und Videos
   zugeordnet. Karussell-Bilder und Video-Vorschaubilder sind enthalten.
   Profilbilder sowie der separate Unterordner für markierte Beiträge sind
   ausgeschlossen.
2. FFmpeg extrahiert **zwei Frames pro Sekunde** in Originalabmessungen als JPEG
   mit Qualitätsstufe 2. Die Frames bleiben erhalten. Zeitstempel bezeichnen das
   Abtastraster 0,0 / 0,5 / 1,0 Sekunden usw. Die Videodateien bleiben unverändert.
3. Jedes Bild und jeder extrahierte Frame wird lokal mit RapidOCR verarbeitet.
   Die Ergebnisse enthalten Text, Erkennungswert und Textpositionen. Für anhand
   der Caption deutschsprachige Beiträge ergänzt Tesseract `deu+eng` eine separate
   Transkriptionsalternative aus den erkannten Textregionen.
4. Alle erkannten Zeilen bleiben in den Rohresultaten. Für den zusammengeführten
   Analysetext werden Zeilen mit mindestens drei Buchstaben/Ziffern und
   Erkennungswert >= 0,85 übernommen. Dieser Wert ist ein Modellscore, keine
   Garantie fehlerfreier Erkennung. Exakt normalisierte Textwiederholungen werden
   pro Beitrag zusammengefasst; Quellen und Zeitpunkte bleiben erhalten.

## Start und Fortsetzung

Im Projektverzeichnis:

```powershell
& .\.tools\ocr\venv\Scripts\python.exe -X utf8 -u -c "import sys; sys.path.insert(0, '.tools/ocr'); import ocr_hybrid; ocr_hybrid.main()"
```

Ein Dateilock verhindert parallele OCR-Läufe. Er wird auch bei einem Prozessende
vom Betriebssystem freigegeben. Ein erneuter Lauf erfasst inzwischen neu geladene
Postdateien und verwendet passende vorhandene OCR-Ergebnisse erneut.

Die Prüfsumme des Bilds/Frames sowie der Konfigurationsfingerabdruck müssen zum
Cache passen. Beschädigte OCR-Zwischendateien werden neu erzeugt. Veraltete oder
fehlgeschlagene Resultate dürfen nicht als aktuelle Ergebnisse zusammengeführt
werden. Fehler werden ausgewiesen und führen zum Status `complete_with_errors`,
nicht zum vollständigen Erfolg. Nach einer Reparatur kann derselbe Starter erneut
verwendet werden. Originalmedien und Wiederaufnahmedaten werden bewahrt.

## Ergebnisse

Unter `downloads/instagram/ocr`:

- `status.json`: Phase, Fortschritt, Fehler und Prozessnummer.
- `events.jsonl`: getrenntes Fehler-/Ereignisprotokoll.
- `input-manifest.json`: erfasste Beiträge und Medien mit Konfiguration.
- `frames/`: extrahierte Video-Frames und Abschlussmarker mit Video-Prüfsummen.
- `results/`: Rohtexte, Textpositionen und Erkennungswerte pro Bild/Frame.
- `posts/`: Bildunterschrift und zusammengeführte OCR mit Quellen pro Beitrag.
- `posts-with-ocr.json`: gesamte angereicherte Datengrundlage.
- `posts-with-ocr.csv`: dieselbe Textgrundlage als UTF-8-Tabelle mit Semikolon.
- `summary.json`: tatsächliche Abdeckung und Fehler nach dem Lauf.

`summary.complete` ist nur wahr, wenn alle erwarteten OCR-Resultate vorhanden und
keine Verarbeitungsfehler gemeldet sind. Teilweise Zusammenführungen behalten
ihre echten Abdeckungszahlen; fehlende Resultate werden nicht als leerer Text
oder als erfolgreicher vollständiger Lauf ausgegeben.

Ein einmaliger Abschlusslauf kann mit `ocr_pipeline.finish_pending()` gestartet
werden. Er wartet auf die Freigabe des aktiven OCR-Dateilocks und scannt danach
erneut. Damit können während des langen ersten Durchgangs neu heruntergeladene
Beiträge aufgenommen werden, ohne eine zweite OCR-Instanz parallel zu starten.
Dieser ältere Abschlussstarter arbeitet ausschließlich auf der CPU. Für die
kombinierte Verarbeitung wird der oben gezeigte Hybrid-Starter verwendet.

## Parallele CPU- und GPU-Verarbeitung

Sechs CPU-Arbeiter und **ein** isolierter DirectML-GPU-Prozess erhalten über
einen gemeinsamen Verteiler jeweils verschiedene offene Aufgaben. Der GPU-Prozess
nutzt die getrennte Umgebung `gpu-venv`; die CPU-Umgebung bleibt unverändert.
Jeder Beitrag verwendet weiterhin dieselben Modelle, Originalabmessungen,
Textfilter und zwei Frames pro Sekunde. Die Hardware-Einstellungen stehen in
`execution.yaml`, getrennt von der inhaltlichen Konfiguration. Deshalb bleiben
passende vorhandene CPU-Ergebnisse auch nach der Umstellung gültig.

Bei GPU-Fehler, Prozessabbruch, ungültigem Ergebnis oder mehr als 120 Sekunden
ohne Antwort übernimmt ein CPU-Arbeiter die betroffene Aufgabe. Die CPU prüft
zuvor erneut den Cache: Ist die GPU erst nach dem atomaren Speichern abgestürzt,
wird das fertige Ergebnis wiederverwendet. Es entsteht keine doppelte OCR.
Nach drei aufeinanderfolgenden GPU-Fehlern wird die GPU für diesen Lauf deaktiviert;
alle übrigen Aufgaben gehen an die CPU. Ein GPU-Erfolg setzt diesen Fehlerzähler
zurück. CPU-Fehler bleiben als tatsächliche Verarbeitungslücken sichtbar.

Der GPU-Prozess wird bei Zeitüberschreitung gezielt beendet; ein nativer
Treiberabsturz kann den CPU-Hauptprozess nicht mit beenden. `gpu-stderr.log`
bewahrt die GPU-Diagnostik, `events.jsonl` protokolliert jeden CPU-Rückfall.
`status.json` enthält `cache_reused`, `cpu_done`, `gpu_done`, `gpu_fallbacks`
und den Aktivitätsstatus der GPU. Nach der OCR speichert `execution-summary.json`
diese Zähler dauerhaft. Neue Einzelergebnisse nennen ihren `execution_provider`.

Für DirectML werden Memory Patterns deaktiviert und ONNX-Sitzungen sequenziell
ausgeführt, wie in der [offiziellen ONNX-Runtime-Dokumentation](https://onnxruntime.ai/docs/execution-providers/DirectML-ExecutionProvider.html#configuration-options)
vorgegeben. Dies betrifft die Ausführung innerhalb jeder GPU-Sitzung; CPU und
GPU arbeiten weiterhin parallel. Der GPU-Arbeiter prüft, dass alle drei
OCR-Modelle DirectML tatsächlich als ersten Provider verwenden.

Karussell-Dateien werden numerisch statt alphabetisch geordnet. Innerhalb eines
Videos bleiben Frames chronologisch. Neue OCR-Zeilen, die nicht bereits in der
Caption stehen, werden als Prüfbedarf für die inhaltliche Auswertung markiert.
Die CSV maskiert Text, der sonst als Tabellenformel interpretiert werden könnte.

Es werden keine neuen Themen aus OCR automatisch als bestätigt übernommen.
OCR-Fehler und Text/Bild-Zusammenspiel müssen bei der inhaltlichen Neubewertung
berücksichtigt werden. Die bisherige Caption-Auswertung bleibt als alter Stand
erhalten und kann anschließend mit diesem zusätzlichen Text geprüft werden.

## Prüfung

```powershell
& .\.tools\ocr\venv\Scripts\python.exe -m pytest .tools\ocr\test_ocr_pipeline.py .tools\ocr\test_ocr_hybrid.py -q --override-ini addopts= --cov=ocr_pipeline --cov=ocr_hybrid --cov-branch --cov-report=json:.tools/ocr/coverage.json --cov-fail-under=100
```

Die synthetischen Tests simulieren OCR und FFmpeg. Sie prüfen u.a. Zuordnung,
2-fps-Aufruf und Zeitstempel, Cache/Wiederanlauf, beschädigte Resultate, Fehler,
Einzelinstanz-Lock, Quellenbezug und die Abgrenzung veralteter Ergebnisse.
Zeilen- und Branch-Abdeckung müssen jeweils 100 % sein.
Die Hybrid-Tests prüfen zusätzlich parallele disjunkte Aufgabenverteilung,
GPU-Protokoll/Provider, Timeout, nativen Prozessabbruch, begrenzte GPU-Neustarts,
CPU-Rückfall einschließlich CPU-Fehler und Wiederaufnahme nach einem Absturz
zwischen atomarem Speichern und Bestätigung. Externe Modelle und Dienste werden
dabei simuliert; der echte GPU-Pilot ist separat in `tmp/hybrid-pilot.json` belegt.
