"""6.2.3: German names for every internal value a page shows – status, event, source, kind.

A value without a name is shown as "unbekannt (value)", never raw; counts agree with their noun.
"""
from __future__ import annotations

from collections.abc import Mapping

from ..review.commands import CommandKind
from ..review.views import STATUS_LABELS, german_number

STATUSES: dict[str, str] = {
    **{str(status): label for status, label in STATUS_LABELS.items()},
    "relevant": "Als relevant eingestuft",
    "irrelevant": "Als irrelevant eingestuft",
    "legacy": "Altbestand – Ablauf nicht vollständig erfasst",
}

EVENTS: dict[str, str] = {
    "state": "Status geändert",
    "edit": "Felder bearbeitet",
    "relevance": "Relevanz entschieden",
    "recheck": "Mail erneut geprüft",
    "legacy": "Altbestand",
    CommandKind.CONFIRM: "Bestätigt",
    CommandKind.CONFIRM_DUPLICATE: "Trotz möglicher Dublette bestätigt",
    CommandKind.REJECT: "Verworfen",
    CommandKind.ALREADY_DONE: "Als schon erledigt erfasst",
    CommandKind.START_CLARIFICATION: "Klärung begonnen",
    CommandKind.ANSWER: "Rückfrage beantwortet",
    CommandKind.CANCEL_CLARIFICATION: "Klärung abgebrochen",
    CommandKind.RELEVANCE: "Relevanz entschieden",
    CommandKind.EDIT: "Felder bearbeitet",
    CommandKind.MERGE: "Vorschläge zusammengeführt",
    CommandKind.SEPARATE: "Vorschläge getrennt",
    CommandKind.RESTORE: "Vorschlag wiederhergestellt",
    CommandKind.DEFAULTS: "Standardwerte übernommen",
    CommandKind.RECHECK: "Vorschlag erneut geprüft",
    CommandKind.RETARGET: "Ziel geändert",
    CommandKind.RECHECK_MAIL: "Mail erneut geprüft",
    CommandKind.SERIES_ANSWER: "Terminserie beantwortet",
    CommandKind.SERIES_CONFIRM: "Terminserie bestätigt",
    CommandKind.CHOOSE_EVENT: "Kalendereintrag gewählt",
    CommandKind.VERIFY_ENTRY: "Eintrag beim Anbieter geprüft",
    CommandKind.CHOOSE_VARIANT: "Wert aus einem Konflikt gewählt",
}

SOURCES: dict[str, str] = {"system": "Mailhelp", "web": "Weboberfläche", "telegram": "Telegram",
                           "unknown": "unbekannt"}

KINDS: dict[str, str] = {"event": "Termin", "task": "Aufgabe"}


def label(names: Mapping[str, str], value: object) -> str:
    """The German name of *value*; unknown values stay recognisable but are marked as such."""
    text = str(value)
    return names.get(text) or f"unbekannt ({text})"


def count_text(number: int, one: str, many: str) -> str:
    """"1 Vorschlag", "2 Vorschläge", "1.234 Mails" – the noun agrees with the number."""
    return f"{german_number(number)} {one if number == 1 else many}"


__all__ = ["EVENTS", "KINDS", "SOURCES", "STATUSES", "count_text", "label"]
