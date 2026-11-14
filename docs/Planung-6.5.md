# Mailhelp 6.5 – Weniger Fehlvorschläge: Annahmequote messen und gezielt verbessern

**Zielversion:** 6.5.0, Umsetzung in Patchversionen 6.5.1 bis 6.5.5

**Stand:** 14. November 2026

**Status:** Entwurf zur Prüfung

**Ausgangsstand:** 6.4.x (nach [Planung 6.4](Planung-6.4.md)); fachlich unabhängig davon

**Grundlage:** [Entwicklungsregeln](../AGENTS.md), [Projektspezifikation](../Mailhelp-Projektspezifikation.md),
[Planung Lernen](Planung-Lernen.md), [Planung 6.0](Planung-6.0.md) (Regelvorschläge verwerfen)

---

## 0. Bestandsaufnahme

Ausgezählt wurde der Produktionsbestand vom 14. November 2026 (nur Zählwerte, keine Inhalte).

| Kennzahl | Wert |
| :--- | :--- |
| Entschiedene Vorschläge | 249 |
| davon angenommen (angelegt, bereits vorhanden, zusammengeführt) | 50 (20 %) |
| davon verworfen | 199 (80 %), fünf davon als „Schon erledigt“ |
| Aufgaben: angenommen / verworfen | 11 / 94 (10 % Annahme) |
| Termine: angenommen / verworfen | 39 / 105 (27 % Annahme) |
| Absender mit Ablehnungen | 43; die fünf häufigsten verursachen 107 der 199 Ablehnungen |
| Absender mit 16 Ablehnungen und keiner Annahme | 2 |
| Lernprotokoll `learning/decisions.jsonl` | 238 Einträge |
| Regellernen | ein Lauf über 100 Entscheidungen gespeichert, zurzeit kein offener Regelvorschlag |

**Was das bedeutet:** Vier von fünf Vorschlägen kosten eine Entscheidung und einen Modellaufruf, ohne
dass etwas entsteht. Bei Aufgaben sind es neun von zehn. Das ist der größte Hebel für den täglichen
Nutzen – größer als jede weitere Verbesserung der Oberfläche.

**Einschränkungen der Auszählung:** Der zeitliche Verlauf wurde nicht ausgewertet. Es ist offen, ob
die Quote nach dem Regellernlauf besser wurde und wie viele Ablehnungen aus Testphasen stammen.
Der Bestand speichert außer „Schon erledigt“ keinen Grund einer Ablehnung. Deshalb beginnt dieser
Plan mit Messen und erst danach mit Ändern.

| ID | Befund | Nachweis |
| :--- | :--- | :--- |
| Q1 | Die Annahmequote ist nirgends sichtbar – weder in der Auswertung noch unter „Lernen“. | `web/archive_pages.py`, `web/learning_overview.py` |
| Q2 | Warum verworfen wurde, ist unbekannt. „Nicht für mich“, „nur Information“, „falsch erkannt“ und „Werbung“ sehen im Bestand gleich aus. | Vorschlagszustände: `resolution` nur bei „Schon erledigt“ |
| Q3 | Wenige Absender verursachen die Mehrzahl der Ablehnungen; Mailhelp weist darauf nicht hin. | Auszählung |
| Q4 | Das Regellernen muss von Hand gestartet werden; es gibt keinen Hinweis, wann sich ein Lauf lohnt. | `learning_overview.py` („Sinnvoll nach wiederholten Korrekturen oder Ablehnungen“) |
| Q5 | Aufgaben werden deutlich häufiger verworfen als Termine. Ob die Ursache die Relevanzprüfung, die Aktionserkennung oder die Zuständigkeit ist, ist ohne Q2 nicht zu sagen. | Auszählung |

---

## 1. Ziele und Nichtziele

**Ziele**

1. Die Annahmequote ist sichtbar: gesamt, je Art, je Thema, je Absender und im Zeitverlauf.
2. Eine Ablehnung kann mit einem Tipp begründet werden; der Grund ist nie Pflicht.
3. Mailhelp schlägt von sich aus vor, was die Quote verbessern würde – und ändert nichts ohne
   ausdrückliche Bestätigung.
4. Messbares Ziel für die Abnahme am echten Bestand: Annahmequote der Vorschläge aus den vier Wochen
   nach Abschluss mindestens 40 % (heute 20 %), ohne dass angenommene Arten von Mails verloren gehen.

**Nichtziele**

- Kein automatisches Aussortieren und keine automatische Regeländerung.
- Kein neues Modell und kein Feintuning; Prompts ändern sich nur über den vorhandenen Prüfweg
  (`python -m devtools.check prompts`).
- Keine Weitergabe von Mailinhalten über das hinaus, was das Regellernen heute schon an das Modell gibt.

---

## 2. Entscheidungen

| ID | Frage | Vorschlag |
| :--- | :--- | :--- |
| **E1** | Gründe einer Ablehnung | Fünf feste Gründe: „Betrifft mich nicht“, „Nur zur Information“, „Werbung oder Rundschreiben“, „Falsch erkannt (Datum, Inhalt)“, „Anderer Grund“. Feste Gründe sind auswertbar; Freitext wäre es nicht. |
| **E2** | Wann wird gefragt? | **Nach** dem Verwerfen, auf der Ergebniskarte („Verworfen. Warum?“ mit fünf kleinen Schaltflächen). Verwerfen bleibt ein Schritt – auch per Wisch (6.3). In Telegram dieselben Gründe als Schaltflächen unter der Bestätigung. **Alternative:** vor dem Verwerfen fragen; das macht jede Ablehnung langsamer und wird nicht empfohlen. |
| **E3** | Schwelle für Hinweise zu Absendern | Mindestens 5 entschiedene Vorschläge eines Absenders in 90 Tagen, davon höchstens 10 % angenommen. |
| **E4** | Was schlägt Mailhelp bei einem solchen Absender vor? | Je nach häufigstem Grund: bei „Werbung“ oder „Betrifft mich nicht“ den Eintrag im Absender-Vorfilter (`irrelevant-senders.json`); sonst einen Regellernlauf, beschränkt auf diesen Absender. Beides nur als Vorschlag mit Vorschau. |
| **E5** | Hinweis auf einen Lernlauf | Auf „Offen“ und „Lernen“, sobald seit dem letzten Lauf 20 neue Ablehnungen vorliegen; höchstens einmal je Woche; abschaltbar. |

---

## 3. Maßnahmen

### 3.1 Annahmequote sichtbar machen (Q1, Q5)

- Neue Auswertung „Vorschläge“ unter **Lernen** (Lernfunktionen stehen im Menü Lernen, nicht unter
  Themen): Kacheln „Annahmequote gesamt“, „Aufgaben“, „Termine“; Verlauf je Woche; Tabellen je Thema
  und je Absender (Zahl entschieden, angenommen, verworfen, Quote), sortierbar, mit Link zu den
  betroffenen Vorschlägen im Verlauf.
- Quelle ist der vorhandene Bestand (Vorschlagszustände und `learning/decisions.jsonl`); es entsteht
  kein zweiter Zähler. Entfernte Inhalte nach Aufbewahrung zählen weiter, werden aber nicht benannt
  („Absender entfernt“).
- Zeitraumwahl wie in der Auswertung (6.2.6); Leerzustand mit einem Satz statt einer Tabelle voller
  Nullen (6.2.10).

### 3.2 Grund einer Ablehnung (Q2, E1, E2)

- Die Ergebniskarte einer Ablehnung zeigt die fünf Gründe. Ein Tipp speichert den Grund am Vorschlag
  und im Lernprotokoll; er ändert nichts an der Entscheidung.
- Der Grund ist ein Befehl über `/aktion` (Sitzung, CSRF, Version, Idempotenzschlüssel) bzw. eine
  Telegram-Schaltfläche. Er ist kein externer Schreibzugriff. Ein zweiter Grund ersetzt den ersten.
- Ohne Grund bleibt alles wie heute; die Auswertung führt „ohne Angabe“ als eigene Zeile.
- Das Regellernen erhält den Grund als zusätzliches Merkmal der Entscheidung.

### 3.3 Hinweise zu Absendern (Q3, E3, E4)

- Unter **Lernen → Vorschläge** und einmalig auf der Ergebniskarte der auslösenden Ablehnung:
  „Von diesem Absender hast du 16 von 16 Vorschlägen verworfen. Künftig aussortieren?“
- „Ansehen“ öffnet eine Vorschau: welche gespeicherten Mails der Filter getroffen hätte, darunter
  ausdrücklich alle, aus denen ein **angenommener** Vorschlag entstand.
- Übernehmen läuft über den vorhandenen Weg für Konfigurationsänderungen: Alt-Neu-Vergleich,
  ausdrückliche Bestätigung, versionsgebunden. „Nicht mehr vorschlagen“ merkt sich die Ablehnung
  des Hinweises (wie bei Regelvorschlägen seit 6.0.4) und lässt sie wieder aufheben.

### 3.4 Hinweis auf einen Lernlauf (Q4, E5)

- Hinweiszeile nach E5 mit der Zahl neuer Ablehnungen und einem Link zur Vorbereitung des Laufs.
  Der Lauf selbst, seine Kostenanzeige und die Bestätigung der Regeländerungen bleiben unverändert.

### 3.5 Ursachen bei Aufgaben klären (Q5)

- Sobald vier Wochen mit Gründen vorliegen: Auswertung der Aufgaben-Ablehnungen nach Grund und
  Verarbeitungsschritt. Erst daraus folgt, ob Relevanz, Aktionserkennung oder Zuständigkeit
  nachgeschärft wird. Diese Auswertung ist ein Arbeitspaket mit Bericht, keine Codeänderung auf
  Verdacht; eine Prompt-Änderung daraus wäre ein eigener Patch mit dem Prompt-Prüflauf.

---

## 4. Umsetzungsschritte

| Schritt | Patch | Arbeitspaket | Tests |
| :--- | :--- | :--- | :--- |
| D1 | 6.5.1 | Auswertung „Vorschläge“ (3.1) | Zählung gegen synthetischen Bestand mit bekannten Quoten; Zeiträume; Bestand mit entfernten Inhalten; Leerzustand; Desktop und Telefon; Anmeldung erforderlich |
| D2 | 6.5.2 | Grund einer Ablehnung im Web und im Lernprotokoll (3.2) | Grund setzen, ersetzen, doppelter Tipp, veraltete Version, abgelaufene und widerrufene Sitzung, CSRF; Neustart zwischen Annahme und Ausführung; ohne JavaScript; nach Wisch |
| D3 | 6.5.3 | Grund in Telegram; Grund als Merkmal im Regellernen (3.2) | Schaltflächen, doppelter Druck, alter Vorschlag; Lernlauf mit und ohne Gründe; Prompt-Prüflauf |
| D4 | 6.5.4 | Hinweise zu Absendern und auf einen Lernlauf (3.3, 3.4) | Schwellen knapp darunter und darüber; Vorschau nennt angenommene Vorschläge; Bestätigung versionsgebunden; „Nicht mehr vorschlagen“ und Aufheben; höchstens ein Hinweis je Woche |
| D5 | 6.5.5 | Doku, Abnahme, `docs/Release-6.5.md` | `python -m devtools.check full`, vollständige Browser-Suite |
| D6 | später | Bericht zu Aufgaben-Ablehnungen (3.5) nach vier Wochen Betrieb | – |

D1 ist allein nützlich und zeigt, ob die Zahlen aus der Bestandsaufnahme über die Zeit stimmen.

---

## 5. Abnahmekriterien

- Die Auswertung nennt für den Bestand vom 14. November dieselben Zahlen wie die Bestandsaufnahme.
- Verwerfen kostet weiterhin genau einen Schritt; der Grund ist ein freiwilliger zweiter.
- Kein Hinweis führt ohne ausdrückliche, versionsgebundene Bestätigung zu einer Änderung.
- Die Vorschau eines Absenderfilters zeigt jede Mail, aus der ein angenommener Vorschlag entstand.
- 100 % Zeilen- und Branch-Abdeckung, 100 % JavaScript-Blockabdeckung.
- Am echten Bestand, vier Wochen nach D4: Annahmequote neuer Vorschläge mindestens 40 %.

## 6. Risiken

| Risiko | Gegenmaßnahme |
| :--- | :--- |
| Ein Absenderfilter sortiert künftig eine wichtige Mail aus. | Vorschau mit angenommenen Vorschlägen; Schwelle „höchstens 10 % angenommen“; aussortierte Mails bleiben im Archiv und lassen sich erneut prüfen (3.6.1). |
| Die Frage nach dem Grund wird als lästig empfunden und ignoriert. | Nie Pflicht, ein Tipp, verschwindet mit der Karte; die Auswertung funktioniert auch mit „ohne Angabe“. |
| Die hohe Ablehnungsquote stammt aus Testphasen und ist heute schon besser. | D1 zuerst; das Ziel aus 1.4 wird nach D1 an den Verlauf angepasst. |
| Mehr Daten im Lernprotokoll. | Gründe folgen der vorhandenen Aufbewahrung (`decision_learning_days`). |

## 7. Dokumentation

`README.md`, `CHANGELOG.md`, `docs/Bedienung.md` (Gründe, Hinweise; Hilfeindex neu erzeugen),
Projektspezifikation (Lernprotokoll, Befehl „Grund“, Hinweisregeln), `config.example.yaml` (Schwellen
und Abschalten der Hinweise).
