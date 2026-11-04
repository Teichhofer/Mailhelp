# Mailhelp 3.8 – Web-Lernmodus und Betrieb

Arbeitsstand 3.8.26, 4. November 2026. Die Gesamtabnahme läuft; ihre Ergebnisse werden
nach den vollständigen Prüfläufen unten ergänzt. 4.0.0 wird hier nicht veröffentlicht.

## Lernen im Browser

Nach der Anmeldung `/lernen` öffnen. Postfach, Ordner (ein Name je Zeile), Anzahl
Mails, Preisobergrenze in USD je Million Tokens und Gesamtbudget wählen. Die
verfügbare Ordnerliste stammt aus dem letzten Postfachabruf. Zunächst die Schätzung
anzeigen und erst danach den kostenpflichtigen lesenden Lernlauf ausdrücklich starten.

Die Schätzung reserviert konservativ Eingabe, Ausgabe, Routen und Reparaturen.
Die Preisobergrenze muss die tatsächlich verwendeten Modelle einschließlich Ausgabe
und Reasoning abdecken. Sie ist eine Annahme des Benutzers, keine garantierte
Anbieterabrechnung. Jeder tatsächliche Modellaufruf reserviert vor dem Netzwerkzugriff
Tokens einschließlich möglicher Transportwiederholungen. Reservierungen bleiben nach
Abbruch oder verlorener Antwort erhalten. Ein nicht ausreichendes Budget pausiert den
Lauf; für andere Preisannahmen oder mehr Umfang einen neuen Lauf starten.

Der Lernlauf verwendet eigene IMAP-Verbindungen und verändert keine Mailflags.
Pause und Abbruch greifen an den Aufruf- beziehungsweise Mailgrenzen. Nach Neustart
wartet der persistierte Lauf auf eine ausdrücklich bestätigte Fortsetzung mit gültiger
Sitzung. Bereits abgeschlossene Mails werden nicht nochmals analysiert; eine beim
Absturz laufende Analyse kann erneut nötig sein. Zwischenstände enthalten Kategorien,
Betreffbelege und Absender, keine Zugangsdaten oder vollständigen Mailtexte.

Jeder neue Lauf besitzt eine eigene Generation. Ein sofortiger Neustart nach
„Abbrechen“ kann daher keine Ergebnisse, Reservierungen oder Fehlermeldungen aus
dem vorherigen Lauf übernehmen, auch wenn dessen Netzwerkantwort noch unterwegs ist.

Im Review jede Karte bearbeiten und als Thema, Ausschlussthema oder „Nicht übernehmen“
auswählen. Die Zuordnung gilt zunächst nur für das gewählte Postfach; „Für alle
Postfächer“ erweitert sie ausdrücklich. Absender werden ausschließlich bei gewähltem
Ausschlussthema und zusätzlichem Häkchen ignoriert. Änderungen als Entwurf speichern.
Zusätzliche Ordner werden separat ausgewählt; die Rollen `junk` und `trash` sind
anfangs abgewählt. Erst „Ausgewählte Themen, Filter und Ordner ausdrücklich übernehmen“
schreibt die vier lokalen Dateien gemeinsam. Das Journal vervollständigt unterbrochene
Übernahmen bei Wiederanlauf. Bei fremden Dateiänderungen stoppt die Wiederherstellung.

Die Terminalalternative `mailhelp --learn ANZAHL` bleibt erhalten und verwendet
denselben Klassifikationskern. Keine Lernaktion legt Termine oder Aufgaben an.

## Neuladen und Selbsttest

Unter `/dienst/neu-laden` den gespeicherten Stand ausdrücklich übernehmen. Der nächste
sichere Mailzyklus bereitet eine vollständige neue Laufzeitgeneration vor: Themen,
Prompts, Postfachänderungen und entfernte Postfächer, Zugangsdaten sowie Zielprofile
und OAuth-Tokens. Offene Vorschläge bleiben an ihre bisherige Version und ihr Ziel
gebunden; das Neuladen autorisiert keine neue Anlage.

Unfertige Mailanalysen und Warteschlangen werden unter ihrer ursprünglichen
Konfiguration abgeschlossen. Bei wartender Relevanzentscheidung diese zuerst
beantworten; bei Analysefehlern zuerst die Ursache beheben beziehungsweise erneut
prüfen. Es werden keine halben Analysen mit einem neuen Fingerprint liegen gelassen.
Hintergrunddienste werden angehalten, laufende Bedienaktionen dürfen abschließen.
Neue Adapter werden aufgebaut und lesend geprüft. Sitzung und Dateistand werden vor
der Aktivierung nochmals geprüft; ein Fehler erhält die bisherige Generation.
Danach wechseln die HTTP-Routen am bestehenden Socket, und alte Verbindungen schließen.

Änderungen am Web-Zugang einschließlich Sitzungsschlüssel, Web-Konfiguration,
Datenverzeichnis oder Test-/Produktivmodus erfordern weiterhin einen Prozessneustart.
Diese Grenzen werden beim Neuladen abgelehnt. Prozessvariablen haben weiterhin Vorrang
vor `.env`. Der erste Einrichtungsabschluss aktiviert dagegen den Normalbetrieb im
selben Prozess und bietet den Link zum Lernmodus an.

`/dienst/selbsttest` prüft alle Komponenten lesend im Hintergrund. Die Diagnose
enthält je Komponente Ergebnis und Handlungsempfehlung. Die ausdrücklich separaten
Telegram-, Push- und kostenpflichtigen Modell-Testaktionen werden dabei ausgelassen.
`/status` zeigt die erfassten Cloudkosten des laufenden Monats in der konfigurierten
Zeitzone, Aufrufe ohne Preisangabe und die letzte beobachtete Abfrage je Postfach.

## Sicherheits- und Anbietermatrix

`tests/external/test_provider_safety_matrix.py` verwendet Produktionsadapter mit
unabhängig gespeichertem synthetischem HTTP-Dienstzustand. Anbieter sind Google
Kalender, Todoist, Outlook-Kalender, Microsoft To Do, CalDAV-Kalender und -Aufgaben
sowie Apple Erinnerungen. Es werden keine echten Konten oder Daten verwendet.

| Szenario | Nachweis |
| :--- | :--- |
| P1 | Web- und Telegram-Bestätigung derselben Version in beiden Reihenfolgen |
| P2/P7 | Wiederholung während der tatsächlichen HTTP-Schreiboperation; gleiche Command-ID, höchstens eine Anlage |
| P3/P4 | Bearbeiten beziehungsweise Ablehnen vor alter Bestätigung; alte Version schreibt nicht |
| P5 | Zusammenführen und anschließende alte Bestätigung; neue Version bleibt unbestätigt |
| P6 | Widerruf vor Ausführung und erneute Autorisierung an der Adaptergrenze |
| CSRF | Fehlender oder ungültiger Schutz verhindert jede externe Aktion |
| A1–A4 | Harter Abbruch vor Schreiben, nach externem Erfolg, vor und nach lokaler Erfolgsmarkierung; zwei frische Neustarts |
| Verlorene Antwort | Echtes Transport-Timeout nach persistiertem Erfolg, anschließend lesender Abgleich mit frischen Adaptern |
| Zieländerung/Testmodus | Keine externe Anfrage bei abweichendem bestätigtem Ziel oder Testmodus |
| Kalenderänderung/Storno | Bestehende Ressource ändern; Google/CalDAV stornieren im Kalenderformat, Outlook löscht den Termin |
| A5–A7 | Bestehende gemeinsame Merge-Journal-Prüfungen laufen erneut in der Gesamtsuite |

Aufgabenänderung und -löschung sind keine unterstützten Mailhelp-Operationen; dafür
werden keine fiktiven Erfolgsszenarien behauptet. Harte Kalenderlöschung ist nur beim
Outlook-Stornoweg vorgesehen. Google und CalDAV verwenden eine bestätigte Stornierung.
Eine unklare Änderung einer bestehenden CalDAV-Ressource wird nicht blind wiederholt;
der deterministische Neuanlagepfad lässt sich über seine Ressourcenadresse abgleichen.

## Abnahme

Ergebnisse und Plattformberichte folgen nach Abschluss der Prüfläufe.
