# Mailhelp 7.4 – Mehrtägige Termine und Datumsbereiche

Geprüft für Mailhelp 7.4.

Umsetzung von [Planung 7.4](Planung-7.4.md) in einem Patch (7.4.1); die Schritte M1 bis M5 hängen
eng zusammen.

## 7.4.1 – Datumsbereiche, getaktete Mehrtagestermine und Abnahme (M1 bis M5)

**Erkennung (M1)** in `proposals/action_normalization.py`:

- Wochentage am Anfang und Ende, ausgeschrieben oder abgekürzt, mit oder ohne Punkt und Komma:
  „Donnerstag 07. bis Freitag 08. Januar 2027“, „Do 07. – Fr 08.01.2027“, „Do. 07. bis Fr. 08.01.2027“.
- Kurzformen: `07./08.01.2027`, `07.-08.01.2027`, `7./8.1.2027`, „7./8. Januar 2027“.
- Monats- und Jahreswechsel: „28. Januar bis 2. Februar 2027“, `28.01. bis 02.02.2027`,
  „28. Dezember bis 2. Januar 2027“ (Beginn im Vorjahr).
- Ein genannter Wochentag wird gegen den Kalendertag geprüft; ein Widerspruch führt zur Rückfrage
  „Wochentag und Kalenderdatum widersprechen sich.“ statt zu einer Vermutung. Unmögliche
  Kalendertage ergeben keinen Bereich.

**Getaktete Mehrtagestermine (M2):** Hat ein Bereich Uhrzeiten, beginnt der Termin am ersten Tag zur
Beginnzeit und endet am letzten Tag zur Endzeit. Dafür kennt `_normalize_timed` einen Endtag, statt
eine zweite, fast gleiche Funktion zu führen; Zeitzonen, Sommerzeit, Dauer und Zonenbezeichnungen
gelten unverändert. Mit Dauer endet der Termin nach der Dauer; ohne Endzeit und Dauer fragt Mailhelp
„Wann endet der Termin am 08.01.2027?“ und behält den bekannten Beginn. Ausdrücklich ganztägige
Bereiche bleiben ganztägig.

**Originalfall (M3):** „Donnerstag 07. bis Freitag 08. Januar 2027“, 11.30 bis 12.30 Uhr, ergibt ohne
Rückfrage `2027-01-07T11:30:00+01:00` bis `2027-01-08T12:30:00+01:00`, nicht ganztägig
(`tests/unit/test_date_ranges_multiday.py`).

**Klärung und Bearbeitung (M4):** Die Bearbeitung nimmt Beginn und Ende als vollständige Zeitpunkte
an, ein abweichender Endtag ist also möglich. **Fehlerkorrektur:** Die neue Endfrage mit Datum blieb
nach einer Bearbeitung, einer Standarddauer oder dem Zusammenführen offen, weil diese Stellen nur die
festen Fragen „Wann beginnt/endet der Termin?“ erkannten. `domain.proposal.time_question` erkennt
jetzt beide Formen; Regressionstest in `tests/reconciliation/test_defaults.py`.

**Kalenderadapter (M5):** Google Kalender, CalDAV und Outlook schreiben einen getakteten Termin über
zwei Tage als eine Spanne (`tests/external/test_multiday_writes.py`); die Adapter selbst mussten nicht
geändert werden.

**Abweichung.** Datumsbereiche ohne Jahreszahl („07. bis 08. Januar“) erkennt Mailhelp nicht
automatisch; sie führen wie bisher zur Rückfrage nach dem Datum. Das Jahr müsste aus dem Mailkontext
geraten werden, was die Normalisierung bewusst nicht tut.

Prüfung 7.4.1: 5 707 Python-Tests mit 100 % Zeilen- und Branch-Abdeckung. Browser 956 bestanden,
JavaScript zu 100 % abgedeckt. Der erste Lauf meldete fünf nicht abgedeckte Zeilen in `open-list.js`
aus 7.3.4 (Rücksprung nach „Ignorieren“): Der Test navigierte sofort weiter, und die Abdeckung ging je
nach Zeitablauf verloren. Er hält jetzt die Seite der Aktion an, bis die Abdeckung eingesammelt ist.
