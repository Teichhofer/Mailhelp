"""Generate the two static language versions. This is a development-only tool."""
import hashlib
import os
import re
import shutil
from html import escape as e
from pathlib import Path

# The delivered site was built on Windows: every generated text file ends its lines with CRLF. Writing them
# explicitly keeps the build byte for byte reproducible on every platform (7.9.10; fingerprints hash bytes).
NEWLINE = "\r\n"
# INBOXSTRIDE_SITE_ROOT builds a copy elsewhere (the reproduction test); by default the checkout itself.
ROOT = Path(os.environ.get("INBOXSTRIDE_SITE_ROOT") or Path(__file__).parent)
PUBLIC = ROOT / "public"

ICONS = {
 "arrow": '<path d="M5 12h14m-6-6 6 6-6 6"/>',
 "down": '<path d="M12 5v14m-6-6 6 6 6-6"/>',
 "check": '<path d="m5 12 4 4L19 6"/>',
 "mail": '<rect x="3" y="5" width="18" height="14" rx="3"/><path d="m4 7 8 6 8-6"/>',
 "calendar": '<rect x="4" y="5" width="16" height="16" rx="3"/><path d="M8 3v4m8-4v4M4 11h16m-11 4h1m4 0h1"/>',
 "list": '<path d="m3 7 2 2 3-4m3 2h10M3 16l2 2 3-4m3 2h10"/>',
 "cloud": '<path d="M7 18a5 5 0 1 1 0-10 7 7 0 0 1 13 2 4 4 0 0 1-1 8H7Z"/>',
 "lock": '<rect x="5" y="10" width="14" height="11" rx="3"/><path d="M8 10V7a4 4 0 0 1 8 0v3m-4 5v2"/>',
 "spark": '<path d="m12 3 2.2 6.8L21 12l-6.8 2.2L12 21l-2.2-6.8L3 12l6.8-2.2L12 3Z"/>',
 "hand": '<path d="M8 13V6a2 2 0 0 1 4 0v6-3a2 2 0 0 1 4 0v3-1a2 2 0 0 1 4 0v5c0 4-3 6-7 6-3 0-4-1-6-3l-4-5a2 2 0 0 1 3-2l2 1Z"/>',
}
def icon(name):
 return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'+ICONS[name]+'</svg>'
def brand():
 return '<span class="brand-mark"><img src="/assets/inboxstride-logo-512.png" width="34" height="34" alt=""></span><span>inboxstride</span>'

COPY = {'de': {'home': '/',
        'other': '/en/',
        'title': 'Inboxstride – E-Mails im Griff. Mehr Zeit für dich.',
        'description': 'E-Mails in Aufgaben und Termine verwandeln, Fristen im Blick behalten und weniger '
                       'kopieren. Entdecke Inboxstride und lass dich zum Start informieren.',
        'skip': 'Zum Inhalt',
        'nav': ['Vorteile', 'So funktioniert’s', 'Frühzugang'],
        'ids': ['vorteile', 'ablauf', 'interesse'],
        'cta': 'Zum Start dabei sein',
        'availability': 'Demo ist live · Service in Vorbereitung',
        'hero': 'E-Mails im Griff.<br><span>Mehr Zeit für dich.</span>',
        'intro': 'Wieder eine Aufgabe aus einer E-Mail kopieren? Eine Frist im langen Thread suchen? Inboxstride '
                 'erkennt Aufgaben, Fristen und Termine und bereitet sie für deine Freigabe vor. Damit aus Lesen '
                 'endlich Erledigen wird.',
        'learn': 'Entdecke die Möglichkeiten',
        'micro': ['Du entscheidest, was passiert', 'Direkt im Browser nutzen'],
        'float1': 'Neue E-Mail: Workshop-Einladung',
        'float1sub': 'Freitag, 14 Uhr · Anmeldung erforderlich',
        'float2': 'Termin und Aufgabe vorbereitet',
        'float2sub': 'Du bestätigst die Übernahme',
        'preview': 'Illustration des geplanten Ablaufs',
        'strip': 'In deinen E-Mails steckt mehr. <strong>Mach etwas daraus.</strong>',
        'stripPoints': ['E-Mails', 'Aufgaben', 'Termine'],
        'benefitLabel': 'Dein Postfach kann mehr',
        'benefitTitle': 'Aus Nachrichten werden<br>klare nächste Schritte.',
        'benefitIntro': 'Weniger suchen, weniger übertragen. Sieh, was eine Nachricht für dich bedeutet und '
                        'welcher nächste Schritt daraus entsteht.',
        'benefits': [['Lange Mail. Klarer Überblick.',
                      'Eine verständliche Zusammenfassung bringt die wichtigen Inhalte auf den Punkt. Du erkennst '
                      'schneller, ob eine Nachricht nur informiert oder etwas von dir verlangt.'],
                     ['Aufgaben statt Copy & Paste.',
                      'Aus „Bitte bis Freitag anmelden“ wird ein Aufgabenvorschlag mit Frist und Mail-Kontext. Du '
                      'prüfst ihn und gibst die Übernahme in deine angebundene Aufgabenliste frei.'],
                     ['Termine ohne Abtippen.',
                      'Datum, Uhrzeit und Ort werden als Kalendervorschlag vorbereitet. Auch Terminänderungen '
                      'werden erkannt. Du prüfst die Angaben und bestätigst die Übernahme.']],
        'miniMail': 'Das Wichtigste auf einen Blick',
        'miniTask': 'Anmeldung abschicken',
        'miniDeadline': 'Bis Freitag erledigen',
        'miniMonth': 'FREITAG',
        'storyLabel': 'Vom Lesen zum Handeln',
        'storyTitle': 'Einmal lesen.<br>Den nächsten Schritt sehen.',
        'storyText': 'Eine Workshop-Einladung wird zum Terminvorschlag. Die Anmeldung dazu zu einer Aufgabe mit '
                     'Frist. Die lange Nachricht zu einer übersichtlichen Zusammenfassung. Inboxstride bringt '
                     'Struktur in das, was sonst im Postfach liegen bleibt – und gibt dir einen klaren '
                     'Ausgangspunkt für deinen Tag.',
        'photoAlt': 'Laptop mit der echten Demo-Oberfläche und Beispieldaten an einem sonnigen Arbeitsplatz',
        'artAlt': 'Papierumschlag mit einer Aufgabenkarte und einem Kalenderblatt',
        'stepsLabel': 'So funktioniert’s',
        'stepsTitle': 'Deine E-Mails.<br>Ein neuer Überblick.',
        'steps': [['Dein Postfach verbinden',
                   'Dein bestehendes E-Mail-Postfach ist der Ausgangspunkt. Inboxstride bringt die wichtigen '
                   'Inhalte für dich zusammen.'],
                  ['Das Wesentliche entdecken',
                   'Erhalte Zusammenfassungen sowie Vorschläge für Aufgaben, Fristen und Termine. Entdecke, was '
                   'in deinen Nachrichten steckt.'],
                  ['Den nächsten Schritt freigeben',
                   'Prüfe die Vorschläge und bestätige, was in deinen Kalender oder deine Aufgabenliste '
                   'übernommen werden soll.']],
        'faqLabel': 'Dein Postfach. Deine Möglichkeiten.',
        'faqTitle': 'Noch neugierig?',
        'faqIntro': 'So kann Inboxstride dich im Alltag unterstützen.',
        'faq': [['Was kann Inboxstride aus meinen E-Mails machen?',
                 'Lange Nachrichten werden zu klaren Zusammenfassungen. Bitten und Fristen zu '
                 'Aufgabenvorschlägen. Einladungen und Terminänderungen zu vorbereiteten Kalendereinträgen. Du '
                 'siehst, was relevant ist, und entscheidest über den nächsten Schritt.'],
                ['Welche Postfächer, Kalender und Aufgabenlisten sind vorgesehen?',
                 'Die Entwicklung unterstützt IMAP-Postfächer sowie Anbindungen für Google Kalender, Outlook und '
                 'CalDAV. Bei Aufgaben gibt es Anbindungen für Todoist, Microsoft To Do, CalDAV und Apple '
                 'Erinnerungen. Welche davon im gehosteten Angebot zum Start verfügbar sind und welche '
                 'Voraussetzungen gelten, geben wir mit dem Startumfang bekannt.'],
                ['Funktioniert das auch auf dem Smartphone?',
                 'Die Oberfläche ist für Smartphone und Desktop ausgelegt und im Browser nutzbar. Du kannst '
                 'Vorschläge unterwegs prüfen und freigeben. Eine mobile Ansicht gehört zum vorgesehenen '
                 'Angebot.'],
                ['Wie werden meine E-Mail-Daten verarbeitet?',
                 'Das gehostete Angebot ist in Vorbereitung. Die konkreten Angaben zu Hosting, KI-Anbietern, '
                 'Berechtigungen und Speicherfristen stehen noch aus und folgen vor einer Postfachverbindung. '
                 'Diese Vormerkseite liest keine E-Mails: Hier hinterlässt du nur deine Kontaktadresse.'],
                ['Brauche ich dafür technische Kenntnisse?',
                 'Inboxstride wird als gehosteter Service entwickelt. Du nutzt die Funktionen im Browser und '
                 'konzentrierst dich auf deine E-Mails und Entscheidungen. Wir kümmern uns um den technischen '
                 'Betrieb.'],
                ['Behalte ich die Kontrolle über meine Aufgaben und Termine?',
                 'Ja. Du prüfst die vorbereiteten Vorschläge und gibst die Übernahme in deinen Kalender oder '
                 'deine Aufgabenliste frei. So bleibt die Entscheidung bei dir.'],
                ['Kann ich Inboxstride schon ausprobieren?',
                 'Ja: Die verlinkte Live-Demo zeigt dir die Oberfläche mit 30 vorbereiteten Beispielmails. Du '
                 'brauchst kein Konto und verbindest keine Dienste. Aktionen werden nur simuliert; du erhältst '
                 'einen eigenen Demo-Bereich für zwei Stunden. Du startest die Demo auf Deutsch oder Englisch. Der '
                 'gehostete Service für dein eigenes Postfach ist noch in Vorbereitung. Hinterlasse deine '
                 'E-Mail-Adresse, wenn du zum Start informiert werden möchtest.']],
        'signupLabel': 'Neugierig geworden?',
        'signupTitle': 'Bereit für mehr<br>Überblick?',
        'signupText': 'Hinterlasse deine E-Mail-Adresse. Wir melden uns zum Start mit einem ersten Einblick in '
                      'die Funktionen und deine Möglichkeiten, Inboxstride zu nutzen.',
        'note': 'Unverbindliches Interesse · jederzeit widerrufbar',
        'email': 'Deine E-Mail-Adresse',
        'placeholder': 'du@beispiel.de',
        'submit': 'Startinfos erhalten',
        'consent': 'Ich möchte per E-Mail zum Start von Inboxstride kontaktiert werden. Ich kann meine '
                   'Einwilligung jederzeit widerrufen.',
        'privacyNote': 'Informationen zur Verarbeitung deiner Daten findest du in unserer',
        'privacyName': 'Datenschutzerklärung',
        'privacyPath': '/datenschutz/',
        'legalName': 'Impressum',
        'legalPath': '/impressum/',
        'termsName': 'Nutzungsbedingungen',
        'termsPath': '/nutzungsbedingungen/',
        'loading': 'Wird gespeichert …',
        'error': 'Das hat gerade nicht geklappt. Bitte versuche es später erneut.',
        'copyright': 'Ein Angebot der Hartmann GbR',
        'tagline': 'Deine E-Mails. Dein nächster Schritt.',
        'back': 'Zur Startseite',
        'thanksTitle': 'Danke für dein Interesse.',
        'thanksText': 'Deine Anfrage ist bei uns vorgemerkt. Wir melden uns per E-Mail mit Informationen zum '
                      'Start von Inboxstride.',
        'needsLabel': 'Für den Start vorgesehen',
        'needsTitle': 'Dein Alltag braucht<br>weniger Handarbeit.',
        'needsIntro': 'Mehrere Postfächer, offene Aufgaben und anstehende Termine: Behalte die Zusammenhänge im '
                      'Blick.',
        'needs': [['Mehrere Postfächer. Ein Überblick.',
                   'Führe wichtige Inhalte aus deinen angebundenen Postfächern zusammen. Die Zuordnung zum '
                   'jeweiligen Postfach bleibt erhalten.'],
                  ['Mit einem Tagesüberblick starten.',
                   'Eine tägliche Zusammenfassung bündelt Termine, Aufgaben und offene Vorschläge. Damit du '
                   'deinen Tag planen kannst, ohne jede Mail erneut zu öffnen.'],
                  ['Die Frist sehen. Den Kontext behalten.',
                   'Sieh erkannte Fristen und die zugehörige Nachricht zusammen. Du kannst den Vorschlag anhand '
                   'seiner Quelle prüfen, statt einer KI-Aussage blind zu vertrauen.'],
                  ['Erst prüfen. Dann übernehmen.',
                   'Du kannst Vorschläge ansehen und bearbeiten. Eintragungen in Kalender und Aufgabenliste '
                   'brauchen deine ausdrückliche Freigabe. Bearbeiten allein löst keine Anlage aus.']],
        'filmLabel': 'Weniger Inbox-Chaos',
        'filmTitle': 'Mehr Klarheit.<br>Ein guter nächster Schritt.',
        'filmText': 'Ein kurzer Blick auf die Idee hinter Inboxstride: aus Nachrichten wird Überblick.',
        'filmCaption': 'KI-generierte Illustration · 10 Sekunden · mit Ton · kein Mitschnitt der Anwendung',
        'filmFallback': 'Video als MP4 herunterladen',
        'demoCta': 'Demo ausprobieren',
        'demoHint': 'Ohne Konto · 30 Beispielmails · keine echten Verbindungen',
        'demoLabel': 'Die Live-Demo ist da',
        'demoTitle': 'Nicht nur lesen. Selbst ausprobieren.',
        'demoText': 'Entdecke Aufgaben, Fristen und Termine in 30 vorbereiteten Mails. Prüfe Vorschläge und '
                    'probiere Entscheidungen in deinem eigenen Demo-Bereich aus. Ohne Postfach, Telegram oder '
                    'Kalender zu verbinden.',
        'demoNote': 'Nur Beispieldaten. Aktionen werden simuliert. Dein Bereich gilt zwei Stunden.'},
 'en': {'home': '/en/',
        'other': '/',
        'title': 'Inboxstride – Less inbox chaos. More time for you.',
        'description': 'Turn emails into tasks and calendar suggestions, keep deadlines in sight and cut the copy '
                       'and paste. Discover Inboxstride and get launch updates.',
        'skip': 'Skip to content',
        'nav': ['Benefits', 'How it works', 'Early access'],
        'ids': ['benefits', 'how-it-works', 'interest'],
        'cta': 'Get launch updates',
        'availability': 'Live demo available · Hosted service coming soon',
        'hero': 'Less inbox chaos.<br><span>More time for you.</span>',
        'intro': 'Copying another task out of an email? Hunting for a deadline in a long thread? Inboxstride '
                 'spots tasks, deadlines and events and prepares them for your approval. Turn reading into '
                 'getting things done.',
        'learn': 'Explore the possibilities',
        'micro': ['You decide what happens', 'Use it in your browser'],
        'float1': 'New email: workshop invitation',
        'float1sub': 'Friday, 2 pm · RSVP requested',
        'float2': 'Event and task prepared',
        'float2sub': 'You approve the next step',
        'preview': 'Illustration of the planned workflow',
        'strip': 'There’s more in your emails. <strong>Put it to work.</strong>',
        'stripPoints': ['Emails', 'Tasks', 'Calendar'],
        'benefitLabel': 'Your inbox has potential',
        'benefitTitle': 'Turn your messages<br>into clear next steps.',
        'benefitIntro': 'Less searching. Less copying. See what a message means for you and which next step it '
                        'calls for.',
        'benefits': [['Long email. Clear takeaway.',
                      'A readable summary brings the important details together. Quickly see whether a message is '
                      'just for your information or needs you to act.'],
                     ['Tasks without the copy and paste.',
                      '“Please register by Friday” becomes a task suggestion with a deadline and email context. '
                      'Review it and approve adding it to your connected task list.'],
                     ['Calendar entries without retyping.',
                      'Date, time and location are prepared as a calendar suggestion. Changes to events are '
                      'picked up too. Check the details and approve adding the entry.']],
        'miniMail': 'The important bits, at a glance',
        'miniTask': 'Send the registration',
        'miniDeadline': 'Complete by Friday',
        'miniMonth': 'FRIDAY',
        'storyLabel': 'From reading to doing',
        'storyTitle': 'Read it.<br>See what comes next.',
        'storyText': 'A workshop invitation becomes a calendar suggestion. The RSVP becomes a task with a '
                     'deadline. The long message becomes a clear summary. Inboxstride gives structure to the '
                     'things that would otherwise stay in your inbox – and gives you a clear starting point for '
                     'your day.',
        'photoAlt': 'Laptop displaying the real demo interface with sample data in a sunlit workspace',
        'artAlt': 'A paper envelope holding a task card and a calendar page',
        'stepsLabel': 'How it works',
        'stepsTitle': 'Your emails.<br>A fresh perspective.',
        'steps': [['Connect your inbox',
                   'Start with your existing email inbox. Inboxstride brings the important information together '
                   'for you.'],
                  ['Discover what matters',
                   'Get summaries and suggestions for tasks, deadlines and events. See what’s waiting in your '
                   'messages.'],
                  ['Approve your next step',
                   'Review the suggestions and confirm what should go into your calendar or task list.']],
        'faqLabel': 'Your inbox. Your possibilities.',
        'faqTitle': 'Still curious?',
        'faqIntro': 'A closer look at how Inboxstride can help with your day.',
        'faq': [['What can Inboxstride do with my emails?',
                 'Long messages become clear summaries. Requests and deadlines become task suggestions. '
                 'Invitations and changes become prepared calendar entries. See what matters and decide on your '
                 'next step.'],
                ['Which inboxes, calendars and task lists are planned?',
                 'Development supports IMAP inboxes and connections for Google Calendar, Outlook and CalDAV. Task '
                 'connections include Todoist, Microsoft To Do, CalDAV and Apple Reminders. We will announce '
                 'which connections the hosted service offers at launch, along with their requirements.'],
                ['Can I use it on my phone?',
                 'The interface is designed for mobile and desktop browsers. Review and approve suggestions on '
                 'the go. A mobile view is part of the planned service.'],
                ['How will my email data be processed?',
                 'The hosted service is still being prepared. Specific details about hosting, AI providers, '
                 'permissions and retention are pending and will be provided before you connect an inbox. This '
                 'signup page does not read your emails: you only leave your contact address here.'],
                ['Will I need technical knowledge?',
                 'Inboxstride is being developed as a hosted service. Use it in your browser and focus on your '
                 'emails and decisions. We take care of the technical operation.'],
                ['Do I stay in control of my tasks and calendar?',
                 'Yes. You review the prepared suggestions and approve what is added to your calendar or task '
                 'list. The decision stays with you.'],
                ['Can I try Inboxstride already?',
                 'Yes. The linked live demo lets you explore the interface with 30 prepared sample emails. No '
                 'account or service connection is needed. Actions are simulated in your own workspace, which '
                 'lasts two hours. Start the demo in English or German. The hosted service for your own '
                 'inbox is still being prepared. Leave your email address if you would like launch updates.']],
        'signupLabel': 'Curious to see more?',
        'signupTitle': 'Ready for a<br>clearer inbox?',
        'signupText': 'Leave your email address. We’ll be in touch at launch with a first look at the features '
                      'and how you can use Inboxstride.',
        'note': 'Non-binding interest · withdraw at any time',
        'email': 'Your email address',
        'placeholder': 'you@example.com',
        'submit': 'Keep me posted',
        'consent': 'I would like to be contacted by email when Inboxstride launches. I can withdraw my consent at '
                   'any time.',
        'privacyNote': 'Find out how we process your data in our',
        'privacyName': 'privacy policy',
        'privacyPath': '/en/privacy/',
        'legalName': 'Legal notice',
        'legalPath': '/en/legal/',
        'termsName': 'Terms of use',
        'termsPath': '/en/terms/',
        'loading': 'Saving …',
        'error': 'Something went wrong. Please try again later.',
        'copyright': 'A service by Hartmann GbR',
        'tagline': 'Your emails. Your next step.',
        'back': 'Back to the homepage',
        'thanksTitle': 'Thank you for your interest.',
        'thanksText': 'Your enquiry has been registered. We’ll contact you by email with information about the '
                      'Inboxstride launch.',
        'needsLabel': 'Planned for launch',
        'needsTitle': 'Your day needs<br>less busywork.',
        'needsIntro': 'Multiple inboxes, outstanding tasks and upcoming events: keep the connections in view.',
        'needs': [['Multiple inboxes. One overview.',
                   'Bring important content from your connected inboxes together. Each item stays linked to the '
                   'inbox it came from.'],
                  ['Start with a daily overview.',
                   'A daily briefing brings together events, tasks and pending suggestions. Plan your day without '
                   'opening every email again.'],
                  ['See the deadline. Keep the context.',
                   'See detected deadlines alongside the relevant message. Check suggestions against their source '
                   'instead of taking an AI answer on trust.'],
                  ['Review first. Add it when ready.',
                   'Read and edit suggestions before acting. Adding calendar entries or tasks requires your '
                   'explicit approval. Editing alone does not create an entry.']],
        'filmLabel': 'Less inbox chaos',
        'filmTitle': 'A clearer view.<br>A better next step.',
        'filmText': 'A quick glimpse of the idea behind Inboxstride: turn messages into clarity.',
        'filmCaption': 'AI-generated illustration · 10 seconds · with audio · not a recording of the app',
        'filmFallback': 'Download the MP4 video',
        'demoCta': 'Try the live demo',
        'demoHint': 'No account · 30 sample emails · no real connections',
        'demoLabel': 'The live demo is here',
        'demoTitle': 'Go beyond reading. Try it yourself.',
        'demoText': 'Explore tasks, deadlines and events in 30 prepared emails. Review suggestions and try '
                    'decisions in your own demo workspace. No inbox, Telegram or calendar connection needed.',
        'demoNote': 'Sample data only. Actions are simulated. Your workspace lasts two hours.'}}

def header(lang, other=None, current=None):
 c=COPY[lang]
 return f'''<a class="skip" href="#main">{c['skip']}</a><header class="wrap header"><a class="brand" href="{c['home']}" aria-label="Inboxstride">{brand()}</a><nav class="nav" aria-label="{'Hauptnavigation' if lang=='de' else 'Main navigation'}">'''+''.join(f'<a href="{c["home"]}#{target}">{label}</a>' for target,label in zip(c['ids'][:2],c['nav'][:2], strict=False))+f'''</nav><div class="header-right"><nav class="language" aria-label="{'Sprache' if lang=='de' else 'Language'}"><a href="{(current or c['home']) if lang=='de' else other or '/'}" lang="de" hreflang="de" {'class="active" aria-current="page"' if lang=='de' else ''}>DE</a><span aria-hidden="true">/</span><a href="{(current or c['home']) if lang=='en' else other or '/en/'}" lang="en" hreflang="en" {'class="active" aria-current="page"' if lang=='en' else ''}>EN</a></nav><a class="button small demo-link" href="https://demo.inboxstride.de/{lang}/">{c['demoCta']}{icon('arrow')}</a></div></header>'''

def consent_panel(lang):
 de = lang == 'de'
 title = 'Deine Wahl für Statistik' if de else 'Your choice for analytics'
 text = ('Mit deiner Zustimmung laden wir Google Tag Manager und Google Analytics, um Seitenaufrufe und die Nutzung dieser Website auszuwerten. Dabei erhält Google Geräte- und Nutzungsdaten; eine Verarbeitung in den USA ist möglich. Ohne Zustimmung bleiben beide Dienste aus. Deine Auswahl kannst du jederzeit unter „Cookie-Einstellungen“ ändern.' if de else 'With your consent, we load Google Tag Manager and Google Analytics to understand page views and use of this website. Google receives device and usage data; processing in the United States is possible. Both services stay off without consent. You can change your choice at any time under “Cookie settings”.')
 return f'''<section class="consent-panel" data-consent-panel hidden role="region" aria-labelledby="consent-title" data-accepted="{'Aktuell: Statistik erlaubt.' if de else 'Current choice: analytics allowed.'}" data-rejected="{'Aktuell: nur notwendige Speicherung.' if de else 'Current choice: necessary storage only.'}"><h2 id="consent-title">{title}</h2><p>{text}</p><p><a href="{COPY[lang]['privacyPath']}">{'Datenschutzerklärung' if de else 'Privacy policy'}</a> · <a href="https://business.safety.google/privacy/" target="_blank" rel="noopener noreferrer">{'Googles Datennutzung' if de else 'How Google uses data'}</a></p><p class="consent-status" data-consent-status aria-live="polite"></p><div class="consent-actions"><button type="button" class="button" data-consent-reject>{'Nur notwendige' if de else 'Necessary only'}</button><button type="button" class="button" data-consent-accept>{'Statistik erlauben' if de else 'Allow analytics'}</button></div><button type="button" class="consent-close" data-consent-close hidden>{'Auswahl beibehalten' if de else 'Keep current choice'}</button></section>'''

def footer(lang):
 c=COPY[lang]
 return f'''<footer class="wrap"><div class="footer"><a class="brand" href="{c['home']}" aria-label="Inboxstride">{brand()}</a><div class="footer-links"><a href="{c['legalPath']}">{c['legalName']}</a><a href="{c['privacyPath']}">{c['privacyName'].capitalize()}</a><a href="{c['termsPath']}">{c['termsName']}</a><a href="mailto:inboxstride@email.de">{'Kontakt' if lang=='de' else 'Contact'}</a><button type="button" class="consent-settings" data-consent-settings hidden>{'Cookie-Einstellungen' if lang=='de' else 'Cookie settings'}</button></div></div><div class="footer-bottom"><span>© 2026 Inboxstride · {c['copyright']}</span><span>{c['tagline']}</span></div></footer>'''

def frame(lang, title, body, path, other, *, noindex=False):
 c=COPY[lang]
 return f'''<!doctype html>
<html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="theme-color" content="#174d3b"><title>{e(title)}</title><meta name="description" content="{e(c['description'])}"><link rel="canonical" href="https://inboxstride.de{path}"><link rel="alternate" hreflang="{lang}" href="https://inboxstride.de{path}"><link rel="alternate" hreflang="{'en' if lang=='de' else 'de'}" href="https://inboxstride.de{other}"><link rel="icon" type="image/png" href="/assets/inboxstride-favicon.png"><link rel="stylesheet" href="/assets/site.css"><meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(c['description'])}"><meta property="og:type" content="website"><meta property="og:url" content="https://inboxstride.de{path}"><meta property="og:image" content="https://inboxstride.de/assets/workspace-screen-v2.webp">{'<meta name="robots" content="noindex">' if noindex else ''}<script src="/assets/site.js" defer></script><script src="/assets/consent.js" defer></script></head><body>{header(lang,other,path)}{body}{footer(lang)}{consent_panel(lang)}</body></html>'''

def homepage(lang):
 c=COPY[lang]; a,b,signup=c['ids']
 benefit_art=[f'<div class="mini-window"><div class="mini-title">{icon("spark")}{c["miniMail"]}</div>'+''.join('<div class="mini-row"><span class="bullet">'+icon('check')+'</span><i class="'+size+'"></i></div>' for size in ['long','short','long'])+'</div>',f'<div class="mini-window task"><div class="mini-title">{icon("list")}{c["miniTask"]}</div><div class="mini-row"><span class="bullet">{icon("check")}</span>{c["miniDeadline"]}</div><div class="mini-row"><i class="long"></i></div></div>',f'<div class="mini-date"><div class="month">{c["miniMonth"]}</div><strong>21</strong></div><span class="date-check">{icon("check")}</span>']
 benefits=''.join(f'<article class="benefit"><div class="benefit-art" aria-hidden="true">{art}</div><div class="benefit-copy"><h3>{title}</h3><p>{text}</p></div></article>' for (title,text),art in zip(c['benefits'],benefit_art, strict=False))
 steps=''.join(f'<article class="step"><div class="step-icon">{icon(kind)}</div><div><h3>{title}</h3><p>{text}</p></div></article>' for (title,text),kind in zip(c['steps'],['mail','spark','check'], strict=False))
 needs=''.join(f'<article class="everyday-item"><span class="everyday-icon">{icon(kind)}</span><div><h3>{e(title)}</h3><p>{e(text)}</p></div></article>' for (title,text),kind in zip(c['needs'],['mail','calendar','list','hand'], strict=False))
 faq=''.join(f'<details><summary>{q}</summary><p>{answer}</p></details>' for q,answer in c['faq'])
 return f'''<main id="main"><section class="wrap hero"><div class="hero-copy"><div class="eyebrow"><span class="dot" aria-hidden="true"></span>{c['availability']}</div><h1>{c['hero']}</h1><p>{c['intro']}</p><div class="hero-actions"><a class="button demo-link" href="https://demo.inboxstride.de/{lang}/">{c['demoCta']}{icon('arrow')}</a><a class="button outline interest-link" href="#{signup}">{c['cta']}{icon('arrow')}</a></div><p class="demo-hint">{c['demoHint']}</p><div class="micro">{''.join('<span>'+icon('check')+t+'</span>' for t in c['micro'])}</div></div><div class="hero-art"><img class="hero-image" src="/assets/workflow.webp" width="800" height="800" alt="{e(c['artAlt'])}" fetchpriority="high"><div class="float-card top"><span class="float-icon">{icon('mail')}</span><div><strong>{c['float1']}</strong><small>{c['float1sub']}</small></div></div><div class="float-card bottom"><span class="float-icon done">{icon('check')}</span><div><strong>{c['float2']}</strong><small>{c['float2sub']}</small></div></div><p class="preview-caption">{c['preview']}</p></div></section>
<div class="wrap intro-line"><p>{c['strip']}</p><div class="intro-points">{''.join('<span>'+icon(kind)+name+'</span>' for name,kind in zip(c['stripPoints'],['mail','list','calendar'], strict=False))}</div></div>
<section class="wrap demo-banner" aria-labelledby="demo-heading"><div><p class="section-label">{c['demoLabel']}</p><h2 id="demo-heading">{c['demoTitle']}</h2><p>{c['demoText']}</p><small>{c['demoNote']}</small></div><a class="button demo-link" href="https://demo.inboxstride.de/{lang}/">{c['demoCta']}{icon('arrow')}</a></section>
<section class="wrap section film" aria-labelledby="film-title"><div class="section-heading"><div><p class="section-label">{c['filmLabel']}</p><h2 id="film-title">{c['filmTitle']}</h2></div><p>{c['filmText']}</p></div><figure><video controls playsinline preload="none" width="1280" height="720" poster="/assets/inboxstride-film-poster.webp" aria-describedby="film-caption" aria-label="{e(c['filmText'])}"><source src="/assets/inboxstride-film.mp4" type="video/mp4"><a href="/assets/inboxstride-film.mp4">{c['filmFallback']}</a></video><figcaption id="film-caption">{c['filmCaption']}</figcaption></figure></section>
<section class="wrap section" id="{a}"><p class="section-label">{c['benefitLabel']}</p><div class="section-heading"><h2>{c['benefitTitle']}</h2><p>{c['benefitIntro']}</p></div><div class="benefits">{benefits}</div></section>
<section class="wrap story"><div class="story-picture"><img src="/assets/workspace-screen-v2.webp" srcset="/assets/workspace-screen-v2-small.webp 640w, /assets/workspace-screen-v2.webp 1080w" sizes="(max-width:760px) 100vw, 600px" width="1080" height="810" alt="{e(c['photoAlt'])}" loading="lazy" decoding="async"></div><div class="story-copy"><p class="section-label">{c['storyLabel']}</p><h2>{c['storyTitle']}</h2><p>{c['storyText']}</p><a class="text-link" href="#{signup}">{c['cta']}{icon('arrow')}</a></div></section>
<section class="wrap section everyday" aria-labelledby="everyday-title"><p class="section-label">{c['needsLabel']}</p><div class="section-heading"><h2 id="everyday-title">{c['needsTitle']}</h2><p>{c['needsIntro']}</p></div><div class="everyday-grid">{needs}</div></section>
<section class="wrap section" id="{b}"><p class="section-label">{c['stepsLabel']}</p><div class="section-heading"><h2>{c['stepsTitle']}</h2></div><div class="steps">{steps}</div></section>
<section class="wrap faq"><div class="faq-intro"><p class="section-label">{c['faqLabel']}</p><h2>{c['faqTitle']}</h2><p>{c['faqIntro']}</p></div><div class="faq-list">{faq}</div></section>
<section class="wrap signup" id="{signup}"><div class="signup-copy"><p class="section-label">{c['signupLabel']}</p><h2>{c['signupTitle']}</h2><p>{c['signupText']}</p><div class="signup-note">{icon('lock')}{c['note']}</div></div><form class="signup-form" data-interest method="post" action="/api/interest" data-loading="{e(c['loading'])}" data-error="{e(c['error'])}"><input type="hidden" name="lang" value="{lang}"><div class="trap" aria-hidden="true"><label for="website">Website</label><input type="text" id="website" name="website" autocomplete="off" tabindex="-1"></div><label class="email-label" for="email">{c['email']}</label><input type="email" id="email" name="email" maxlength="254" autocomplete="email" inputmode="email" required placeholder="{c['placeholder']}"><label class="consent"><input type="checkbox" name="consent" value="yes" required><span>{c['consent']}</span></label><button class="button" type="submit">{c['submit']}{icon('arrow')}</button><p class="privacy-note">{c['privacyNote']} <a href="{c['privacyPath']}">{c['privacyName']}</a>.</p><p class="form-status" role="status" aria-live="polite" aria-atomic="true"></p></form></section></main>'''

LEGAL={
 'de': '''<h1>Impressum</h1><h2>Angaben gemäß § 5 DDG</h2><address>Hartmann GbR<br>Vertreten durch Stefan Hartmann<br>Teichhof 1<br>74670 Sindringen<br>Deutschland</address><h2>Kontakt</h2><p>E-Mail <a href="mailto:inboxstride@email.de">inboxstride@email.de</a></p><h2>Zum Angebot</h2><p>Inboxstride befindet sich in Vorbereitung. Diese Website informiert über den geplanten Service und ermöglicht unverbindliche Interessentenanfragen.</p>''',
 'en': '''<h1>Legal notice</h1><h2>Information under section 5 DDG</h2><address>Hartmann GbR<br>Represented by Stefan Hartmann<br>Teichhof 1<br>74670 Sindringen<br>Germany</address><h2>Contact</h2><p>Email <a href="mailto:inboxstride@email.de">inboxstride@email.de</a></p><h2>About this offering</h2><p>Inboxstride is in preparation. This website describes the planned service and accepts non-binding expressions of interest.</p>'''
}
PRIVACY = {'de': '<h1>Datenschutzerklärung</h1><p>Stand 16. November 2026</p><h2>Verantwortlicher</h2><p>Hartmann GbR, '
       'Stefan Hartmann, Teichhof 1, 74670 Sindringen, Deutschland. Kontakt <a '
       'href="mailto:inboxstride@email.de">inboxstride@email.de</a>.</p><h2>Interessentenanfragen</h2><p>Wenn du '
       'über unser Formular Interesse anmeldest, speichern wir deine E-Mail-Adresse, den Zeitpunkt, die gewählte '
       'Sprache und den Text sowie die Fassung deiner Einwilligung. Wir verwenden diese Daten, um dich per E-Mail '
       'zum Start von Inboxstride zu kontaktieren. Rechtsgrundlage ist deine Einwilligung gemäß Art. 6 Abs. 1 '
       'lit. a DSGVO.</p><p>Die Einwilligung ist freiwillig. Du kannst sie jederzeit mit Wirkung für die Zukunft '
       'per E-Mail an <a href="mailto:inboxstride@email.de">inboxstride@email.de</a> widerrufen. Die '
       'Rechtmäßigkeit der bisherigen Verarbeitung bleibt davon unberührt. Bei Widerruf löschen wir deinen '
       'Interessenteneintrag. Einträge werden spätestens nach zwölf Monaten automatisch gelöscht.</p><h2>Betrieb '
       'der Website</h2><p>Die Website und die Interessentendaten werden auf der vom Betreiber verwalteten '
       'Serverinfrastruktur gespeichert. Technische Hosting-Dienstleister können im Rahmen der Bereitstellung der '
       'Infrastruktur Empfänger von Daten sein. Beim Aufruf werden technisch notwendige Verbindungsdaten wie '
       'IP-Adresse und angeforderte Datei verarbeitet, um die Website auszuliefern und Missbrauch zu begrenzen. '
       'Rechtsgrundlage ist Art. 6 Abs. 1 lit. f DSGVO, insbesondere der sichere und zuverlässige Betrieb der '
       'Website. Für diese Landingpage ist die Speicherung regulärer Zugriffsprotokolle deaktiviert. '
       'Formulareingaben werden nicht in Fehlerprotokolle geschrieben.</p><h2>Lokale Inhalte und '
       'Video</h2><p>Schriften, Bilder und das eingebundene Video werden von unserem eigenen Server ausgeliefert. '
       'Der Videoplayer lädt das Video erst zur Wiedergabe; es wird kein externer Videodienst eingebunden. Das '
       'Video ist eine KI-generierte Illustration und kein Mitschnitt der Anwendung. Das Interessentenformular '
       'sendet deine Anfrage an unseren eigenen Server.</p>\n'
       '<h2>Deine Cookie-Auswahl</h2><p>Google-Dienste werden erst nach deiner freiwilligen Zustimmung zu '
       '„Statistik erlauben“ geladen. „Nur notwendige“ lehnt die Statistik ab; die Website und das Formular '
       'bleiben nutzbar. Ohne Auswahl oder ohne JavaScript findet keine Google-Analyse statt, auch keine '
       'einwilligungslose Statistikübertragung. Unter „Cookie-Einstellungen“ im Fußbereich kannst du deine Wahl '
       'jederzeit ändern oder die Einwilligung mit Wirkung für die Zukunft widerrufen. Bei Widerruf wird die '
       'Seite neu geladen und die von dieser Website erreichbaren Google-Analytics-Cookies werden entfernt. Die '
       'Rechtmäßigkeit bereits erfolgter Verarbeitung bleibt unberührt.</p><p>Das notwendige Cookie '
       '<code>inboxstride_consent</code> speichert ausschließlich Auswahl, Zeitpunkt und Fassung des Hinweises '
       'für höchstens 180 Tage, ohne Besucherkennung. Es dient dem Merken und Durchsetzen deiner Entscheidung. '
       'Grundlage für diese notwendige Speicherung ist § 25 Abs. 2 Nr. 2 TDDDG, für die damit verbundene '
       'Verarbeitung Art. 6 Abs. 1 lit. f DSGVO. Nach Ablauf oder einer relevanten Änderung fragen wir '
       'erneut.</p>\n'
       '<h2>Google Tag Manager und Google Analytics</h2><p>Nach Zustimmung verwenden wir Google Tag Manager '
       '(Container GTM-55C4ZT5N) zum Laden von Google Analytics 4 (Kennung G-ZQP60GV6NS). Anbieter ist Google '
       'Ireland Limited, Gordon House, Barrow Street, Dublin 4, Irland. Zweck ist die statistische Auswertung der '
       'Website, etwa Seitenaufrufe, Nutzung und technische Funktion. Dabei können Cookie-Kennungen, aufgerufene '
       'Seiten, Interaktionen, Zeitangaben, verweisende Seiten, Browser-/Geräteinformationen und die für die '
       'Übertragung nötige IP-Adresse verarbeitet werden. Google Analytics 4 speichert nach Angaben von Google '
       'keine einzelnen IP-Adressen. Die Verarbeitung ist nicht anonym; Cookie-Kennungen ermöglichen die '
       'Wiedererkennung.</p><p>Rechtsgrundlagen sind deine Einwilligung gemäß Art. 6 Abs. 1 lit. a DSGVO und § 25 '
       'Abs. 1 TDDDG. Die Einwilligung in Statistik ist von der Einwilligung zur Kontaktaufnahme getrennt. '
       'Werbespeicherung, Werbepersonalisierung und die Freigabe nutzerbereitgestellter Daten an Google bleiben '
       'im Einwilligungsmodus abgelehnt. Unsere Einbindung übergibt keine E-Mail-Adresse aus dem Formular an die '
       'Analyse und entfernt Suchparameter sowie URL-Fragmente aus den von ihr gesetzten Seiten- und '
       'Verweisadressen.</p><p>Google Analytics kann insbesondere Cookies mit den Namen <code>_ga</code> und '
       '<code>_ga_…</code> verwenden. Google nennt dafür standardmäßig bis zu zwei Jahre; unsere Einbindung '
       'fordert eine Laufzeit von höchstens 180 Tagen ohne laufende Verlängerung an. Browser können kürzere '
       'Laufzeiten anwenden. Die Löschung von Ereignis- und Nutzerdaten bei Google richtet sich zusätzlich nach '
       'der Aufbewahrungseinstellung der Analytics-Property; in Standard-Properties sind hierfür zwei oder 14 '
       'Monate vorgesehen. Bereits aggregierte Statistiken können länger erhalten bleiben. Die konkrete '
       'Property-Einstellung ist noch nicht überprüft; Auskunft dazu erhältst du über unseren '
       'Kontakt.</p><p>Empfänger können neben Google Ireland auch Google LLC und weitere von Google eingesetzte '
       'Dienstleister sein. Eine Verarbeitung in den USA ist möglich. Google beschreibt hierfür insbesondere den '
       'EU-US Data Privacy Framework für zertifizierte Empfänger und Standardvertragsklauseln. Informationen zu '
       'den Übermittlungsgrundlagen und zur Datennutzung findest du bei <a '
       'href="https://policies.google.com/privacy/frameworks?hl=de" target="_blank" rel="noopener '
       'noreferrer">Google zu internationalen Übermittlungen</a>, in <a '
       'href="https://policies.google.com/privacy?hl=de" target="_blank" rel="noopener noreferrer">Googles '
       'Datenschutzerklärung</a> und unter <a href="https://business.safety.google/privacy/" target="_blank" '
       'rel="noopener noreferrer">Googles Datennutzung bei Partnerangeboten</a>.</p><h2>Live-Demo auf '
       'demo.inboxstride.de</h2><p>Die getrennte Demo verwendet 30 synthetische Beispielmails. Sie verbindet kein '
       'echtes Postfach, Telegram, KI-Dienst, Kalender- oder Aufgabenkonto. Entscheidungen verändern nur deinen '
       'eigenen Demo-Bereich. Bitte gib keine echten personenbezogenen oder vertraulichen Informationen in '
       'Demofelder ein.</p><p>Für die sichere Nutzung setzt die Demo hostgebundene, notwendige Cookies: '
       '<code>mh_pair</code> für bis zu 15 Minuten zum geschützten Start und <code>mh_session</code> für die '
       'zweistündige Sitzung. <code>mailhelp_lang</code> merkt sich deine gewählte Sprache für bis zu ein Jahr. '
       'Sitzung, Demo-Entscheidungen und gegebenenfalls eingegebene Texte werden getrennt '
       'von anderen Besuchern auf unserem Server gespeichert. Abgelaufene Besucherbereiche werden im laufenden '
       'Betrieb regelmäßig gelöscht. Für den Schutz vor Missbrauch wird die Client-IP-Adresse kurzzeitig im '
       'Arbeitsspeicher zur Startbegrenzung verarbeitet. Reguläre nginx-Zugriffsprotokolle der Demo sind '
       'deaktiviert; technische Betriebsereignisse werden protokolliert.</p><p>Die notwendigen Cookies beruhen '
       'auf § 25 Abs. 2 Nr. 2 TDDDG. Die zugehörige Datenverarbeitung zur Bereitstellung der ausdrücklich '
       'aufgerufenen Demo und zum sicheren Betrieb erfolgt auf Grundlage von Art. 6 Abs. 1 lit. f DSGVO. In der '
       'Demo wird kein Google Analytics eingebunden. Der Link von der Landingpage aktiviert dort keine '
       'Postfachverbindung und überträgt deine Formularadresse nicht an die Demo.</p><h2>Deine Rechte</h2><p>Du '
       'hast im Rahmen der gesetzlichen Voraussetzungen das Recht auf Auskunft, Berichtigung, Löschung, '
       'Einschränkung der Verarbeitung, Datenübertragbarkeit und Widerruf deiner Einwilligung. Einer auf '
       'berechtigten Interessen beruhenden Verarbeitung kannst du aus Gründen deiner besonderen Situation '
       'widersprechen. Außerdem kannst du dich bei einer Datenschutzaufsichtsbehörde beschweren. Zuständig ist '
       'unter anderem der Landesbeauftragte für den Datenschutz und die Informationsfreiheit '
       'Baden-Württemberg.</p><p>Für die Bearbeitung deiner Rechte erreichst du uns unter <a '
       'href="mailto:inboxstride@email.de">inboxstride@email.de</a>.</p>',
 'en': '<h1>Privacy policy</h1><p>Last updated 16 November 2026</p><h2>Data controller</h2><p>Hartmann GbR, '
       'Stefan Hartmann, Teichhof 1, 74670 Sindringen, Germany. Contact <a '
       'href="mailto:inboxstride@email.de">inboxstride@email.de</a>.</p><h2>Expressions of interest</h2><p>If you '
       'register your interest using our form, we store your email address, the date and time, your chosen '
       'language, and the text and version of your consent. We use this information to contact you by email about '
       'the launch of Inboxstride. Processing is based on your consent under Article 6(1)(a) GDPR.</p><p>Consent '
       'is voluntary. You can withdraw it at any time with effect for the future by emailing <a '
       'href="mailto:inboxstride@email.de">inboxstride@email.de</a>. This does not affect the lawfulness of '
       'earlier processing. We delete your interest record following withdrawal. Records are automatically '
       'deleted after a maximum of twelve months.</p><h2>Website operation</h2><p>The website and interest '
       'records are stored on the server infrastructure managed by the operator. Technical hosting providers may '
       'receive data when providing that infrastructure. Connection information such as your IP address and the '
       'requested file is processed as needed to deliver this website and limit abuse. The legal basis is Article '
       '6(1)(f) GDPR, particularly the secure and reliable operation of the website. Regular access logging is '
       'disabled for this landing page. Form contents are not written to error logs.</p><h2>Local content and '
       'video</h2><p>Fonts, images and the embedded video are served from our own server. The player loads the '
       'video for playback; no external video provider is embedded. The video is an AI-generated illustration, '
       'not a recording of the application. The interest form sends your enquiry to our own server.</p>\n'
       '<h2>Your cookie choice</h2><p>Google services load only after you voluntarily choose “Allow analytics”. '
       '“Necessary only” declines analytics; the website and form remain available. Without a choice or without '
       'JavaScript, no Google analytics runs, including no consent-free measurement requests. Use “Cookie '
       'settings” in the footer to change your choice or withdraw consent at any time for the future. Withdrawal '
       'reloads the page and removes Google Analytics cookies accessible to this website. Earlier lawful '
       'processing is unaffected.</p><p>The necessary <code>inboxstride_consent</code> cookie stores only your '
       'choice, its time and the notice version for up to 180 days, without a visitor identifier. This remembers '
       'and enforces your decision. Its necessary storage is based on section 25(2)(2) TDDDG; associated '
       'processing is based on Article 6(1)(f) GDPR. We ask again after expiry or a relevant change.</p>\n'
       '<h2>Google Tag Manager and Google Analytics</h2><p>With consent, we use Google Tag Manager (container '
       'GTM-55C4ZT5N) to load Google Analytics 4 (ID G-ZQP60GV6NS). The provider is Google Ireland Limited, '
       'Gordon House, Barrow Street, Dublin 4, Ireland. The purpose is statistical analysis of this website, '
       'including page views, use and technical performance. Processing may include cookie identifiers, visited '
       'pages, interactions, timestamps, referring pages, browser/device details and the IP address needed for '
       'transmission. Google states that Analytics 4 does not store individual IP addresses. Processing is not '
       'anonymous: cookie identifiers allow recognition of returning visitors.</p><p>The legal bases are your '
       'consent under Article 6(1)(a) GDPR and section 25(1) TDDDG. Analytics consent is separate from consent to '
       'launch contact. Advertising storage, ad personalization and permission to provide user data to Google '
       'remain denied in consent mode. Our integration does not send the form email address to analytics and '
       'strips query parameters and URL fragments from page and referrer addresses it sets.</p><p>Google '
       'Analytics may use cookies including <code>_ga</code> and <code>_ga_…</code>. Google gives a default '
       'lifetime of up to two years; our integration requests a maximum of 180 days without ongoing renewal. '
       'Browsers may shorten these periods. Event- and user-level data deletion at Google also depends on the '
       "Analytics property's retention settings; standard properties offer two or 14 months. Aggregated "
       'statistics may be retained longer. The specific property setting has not yet been verified; contact us '
       'for further information.</p><p>Recipients may include Google Ireland, Google LLC and service providers '
       'used by Google. Processing in the United States is possible. Google describes transfer mechanisms '
       'including the EU-US Data Privacy Framework for certified recipients and standard contractual clauses. '
       'Further information is available in <a href="https://policies.google.com/privacy/frameworks?hl=en" '
       'target="_blank" rel="noopener noreferrer">Google\'s international transfer framework</a>, <a '
       'href="https://policies.google.com/privacy?hl=en" target="_blank" rel="noopener noreferrer">Google\'s '
       'privacy policy</a> and <a href="https://business.safety.google/privacy/" target="_blank" rel="noopener '
       'noreferrer">how Google uses data from partner services</a>.</p><h2>Live demo at '
       'demo.inboxstride.de</h2><p>The separate demo uses 30 synthetic sample emails. It does not connect a real '
       'inbox, Telegram, AI service, calendar or task account. Decisions only change your own demo workspace. '
       'Please do not enter real personal or confidential information in demo fields.</p><p>For secure use, the '
       'demo sets necessary host-only cookies: <code>mh_pair</code> for up to 15 minutes to protect starting the '
       'demo and <code>mh_session</code> for the two-hour session. <code>mailhelp_lang</code> remembers your chosen '
       'language for up to one year. Session data, demo decisions and any text you '
       'enter are stored on our server separately from other visitors. Expired visitor workspaces are regularly '
       'deleted while the service is running. For abuse prevention, the client IP address is temporarily '
       'processed in memory to limit starts. Regular nginx access logging is disabled for the demo; technical '
       'operating events are logged.</p><p>Necessary cookies are based on section 25(2)(2) TDDDG. Related '
       'processing to provide the demo you request and operate it securely is based on Article 6(1)(f) GDPR. '
       'Google Analytics is not embedded in the demo. Following the link from the landing page does not connect '
       'an inbox or send your form email address to the demo.</p><h2>Your rights</h2><p>Subject to the applicable '
       'legal conditions, you have rights of access, correction, erasure, restriction, data portability and '
       'withdrawal of consent. You may object to processing based on legitimate interests on grounds relating to '
       'your particular situation. You also have the right to complain to a data protection supervisory '
       'authority, including the State Commissioner for Data Protection and Freedom of Information '
       'Baden-Württemberg.</p><p>To exercise your rights, contact <a '
       'href="mailto:inboxstride@email.de">inboxstride@email.de</a>.</p>'}


# Public service notices supplement the existing website, consent and demo notices.
PRIVACY['de'] = PRIVACY['de'].replace('Die Website und die Interessentendaten werden auf der vom Betreiber verwalteten Serverinfrastruktur gespeichert.', 'Die Website und die Interessentendaten werden auf der vom Betreiber verwalteten Serverinfrastruktur bei centron in Deutschland gespeichert.')
PRIVACY['en'] = PRIVACY['en'].replace('The website and expressions of interest are stored on server infrastructure managed by the operator.', 'The website and expressions of interest are stored on infrastructure managed by the operator and hosted by centron in Germany.')
PRIVACY['de'] = PRIVACY['de'].replace('Stand 16. November 2026', 'Stand 18. November 2026').replace(
    '<h2>Deine Rechte</h2>', (ROOT/'content/service-privacy-de.html').read_text('utf-8')+'<h2>Deine Rechte</h2>')
PRIVACY['en'] = PRIVACY['en'].replace('Last updated 16 November 2026', 'Last updated 18 November 2026').replace(
    '<h2>Your rights</h2>', (ROOT/'content/service-privacy-en.html').read_text('utf-8')+'<h2>Your rights</h2>')
TERMS = {'de': (ROOT/'content/terms-de.html').read_text('utf-8'),
         'en': (ROOT/'content/terms-en.html').read_text('utf-8')}

def write(path,content):
 target=PUBLIC/path.lstrip('/')/'index.html'
 target.parent.mkdir(parents=True,exist_ok=True)
 target.write_text(content,encoding='utf-8', newline=NEWLINE)

for lang,c in COPY.items():
 write(c['home'],frame(lang,c['title'],homepage(lang),c['home'],c['other']))
 for kind,content,pair in [('legal',LEGAL,('/impressum/','/en/legal/')),('privacy',PRIVACY,('/datenschutz/','/en/privacy/')),('terms',TERMS,('/nutzungsbedingungen/','/en/terms/'))]:
  path,other=pair if lang=='de' else pair[::-1]
  body=f'<main class="legal" id="main">{content[lang]}<a class="button" href="{c["home"]}">{c["back"]}{icon("arrow")}</a></main>'
  write(path,frame(lang,{'legal':c['legalName'],'privacy':c['privacyName'].capitalize(),'terms':c['termsName']}[kind],body,path,other))
 thanks='/danke/' if lang=='de' else '/en/thanks/'
 other='/en/thanks/' if lang=='de' else '/danke/'
 write(thanks,frame(lang,c['thanksTitle'],f'<main id="main" class="legal"><h1>{c["thanksTitle"]}</h1><p>{c["thanksText"]}</p><a class="button" href="{c["home"]}">{c["back"]}{icon("arrow")}</a></main>',thanks,other,noindex=True))

(PUBLIC/'assets/favicon.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48"><rect width="48" height="48" rx="13" fill="#174d3b"/><path d="M12 24h24m-10-10 10 10-10 10" fill="none" stroke="#d8efa3" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg>', newline=NEWLINE)
(PUBLIC/'robots.txt').write_text('User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /danke/\nDisallow: /en/thanks/\nSitemap: https://inboxstride.de/sitemap.xml\n', newline=NEWLINE)
paths=['/','/en/','/impressum/','/en/legal/','/datenschutz/','/en/privacy/','/nutzungsbedingungen/','/en/terms/']
(PUBLIC/'sitemap.xml').write_text('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+''.join('<url><loc>https://inboxstride.de'+p+'</loc></url>' for p in paths)+'</urlset>', newline=NEWLINE)

print('Static pages generated')


# Generate versioned asset names for long-lived browser caches.
assets = ROOT / "public/assets"
mapping = {}
for name in ["dm-sans-latin.woff2", "workflow.webp", "workspace-screen-v2.webp", "workspace-screen-v2-small.webp", "favicon.svg", "inboxstride-logo-512.png", "inboxstride-favicon.png", "inboxstride-google-logo-120.png", "inboxstride-film.mp4", "inboxstride-film-poster.webp"]:
    source = assets / name
    digest = hashlib.sha256(source.read_bytes()).hexdigest()[:12]
    target = source.with_name(source.stem + "." + digest + source.suffix)
    shutil.copyfile(source, target)
    mapping["/assets/" + name] = "/assets/" + target.name

css = (assets / "site.css").read_text("utf-8")
css = css.replace("/assets/dm-sans-latin.woff2", mapping["/assets/dm-sans-latin.woff2"])
(assets / "site.css").write_text(css, encoding="utf-8", newline=NEWLINE)
for name in ["site.css", "site.js", "consent.js"]:
    source = assets / name
    digest = hashlib.sha256(source.read_bytes()).hexdigest()[:12]
    target = source.with_name(source.stem + "." + digest + source.suffix)
    shutil.copyfile(source, target)
    mapping["/assets/" + name] = "/assets/" + target.name

for path in (ROOT / "public").rglob("*.html"):
    text = path.read_text("utf-8")
    for before, after in mapping.items():
        text = text.replace(before, after)
    path.write_text(re.sub(r">\s*<", ">\n<", text) + "\n", encoding="utf-8", newline=NEWLINE)

print("Fingerprinted local assets and formatted static pages")
