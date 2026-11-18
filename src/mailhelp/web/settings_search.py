"""5.3 (H3): one catalog and one search for the settings, used by the form and the live search.

Only public metadata is searched: labels, keys, groups, areas, help texts and curated synonyms.
Current values, passwords, mail content and private account names are never part of an entry.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from ..i18n import Locale, current, msg, tr, use_locale
from .setting_help import SETTING_HELP

MAX_QUERY = 80
LIVE_LIMIT = 10
EXTRA_CATALOG = Path(__file__).resolve().parents[1] / "helpdocs" / "settings.json"

# Words that mean the same thing to a person looking for a setting; every word finds the others.
SYNONYMS: tuple[tuple[str, ...], ...] = (
    ("ki", "llm", msg("modell"), "openrouter", "ollama", "kuenstliche intelligenz"),
    ("postfach", msg("konto"), "imap", "mailkonto", "mailbox", "account"),
    ('abruf', "intervall", msg("abrufen"), "polling"),
    ("telegram", "bot", "chat"),
    ("push", msg("benachrichtigung"), "meldung", msg("hinweis"), msg("ruhezeit")),
    ('kalender', msg("termin"), "google", "outlook", "caldav", "calendar", "event"),
    ('aufgabe', "todoist", "todo", "erinnerung", "task", "reminder"),
    ('aufbewahrung', "loeschen", msg("frist"), "retention"),
    ('protokoll', "log", "logging"),
    ('passwort', msg("zugangsdaten"), "token", "schluessel"),
    ('entwurf', msg("antwort"), "reply"),
    ('zeitlimit', "timeout", msg("wartezeit")),
    ("rueckkehr", "zurueck", "vorversion", "rollback", "downgrade"),
    ("sicherung", "sichern", "backup", "back up"),
    ('neustart', msg("neu starten"), "restart"),
    # 5.5.6: "Lernfunktion", "lernt" or "Lernlauf" reach the learning mode and its settings.
    ('lernen', "lernt", msg("lernmodus"), msg("lernlauf"), "lernfunktion", msg("lernbestand"), "learn"),
    # 5.7.4: "Regellernen" and "Lernübersicht" reach the learning area.
    ('regellernen', "lernuebersicht"),
)


def normalize(text: str) -> str:
    """Case, umlauts and spaces folded the same way for entries and queries."""
    folded = text.casefold()
    for umlaut, plain in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        folded = folded.replace(umlaut, plain)
    return " ".join(folded.split())


@dataclass(frozen=True)
class Entry:
    id: str
    label: str
    area: str
    summary: str
    href: str
    path: str = msg("Weboberfläche")
    key: str | None = None
    group: str = ""
    help: str = ""
    synonyms: tuple[str, ...] = field(default_factory=tuple)

    @property
    def title_text(self) -> str:
        return normalize(" ".join(filter(None, (self.label, self.key or "", self.group, self.area))))

    @property
    def text(self) -> str:
        return normalize(" ".join((self.title_text, self.summary, self.help, " ".join(self.synonyms))))


def anchor(name: str) -> str:
    """The stable element id of one setting on its area page."""
    return 'einstellung-' + re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")


def _summary(text: str) -> str:
    first = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
    return first if len(first) <= 160 else first[:159] + "…"


def _synonyms(text: str) -> tuple[str, ...]:
    words = set(re.findall(r"[a-z0-9]+", normalize(text)))
    return tuple(sorted({word for group in SYNONYMS if words & {normalize(item) for item in group}
                         for word in group}))


# Pages with their own way of changing settings; found like settings, opened as a page.
PAGES: tuple[tuple[str, str, str, str, str], ...] = (
    ('page:lernen', msg("Lernen"), msg("Lernen"), "/lernen", msg("Lernübersicht: Postfach und Entscheidungen")),
    (
        'page:regellernen',
        msg("Aus Entscheidungen lernen"),
        msg("Lernen"),
        "/lernen/entscheidungen",
        msg("Regeln lernen, Themen verbessern, Themenregeln aus protokollierten Entscheidungen"),
    ),
    (
        'page:lernlauf',
        msg("Aus dem Postfach lernen"),
        msg("Lernen"),
        "/lernen/postfach",
        msg("Lesenden Lernlauf aus vorhandenen Mails starten"),
    ),
    (
        "page:postfaecher",
        msg("Postfächer"),
        msg("Konten und Verbindungen"),
        "/einstellungen/postfaecher",
        msg(
            
                "Postfach hinzufügen, Verbindung prüfen, Ordner, Startgrenze, Ziele, "
                "Filter, Themen, Antworten und Benachrichtigungen je Postfach"
            
        ),
    ),
    (
        "page:iserv",
        msg("IServ-Konten"),
        msg("Konten und Verbindungen"),
        "/einstellungen/iserv",
        msg("Elternbriefe aus IServ abrufen; Schuladresse, Postfach und Startgrenze"),
    ),
    (
        'page:zielprofile',
        msg("Zielprofile"),
        msg("Konten und Verbindungen"),
        "/einstellungen/zielprofile",
        msg(
            
                "Kalender und Aufgabenlisten je Postfach: Google, Todoist, Outlook, "
                "Microsoft To Do, CalDAV, Apple Erinnerungen"
            
        ),
    ),
    (
        'page:zugangsdaten',
        msg("Zugangsdaten"),
        msg("Konten und Verbindungen"),
        "/einstellungen?bereich=zugangsdaten",
        msg("Passwörter und API-Schlüssel hinterlegen; angezeigt wird nur hinterlegt oder fehlt"),
    ),
    (
        'page:einrichtung',
        msg("Einrichtung"),
        msg("Konten und Verbindungen"),
        "/einrichtung",
        msg("Verbindungen Schritt für Schritt einrichten"),
    ),
    (
        'page:diagnose',
        msg("Verbindungen prüfen"),
        msg("Konten und Verbindungen"),
        "/diagnose",
        msg("Diagnose: Zugriffe je Dienst lesend prüfen, mit Selbsttest für alles"),
    ),
    (
        'page:themen',
        msg("Themen"),
        msg("Inhalte und Benachrichtigungen"),
        "/themen",
        msg("Relevante und irrelevante Themen pflegen; Thema bearbeiten, Themen suchen, neues Thema mit Vorschau"),
    ),
    (
        'page:absender',
        msg("Absender-Regeln"),
        msg("Inhalte und Benachrichtigungen"),
        "/einstellungen/absender",
        msg("Absender und Domains ignorieren, VIP-Absender, Muster wie no-reply@*, Betreffe"),
    ),
    (
        'page:benachrichtigungsprofil',
        msg("Benachrichtigungsprofil"),
        msg("Inhalte und Benachrichtigungen"),
        "/einstellungen/benachrichtigungen",
        msg("Ruhezeiten, Bündelung, Kanäle je Kategorie und Telegram-Inhalte"),
    ),
    (
        'page:zustellhistorie',
        msg("Zustellhistorie"),
        msg("Inhalte und Benachrichtigungen"),
        "/benachrichtigungen",
        msg("Gesendete Benachrichtigungen"),
    ),
    ("page:geraete", msg("Geräte"), "System", "/geraete", msg("Angemeldete Browser verwalten")),
    (
        "page:neustarten",
        msg("Mailhelp neu starten"),
        "System",
        "/einstellungen/neustarten",
        msg("Kontrollierter Neustart mit Bestätigung, damit gespeicherte Änderungen wirken"),
    ),
    (
        'page:neu-laden',
        msg("Konfiguration neu laden"),
        "System",
        "/dienst/neu-laden",
        msg("Verbindungen ohne Prozessneustart wechseln"),
    ),
    (
        'page:selbsttest',
        msg("Lesender Selbsttest"),
        "System",
        "/dienst/selbsttest",
        msg("Alle Komponenten und Handlungsempfehlungen"),
    ),
    (
        'page:beenden',
        msg("Mailhelp beenden"),
        "System",
        "/einstellungen/beenden",
        msg("Dienst kontrolliert anhalten"),
    ),
)


def catalog() -> tuple[Entry, ...]:
    return _catalog(current())


@cache
def _catalog(locale: Locale) -> tuple[Entry, ...]:
    with use_locale(locale):
        return _entries()


def _entries() -> tuple[Entry, ...]:
    """Every searchable entry: the settings of the general areas and the special pages."""
    # Late: the settings pages import the search at load time.
    from .settings_pages import AREAS, _names, setting_label

    entries = []
    for area_key, title, _text, groups in AREAS:
        for group in groups:
            for name in _names(group):
                help_text = tr(SETTING_HELP[name])
                label = tr(setting_label(name))
                entries.append(
                    Entry(
                        id=f"setting:{name}",
                        label=label,
                        area=tr(title),
                        summary=_summary(help_text),
                        href='/einstellungen?bereich={p0}#{p1}'.format(p0=f'{area_key}', p1=f'{anchor(name)}'),
                        key=name,
                        group=tr(group),
                        path="Weboberfläche",
                        help=help_text,
                        synonyms=_synonyms(f"{label} {name} {group} {title} {help_text}"),
                    )
                )
    for identity, label, area, href, text in PAGES:
        entries.append(
            Entry(
                id=identity,
                label=tr(label),
                area=tr(area),
                summary=tr(text),
                href=href,
                path=tr("Eigene Seite"),
                synonyms=_synonyms(f"{label} {text}"),
            )
        )
    entries.extend(extra_catalog())
    return tuple(entries)


def setting_href(name: str) -> str:
    """6.2.4: the link to one setting on its area page; pages link there instead of naming config.yaml."""
    return next(entry.href for entry in catalog() if entry.key == name)


def extra_catalog() -> tuple[Entry, ...]:
    """Generated public file/setup metadata; a broken resource never disables normal settings."""
    try:
        path = EXTRA_CATALOG if current() == Locale.DE else EXTRA_CATALOG.parent / "en" / EXTRA_CATALOG.name
        rows = json.loads(path.read_text(encoding="utf-8"))
        return tuple(Entry(**row, synonyms=_synonyms(row["label"] + " " + row["help"])) for row in rows)
    except (OSError, ValueError, TypeError, KeyError):
        return ()


def bounded(query: str) -> str:
    """The query as the form treats it: surrounding space removed, at most 80 characters."""
    return query.strip()[:MAX_QUERY]


def _rank(entry: Entry, phrase: str, words: list[str]) -> int:
    if phrase in {normalize(entry.label), normalize(entry.key or "")}:
        return 0
    starts = set(re.findall(r"[a-z0-9]+", entry.title_text))
    if all(any(start.startswith(word) for start in starts) for word in words):
        return 1
    if all(word in entry.title_text for word in words):
        return 2
    return 3


def search(query: str) -> list[Entry]:
    """Every entry that contains all words, best first; equal ranks alphabetically."""
    phrase = normalize(bounded(query))
    words = phrase.split()
    if not words:
        return []
    found = [entry for entry in catalog() if all(word in entry.text for word in words)]
    return sorted(found, key=lambda entry: (_rank(entry, phrase, words), normalize(entry.label), entry.id))
