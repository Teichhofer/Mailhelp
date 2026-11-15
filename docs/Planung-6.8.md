# Mailhelp 6.8 – Web-Push zuverlässig aktivieren und bei neuen Vorschlägen zustellen

**Zielversion:** 6.8.0, Umsetzung in Patchversionen 6.8.1 bis 6.8.7

**Stand:** 14. November 2026 (überarbeitet nach Prüfung am Code; ergänzt um Push bei neu erkannten
Aufgaben und Terminen)

**Status:** E1 bis E7 in 6.8.1 umgesetzt; die vorgesehenen Arbeitspakete sind in
einer Veröffentlichung gebündelt. Automatisierte Abnahme abgeschlossen; reale
Geräteabnahme aus D7 noch offen. Befund, Nachweise und Betrieb: [Release 6.8](Release-6.8.md).

**Ausgangsstand:** 6.7.4

**Grundlage:** [Entwicklungsregeln](../AGENTS.md), [Web-Push-Implementierung in 2.0](Release-2.0.md),
[Planung 6.7](Planung-6.7.md)

---

## 0. Bestandsaufnahme

Web-Push hat zwei getrennte Ketten. Eine erfolgreiche Aktivierung beweist nicht, dass später eine
Benachrichtigung ankommt.

**Aktivierung:** Einstellungen → „Push aktivieren“ → Browser erlaubt Benachrichtigungen (HTTPS oder
`localhost`; auf iOS nur als installierte Web-App) → Service Worker aktiv → Mailhelp liefert den
öffentlichen VAPID-Schlüssel → Browser erzeugt ein Abonnement → `/api/push/subscribe` speichert es
für die Sitzung.

**Zustellung:** Kategorie ist für Web-Push eingestellt → Warteschlange findet ein gültiges
Abonnement → Mailhelp sendet eine neutrale, verschlüsselte Nachricht an den Push-Anbieter → der
Service Worker zeigt sie an → ein Tipp öffnet Mailhelp.

### 0.1 Was die Prüfung ergeben hat

Geprüft wurden `web/static/app.js`, `web/static/sw.js`, `web/experience.py`,
`notifications/webpush.py`, `notifications/notification_config.py`,
`notifications/notification_runtime.py`, `runtime/experience.py`, `runtime/setup_runtime.py`, die
Tests dazu und die `config.yaml` dieses Arbeitsverzeichnisses. **Nicht** geprüft wurden ein echtes
Gerät, ein echter Push-Anbieter und die Konfiguration der ausgelieferten Instanz (6.7.4 läuft nicht
aus diesem Verzeichnis). Die Spalte „Sicherheit“ sagt, worauf sich ein Befund stützt.

| ID | Stufe | Befund | Nachweis | Sicherheit |
| :--- | :--- | :--- | :--- | :--- |
| **B1** | Zustellung | **Ein vorhandenes Browser-Abonnement wird ungeprüft weiterverwendet.** `subscribe()` gibt ein bestehendes Abonnement zurück, ohne dessen Schlüssel mit dem aktuellen öffentlichen Schlüssel des Servers zu vergleichen. Hat der Server ein neues VAPID-Schlüsselpaar (neues Datenverzeichnis, neues Docker-Volume, Umzug auf einen anderen Rechner), meldet die Oberfläche „Push ist auf diesem Gerät aktiviert“, der Anbieter lehnt aber jede Nachricht ab. | `app.js` (`if (existing) return existing;`); der Browsertest schreibt dieses Verhalten sogar fest („registered again, not replaced“). | Am Code belegt; am Gerät nicht nachgestellt. Passt zu einer Instanz, die neu ausgeliefert wurde. |
| **B2** | Zustellung | **Eine Ablehnung durch den Anbieter bleibt ohne Folge.** Nur 404 und 410 entfernen das Gerät. Bei 401/403 (falscher Schlüssel, ungültige Absenderangabe) bleibt das Abonnement gespeichert; jede weitere Nachricht scheitert gleich, und das Gerät gilt weiter als aktiviert. | `webpush.py`, `deliver` | Am Code belegt |
| **B3** | Anzeige | **Der Service Worker kennt nur zwei Arten.** Er ordnet `decisions` und `briefing` zu; die Warteschlange sendet aber die Kategorien `decisions`, `daily_briefing`, `action_results`, `system_errors` und für den Test `test`. Alles außer `decisions` erscheint deshalb als „Neue Entscheidungen warten in Mailhelp.“ und öffnet `/offen` – auch der Test-Push und der Tagesüberblick. | `sw.js` (`NOTIFICATIONS`), `notification_runtime.py` (`push.deliver(first.device, first.category)`), `setup_runtime.py` (`push.deliver(device, "test")`) | Am Code belegt |
| **B4** | Konfiguration | **Web-Push ist am Server standardmäßig aus und nur mit Neustart einschaltbar.** Ohne `push.enabled: true` wird der Push-Dienst beim Start nicht angelegt; `/api/push/public-key` antwortet mit 503. Die `config.yaml` dieses Verzeichnisses enthält keinen Abschnitt `push`. Die Schaltflächen erscheinen trotzdem. | `config/models.py`, `runtime/experience.py` Zeile 57, `configuration.py` (`SETUP_FIELDS`, nicht in `LIVE_FIELDS`) | Am Code belegt; Stand der ausgelieferten Instanz unbekannt |
| **B5** | Konfiguration | **Ein eigenes Benachrichtigungsprofil erhält Web-Push nicht von selbst.** Die Standardzuordnung (Entscheidungen und Tagesüberblick per Push) gilt nur, solange kein Profil gespeichert ist. Mit Profil oder Postfach-Überschreibung gilt allein dessen Kanalliste; fehlt dort `web_push`, wird nie etwas gesendet – ohne Hinweis. Aktionsergebnisse und Betriebsfehler haben auch im Standard kein Push. | `notification_config.py` (`effective_profile`), `notification_runtime.py` (`destinations`) | Am Code belegt |
| **B6** | Aktivierung | **Verschiedene Ursachen ergeben dieselbe oder eine irreführende Meldung.** 503 beim Speichern („Web-Push ist deaktiviert“) erscheint als „Nicht gespeichert. Bitte Anmeldung prüfen“. Mit vorhandenem Abonnement wird der Schlüssel gar nicht abgefragt, die klare Meldung „auf dem Server nicht eingeschaltet“ entfällt dann. Scheitert die Registrierung des Service Workers, wartet `navigator.serviceWorker.ready` endlos: Es passiert sichtbar nichts. | `app.js` (`changePush`), `web/experience.py` | Am Code belegt |
| **B7** | Aktivierung | **Die Seite zeigt den Zustand des Geräts nicht.** Unter den Schaltflächen steht immer „HTTPS oder localhost erforderlich. Auf iOS zuerst zum Home-Bildschirm hinzufügen.“ – auch wenn das Gerät längst aktiviert ist oder die Voraussetzung fehlt. | `web/experience.py` (`controls`) | Am Code belegt |
| **B8** | Zustellung | **Der ältere Sendeweg verschluckt Fehler.** `PushService.notify` (genutzt, wenn die Benachrichtigungs-Warteschlange nicht läuft) ignoriert Netzwerkfehler und alle Ablehnungen außer 404/410 ohne Protokoll. | `webpush.py`, `notify`; `runtime/experience.py` (`_push`) | Am Code belegt; nur relevant ohne Warteschlange |
| **B9** | VAPID | **Die Absenderangabe ist ein Beispielwert.** `push.subject` steht ab Werk auf `mailto:admin@example.invalid` und ist in der Weboberfläche nicht änderbar. Ob ein Anbieter (insbesondere Apple) diesen Wert ablehnt, ist offen. | `config/models.py`, `defaults/initial-config.yaml` | Vermutung; in D1 zu klären |
| **B10** | Tests | **Kein Test berührt einen echten Browser-Push.** `ui_tests/test_ui_v20.py` ersetzt Service Worker und Push-API durch Attrappen; die Servertests ersetzen den Anbieter. Die Lücken B1 und B3 liegen genau an diesen Nahtstellen. | Testdateien | Am Code belegt |
| **B11** | Konfiguration | **Die mitgelieferten Vorlagen schicken Entscheidungen nur an Telegram.** `config.example.yaml` und die Vorlage der Ersteinrichtung (`defaults/initial-config.yaml`) legen ein Benachrichtigungsprofil mit `decisions: [telegram]` an. Sobald ein Profil existiert, gilt nur noch dessen Liste (B5). Wer Web-Push einschaltet und ein Gerät aktiviert, bekommt deshalb für **neu erkannte Aufgaben und Termine keinen Push** – auch wenn alles andere funktioniert. Die Einrichtung bietet `web_push` für die Kategorien zwar zur Auswahl an, trägt es aber nicht ein. | `config.example.yaml` Zeile 51, `defaults/initial-config.yaml` Zeile 50, `web/setup_site.py` (Auswahl der Kanäle) | Am Code belegt; wahrscheinlichste Ursache für „neue Vorschläge lösen keinen Push aus“ |
| **B12** | Zustellung | **Auch eigene Änderungen lösen einen Entscheidungs-Push aus.** Die Warteschlange erzeugt je Vorschlag **und Version** eine Zustellung. Beantwortet man eine Rückfrage oder wählt einen Wert eines Widerspruchs, entsteht eine neue Version – und das eigene Gerät meldet kurz darauf „Neue Entscheidungen …“, obwohl nichts Neues erkannt wurde. | `notification_runtime.py` (`decisions`, `enqueue_decision`: Schlüssel aus Vorschlag und Version) | Am Code belegt; am Gerät nicht beobachtet |
| **B13** | Zustellung | **Ein neu aktiviertes Gerät erhält sofort einen Push für alle schon offenen Vorschläge.** Die Warteschlange ergänzt bei jedem Durchlauf für jedes Gerät alle offenen Entscheidungen, die es noch nicht bekommen hat. Nach dem Aktivieren – und nach jeder Neuanmeldung wegen eines Schlüsselwechsels (E1) – meldet das Gerät deshalb alte Vorschläge als neu. | `notification_runtime.py` (`_produce`), `notifications.py` (`enqueue`: Kennung enthält das Gerät) | Am Code belegt |

**Bewertung:** B3 ist unabhängig vom gemeldeten Fehler sicher falsch. Für „neu erkannte Aufgaben und
Termine lösen keinen Push aus“ ist B11 die wahrscheinlichste Erklärung, weil sie jede Installation
aus den Vorlagen betrifft. B1 mit B2 und B4 mit B5 erklären „aktiviert, aber es kommt gar nichts“. Welche davon auf der
betroffenen Instanz zutrifft, entscheidet D1; behoben werden alle belegten Befunde, weil jeder für
sich zu demselben Fehlerbild führt.

---

## 1. Ziele und Nichtziele

### Ziele

1. Der gemeldete Fehler ist auf eine Stufe eingegrenzt und mit einem wiederholbaren Ablauf belegt.
2. Die Einstellungsseite zeigt je Gerät, welche Stufe der Kette erreicht ist, und nennt bei der
   ersten fehlenden Stufe genau eine nächste Handlung.
3. Ein Gerät, dessen Abonnement nicht mehr zum Server passt, wird erkannt und mit einem Tipp neu
   angemeldet; es gilt nie als aktiviert, solange der Anbieter ablehnt.
4. Jede Push-Art zeigt ihren eigenen Text und öffnet das passende Ziel.
5. Ein Test-Push beweist die ganze Kette bis zur Anzeige auf dem Gerät.
6. **Jede neu erkannte Aufgabe, jeder neu erkannte Termin (auch Terminänderung und -absage) und jede
   neue Relevanzfrage löst auf jedem aktivierten Gerät einen Push aus** – innerhalb einer Minute nach
   dem Erscheinen unter „Offen“, sofern keine Ruhezeit oder Bündelung gilt. Eigene Antworten und
   bereits bekannte Vorschläge lösen keinen aus.
7. Push-Inhalte bleiben neutral; VAPID-Geheimnisse, Abonnement-Adressen und Schlüssel erscheinen
   weder in Protokollen noch auf Bildschirmen.

### Nichtziele

- Kein Umbau des Benachrichtigungssystems, keine neue Push-Infrastruktur, kein Wechsel der Bibliothek.
- Keine Änderung an Telegram, Ruhezeiten, Bündelung oder Mailverarbeitung.
- Keine Mailinhalte, Betreffzeilen, Namen oder Termine in Push-Nachrichten.
- Kein stilles Ändern eines gespeicherten Benachrichtigungsprofils. Die Vorlagen für neue
  Installationen ändern sich (E6); bestehende Profile werden nur nach ausdrücklicher Bestätigung
  angepasst.
- Keine Änderung, wann Telegram eine Entscheidung meldet; die Regeln aus E7 gelten nur für Web-Push.
- Web-Push bleibt ein zusätzlicher Hinweisweg: Keine Bestätigung und kein Schreibzugriff über eine
  Benachrichtigung.

---

## 2. Entscheidungen

| ID | Frage | Vorschlag |
| :--- | :--- | :--- |
| **E1** | Abonnement passt nicht zum Server (B1) | Beim Aktivieren vergleicht der Browser den Schlüssel des vorhandenen Abonnements mit dem des Servers. Bei Abweichung meldet er das alte ab und erzeugt ein neues – ohne Rückfrage, weil das alte ohnehin nichts mehr empfangen kann. Die Statusanzeige prüft dasselbe beim Laden der Seite und sagt „Neu aktivieren nötig“. |
| **E2** | Ablehnung durch den Anbieter (B2) | 401 und 403 kennzeichnen das Gerät als „vom Anbieter abgelehnt“. Es bleibt gespeichert (zur Anzeige), erhält aber keine weiteren Nachrichten, bis es neu aktiviert wird. Kein automatisches Löschen: Sonst verschwindet die Ursache aus der Anzeige. |
| **E3** | Texte und Ziele je Art (B3) | Feste Zuordnung im Service Worker für `decisions` → `/offen` (Text: „Neue Aufgaben oder Termine zur Entscheidung.“), `daily_briefing` → `/briefing`, `action_results` → `/verlauf`, `system_errors` → `/status`, `test` → `/einstellungen?bereich=benachrichtigungen`. Texte bleiben neutral; der Test heißt „Test: Web-Push funktioniert auf diesem Gerät.“ Unbekannte Arten zeigen „Neue Informationen in Mailhelp.“ und öffnen `/` statt sich als Entscheidung auszugeben. |
| **E4** | Fehlende Kanalzuordnung bei bestehenden Installationen (B5, B11) | Ist Push am Server an und mindestens ein Gerät aktiviert, aber die Kategorie „Entscheidungen“ des wirksamen Profils (oder eines Postfachs) enthält Web-Push nicht, zeigt die Karte „Benachrichtigungen“ den Hinweis „Neue Vorschläge werden nicht per Push gemeldet“ mit der Schaltfläche **„Web-Push für neue Vorschläge einschalten“**. Sie führt in den vorhandenen Bestätigungsweg für Einstellungen (Alt-Neu-Vergleich, ausdrückliche Bestätigung) und ergänzt `web_push` bei Entscheidungen und Tagesüberblick. **Alternative:** nur Hinweis mit Link zum Profil; dann muss man die Liste selbst finden und bearbeiten. |
| **E5** | Einschalten ohne Neustart (B4) | Bleibt bei „Neustart erforderlich“; die Oberfläche sagt das ausdrücklich und blendet die Schaltflächen aus, solange der Server Push nicht anbietet. Ein Wechsel im laufenden Betrieb würde den Aufbau der Laufzeitdienste berühren und ist kein Teil dieser Version. |
| **E6** | Vorlagen für neue Installationen (B11) | `config.example.yaml` und die Vorlage der Ersteinrichtung setzen `decisions: [telegram, web_push]` und `daily_briefing: [telegram, web_push]`. Das ist ohne Wirkung, solange `push.enabled` aus ist oder kein Gerät aktiviert ist (die Warteschlange prüft beides), und richtig, sobald beides zutrifft. |
| **E7** | Was gilt als „neu“? (B12, B13) | Web-Push für Entscheidungen nur bei **erstmals offenem** Vorschlag, neuer Relevanzfrage und neuer Version, deren Herkunft das System ist (eine weitere Mail ergänzt oder widerspricht; im Verlauf `source = system`). Versionen aus eigenen Antworten, Wertwahl oder Bearbeitung (`web`, `telegram`) lösen keinen Push aus. Ein Gerät erhält nur Vorschläge, die nach seiner Aktivierung erschienen sind; beim Aktivieren zeigt die Karte stattdessen „3 Vorschläge warten schon“ mit Link. Mehrere neue Vorschläge in einem Durchlauf ergeben eine Meldung (wie bisher je Gerät gebündelt). |

---

## 3. Maßnahmen

### 3.1 Zustandsanzeige je Gerät (B6, B7)

Die Karte „Benachrichtigungen“ zeigt statt des festen Hinweistexts eine Liste von Stufen, jede mit
Haken, Kreuz oder „noch nicht geprüft“, und unter der ersten fehlenden Stufe genau eine Handlung:

| Stufe | Geprüft durch | Meldung, wenn sie fehlt |
| :--- | :--- | :--- |
| 1. Server bietet Push an | Server | „Web-Push ist am Server ausgeschaltet. Unter Einrichtung einschalten und Mailhelp neu starten.“ (Link) |
| 2. Sichere Verbindung | Browser | „Diese Adresse ist nicht per HTTPS erreichbar. Mailhelp über die HTTPS-Adresse öffnen.“ |
| 3. Browser kann Push | Browser | „Dieser Browser unterstützt kein Web-Push.“ Auf iOS außerhalb der installierten App: „Auf dem iPhone zuerst zum Home-Bildschirm hinzufügen und von dort öffnen.“ |
| 4. Berechtigung | Browser | abgelehnt: „Benachrichtigungen sind für diese Seite blockiert. In den Browsereinstellungen erlauben.“ – offen: Schaltfläche „Push aktivieren“ |
| 5. Hintergrunddienst aktiv | Browser, mit Zeitgrenze von 10 Sekunden | „Der Hintergrunddienst startet nicht. Seite neu laden; hilft das nicht, Websitedaten für Mailhelp löschen.“ |
| 6. Abonnement passt zum Server | Browser und Server | „Dieses Gerät muss neu aktiviert werden.“ mit Schaltfläche (E1) |
| 7. Am Server gespeichert | Server | „Nicht gespeichert: Anmeldung abgelaufen.“ bzw. der genaue Grund |
| 8. Neue Vorschläge werden per Push gemeldet | Server | „Neue Vorschläge werden nicht per Push gemeldet.“ mit Schaltfläche nach E4 (je Postfach) |
| 9. Letzte Zustellung | Server | „Vom Anbieter abgelehnt am … – neu aktivieren.“ bzw. „Zuletzt zugestellt am …“ |

- Ein neuer Endpunkt liefert die Serversicht für die aktuelle Sitzung: Push angeboten, öffentlicher
  Schlüssel, Gerät gespeichert, Aktivierungszeitpunkt, Kennzeichnung nach E2, Kategorien mit Push
  (je Postfach), Zeit und Ergebnis der
  letzten Zustellung als fester Code. Er enthält weder Abonnement-Adresse noch Schlüssel des Geräts.
- Ohne JavaScript zeigt die Karte die Serverstufen (1, 7, 8, 9) und den Satz, dass Aktivieren
  JavaScript braucht.
- Die Antworten von `/api/push/subscribe` unterscheiden mit festen Codes: Push aus (503), Sitzung
  abgelaufen, Anbieter nicht erlaubt, Abonnement ungültig, Schlüsselkonflikt. Die Oberfläche zeigt
  zu jedem Code einen eigenen Satz.

### 3.2 Abonnement und Schlüssel (B1, B2, B9)

- Aktivieren nach E1 in `app.js`; der Vergleich nutzt den Schlüssel, den der Browser am Abonnement
  führt.
- `webpush.py`: Kennzeichnung nach E2 im Gerätezustand; `destinations` überspringt gekennzeichnete
  Geräte; erneutes Aktivieren hebt die Kennzeichnung auf. Ältere Zustände ohne das Feld bleiben gültig.
- Der ältere Sendeweg `notify` (B8) nutzt dieselbe Fehlerbehandlung wie `deliver` und protokolliert
  das Ergebnis als Code.
- Beim Start mit eingeschaltetem Push und unverändertem Beispielwert in `push.subject` erscheint eine
  Warnung auf der Statusseite und in der Verbindungsprüfung. Ob der Wert die Zustellung verhindert,
  klärt D1; falls ja, wird er Pflichtangabe in der Einrichtung.
- Verbindungsprüfung: Das VAPID-Schlüsselpaar ist seit dem letzten Start unverändert (Fingerabdruck
  im Zustand, nie der Schlüssel selbst); ein Wechsel wird als eigenes Ergebnis angezeigt, weil er
  alle Geräte ungültig macht.

### 3.3 Service Worker: Texte und Ziele (B3)

- Zuordnung nach E3 in `sw.js`; der Server sendet weiterhin nur die Art, nie Text oder Adresse.
- Neuer Wächtertest: Er liest die sendbaren Arten aus dem Python-Code und die Zuordnung aus `sw.js`
  und scheitert, wenn einer Art der Eintrag fehlt. Genau diese Naht hat bisher kein Test geprüft.
- Die geänderte Datei führt über den vorhandenen Mechanismus (Kürzel im Namen des Zwischenspeichers)
  zu einem neuen Service Worker; die Zustandsanzeige nennt in Stufe 5 dessen Stand.

### 3.4 Test-Push über die ganze Kette (B10)

- „Test-Push an dieses Gerät senden“ steht direkt auf der Karte „Benachrichtigungen“ (bisher nur in
  der Verbindungsprüfung) und ist erst ab Stufe 7 bedienbar.
- Der Ablauf zeigt drei Ergebnisse nacheinander: „an den Anbieter übergeben“ (Antwort des
  Anbieters), „auf diesem Gerät angekommen“ (der Service Worker meldet den Empfang an die offene
  Seite) und, falls nach 20 Sekunden nichts ankam, „Der Anbieter hat angenommen, das Gerät hat
  nichts angezeigt“ mit den Prüfpunkten Fokus-Modus, Systemeinstellungen, Energiesparen.
- Der Test nutzt den vorhandenen Test-Push der Verbindungsprüfung (`push_test`) mit Sitzung, CSRF
  und Idempotenzschlüssel und ist auf wenige Aufrufe je Minute begrenzt.

### 3.5 Push bei neu erkannten Aufgaben und Terminen (B11, B12, B13, E4, E6, E7)

- **Vorlagen** nach E6; der Test, der Beispielkonfiguration und Vorlage gegen das Schema prüft,
  prüft zusätzlich, dass „Entscheidungen“ Web-Push enthält.
- **Bestehende Profile** nach E4: Hinweis auf der Karte „Benachrichtigungen“, in der
  Zustandsanzeige als Stufe 8 („Neue Vorschläge werden per Push gemeldet“) und in der
  Einstellungssuche; Übernahme nur über den Bestätigungsweg. Postfach-Überschreibungen werden je
  Postfach genannt.
- **Auslöser** nach E7 in `notification_runtime.py`: Für den Kanal Web-Push wird eine Entscheidung
  nur dann in die Warteschlange gestellt, wenn sie neu ist im Sinn von E7. Grundlage ist die Herkunft
  der Version aus dem Verlauf (`HistoryEvent.source`); zu prüfen in der Umsetzung, ob jede
  Versionserhöhung dort ein Ereignis schreibt – sonst wird die Herkunft beim Erzeugen der Version
  am Vorschlag festgehalten.
- **Aktivierungszeitpunkt** je Gerät im Push-Zustand; Zustellungen nur für Entscheidungen, die danach
  erstmals offen waren. Geräte aus älteren Zuständen ohne Zeitpunkt erhalten beim ersten Start mit
  6.8.5 den Startzeitpunkt als Aktivierungszeitpunkt; schon offene Vorschläge lösen dadurch keine
  neue Meldung aus (sie wurden, soweit Push eingetragen war, bereits gemeldet).
- **Durchgängiger Test in der echten Zusammensetzung:** synthetische Mail → Analyse mit
  simuliertem Modell → Vorschlag unter „Offen“ → Durchlauf der Warteschlange → simulierter Anbieter
  erhält genau eine Nachricht der Art `decisions` an das aktivierte Gerät. Derselbe Test für eine
  Aufgabe, einen Termin, eine Terminänderung, eine Relevanzfrage und für zwei Postfächer.

### 3.6 Protokoll

- Jede Stufe hat eine feste, nicht geheime Kennung. Protokollzeilen enthalten Stufe, Ergebniscode,
  HTTP-Statusklasse des Anbieters und den Anbieter als Kurzname (`fcm`, `mozilla`, `apple`,
  `windows`), keine Rohantwort, keine Adresse, keine Schlüssel.
- Wiederholte gleiche Fehler folgen der Zusammenfassung aus 6.4.

---

## 4. Umsetzungsschritte

| Schritt | Patch | Arbeitspaket | Prüfung |
| :--- | :--- | :--- | :--- |
| **D1** | 6.8.1 | **Fehler am Gerät eingrenzen.** Zustandsanzeige nach 3.1 als reine Anzeige (noch ohne Korrekturen) und Protokollcodes nach 3.5. Damit durchläuft der Betreiber auf dem betroffenen Gerät Aktivierung und Test-Push und hält fest: Gerät, Browser, Installationsart, Adresse (HTTPS-Proxy, LAN, `localhost`), erste fehlende Stufe, Code des Anbieters. Dabei wird B9 geklärt. | Browsertests je Stufe mit den vorhandenen Attrappen: jede Stufe einzeln fehlend, Zeitgrenze des Hintergrunddiensts, ohne JavaScript, Desktop und Telefon. Servertests für den Zustands-Endpunkt: Anmeldung erforderlich, keine Adresse und kein Schlüssel in der Antwort, fremde Sitzung sieht nichts. |
| **D2** | 6.8.2 | **Abonnement und Schlüssel** (3.2): Neuanmeldung bei Schlüsselwechsel, Kennzeichnung bei Ablehnung, gleicher Fehlerweg für `notify`, Warnung zum Beispielwert, Fingerabdruck des Schlüsselpaars. | **Regression B1:** vorhandenes Abonnement mit fremdem Schlüssel – vor dem Fix „aktiviert“ ohne neues Abonnement, danach neues Abonnement. **Regression B2:** Anbieter antwortet 403 – vor dem Fix weitere Sendeversuche, danach keiner und Anzeige „abgelehnt“. Dazu: 401, 404, 410, 429, 5xx, Netzwerkfehler; Neustart; widerrufene Sitzung; doppeltes Aktivieren; alter Zustand ohne Feld. |
| **D3** | 6.8.3 | **Service Worker** (3.3): Texte und Ziele je Art, Wächtertest. | **Regression B3:** Push der Arten `daily_briefing`, `action_results`, `system_errors`, `test` – vor dem Fix Text und Ziel von „Entscheidungen“, danach die eigenen. Unbekannte Art; beschädigte Nutzdaten; Klick mit offenem, mit fremdem und ohne Fenster. |
| **D4** | 6.8.4 | **Konfiguration und Meldungen** (3.1 Rest, E5): Schaltflächen nur bei angebotenem Push, eigene Sätze je Fehlercode (die fehlende Kanalzuordnung folgt in D5). | Push aus: keine Schaltflächen, Link zur Einrichtung. Jeder Fehlercode von `/api/push/subscribe` mit seinem Satz. CSRF, abgelaufene Sitzung. |
| **D5** | 6.8.5 | **Push bei neu erkannten Aufgaben und Terminen** (3.5): Vorlagen, Übernahme für bestehende Profile, Auslöser nach E7, Aktivierungszeitpunkt. | **Regression B11:** Installation aus der Vorlage mit eingeschaltetem Push und aktiviertem Gerät, neue Aufgabe – vor dem Fix keine Push-Zustellung, danach genau eine. **Regression B12:** Antwort auf eine Rückfrage erzeugt Version 2 – vor dem Fix ein Push, danach keiner; zweite Mail ändert den Termin (Herkunft System) – Push. **Regression B13:** Gerät aktiviert bei drei offenen Vorschlägen – vor dem Fix ein Push, danach keiner; vierter Vorschlag danach – ein Push. Dazu: Bündelung mehrerer neuer Vorschläge, Ruhezeit (Zustellung danach), zwei Geräte, Postfach ohne Push, Neustart der Warteschlange ohne zweite Zustellung, alter Push-Zustand ohne Zeitpunkt, Übernahme im Bestätigungsweg mit CSRF und Version. |
| **D6** | 6.8.6 | **Test-Push über die ganze Kette** (3.4). | Rückmeldung des Service Workers an die Seite; Zeitgrenze; Begrenzung der Aufrufe; ohne offenes Fenster; Anbieter lehnt ab. |
| **D7** | 6.8.7 | **Abnahme am Gerät und Dokumentation.** Matrix aus Abschnitt 5; `README.md`, `CHANGELOG.md`, `docs/Bedienung.md` (Hilfeindex neu erzeugen), `docs/Betrieb.md` (Datenverzeichnis sichern, Folgen eines Schlüsselwechsels), `docs/Fehlerbehebung.md` (Stufen und Meldungen), Projektspezifikation, `config.example.yaml`, `docs/Release-6.8.md`; in `docs/Bedienung.md` ausdrücklich, wann ein Push kommt und wann nicht (E7). | `python -m devtools.check full`, vollständige Browser-Suite mit 100 % JavaScript-Blockabdeckung. |

**Reihenfolge:** D1 zuerst, weil es den gemeldeten Fehler eingrenzt und ohne Risiko ausgeliefert
werden kann. D3 und D5 sind von allem unabhängig und sofort umsetzbar; D5 behebt voraussichtlich den
häufigsten Fall (B11). D2 und D4 folgen in der Reihenfolge,
die D1 nahelegt. Zeigt D1 eine Ursache außerhalb von B1 bis B13, wird sie als B14 mit eigenem
Regressionstest vor D2 eingeschoben; die übrigen Schritte bleiben, weil ihre Befunde belegt sind.

---

## 5. Abnahmekriterien

- Der gemeldete Fehler ist in `docs/Release-6.8.md` einer Stufe zugeordnet, mit Gerät, Browser,
  Adresse und dem Befund (B1 bis B9 oder neu), der ihn erklärt.
- Jeder der Regressionstests zu B1, B2, B3, B11, B12 und B13 scheitert auf 6.7.4 und besteht danach.
- Eine neu erkannte Aufgabe, ein neuer Termin, eine Terminänderung und eine neue Relevanzfrage lösen
  im durchgängigen Test je genau eine Push-Zustellung je aktiviertem Gerät aus; eine eigene Antwort
  und das Aktivieren eines Geräts lösen keine aus.
- Eine Installation aus der Vorlage meldet neue Vorschläge per Push, sobald Push eingeschaltet und
  ein Gerät aktiviert ist; eine bestehende Installation zeigt den Hinweis aus E4 und lässt sich mit
  einer bestätigten Änderung umstellen.
- Die Einstellungsseite zeigt für jede der neun Stufen den Zustand und bei der ersten fehlenden
  genau eine Handlung; keine zwei Ursachen teilen sich einen Satz.
- Nach einem Wechsel des VAPID-Schlüsselpaars gilt kein Gerät mehr als aktiviert; ein Tipp auf
  „Neu aktivieren“ stellt die Zustellung wieder her.
- Ein vom Anbieter abgelehntes Gerät erhält keine weiteren Sendeversuche und wird als abgelehnt
  angezeigt.
- Jede Push-Art zeigt ihren eigenen neutralen Text und öffnet ihr Ziel; der Wächtertest deckt jede
  sendbare Art ab.
- **Am Gerät**, je einmal auf Android (Chrome), iPhone (installierte Web-App) und Desktop (Chrome
  oder Edge), jeweils über die HTTPS-Adresse:

  | Prüfung | Erwartung |
  | :--- | :--- |
  | Aktivieren | alle Stufen bis 7 mit Haken |
  | Test-Push bei offener Seite | „übergeben“ und „angekommen“; Systemmeldung mit Testtext |
  | Test-Push bei geschlossener App | Systemmeldung erscheint; Tipp öffnet die Benachrichtigungseinstellungen |
  | Neue Aufgabe aus einer Testmail | innerhalb einer Minute Meldung „Neue Aufgaben oder Termine zur Entscheidung.“, Tipp öffnet „Offen“ |
  | Neuer Termin aus einer Testmail | wie oben |
  | Rückfrage auf dem Gerät beantworten | keine Meldung |
  | Gerät neu aktivieren bei offenen Vorschlägen | keine Meldung; Karte nennt die Zahl der wartenden Vorschläge |
  | Tagesüberblick | eigener Text, Tipp öffnet den Tagesüberblick |
  | Neustart des Dienstes | Gerät bleibt aktiviert, Test-Push kommt an |
  | Gerät unter „Geräte“ abmelden | keine weitere Zustellung |

- Push-Nachrichten und Protokolle enthalten keine Mailinhalte, keinen privaten VAPID-Schlüssel,
  keine Abonnement-Adressen und keine Geräteschlüssel (Test über alle neuen Protokollzeilen und
  Antworten).
- 100 % Zeilen- und Branch-Abdeckung, 100 % JavaScript-Blockabdeckung; automatisierte Tests nur
  gegen simulierte Dienste. Der echte Versand in der Geräteabnahme sendet ausschließlich den festen
  Testtext und erfolgt mit ausdrücklicher Freigabe.

---

## 6. Risiken und Gegenmaßnahmen

| Risiko | Gegenmaßnahme |
| :--- | :--- |
| Die Tests bestehen mit Attrappen, das echte Gerät scheitert weiter. | Die Geräteabnahme ist Pflicht; die Zustandsanzeige aus D1 macht jeden weiteren Fehler ohne Entwicklerwerkzeuge ablesbar. |
| Die automatische Neuanmeldung (E1) ersetzt ein noch gültiges Abonnement. | Sie greift nur bei nachgewiesener Abweichung der Schlüssel; gleiche Schlüssel lassen das Abonnement unberührt (Test). |
| Die Kennzeichnung „abgelehnt“ (E2) trifft ein Gerät wegen einer vorübergehenden Störung. | Nur 401 und 403 kennzeichnen; 429, 5xx und Netzwerkfehler bleiben wiederholbar nach der Regel der Warteschlange. |
| Die Zustandsanzeige verrät Angaben über andere Geräte. | Der Endpunkt liefert nur die eigene Sitzung; Test mit zwei Sitzungen. |
| Ein Schlüsselwechsel durch ein nicht dauerhaftes Docker-Volume wiederholt sich. | Fingerabdruck-Prüfung beim Start mit sichtbarem Ergebnis; `docs/Betrieb.md` nennt `web-vapid` als zu sichernden Zustand. |
| iOS zeigt Meldungen nur in der installierten App und nur bei sichtbarer Benachrichtigung je Push. | Stufe 3 erklärt die Installation; der Service Worker zeigt für jeden Push eine Meldung (bleibt so, Test). |
| Zu viele Meldungen, wenn ein Mailschwung viele Vorschläge erzeugt. | Bündelung je Gerät und Durchlauf (eine Meldung für mehrere neue Vorschläge); Bündelungsfenster und Ruhezeiten des Profils gelten weiter. |
| Telegram und Web-Push melden denselben Vorschlag doppelt. | Gewollt, wenn beide Kanäle eingetragen sind; die Karte „Benachrichtigungen“ zeigt, welche Kanäle für Entscheidungen gelten, und das Profil lässt Telegram abwählen. |
| Die Herkunft einer Version ist im Verlauf nicht für jeden Weg erfasst. | Zuerst Test über alle Wege, die eine Version erzeugen; fehlt sie, wird sie am Vorschlag festgehalten (3.5). Im Zweifel gilt eine Version als „System“ und löst einen Push aus – lieber eine Meldung zu viel als ein übersehener Vorschlag. |
| Der Test-Push zeigt private Daten auf dem Sperrbildschirm. | Nur der feste Testtext; die Texte stehen im Service Worker, nie in der Nachricht. |

---

## 7. Relevante Dateien und Tests

- Aktivierung im Browser: `src/mailhelp/web/static/app.js`, `src/mailhelp/web/experience.py`
- Service Worker: `src/mailhelp/web/static/sw.js`
- VAPID, Abonnements, Anbieteraufrufe: `src/mailhelp/notifications/webpush.py`
- Vorlagen: `config.example.yaml`, `src/mailhelp/defaults/initial-config.yaml`
- Herkunft von Versionen: `src/mailhelp/review/archive.py` (`HistoryEvent`)
- Kanäle und Warteschlange: `src/mailhelp/notifications/notification_config.py`,
  `src/mailhelp/notifications/notification_runtime.py`, `src/mailhelp/runtime/experience.py`
- Verbindungsprüfung und Test-Push: `src/mailhelp/runtime/setup_runtime.py`, `src/mailhelp/web/setup_site.py`
- Browserablauf mit Attrappen: `ui_tests/test_ui_v20.py`, `ui_tests/test_ui_pwa.py`
- Server- und Laufzeittests: `tests/services/test_experience_v20.py`,
  `tests/notifications/test_runtime.py`, `tests/notifications/test_setup_web.py`
