# Mailhelp 6.7 – Offene Punkte der Bedienung abschließen

**Zielversion:** 6.7.0, Umsetzung in Patchversionen 6.7.1 bis 6.7.4

**Stand:** 14. November 2026

**Status:** Umsetzung beauftragt. E3 am 14.11.2026 ausdrücklich entschieden: Fristen in Telegram anzeigen, nach denselben Regeln wie im Web.

**Ausgangsstand:** 6.6.x; D1 bis D3 sind von 6.4 bis 6.6 unabhängig und können vorgezogen werden

**Grundlage:** [Entwicklungsregeln](../AGENTS.md), [UI-Prüfung 5.7.5](Pruefung-UI-5.7.5.md),
[Release 6.2](Release-6.2.md), [Release 6.3](Release-6.3.md),
[Planung Fristen](Planung-Fristen-Zusammenfassung.md)

---

## 0. Bestandsaufnahme

Dieser Plan sammelt, was frühere Versionen ausdrücklich verschoben oder offen gelassen haben. Jeder
Punkt ist klein; zusammen verhindern sie, dass Restposten über weitere Versionen mitlaufen.

| ID | Offener Punkt | Herkunft |
| :--- | :--- | :--- |
| P1 | **UI-12, Rest:** Der Vorschlagsabgleich erklärt beide Entscheidungen bereits in je einem Satz mit den Titeln („Zuordnen verbindet ‚…‘ mit ‚…‘ und dessen Quellen. Die entstehende Version muss anschließend separat bestätigt werden.“). Offen ist die Fachsprache: die Schaltfläche „Zusatz ausdrücklich zuordnen“, „dessen Quellen“, „entstehende Version“. Beide Schaltflächen sind gleich gewichtet, auch wenn Mailhelp eine Zuordnung für wahrscheinlich hält. Auf „Offen“ steht die Bedeutung von „Verwerfen“ und „Schon erledigt“ in einem aufklappbaren Absatz. | [UI-Prüfung 5.7.5](Pruefung-UI-5.7.5.md); in [Release 6.2](Release-6.2.md) verschoben |
| P2 | **Wischgeste auf echten Geräten** (Grundprüfung und Behebung der Erkennungsfehler sind in [Planung 6.3.2](Planung-6.3.2.md), Teil B, vorgezogen; hier bleibt die Feinabstimmung): Die Werte (12 px Erkennen, 40 % Schwelle, 24 px Rand) sind nur in Chrome mit Telefon-Emulation geprüft. Ungeprüft: iOS Safari (Zurück-Geste am Rand, Gummiband-Scrollen), Android Chrome, Vibrationsimpuls. | [Release 6.3](Release-6.3.md) |
| P3 | **`docs/Bedienung.md`** trägt „Stand: Mailhelp 5.3“. Spätere Funktionen sind als „ab 5.9.2 …“, „ab 6.0.6 …“ eingestreut; die Reihenfolge folgt der Entstehung, nicht dem Arbeitsablauf. Der Hilfechat beantwortet Fragen aus diesem Text. | `docs/Bedienung.md` |
| P4 | **Fristzeile in Telegram:** offen seit 8. November, ob die Fristen der Zusammenfassung auch in der Telegram-Zusammenfassung erscheinen. | [Planung Fristen](Planung-Fristen-Zusammenfassung.md), Abschnitt 7 |
| P5 | **Tipp-Text der Wischgeste** nennt „Anlegen“ und „Verwerfen“ auch dann, wenn die erste Karte eine Relevanzfrage ist. | [Release 6.3](Release-6.3.md), Abweichungen |

---

## 1. Ziele und Nichtziele

**Ziele**

1. Die Erklärsätze und Schaltflächen im Vorschlagsabgleich kommen ohne Fachbegriffe aus und sagen,
   was danach noch zu tun ist.
2. Die Wischgeste ist auf je einem iPhone und einem Android-Telefon gemessen; die Werte sind
   bestätigt oder angepasst.
3. `docs/Bedienung.md` beschreibt den Stand 6.x in der Reihenfolge der täglichen Arbeit, ohne
   Versionsgeschichte im Fließtext.
4. P4 ist entschieden und – falls ja – umgesetzt.

**Nichtziele**

- Kein neues Aussehen, keine neuen Seiten.
- Keine Änderung an Bestätigungen, Routen oder Datenmodell (außer P4, falls gewählt).

---

## 2. Entscheidungen

| ID | Frage | Vorschlag |
| :--- | :--- | :--- |
| **E1** | Wortlaut der Erklärung im Abgleich (P1) | Die vorhandenen Sätze bleiben an ihrer Stelle und werden umformuliert: „Fügt die Angaben aus ‚…‘ zu ‚…‘ hinzu. Es entsteht kein zweiter Eintrag; den ergänzten Vorschlag bestätigst du danach unter Offen.“ bzw. „Beide bleiben getrennte Vorschläge unter Offen.“ Hervorgehoben wird genau eine Schaltfläche, und nur dann, wenn Mailhelp die Zuordnung selbst zur Prüfung vorgelegt hat (`merge_review_required`); sonst keine. |
| **E2** | Begriffe (P1) | „Zusatz ausdrücklich zuordnen“ wird „Zu diesem Eintrag hinzufügen“; „Als eigenen Vorschlag behalten“ bleibt. „Vorschlagsabgleich“ als Seitenname bleibt (in 6.2 entschieden). Das Wort „ausdrücklich“ entfällt aus Schaltflächen; die Bestätigungspflicht selbst ändert sich nicht. |
| **E3** | Fristzeile in Telegram (P4) | **Ja**, als letzte Zeile der Zusammenfassung, höchstens drei Fristen, nur künftige, mit derselben Regel wie im Web (Anmeldefrist entfällt bei bestehender Anmeldung). **Alternative:** nein und den Punkt schließen. |
| **E4** | Aufbau von `Bedienung.md` (P3) | Nach Arbeitsablauf: Offen entscheiden (Tippen, Wischen, Tastatur) → Rückfragen und Widersprüche → Vorschlagsabgleich → Nach dem Anlegen → Mails und Verlauf → Lernen → Telefon. Versionsangaben nur noch in `CHANGELOG.md`. |
| **E5** | Tipp-Text (P5) | Der Text richtet sich nach der Karte, unter der er steht: bei einer Relevanzfrage „nach rechts für relevant, nach links für irrelevant“. |

---

## 3. Maßnahmen

### 3.1 Vorschlagsabgleich verständlich machen (P1, E1, E2)

- Neue Wortlaute und Beschriftungen in `web/reconciliation_pages.py` (`comparison`, dazu
  „Dauerannahme ausdrücklich übernehmen“ und „Gespeicherten Befund wiederherstellen“ auf dieselbe
  Sprache prüfen); die Titel bleiben maskiert und werden auf eine Zeile gekürzt.
- Der vorhandene Erklärtext „Was bedeuten diese Entscheidungen?“ auf den Karten von „Offen“ wird
  auf dieselbe Form gebracht: ein kurzer Satz je Schaltfläche statt eines Absatzes, auf dem Telefon
  weiterhin aufklappbar, damit die erste Entscheidung im oberen Fensterbereich bleibt (6.2.8).
- Dieselben Begriffe in Telegram, im Hilfeindex und in der Einstellungssuche.
- Wächtertest: Die alten Begriffe kommen auf den Kernseiten nicht mehr vor.

### 3.2 Wischgeste auf echten Geräten (P2, P5)

- Messprotokoll mit festen Aufgaben auf je einem iPhone (Safari, auch als installierte Web-App) und
  einem Android-Telefon (Chrome): zehn Karten nacheinander entscheiden; zwanzigmal durch die Liste
  scrollen; vom linken Rand wischen; zoomen; mit nassem oder schnellem Daumen. Gezählt werden
  Fehlauslösungen, nicht erkannte Wische und Konflikte mit der Zurück-Geste.
- Grenzwerte für die Abnahme: keine Fehlauslösung, höchstens einer von zwanzig Wischen nicht erkannt.
- Bei Abweichung: Werte in der Konstante `SWIPE` anpassen, Browsertests nachziehen, Messung
  wiederholen. Die Messung führt der Betreiber am Gerät durch; das Protokoll kommt nach
  `docs/Release-6.7.md`.
- Tipp-Text nach E5.

### 3.3 Bedienungsanleitung neu ordnen (P3, E4)

- `docs/Bedienung.md` neu gliedern und auf Stand 6.x bringen; „Stand“ nennt die Version.
- Hilfeindex neu erzeugen (`python -m devtools.help_index`).
- Prüfung: Zehn typische Fragen an den Hilfechat (Liste in `docs/Release-6.7.md`) finden im
  Hilfeindex den passenden Abschnitt; als Test gegen den Index, ohne Modellaufruf.

### 3.4 Fristzeile in Telegram (P4, E3) – nur falls E3 „ja“

- Die Telegram-Zusammenfassung erhält die Fristzeile aus denselben Daten wie das Web; ältere
  Zustände ohne Fristen bleiben unverändert.
- Keine neue Benachrichtigung, nur eine zusätzliche Zeile in einer bestehenden.

---

## 4. Umsetzungsschritte

| Schritt | Patch | Arbeitspaket | Tests |
| :--- | :--- | :--- | :--- |
| D1 | 6.7.1 | Vorschlagsabgleich: Wortlaut, Begriffe, Hauptaktion (3.1) | Jede Entscheidung mit ihrem neuen Satz; hervorgehoben nur bei vorgelegter Zuordnung; lange und bösartige Titel; ohne JavaScript; Desktop und Telefon; Wächter gegen alte Begriffe; Bestätigungen unverändert |
| D2 | 6.7.2 | Tipp-Text nach Karte; Messung am Gerät und Anpassung der Werte (3.2) | Tipp unter Relevanzfrage und unter Vorschlag; Browsertests mit den endgültigen Werten |
| D3 | 6.7.3 | `docs/Bedienung.md`, Hilfeindex, Fragenliste (3.3) | Hilfeindex aktuell; zehn Fragen finden ihren Abschnitt |
| D4 | 6.7.4 | Fristzeile in Telegram (falls E3 „ja“); Doku, Abnahme, `docs/Release-6.7.md` | Mit, ohne und mit vergangenen Fristen; alter Zustand; Anmeldung besteht; `python -m devtools.check full`, vollständige Browser-Suite |

Alle Schritte sind voneinander unabhängig.

---

## 5. Abnahmekriterien

- Im Vorschlagsabgleich kommen „Zusatz“, „Quellen“ und „entstehende Version“ nicht mehr vor; jede
  Entscheidung sagt, was danach zu tun ist; höchstens eine Schaltfläche ist hervorgehoben.
- Messprotokoll für iPhone und Android liegt vor und erfüllt die Grenzwerte aus 3.2.
- `docs/Bedienung.md` nennt den aktuellen Stand und enthält keine „ab x.y.z“-Angaben mehr.
- P1 bis P5 sind in `docs/Release-6.7.md` als erledigt oder ausdrücklich geschlossen geführt.
- 100 % Zeilen- und Branch-Abdeckung, 100 % JavaScript-Blockabdeckung.

## 6. Risiken

| Risiko | Gegenmaßnahme |
| :--- | :--- |
| Geänderte Begriffe brechen viele Texterwartungen in Tests und die Hilfe. | Ein Patch nur für Begriffe (D1); Hilfeindex und Telegram im selben Patch. |
| Die Messung am Gerät zeigt, dass iOS die Zurück-Geste breiter auslöst als 24 px. | Randzone ist eine Konstante; notfalls auf iOS größer. |
| Die neu geordnete Anleitung verliert Details. | Vorher-Nachher-Abgleich der Abschnittsüberschriften und Schaltflächennamen als Test gegen die Oberfläche. |

## 7. Dokumentation

`README.md`, `CHANGELOG.md`, `docs/Bedienung.md`, Projektspezifikation (Begriffe im Abgleich,
Fristzeile), `docs/Release-6.7.md` mit Messprotokoll und der Liste P1 bis P5.
