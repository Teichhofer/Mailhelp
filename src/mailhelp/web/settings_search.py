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

MAX_QUERY = 80
LIVE_LIMIT = 10
EXTRA_CATALOG = Path(__file__).resolve().parents[1] / "helpdocs" / "settings.json"

# Words that mean the same thing to a person looking for a setting; every word finds the others.
SYNONYMS: tuple[tuple[str, ...], ...] = (
    ("ki", "llm", "modell", "openrouter", "ollama", "kuenstliche intelligenz"),
    ("postfach", "konto", "imap", "mailkonto"),
    ("abruf", "intervall", "abrufen", "polling"),
    ("telegram", "bot", "chat"),
    ("push", "benachrichtigung", "meldung", "hinweis", "ruhezeit"),
    ("kalender", "termin", "google", "outlook", "caldav"),
    ("aufgabe", "todoist", "todo", "erinnerung"),
    ("aufbewahrung", "loeschen", "frist", "retention"),
    ("protokoll", "log", "logging"),
    ("passwort", "zugangsdaten", "token", "schluessel"),
    ("entwurf", "antwort", "reply"),
    ("zeitlimit", "timeout", "wartezeit"),
    ("rueckkehr", "zurueck", "vorversion", "rollback", "downgrade"),
    ("sicherung", "sichern", "backup"),
    ("neustart", "neu starten", "restart"),
    # 5.5.6: "Lernfunktion", "lernt" or "Lernlauf" reach the learning mode and its settings.
    ("lernen", "lernt", "lernmodus", "lernlauf", "lernfunktion", "lernbestand", "learn"),
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
    path: str = "Weboberfläche"
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
    return "einstellung-" + re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")


def _summary(text: str) -> str:
    first = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
    return first if len(first) <= 160 else first[:159] + "…"


def _synonyms(text: str) -> tuple[str, ...]:
    words = set(re.findall(r"[a-z0-9]+", normalize(text)))
    return tuple(sorted({word for group in SYNONYMS if words & {normalize(item) for item in group}
                         for word in group}))


# Pages with their own way of changing settings; found like settings, opened as a page.
PAGES: tuple[tuple[str, str, str, str, str], ...] = (
    ("page:postfaecher", "Postfächer", "Konten und Verbindungen", "/einstellungen/postfaecher",
     "Postfach hinzufügen, Verbindung prüfen, Ordner, Startgrenze, Ziele, Filter, Themen, Antworten und "
     "Benachrichtigungen je Postfach"),
    ("page:iserv", "IServ-Konten", "Konten und Verbindungen", "/einstellungen/iserv",
     "Elternbriefe aus IServ abrufen; Schuladresse, Postfach und Startgrenze"),
    ("page:zielprofile", "Zielprofile", "Konten und Verbindungen", "/einstellungen/zielprofile",
     "Kalender und Aufgabenlisten je Postfach: Google, Todoist, Outlook, Microsoft To Do, CalDAV, Apple Erinnerungen"),
    ("page:zugangsdaten", "Zugangsdaten", "Konten und Verbindungen", "/einstellungen?bereich=zugangsdaten",
     "Passwörter und API-Schlüssel hinterlegen; angezeigt wird nur hinterlegt oder fehlt"),
    ("page:einrichtung", "Einrichtung", "Konten und Verbindungen", "/einrichtung",
     "Verbindungen Schritt für Schritt einrichten"),
    ("page:diagnose", "Diagnose", "Konten und Verbindungen", "/diagnose", "Zugriffe lesend prüfen"),
    ("page:themen", "Themen", "Inhalte und Benachrichtigungen", "/themen",
     "Relevante und irrelevante Themen pflegen"),
    ("page:ignorierte-absender", "Ignorierte Absender", "Inhalte und Benachrichtigungen",
     "/einstellungen/ignorierte-absender", "Absender und Domains ausblenden"),
    ("page:benachrichtigungsprofil", "Benachrichtigungsprofil", "Inhalte und Benachrichtigungen",
     "/einstellungen/benachrichtigungen", "Ruhezeiten, Bündelung, Kanäle je Kategorie und Telegram-Inhalte"),
    ("page:zustellhistorie", "Zustellhistorie", "Inhalte und Benachrichtigungen", "/benachrichtigungen",
     "Gesendete Benachrichtigungen"),
    ("page:geraete", "Geräte", "System", "/geraete", "Angemeldete Browser verwalten"),
    ("page:neustarten", "Mailhelp neu starten", "System", "/einstellungen/neustarten",
     "Kontrollierter Neustart mit Bestätigung, damit gespeicherte Änderungen wirken"),
    ("page:neu-laden", "Konfiguration neu laden", "System", "/dienst/neu-laden",
     "Verbindungen ohne Prozessneustart wechseln"),
    ("page:selbsttest", "Lesender Selbsttest", "System", "/dienst/selbsttest",
     "Alle Komponenten und Handlungsempfehlungen"),
    ("page:beenden", "Mailhelp beenden", "System", "/einstellungen/beenden", "Dienst kontrolliert anhalten"),
)


@cache
def catalog() -> tuple[Entry, ...]:
    """Every searchable entry: the settings of the general areas and the special pages."""
    from .setting_help import SETTING_HELP
    from .settings_pages import AREAS, _names, setting_label
    entries = []
    for area_key, title, _text, groups in AREAS:
        for group in groups:
            for name in _names(group):
                help_text = SETTING_HELP[name]
                label = setting_label(name)
                entries.append(Entry(
                    id=f"setting:{name}", label=label, area=title, summary=_summary(help_text),
                    href=f"/einstellungen?bereich={area_key}#{anchor(name)}", key=name, group=group,
                    help=help_text, synonyms=_synonyms(f"{label} {name} {group} {title} {help_text}")))
    for identity, label, area, href, text in PAGES:
        entries.append(Entry(id=identity, label=label, area=area, summary=text, href=href,
                             path="Eigene Seite", synonyms=_synonyms(f"{label} {text}")))
    entries.extend(extra_catalog())
    return tuple(entries)


def extra_catalog() -> tuple[Entry, ...]:
    """Generated public file/setup metadata; a broken resource never disables normal settings."""
    try:
        rows = json.loads(EXTRA_CATALOG.read_text(encoding="utf-8"))
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
