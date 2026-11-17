# Mailhelp 7.7 – Vorfilter-Regeln und VIP-Absender

**Zielversion:** 7.7, Umsetzung in Patchversionen 7.7.1 bis 7.7.6  
**Stand:** 17. November 2026 (überarbeitet nach Abgleich mit dem Code von 7.5.4)  
**Status:** In Umsetzung; 7.7.1 umgesetzt, siehe [Release 7.7](Release-7.7.md).  
**Ausgangsstand:** Nach Abschluss von 7.5 (Mehrsprachigkeit, 7.5.5–7.5.7 stehen noch aus) und 7.6 (klärungsfreie Demo-Vorschläge).  
**Grundlage:** [Entwicklungsregeln](../AGENTS.md), [Projektspezifikation](../Mailhelp-Projektspezifikation.md), [Architektur](Architektur.md), [Bedienung](Bedienung.md), [Web-Einstellungen](Web-Einstellungen.md).

---

## 1. Ziel

Mails, deren Einordnung schon vorher feststeht, sollen ohne Relevanz-Aufruf des Sprachmodells
eingeordnet werden. Das betrifft zwei Fälle:

- **Immer irrelevant:** Werbung, Versandbestätigungen, No-Reply-Systemmails und Abwesenheitsnotizen.
  Diese Mails kosten heute je einen Relevanz-Aufruf. Bei 30 solchen Mails am Tag und rund
  1.200 Tokens je Aufruf sind das etwa 1 Mio. Tokens im Monat. Hinzu kommen Wartezeit in der
  Abrufreihenfolge und Ratenlimits bei Cloud-Anbietern.
- **Immer relevant (VIP):** Absender wie Familie, Schule oder Arbeitgeber sollen nie als
  irrelevant aussortiert werden. Für IServ-Konten gibt es das heute schon (`always_relevant`).
  Für einzelne Absender gibt es es nicht.

Die Zahlen sind Annahmen. Die tatsächliche Einsparung misst 7.7.5 an den eigenen Aufrufdaten.

**Nicht Ziel von 7.7:** Regeln, die Mails löschen oder verschieben, oder freie reguläre Ausdrücke.
Auch automatisch angelegte Regeln ohne Zustimmung gehören nicht dazu, ebenso wenig Änderungen an
der Bestätigungspflicht für Kalender- und Aufgabeneinträge.

---

## 2. Ist-Zustand (geprüft am Code von 7.5.4)

Gegenüber dem ersten Entwurf dieses Plans gibt es schon deutlich mehr. 7.7 baut darauf auf und
ersetzt es nicht.

| Baustein | Vorhanden | Ort |
| :--- | :--- | :--- |
| Absenderfilter für Adressen und Domains, global und je Postfach | ja, Schema 2 | `domain/relevance.py` (`IrrelevantSenders`, `SenderRules`) |
| Ausnahmeliste je Postfach (`allow`) | ja; hebt nur die Sperre auf, erzwingt **keine** Relevanz | `SenderRules.allow` |
| Sicherung vor Schema-Umstellung | ja (`irrelevant-senders.json.v1`) | `mailbox/sender_filter.py` |
| Überspringen aller Folgeschritte bei „irrelevant“ | ja (`_skip_after_irrelevant`) | `processing/mail_pipeline.py` |
| Keine Bilderkennung bei gesperrtem Absender | ja (`vision = "skipped_sender"`) | `processing/orchestrator_proposals.py` |
| Herkunft der Relevanzentscheidung | ja, `source` in `analysis-<id>.json` (`prefilter`, `iserv`, `self_mail`, Anbieter) | `persistence/archive.py` |
| Web: Absender ignorieren / zulassen an der Mail, Liste mit Hinzufügen/Entfernen | ja, über idempotente `AdminCommand`s | `web/sender_site.py`, `web/sender_pages.py` |
| Absenderhinweise aus verworfenen Vorschlägen inkl. „nicht mehr vorschlagen“ | ja (6.5) | `review/proposal_evaluation.py` (`sender_hints`), `/auswertung` |
| Kostenauswertung je Aufruf (USD, EUR, lokales Ollama) | ja | `web/calls_page.py` |
| Erkennung automatischer Mails (`Auto-Submitted`, `List-Unsubscribe`) | nur im Aktivitätsbericht | `activity/scan.py` (`_automated`) |

**Was fehlt:**

1. Die aufbereiteten Kopfzeilen (`MailHeaders`) enthalten weder `List-Id`, `List-Unsubscribe`,
   `Precedence` noch `Auto-Submitted`. Die Pipeline kann darauf heute also gar nicht filtern.
2. Es gibt keine Muster wie `no-reply@*` oder `*.newsletter.example`, keine Betreffregeln und
   keine VIP-Regel, die Relevanz erzwingt.
3. Es gibt keine Trefferzahlen je Regel und keine Kennzahl für vermiedene Aufrufe.
4. Es gibt keine Hinweise aus der Relevanzbewertung selbst. Die vorhandenen Absenderhinweise
   stützen sich nur auf verworfene Vorschläge, also auf Mails, die schon als relevant galten.
5. `is_irrelevant_sender` wird an sieben Stellen direkt aufgerufen: Pipeline, Bilderkennung,
   Entscheidungstest, Lernmodus, Aktivitätsbericht, Web-Mailseite und Lernaufträge. Eine neue
   Regelart muss an allen sieben Stellen gleich wirken.

**Korrekturen am ersten Entwurf:**

- `processing_filed` gilt für abgelegte **Fehler**. Es ist kein Status für irrelevante Mails und
  wird nicht verwendet.
- Irrelevante Mails durchlaufen schon heute keine Folgeschritte mehr.
- Kosten werden in Euro gezeigt, wie in der übrigen Auswertung.

---

## 3. Fachliches Konzept

### 3.1 Prüfreihenfolge

Die Relevanzprüfung (`_relevance`) prüft künftig in fester Reihenfolge. Der erste Treffer
entscheidet:

1. Eigenes Postfach-Briefing → irrelevant (unverändert)
2. **VIP-Regel** oder IServ-Konto → relevant
3. **Sperrregel** (Adresse, Domain, Muster, Betreff) → irrelevant
4. **Kopfzeilen-Vorfilter**, nur wenn eingeschaltet → irrelevant
5. Kein aktives Thema im Postfach → irrelevant (unverändert)
6. Eigene Notiz oder Weiterleitung (`self_mail`) → wie bisher
7. Sprachmodell

VIP steht vor jeder Sperre. Eine Mail, auf die beides zutrifft, gilt als relevant. Die
Einstellungsseite zeigt solche Überschneidungen beim Anlegen an.

### 3.2 Regelarten

| Art | Beispiel | Abgleich |
| :--- | :--- | :--- |
| Adresse | `newsletter@shop.test` | exakt, kleingeschrieben (wie heute) |
| Domain | `shop.test` | Domain und alle Subdomains (heute nur exakt; siehe 3.5) |
| Muster | `no-reply@*`, `noreply*@*`, `*@mail.shop.test` | nur `*` als Platzhalter, höchstens 3 je Muster, höchstens 120 Zeichen |
| Betreff | `Automatische Antwort:` | enthält, ohne Groß-/Kleinschreibung, nach Unicode-Normalisierung |

Für die Wirkung gibt es nur zwei Aktionen:

- **Ignorieren:** Die Mail gilt als `irrelevant` mit der Begründung „Vorfilter: <Regel>“.
- **VIP:** Die Mail gilt als `relevant` mit der Begründung „VIP-Absender: <Regel>“. Optional
  gibt die Regel Themen vor. Diese müssen im Postfach vorhanden und aktiv sein, sonst bleibt
  die Themenliste leer. Ein eigenes `FORCE_TOPIC` entfällt.

Die Betreffregel gibt es nur zum Ignorieren. Ein Betreff ist frei wählbar und darf deshalb
nie Relevanz erzwingen.

Jede Regel gilt global oder für ein Postfach, wie heute.

### 3.3 Kopfzeilen-Vorfilter

Ein Treffer liegt vor, wenn eine der folgenden Kopfzeilen passt:

- `Auto-Submitted` hat einen anderen Wert als `no`.
- `Precedence` ist `bulk`, `junk` oder `list`.
- `List-Unsubscribe` oder `List-Id` ist vorhanden.

Viele erwünschte Mails tragen genau diese Kopfzeilen, etwa Rundbriefe von Schule, Verein oder
Kita. Deshalb gilt:

- Beide Schalter sind **standardmäßig aus**:
  - „Automatische Systemmails“ (`Auto-Submitted`/`Precedence`)
  - „Newsletter und Verteiler“ (`List-*`)
- **Probelauf:** Vor dem Einschalten zählt Mailhelp, welche Mails *gefiltert worden wären*, und
  zeigt diese an. Es schaltet dabei nichts ab und spart nichts. Der Probelauf lässt sich je
  Schalter starten.
- **Ausnahmen je Verteiler:** Eine `List-Id` kann auf die Ausnahmeliste gesetzt werden. VIP-Regeln
  wirken ohnehin vorher.

### 3.4 Vertrauen und Sicherheit

- Kopfzeilen sind nicht vertrauenswürdige Eingaben. Sie werden nur gekürzt und normalisiert
  gespeichert und nie als Muster ausgewertet.
- **VIP ist fälschbar.** Der `From`-Kopf kann vorgetäuscht werden. Eine VIP-Regel spart deshalb
  ausschließlich den Relevanz-Aufruf. Sie ändert nichts an Extraktion, Rückfragen und der
  versionsbezogenen Bestätigung vor jedem Kalender- oder Todoist-Schreibzugriff. Das schlimmste
  Ergebnis einer gefälschten VIP-Mail ist ein Vorschlag, den die Nutzerin oder der Nutzer
  verwirft.
- **Kein ReDoS:** Muster werden ohne reguläre Ausdrücke segmentweise abgeglichen
  (Präfix/Suffix/Teilstücke). Länge und Platzhalterzahl werden beim Speichern begrenzt.
- **Regeländerungen** sind keine externen Schreibzugriffe. Sie laufen wie heute als idempotente
  `AdminCommand`s im Hauptthread. Im Web gelten Sitzungsprüfung bei der Ausführung, CSRF-Schutz,
  Versionsprüfung der Regeldatei und ein Idempotenzschlüssel.
- **Nichts geht verloren:** Gefilterte Mails bleiben im Mailarchiv unter „irrelevant“ sichtbar, mit
  Regelname als Begründung. Von dort lassen sie sich wie bisher erneut prüfen.

### 3.5 Datenmodell und Migration

Die Datei `irrelevant-senders.json` **behält ihren Namen** und steigt auf Schema 3. Ein Umzug
nach `filter-rules.json` würde Lernaufträge (`runtime/learning_jobs.py`), Entscheidungstest,
Auswertung, Sicherung und Export gleichzeitig berühren und bringt fachlich nichts.

```python
class SenderRule(StrictModel):
    id: str                      # stabil, z. B. sha256(kind, value, mailbox)[:16]
    kind: Literal["address", "domain", "pattern", "subject"]
    value: str                   # normalisiert
    action: Literal["ignore", "vip", "allow_only"] = "ignore"
    subdomains: bool = True      # nur bei domain; migrierte Regeln: False
    topic_ids: list[str] = []    # nur bei vip
    mailbox: int | None = None   # None = alle Postfächer
    enabled: bool = True
    note: str = ""               # max. 200 Zeichen
    created_at: datetime
    origin: Literal["manual", "mail", "hint", "telegram", "migration"] = "manual"

class HeaderPrefilter(StrictModel):
    automated: Literal["off", "trial", "on"] = "off"
    lists: Literal["off", "trial", "on"] = "off"
    trial_since: dict[str, datetime] = {}
    list_exceptions: list[str] = []      # List-Id-Werte

class IrrelevantSenders(StrictModel):    # Name bleibt für Kompatibilität
    schema_version: Literal[3] = 3
    rules: list[SenderRule] = []
    headers: HeaderPrefilter = HeaderPrefilter()
```

- **Migration:** Schema 1 und 2 werden beim Lesen verlustfrei übersetzt.
  - `addresses` und `domains` werden zu globalen Ignorier-Regeln.
  - `mailboxes[n].addresses` und `mailboxes[n].domains` werden zu Postfach-Regeln.
  - `mailboxes[n].allow` wird zu einer Postfach-Ausnahme mit der Aktion `allow_only`, die nur die
    Sperre aufhebt. Diese Bedeutung bleibt erhalten und wird nicht stillschweigend zu VIP. Die
    Einstellungsseite bietet stattdessen „Als VIP übernehmen“ an.
- **Domainabgleich:** Bisher wirkt eine Domainregel nur auf die exakte Domain. Migrierte
  Domainregeln behalten genau dieses Verhalten (`subdomains=False`). Nur neue Regeln schließen
  Subdomains standardmäßig ein.
- **Sicherung:** Vor dem ersten Schreiben von Schema 3 legt Mailhelp
  `irrelevant-senders.json.v2` an, nach dem Muster der vorhandenen `.v1`-Sicherung.
- **Kein Zustand in der Regeldatei:** Trefferzahlen werden nicht in die Regeldatei geschrieben.
  Sonst entstünde bei jeder Mail ein Schreibzugriff und ein Konflikt mit Web-Änderungen und
  Lernaufträgen. Stattdessen hält der Hauptthread `prefilter-hits.json` (Regel-ID →
  Zähler, letzter Treffer). Probelauf-Treffer landen dort gesondert. Kennzahlen zu vermiedenen
  Aufrufen werden aus `analysis-<id>.json` abgeleitet, wo `source` und künftig `rule_id`
  gespeichert sind, und nicht als eigener Zähler fortgeschrieben.

### 3.6 Ein gemeinsamer Auswerter

`mailbox/sender_filter.py` bekommt eine reine Funktion:

```python
def prefilter(headers: MailHeaders, rules: IrrelevantSenders, mailbox: int,
              *, trial: bool = False) -> PrefilterMatch | None
```

Sie liefert Aktion, Regel-ID und Begründung. Alle sieben heutigen Aufrufstellen von
`is_irrelevant_sender` werden darauf umgestellt. `is_irrelevant_sender` bleibt als dünner
Wrapper (`match.action == "ignore"`) für Stellen, die nur Absender kennen.

Ein Architekturtest stellt sicher, dass außerhalb von `sender_filter.py` niemand mehr selbst
Regeln auswertet.

### 3.7 Nachträgliche Wirkung

Neue Regeln wirken auf neu eintreffende Mails. Beim Anlegen zeigt Mailhelp, wie viele bereits
verarbeitete Mails betroffen wären:

- **Ignorieren:** „12 frühere Mails dieses Absenders. Offene Vorschläge daraus bleiben bestehen.“
  Mailhelp verwirft nichts automatisch.
- **VIP:** „3 frühere Mails wurden als irrelevant eingestuft. Erneut prüfen?“ Das läuft über die
  vorhandenen Neuanalyse-Aufträge (`reanalysis_site`) und kostet dann bewusst Modellaufrufe.

### 3.8 Regelhinweise (unter „Lernen“)

Lernfunktionen gehören ins Menü **Lernen**, nicht unter Einstellungen oder Themen. Die
vorhandenen Absenderhinweise aus 6.5 werden um eine zweite Quelle erweitert, statt einen neuen
Dienst zu bauen.

| Quelle | Bedingung | Vorschlag |
| :--- | :--- | :--- |
| Verworfene Vorschläge (vorhanden) | ≥ 5 Vorschläge in 90 Tagen, Annahmequote ≤ 10 % | Absender ignorieren |
| **Relevanzbewertung (neu)** | ≥ 3 Mails desselben Absenders in 30 Tagen, alle vom Modell als irrelevant eingestuft, keine menschliche Gegenentscheidung | Absender ignorieren |
| **Bestätigte Vorschläge (neu)** | ≥ 5 Mails, jede mit mindestens einem bestätigten Vorschlag, nie irrelevant | Als VIP einstufen |

- **Gleiche Domain:** Treffen die Bedingungen für mehrere Adressen derselben Domain zu, wird
  zusätzlich die Domainregel vorgeschlagen. Ausgenommen sind große Mailanbieter wie
  `gmail.com` und `web.de` (Liste in `config.yaml`).
- Schwellwerte stehen in `config.yaml` unter `learning.sender_hints`.
- **„Übernehmen“** legt die Regel über einen `AdminCommand` an (`origin = "hint"`). **„Nicht mehr
  vorschlagen“** nutzt die vorhandene Ablehnungsliste.
- Die Einstellungsseite und die Mailseite verlinken auf offene Hinweise, die Hinweise selbst
  stehen aber nur unter **Lernen**.
- Hinweise lesen nur gespeicherte Analysen. Sie lösen keinen Modellaufruf aus.

### 3.9 Kennzahlen

Auf `/auswertung` kommt ein Abschnitt „Vorfilter“ für den gewählten Zeitraum dazu:

- **Vermiedene Relevanz-Aufrufe**, aufgeteilt nach Briefing, VIP, Sperrregel, Kopfzeile,
  Postfach ohne Thema und Eigenmail.
- **Geschätzte Ersparnis:** Grundlage ist der Median von Tokens und Kosten der echten
  Relevanz-Aufrufe desselben Zeitraums, je Anbieter.
  - Cloud: Euro wie in `calls_page`.
  - Lokales Ollama: Laufzeit × Leistungsannahme aus der Konfiguration.
  - Die Zahl ist immer als **„geschätzt“** gekennzeichnet. Ohne Vergleichsaufrufe zeigt Mailhelp
    „nicht schätzbar“ statt 0.
- **Die fünf Regeln mit den meisten Treffern** und Regeln ohne Treffer seit 90 Tagen (Kandidaten
  zum Aufräumen).
- **Probelauf-Ergebnis** je eingeschaltetem Probelauf.

### 3.10 Oberfläche

- **`/einstellungen/absender`** ersetzt `/einstellungen/ignorierte-absender`. Die alte Adresse
  leitet dauerhaft weiter. Die Seite hat drei Abschnitte:
  - VIP-Absender
  - Ignorierte Absender: Adressen, Domains, Muster und Betreffe, je mit Postfach, Treffern,
    letztem Treffer, Ein/Aus und Entfernen
  - Kopfzeilen-Vorfilter: Schalter aus / Probelauf / an, Probelauf-Ergebnis, Verteiler-Ausnahmen
- **Formular „Neue Regel“:**
  - Felder: Art, Wert, Aktion, Postfach, Notiz.
  - Ungültige Eingaben werden mit Feldhinweis abgelehnt.
  - Vor dem Speichern prüft Mailhelp den Wert gegen die letzten 200 Mails und zeigt
    „würde 14 Mails treffen“.
- **Mailseite:** Das vorhandene Absendermenü wird erweitert:
  - „Absender ignorieren“
  - „Domain ignorieren“ (ausgeblendet bei großen Mailanbietern)
  - „Als VIP einstufen“
  - bei bestehender Regel: „Regel aufheben“
  - Die Mailseite zeigt außerdem, welche Regel diese Mail eingeordnet hat.
- **Telegram:**
  - **Wo:** Die Relevanzrückfrage („Ist diese Mail für dich relevant?“) bekommt neben „Relevant“
    und „Irrelevant“ den Knopf **„🚫 Absender immer ignorieren“**.
  - **Wirkung:** Der Knopf stuft die Mail als irrelevant ein und legt eine Ignorier-Regel für die
    Absenderadresse an (`origin = "telegram"`). Die Regel gilt in dem Postfach, in dem die Mail
    eingegangen ist. Das ist derselbe Geltungsbereich wie beim Knopf an der Mailseite.
  - **Bindung an die Rückfrage:** Die Rückfragedaten enthalten Mail-ID und Version der Rückfrage
    (`RelevanceDialog.version`). Ein Druck auf eine veraltete oder schon entschiedene Rückfrage
    legt keine Regel an und meldet „Nicht mehr aktuell“.
  - **Idempotenz:** Die Regel-ID ist stabil (3.5), und der Telegram-Offset sichert die Entscheidung
    wie bisher ab. Doppelte Drucke oder ein Neustart zwischen Entscheidung und Regelanlage erzeugen
    deshalb genau eine Regel.
  - **Rückmeldung:** „Absender <Adresse> wird künftig ignoriert.“ mit dem Knopf **„Rückgängig“**.
    Er entfernt nur diese Regel, die Einstufung der Mail bleibt bestehen.
  - **Ohne Knopf:** Der Knopf fehlt, wenn die Absenderadresse nicht eindeutig lesbar ist. Er fehlt
    auch bei IServ-Konten und bei Absendern mit VIP-Regel.
  - Die Begründung „Vorfilter: …“ erscheint dort, wo heute schon Begründungen erscheinen.
- **Sprache:** Alle Texte laufen über `tr()` und `de()` und stehen in `i18n/en.py`.
  Gespeicherte Begründungen bleiben deutsch und werden über `stored()` angezeigt (Konvention
  aus 7.5.4).

---

## 4. Patch-Plan

Für jeden Patch gilt:

- Versionssprung in `pyproject.toml` und `src/mailhelp/__init__.py`
- Einträge in `CHANGELOG.md` und `README.md`
- Spezifikation anpassen, wo sich Verhalten ändert
- Regressionstests für jeden Fehler
- 100 % Zeilen- und Branch-Abdeckung
- Prüfung mit `python -m devtools.check full --workers 12`, danach die Browsersuite, nie
  gleichzeitig

| Patch | Inhalt | Abnahme im Patch |
| :--- | :--- | :--- |
| **7.7.1 Modell, Migration, Auswerter** | Schema 3, Migration 1/2 → 3 mit `.v2`-Sicherung; `prefilter()` mit Mustern, Betreff und Domain inklusive Subdomains; `MailHeaders` erweitert um `list_id`, `list_unsubscribe` (nur vorhanden ja/nein), `precedence`, `auto_submitted`, gekürzt und normalisiert. Noch keine Verhaltensänderung in der Pipeline. | Migrationstests aus allen früheren Zuständen (`tests/upgrade/states/7.6/`); Schema-Snapshots; Matcher-Tests einschließlich Laufzeitgrenze bei bösartigen Mustern |
| **7.7.2 Pipeline und Aufrufstellen** | Prüfreihenfolge aus 3.1; VIP-Pfad; `rule_id` in `analysis-<id>.json`; `prefilter-hits.json`; alle sieben Aufrufstellen umgestellt; Architekturtest. | Pipeline-Tests je Pfad, Neustart mitten im Schritt, Mail mit VIP- und Sperrtreffer, gefälschte VIP-Mail endet in normaler Bestätigung |
| **7.7.3 Web und Telegram: Regeln verwalten** | `/einstellungen/absender` mit Weiterleitung; Formular mit Trefferschätzung; Mailseiten-Menü; Anzeige der auslösenden Regel; Nachwirkung aus 3.7; Telegram-Knopf „Absender immer ignorieren“ mit „Rückgängig“; EN-Texte. | Autorisierung, CSRF, Versionskonflikt, doppelt abgeschickte Formulare; Telegram: veraltete Rückfrage, doppelter Druck, Neustart zwischen Entscheidung und Regelanlage, Rückgängig; Browsertests Desktop und Mobil |
| **7.7.4 Kopfzeilen-Vorfilter** | Schalter aus / Probelauf / an, Probelauf-Zählung, Verteiler-Ausnahmen. | Probelauf ändert keine Entscheidung; Ausnahme schlägt den Filter; VIP schlägt den Filter |
| **7.7.5 Hinweise und Kennzahlen** | Neue Hinweisquellen unter **Lernen**, Schwellwerte in `config.yaml`; Abschnitt „Vorfilter“ in `/auswertung` mit Schätzung aus echten Aufrufen. | Keine Hinweise für bereits geregelte oder abgelehnte Absender; Schätzung „nicht schätzbar“ ohne Vergleichsdaten; Hinweise lösen keinen Modellaufruf aus |
| **7.7.6 Dokumentation und Abnahme** | Spezifikation, `Bedienung.md`, `Web-Einstellungen.md`, `config.example.yaml`, Hilfeseiten, `docs/Release-7.7.md`. | Gesamtprüfung, Browsersuite, Abnahme nach Abschnitt 5 |

---

## 5. Abnahmekriterien

1. Eine Mail mit Treffer auf eine Ignorier-Regel löst **keinen** Modellaufruf aus. Das gilt auch
   für die Bilderkennung. Sie erscheint im Archiv als irrelevant, mit Regelname als Begründung.
2. Eine Mail eines VIP-Absenders löst keinen Relevanz-Aufruf aus. Sie durchläuft danach
   Zusammenfassung, Aktionserkennung und Extraktion. Jeder Schreibzugriff braucht weiterhin die
   ausdrückliche Bestätigung.
3. Bestehende `irrelevant-senders.json` der Schemata 1 und 2 verhalten sich nach der Migration
   **identisch**. Das gilt ausdrücklich auch für exakte Domains und `allow`-Ausnahmen.
4. Der Kopfzeilen-Vorfilter ist nach einem Update aus. Der Probelauf ändert keine einzige
   Entscheidung.
5. Entscheidungstest, Lernmodus, Aktivitätsbericht und Pipeline kommen bei derselben Mail zum
   selben Vorfilter-Ergebnis.
6. Die Ersparnis ist als Schätzung gekennzeichnet und aus echten Aufrufdaten abgeleitet.
7. Der Telegram-Knopf „Absender immer ignorieren“ legt genau eine Regel an. Das gilt auch bei
   doppeltem Druck und nach einem Neustart. Auf eine veraltete Rückfrage wirkt er nicht.
   „Rückgängig“ entfernt nur diese Regel.
8. Alle neuen Seiten und Meldungen erscheinen vollständig auf Deutsch und auf Englisch.
9. 100 % Zeilen- und Branch-Abdeckung; die Browsersuite ist grün.

---

## 6. Risiken

| Risiko | Gegenmaßnahme |
| :--- | :--- |
| Erwünschte Rundbriefe werden als Newsletter aussortiert | Kopfzeilenfilter standardmäßig aus, Probelauf vor dem Einschalten, Verteiler-Ausnahmen, VIP vor jeder Sperre |
| Zu breite Regel (z. B. Domain eines großen Mailanbieters) | Trefferschätzung vor dem Speichern, Warnung bei großen Mailanbietern, keine Domainvorschläge für sie |
| Gefälschter VIP-Absender | VIP spart nur den Relevanz-Aufruf; Bestätigungspflicht bleibt unverändert (3.4) |
| Verhaltensänderung durch Migration | Migrierte Domainregeln ohne Subdomains; `allow` bleibt reine Ausnahme; Gleichheitstests aus alten Zuständen |
| Schreibkonflikte durch Trefferzähler | Zähler in eigener Zustandsdatei, nur der Hauptthread schreibt |
| Uneinheitliche Wirkung an den sieben Aufrufstellen | Ein Auswerter, Architekturtest gegen direkte Regelauswertung |

---

## 7. Entscheidungen (17. November 2026)

1. **Postfach-Ausnahmen (`allow`) bei der Migration:** Sie bleiben reine Ausnahmen. Die
   Einstellungsseite bietet „Als VIP übernehmen“ an (3.5).
2. **Schwellwerte für Hinweise:** 3 irrelevante Mails zum Ignorieren, 5 bestätigte Mails für VIP.
   Die Werte sind in `config.yaml` einstellbar und werden nach den ersten Wochen anhand der
   Kennzahlen aus 7.7.5 überprüft (3.8).
3. **Telegram-Knopf „Absender immer ignorieren“:** Er ist Teil von 7.7. Er kommt in die
   Relevanzrückfrage und wird mit 7.7.3 umgesetzt (3.10).
