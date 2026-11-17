"""7.1 (D2): the synthetic original mails of the demo dataset, written for this purpose.

Every address uses a reserved example domain; no real person, mailbox, phone number or document
appears. The first ten mails show the planned flows (Planung 7.1, 5.1); since 7.6 each of them is
complete – date, times, who is meant – so every proposal can be decided at once (Planung 7.6). The
other twenty are deliberately irrelevant (decision of 16 November 2026). ``devtools.demo.dataset``
turns them into ``.eml`` messages and runs them through the real processing path.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from email.utils import format_datetime
from zoneinfo import ZoneInfo

ZONE = ZoneInfo("Europe/Berlin")
RECIPIENT = "Alex Beispiel <alex@familie-beispiel.example>"


@dataclass(frozen=True)
class DemoMail:
    name: str
    sender: str
    subject: str
    sent: str  # local time, Europe/Berlin
    body: str


RELEVANT = (
    DemoMail("01-elternabend", "Frau Lehmann (Klassenleitung 4b) <lehmann@grundschule-lindenpark.example>",
             "Einladung zum Elternabend der Klasse 4b", "2026-11-09 16:12",
             "Liebe Eltern der Klasse 4b,\n\nich lade Sie herzlich zum Elternabend ein:\n\n"
             "Donnerstag, 26. November 2026, von 19:30 bis 21:00 Uhr\nRaum 12, Grundschule am Lindenpark\n\n"
             "Wir besprechen den Ausflug ins Planetarium, die Lesepaten und die Termine bis zu den "
             "Weihnachtsferien.\n\nViele Grüße\nJana Lehmann"),
    DemoMail("02-ausflug-formular", "Frau Lehmann (Klassenleitung 4b) <lehmann@grundschule-lindenpark.example>",
             "Ausflug ins Planetarium – Begleitung und Einverständniserklärung", "2026-11-10 07:48",
             "Liebe Alex,\n\nvielen Dank, dass Sie die Klasse 4b ins Planetarium begleiten. Sie sind fest als "
             "Begleitperson eingeteilt: Freitag, 4. Dezember 2026, von 08:30 bis 13:00 Uhr, Treffpunkt ist der "
             "Schulhof.\n\nBitte geben Sie außerdem Mias unterschriebene Einverständniserklärung bis Freitag, "
             "20. November 2026, im Sekretariat ab.\n\nDanke und viele Grüße\nJana Lehmann"),
    DemoMail("03-workshop-material", "Tom Weber (TSV Beispielstadt, Jugend) <jugend@tsv-beispielstadt.example>",
             "Bastel-Workshop am Samstag – du betreust mit mir", "2026-11-10 19:05",
             "Hallo Alex,\n\ndanke, dass du mit mir den Bastel-Workshop der Jugendabteilung betreust. Er findet am "
             "Samstag, 21. November 2026, von 10:00 bis 12:30 Uhr im Vereinsheim statt.\n\nBitte besorge bis "
             "Freitag, 20. November 2026, zwei Packungen Bastelkleber und einen Block Fotokarton (DIN A4, bunt) "
             "und bring beides zum Workshop mit.\n\nSportliche Grüße\nTom"),
    DemoMail("04-adventsbasar", "Förderverein Grundschule am Lindenpark <vorstand@foerderverein-lindenpark.example>",
             "Adventsbasar – danke für deinen Kuchen", "2026-11-11 12:30",
             "Liebe Alex,\n\nwir freuen uns auf dich beim Adventsbasar am Samstag, 5. Dezember 2026, von 14:00 "
             "bis 17:00 Uhr in der Aula der Grundschule.\n\nDanke, dass du einen Schokoladenkuchen spendest! "
             "Bitte bring ihn am Samstag, 5. Dezember 2026, bis 13:30 Uhr in die Aula.\n\n"
             "Herzliche Grüße\nDein Förderverein"),
    DemoMail("05-lesepaten-treffen", "Frau Lehmann (Klassenleitung 4b) <lehmann@grundschule-lindenpark.example>",
             "Lesepaten: Einführungstreffen", "2026-11-12 14:20",
             "Liebe Alex,\n\nschön, dass Sie Lesepatin bzw. Lesepate der Klasse 4b werden. Das Einführungstreffen "
             "für alle Lesepaten findet am Dienstag, 1. Dezember 2026, von 18:00 bis 19:00 Uhr in der "
             "Schulbibliothek statt.\n\nViele Grüße\nJana Lehmann"),
    DemoMail("06-ausflug-eintritt",
             "Sekretariat Grundschule am Lindenpark <sekretariat@grundschule-lindenpark.example>",
             "Planetarium: Eintritt bitte überweisen", "2026-11-13 08:15",
             "Liebe Eltern der Klasse 4b,\n\nfür den Ausflug ins Planetarium bitten wir Sie, bis Mittwoch, "
             "25. November 2026, 12 € Eintritt auf das Klassenkonto zu überweisen (Verwendungszweck: Planetarium "
             "und der Name Ihres Kindes).\n\nIhr Sekretariat"),
    DemoMail("07-vorspiel", "Musikschule Beispielstadt <info@musikschule-beispielstadt.example>",
             "Einladung zum Vorspielnachmittag der Geigenklasse", "2026-11-13 17:40",
             "Liebe Eltern,\n\nwir laden Sie herzlich zum Vorspielnachmittag der Geigenklasse ein: Mittwoch, "
             "9. Dezember 2026, von 16:00 bis 17:30 Uhr im Kammermusiksaal der Musikschule. Mia spielt dort ihr "
             "erstes Solostück.\n\nMusikalische Grüße\nIhre Musikschule"),
    DemoMail("08-neue-trikots", "Tom Weber (TSV Beispielstadt, Jugend) <jugend@tsv-beispielstadt.example>",
             "Neue Trikots für die Jugend", "2026-11-14 10:02",
             "Hallo zusammen,\n\ndie neuen Trikots der Jugendabteilung sind da. Wir verteilen sie beim nächsten "
             "regulären Training an die Kinder. Ihr müsst dafür nichts tun und nichts bezahlen.\n\n"
             "Sportliche Grüße\nTom"),
    DemoMail("09-mensa-info", "Grundschule am Lindenpark <info@grundschule-lindenpark.example>",
             "Neuer Speiseplan der Mensa online", "2026-11-15 09:30",
             "Liebe Eltern,\n\nder Speiseplan der Mensa für Dezember ist ab sofort auf der Schulwebsite "
             "veröffentlicht. Sie müssen nichts tun; die Bestellungen laufen wie gewohnt weiter.\n\n"
             "Ihre Schulleitung"),
    DemoMail("10-werbung-black-week", "MegaMarkt Online <angebote@megamarkt.example>",
             "Black Week: Bis zu 40 % auf alles!", "2026-11-16 06:00",
             "Nur diese Woche: Bis zu 40 % Rabatt auf Fernseher, Kaffeemaschinen und vieles mehr. "
             "Jetzt im Onlineshop zuschlagen – solange der Vorrat reicht!\n\nIhr MegaMarkt-Team\n"
             "Abmelden: Newsletter-Einstellungen im Kundenkonto"),
)

IRRELEVANT = (
    DemoMail("11-reiseportal", "Fernweh Reisen <newsletter@fernweh-reisen.example>",
             "Last Minute nach Teneriffa ab 299 €", "2026-11-09 07:10",
             "Sonne tanken im Winter: Eine Woche Teneriffa mit Flug und Hotel ab 299 € pro Person. "
             "Nur buchbar bis Sonntag.\n\nIhr Fernweh-Team"),
    DemoMail("12-elektronik", "Technikwelt <info@technikwelt.example>",
             "Neu eingetroffen: Kopfhörer mit Geräuschunterdrückung", "2026-11-09 11:45",
             "Die neuen Over-Ear-Kopfhörer sind da – jetzt mit 30 Stunden Akkulaufzeit. "
             "Entdecken Sie alle Farben im Shop."),
    DemoMail("13-mode", "Modehaus Seidel <news@modehaus-seidel.example>",
             "Die Wintermode ist da", "2026-11-09 18:20",
             "Mäntel, Schals und Stiefel für die kalte Jahreszeit. Für Newsletter-Abonnenten "
             "gibt es 10 % auf den ersten Einkauf."),
    DemoMail("14-lieferdienst", "Frischkiste <hallo@frischkiste.example>",
             "Deine Gemüsekiste: neue Rezepte für die Woche", "2026-11-10 06:30",
             "Diese Woche in der Kiste: Kürbis, Grünkohl und Rote Bete. Drei neue Rezepte findest du in der App."),
    DemoMail("15-gewinnspiel", "Gewinnzentrale <gewinn@gewinnzentrale.example>",
             "Herzlichen Glückwunsch – Sie wurden ausgewählt!", "2026-11-10 13:13",
             "Sie haben die Chance auf einen Gutschein im Wert von 1.000 €. Bestätigen Sie jetzt Ihre Teilnahme "
             "auf unserer Website."),
    DemoMail("16-app-update", "Fotobuch-App <service@fotobuch-app.example>",
             "Neue Funktionen in Version 8", "2026-11-10 15:00",
             "Mit dem Update auf Version 8 lassen sich Fotobücher noch schneller gestalten. "
             "Das Update wird automatisch installiert."),
    DemoMail("17-soziales-netzwerk", "Freundeskreis Online <benachrichtigung@freundeskreis.example>",
             "Du hast 3 neue Benachrichtigungen", "2026-11-11 08:05",
             "Sieh dir an, was deine Kontakte gepostet haben. Öffne die App, um alle Benachrichtigungen zu lesen."),
    DemoMail("18-webinar", "Cloudsoft <events@cloudsoft.example>",
             "Webinar: Datenbanken skalieren in der Cloud", "2026-11-11 10:00",
             "Melden Sie sich zu unserem kostenlosen Webinar für IT-Teams an. Themen: Replikation, "
             "Sharding und Monitoring."),
    DemoMail("19-spendenaufruf", "Hilfswerk Weitblick <spenden@hilfswerk-weitblick.example>",
             "Ihr Beitrag zum Jahresende", "2026-11-11 16:40",
             "Mit Ihrer Spende unterstützen wir Projekte weltweit. Jeder Euro hilft – vielen Dank!"),
    DemoMail("20-umfrage", "Kundenservice Möbelland <umfrage@moebelland.example>",
             "Wie zufrieden waren Sie mit uns?", "2026-11-12 09:00",
             "Bitte nehmen Sie sich zwei Minuten Zeit für unsere Kundenumfrage. Als Dankeschön verlosen wir "
             "einen Einkaufsgutschein."),
    DemoMail("21-kreditkarte", "Bank Beispiel <angebote@bank-beispiel.example>",
             "Ihre neue Kreditkarte ohne Jahresgebühr", "2026-11-12 11:11",
             "Jetzt wechseln und ein Jahr lang keine Gebühren zahlen. Beantragen Sie die Karte bequem online."),
    DemoMail("22-streaming", "Streamflix <neu@streamflix.example>",
             "Neu im Dezember: Serien und Filme", "2026-11-12 19:30",
             "Im Dezember erwarten dich drei neue Serienstaffeln und viele Weihnachtsfilme."),
    DemoMail("23-fitnessstudio", "FitPoint <angebot@fitpoint.example>",
             "Nur im November: Mitgliedschaft ohne Aufnahmegebühr", "2026-11-13 07:00",
             "Starte jetzt ins Training – ohne Aufnahmegebühr und mit einem kostenlosen Probetraining."),
    DemoMail("24-zeitschrift", "Leserservice Gartenfreude <abo@gartenfreude.example>",
             "Drei Ausgaben zum Kennenlernpreis", "2026-11-13 12:45",
             "Lesen Sie drei Ausgaben der Gartenfreude für nur 5 €. Das Angebot endet automatisch."),
    DemoMail("25-energie", "Stromwerk Süd <tarife@stromwerk-sued.example>",
             "Jetzt in den günstigen Ökostromtarif wechseln", "2026-11-14 08:30",
             "Sichern Sie sich unseren neuen Ökostromtarif mit Preisgarantie bis Ende 2027."),
    DemoMail("26-moebelhaus", "Möbelland <prospekt@moebelland.example>",
             "Unser Weihnachtsprospekt", "2026-11-14 14:00",
             "Blättern Sie durch unseren Weihnachtsprospekt mit Ideen für Wohnzimmer, Küche und Kinderzimmer."),
    DemoMail("27-gartencenter", "Gartencenter Grünzeug <news@gruenzeug.example>",
             "Christsterne und Adventskränze eingetroffen", "2026-11-15 07:15",
             "Unsere Adventsausstellung ist eröffnet. Besuchen Sie uns für Kränze, Gestecke und Christsterne."),
    DemoMail("28-softwarelizenz", "Office Suite Pro <lizenz@officesuite.example>",
             "Ihr Upgrade auf die Premium-Lizenz", "2026-11-15 12:00",
             "Mit der Premium-Lizenz erhalten Sie mehr Cloudspeicher und Vorlagen. Jetzt 20 % sparen."),
    DemoMail("29-hotel", "Hotelgruppe Panorama <angebote@panorama-hotels.example>",
             "Wellness-Wochenende zum Sonderpreis", "2026-11-15 16:20",
             "Zwei Nächte mit Frühstück und Spa-Zugang ab 189 € pro Person."),
    DemoMail("30-versicherung", "Versicherung Sicherheim <service@sicherheim.example>",
             "Prüfen Sie jetzt Ihren Hausratschutz", "2026-11-16 07:45",
             "Ist Ihr Hausrat ausreichend versichert? Unser Online-Rechner hilft beim Vergleich der Tarife."),
)

MAILS = RELEVANT + IRRELEVANT


def message(mail: DemoMail) -> bytes:
    item = EmailMessage()
    item["From"] = mail.sender
    item["To"] = RECIPIENT
    item["Subject"] = mail.subject
    item["Date"] = format_datetime(datetime.strptime(mail.sent, "%Y-%m-%d %H:%M").replace(tzinfo=ZONE))
    item["Message-ID"] = f"<{mail.name}@demo.mailhelp.example>"
    item.set_content(mail.body)
    return item.as_bytes()

