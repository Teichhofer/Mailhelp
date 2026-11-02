# Gedrosselter Instagram-Download

Separates Hilfsprogramm fuer Instaloader 4.16; kein Bestandteil von Mailhelp.
Vor jeder API-Abfrage werden zusaetzlich feste 30 Sekunden gewartet.
Instaloaders eigene Anfragezaehlung, laengere 429-Wartezeiten, Anmeldung,
Fehlerbehandlung und Wiederaufnahme bleiben erhalten. Medienabrufe vom CDN
werden nicht durch diesen RateController gedrosselt.

Aktueller Betrieb: ohne Instagram-Anmeldung. Browser-Cookies werden nicht
geladen; keine Login- oder Sitzungsdatei-Option verwenden. Zuerst werden die
oeffentlichen Profilbeitraege abgerufen. Stories und Highlights erfordern eine
Anmeldung und werden deshalb nicht angefordert. Fuer diesen Versuch wird bei
HTTP 302, 400, 401, 403 oder 429 sofort abgebrochen, statt die Sperre zu wiederholen.

Im Mailhelp-Arbeitsverzeichnis starten:

Auf diesem Rechner wurde der direkte Chrome-Import am 29.10.2026 geprueft:
Nach dem Schliessen von Chrome ist die Cookie-Datei lesbar, aber die
Instagram-Sitzungs-Cookies verwenden v20-Verschluesselung. browser-cookie3
0.20.1 kann diese Sitzung nicht entschluesseln. Deshalb Firefox verwenden;
Chrome muss fuer den Firefox-Import nicht geschlossen bleiben.

```powershell
& .\.tools\instaloader\venv\Scripts\python.exe -X utf8 -u -c "import sys; sys.path.insert(0, '.tools/instaloader'); import slow_instaloader; slow_instaloader.main()" --quiet --no-iphone --abort-on=302,400,401,403,429 --no-compress-json --sanitize-paths --max-connection-attempts 1 --request-timeout 60 --dirname-pattern 'downloads/instagram/{target}' raus.life
```

Sitzungsdateien sind Geheimnisse und liegen im bereits von Git ausgeschlossenen
Downloadordner. Keine Passwoerter als Kommandozeilenargument uebergeben.
Unter Windows ist `-X utf8` erforderlich, damit die Ausgabe von Unicode-Zeichen
in Dateinamen (z. B. dem von --sanitize-paths ersetzten Doppelpunkt bei tagged)
auch mit umgeleiteter Ausgabe funktioniert.
Nicht mehrere Instanzen parallel starten oder waehrend einer 429-Wartezeit
neu starten. Es gibt keine garantierte sichere Abrufgeschwindigkeit.
Ohne Anmeldung ist der vollstaendige Profilumfang nicht garantiert.

Die Offline-Tests pruefen wiederholte Pausen, Neustart, die beibehaltene
429-Behandlung und die unveraenderte Weitergabe von CLI-Erfolgen/Fehlern.

```powershell
$env:PYTHONPATH = '.tools\instaloader;.tools\instaloader\venv\Lib\site-packages'
& .\.venv\Scripts\python.exe -m pytest .tools/instaloader/test_slow_instaloader.py -o addopts= --cov=slow_instaloader --cov-branch --cov-config=.tools/instaloader/coverage.ini --cov-fail-under=100 -q
```
