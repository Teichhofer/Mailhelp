# Mailhelp-Projektwebsite

Die statische Website liegt in `website/`. Sie enthält Startseite, Einrichtung,
Konfiguration, Datenschutz, Impressum und Nutzungsbedingungen. Betreiber ist
Stefan Hartmann, Teichhof 1, 74670 Forchtenberg, Deutschland; öffentlicher Kontakt:
mailhelp@email.de. Das Angebot ist ein privates Open-Source-Projekt zum Selbsthosten.

## Lokal ansehen

```powershell
python -m http.server 8765 --bind 127.0.0.1 --directory website
```

Im Browser `http://127.0.0.1:8765/` öffnen. Relative Verweise funktionieren auch
unter dem GitHub-Pages-Projektpfad `/Mailhelp/`.

## Veröffentlichen

Nach Commit und Push in GitHub unter **Settings → Pages → Build and deployment**
die Quelle **GitHub Actions** auswählen. Anschließend den Workflow **GitHub Pages**
unter **Actions → Run workflow** manuell starten. Er veröffentlicht ausschließlich
`website/`, nicht den Repository-Stamm, Konfigurationen, Logs oder Testberichte.
Die erwartete Projektadresse ist `https://teichhofer.github.io/Mailhelp/`.
Die tatsächlich veröffentlichte Adresse steht im Deployment-Ergebnis.

Der Workflow prüft erforderliche Seiten, unvollständige rechtliche Platzhalter,
unerwartete Dateien und symbolische Links. Er startet nicht automatisch beim Push.

## Datenschutz und Pflege

Schriften, CSS und Logo werden lokal geladen. Die Seite verwendet keine eigenen
Cookies, Skripte, Local-Storage-Daten, Analysewerkzeuge, Formulare oder eingebetteten
Fremdinhalte. GitHub Pages verarbeitet dennoch technische Besucherdaten, darunter
IP-Adressen. Das steht ausdrücklich in der Website-Datenschutzerklärung.

Website und selbst betriebene Anwendung haben unterschiedliche Datenflüsse.
Die vorhandenen `DATENSCHUTZ.md` und `NUTZUNGSBEDINGUNGEN.md` bleiben Vorlagen für
Instanzbetreiber; sie sind keine automatisch ausgefüllte Erklärung für jede Installation.
Für eine Google-OAuth-Anwendung müssen deren rechtliche Seiten den tatsächlichen
Instanzbetrieb beschreiben. Die Website-Erklärung allein ersetzt das nicht.

Bei Änderungen an Betreiberkontakt, Hosting, Diensten oder Seitentechnik die
rechtlichen Seiten entsprechend aktualisieren. Die Texte begründen keine pauschale
Garantie rechtlicher Vollständigkeit für andere Betreiber oder neue Funktionen.
