# Mailhelp 5.0 – Ruhigeres Design, Navigation für alle Bildschirmgrößen und schnellere Triage

**Zielversion:** 5.0.7 (Schritte als Patchversionen 5.0.0 bis 5.0.7)  
**Stand:** 9. November 2026 (überarbeitet nach Abgleich mit dem Code von 4.9.7)  
**Status:** In Umsetzung (21.1 in 5.0.0, 21.2 in 5.0.1)  
**Grundlage:** [Entwicklungsregeln](../AGENTS.md), [Projektspezifikation](../Mailhelp-Projektspezifikation.md), [Planung 4.0](Planung-4.0.md) (Gesamtfahrplan)  
**Vorgänger:** [Planung 4.9](Planung-4.9.md) (Konfigurierbare E-Mail-Briefings) und [Planung Lernen](Planung-Lernen.md) (4.9.7)  
**Nachfolger:** [Planung 5.2](Planung-5.2.md) (Aufgaben und Termine nach dem Eintragen überprüfen)

---

## 1. Anlass und Ziel

> Mailhelp 5.0 gibt der Weboberfläche ein ruhigeres, kontrastsicheres Design, eine
> Navigation, die auf Tablet und Smartphone gleich gut erreichbar ist, und eine schnellere
> Triage. Alles bleibt ohne externe Schriften, Skripte oder CDNs, funktioniert ohne
> JavaScript und offline als PWA und erfüllt WCAG 2.1 AA.

### 1.1 Ausgangslage (geprüft am Code von 4.9.7)

Die erste Fassung dieser Planung beschrieb einen älteren Stand. Vorhanden sind bereits:

| Bereich | Heute | Fundstelle |
| --- | --- | --- |
| Dunkelmodus | Farbvariablen für hell und dunkel (`prefers-color-scheme`) | `web/static/app.css` |
| Linke Seitenleiste | Gruppierte Navigation mit Symbolen, **erst ab 1.200 px**; darunter eine horizontal scrollende Leiste mit zehn Einträgen | `web/pages.py`, `app.css` |
| Split-View | Liste und Detail ab 1.024 px auf der Übersicht `/` | `app.css`, `app.js` |
| Tastenkürzel | `J`/`K` und Pfeiltasten, `C`/Enter (bestätigen), `X`/`D` (verwerfen), `E` (bearbeiten), `?` (Hilfe); in Eingabefeldern gesperrt | `app.js` |
| Inbox Zero | Karte „Alles erledigt!“ mit den Vorgängen des Tages | `web/experience.py` |
| Daumenzone | Aktionsleiste der Karte bleibt unten am Bildschirm, Tippflächen 48 px | `app.css` |
| Automatische Prüfung | Kontrast (4,5:1), Tippflächen ab **40 px**, Labels, Überlauf und axe-core (WCAG 2.1 AA) auf jeder Seite, dazu 100 % JavaScript-Blockabdeckung | `ui_tests/checks.py`, `ui_tests/conftest.py` |

Was tatsächlich fehlt oder stört:

- Zwischen 720 und 1.199 px (Tablet, kleines Notebook) und auf dem Smartphone liegt die
  Navigation als scrollende Leiste oben; auf dem Telefon scrollt sie weg und ist schwer
  erreichbar.
- Die Farben der Seitenleiste sind fest eingetragen (`#14372d` und weitere) statt als
  Variablen; `theme-color` und Manifest nutzen ein drittes Grün.
- Vorschlagskarten unterscheiden Termin und Aufgabe nur durch das Symbol in der Kopfzeile.
- Die Seitenleiste zeigt nicht, wie viele Entscheidungen offen sind.
- Die Tastenkürzel sind nur über `?` auffindbar.

### 1.2 Korrektur der Farbpalette

Die erste Fassung schlug für den hellen Modus `#059669` (Akzent), `#ea580c` (Aufgaben)
und `#0d9488` (Entwürfe) vor. Diese Farben erreichen auf Weiß nur **3,77:1, 3,56:1 und
3,74:1** und verfehlen WCAG AA für Text (4,5:1); auch weiße Schrift auf dem Akzent-Knopf
fiele durch. Die heutige Akzentfarbe `#176b4d` erreicht 6,47:1. Die überarbeitete Palette
nutzt deshalb die 700er-Stufen:

| Token | Hell | Dunkel | Zweck |
| --- | --- | --- | --- |
| `--bg` | `#f8fafc` | `#0b0f14` | Hintergrund |
| `--surface` | `#ffffff` | `#141b22` | Karten |
| `--surface-2` | `#f1f5f9` | `#1c242f` | Sekundäre Flächen |
| `--text` | `#0f172a` | `#e2e8f0` | Text |
| `--muted` | `#475569` | `#94a3b8` | Nebentext |
| `--border` | `#e2e8f0` | `#2a3441` | Linien (kein Text) |
| `--accent` | `#047857` | `#34d399` | Aktionen, Links |
| `--accent-soft` | `#ecfdf5` | `#0c2a20` | Hinterlegung |
| `--kind-event` | `#1d4ed8` | `#93c5fd` | Termin |
| `--kind-task` | `#c2410c` | `#fdba74` | Aufgabe |
| `--kind-draft` | `#0f766e` | `#5eead4` | Antwortentwurf |
| `--sidebar-bg` | `#0f2f26` | `#0f1720` | Seitenleiste |

Die Farben gelten für die **Art** des Eintrags, nicht für einen Anbieter: Mailhelp schreibt
außer nach Google und Todoist auch nach CalDAV, Outlook, Microsoft To Do und Apple
Erinnerungen. Farbe ist nie das einzige Merkmal; jede Art trägt zusätzlich Symbol und Text.

## 2. Grundsätze

1. **Keine externen Ressourcen:** keine Webfonts, CDNs oder Dritt-Skripte; Systemschrift.
2. **Ohne JavaScript bedienbar:** Navigation, „Mehr“-Menü und alle Aktionen funktionieren
   als HTML und CSS; JavaScript ergänzt nur (Einklappen, Kürzel, Split-View).
3. **Offline:** Der Service Worker versioniert die Shell automatisch; neue CSS und Skripte
   werden mit der Version ausgeliefert.
4. **Kontrast wird geprüft, nicht behauptet:** ein Test berechnet die Kontraste aller
   Token-Paare aus `app.css` für hell und dunkel; die Browser-Suite prüft jede Seite.
5. **Keine Änderung an Logik und Schreibsicherheit:** 5.0 ändert nur Darstellung und
   Bedienung; Bestätigung, Versionen, CSRF und Idempotenz bleiben unverändert.

## 3. Umsetzungsschritte (Stufe 21)

| Schritt | Inhalt | Fertig, wenn … | Umfang |
| --- | --- | --- | :---: |
| **21.1** 5.0.0 | Design-Tokens | Neue Palette aus 1.2 als Variablen für hell und dunkel; Seitenleiste, `theme-color` und Manifest nutzen Variablen bzw. dieselbe Farbe; `tabular-nums` für Zahlen; weiche Schatten. Unit-Test berechnet die Kontraste aller Text-/Flächen-Paare (≥ 4,5:1) und der Knopfschrift (≥ 4,5:1). | S |
| **21.2** 5.0.1 | Navigation für alle Breiten | Seitenleiste ab **900 px** (statt 1.200 px), bis 1.199 px als Symbolleiste, damit die Split-View ab 1.024 px Platz behält; mit Zähler offener Entscheidungen an „Offen“; ab 1.200 px einklappbar auf Symbole (Zustand je Gerät in `localStorage`, ohne JavaScript ausgeklappt). Unter 900 px eine feste Leiste unten mit „Offen“, „Mails“, „Verlauf“, „Status“ und „Mehr“ (`<details>` mit den übrigen Bereichen, ohne JavaScript bedienbar); Platz für die sichere Zone (`env(safe-area-inset-bottom)`). | M |
| **21.3** 5.0.2 | Kennzeichnung der Karten | Farbstreifen, Symbol und Text je Art (Termin, Aufgabe; Änderung und Absage aus 4.6 als eigene Variante); Beleg als gestaltetes Zitat; Antwortentwurf (4.8) in der Entwurfsfarbe. | S |
| **21.4** 5.0.3 | Split-View verfeinern | Liste mit Statusplakette und Art-Kennzeichen; im Detail bleibt die Aktionsleiste am unteren Rand sichtbar; Breakpoint bleibt 1.024 px. | S |
| **21.5** 5.0.4 | Tastenkürzel ergänzen | `A` zusätzlich zum Bestätigen (`C`/Enter bleiben), Hilfe nennt es; Hinweis „? Tastenkürzel“ in der Seitenleiste. | S |
| **21.6** 5.0.5 | Inbox Zero | Tageswerte als Kennzahlen-Kacheln (Termine, Aufgaben, Abgleiche, Verworfen) mit `tabular-nums`; dezente Einblendung, die `prefers-reduced-motion` beachtet. | S |
| **21.7** 5.0.6 | Barrierefreiheit | Mindest-Tippfläche der Browser-Prüfung von 40 auf **44 px** angehoben und alle Seiten angepasst; Fokusring als Variable; `aria-current` auch in der unteren Leiste; vollständige Browser-Suite inklusive 100 % JavaScript-Blockabdeckung. | S |
| **21.8** 5.0.7 | Abnahme und Release 5.0 | Windows, Docker und Browser-Suite; Release-Bericht `docs/Release-5.0.md`; README, CHANGELOG, Spezifikation. | M |

Jeder Schritt ist ein eigener Commit mit Patchversion und 100 % Zeilen- und
Branch-Abdeckung des Python-Codes; Browser-Tests decken jede neue Darstellung ab.

## 4. Abnahmekriterien

1. Keine externen Ressourcen; die Oberfläche bleibt offline nutzbar.
2. Alle Text-/Flächen-Kombinationen der Tokens erreichen mindestens 4,5:1 in hell und
   dunkel (automatischer Test); axe-core meldet auf keiner Seite einen WCAG-2.1-AA-Verstoß.
3. Auf jeder Breite ist die Hauptnavigation ohne Scrollen erreichbar; auf dem Telefon am
   unteren Rand.
4. Termin, Aufgabe und Entwurf sind ohne Farbwahrnehmung unterscheidbar.
5. Alle Tippflächen sind mindestens 44 px hoch.
6. Alles bleibt ohne JavaScript bedienbar.
7. 100 % Zeilen- und Branch-Abdeckung; Browser-Suite mit 100 % JavaScript-Blockabdeckung.
