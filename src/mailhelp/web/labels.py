"""6.2.3: German names for every internal value a page shows – status, event, source, kind.

A value without a name is shown as "unbekannt (value)", never raw; counts agree with their noun.
"""

from __future__ import annotations

from collections.abc import Mapping
from html import escape

from ..i18n import msg, tr
from ..review.commands import CommandKind
from ..review.views import STATUS_LABELS, german_number

STATUSES: dict[str, str] = {
    "retrying": msg("Erneuter Versuch angefordert"),
    "not_processed": msg("Nicht verarbeitet – abgelegt"),
    **{str(status): label for status, label in STATUS_LABELS.items()},
    "relevant": msg("Als relevant eingestuft"),
    "irrelevant": msg("Als irrelevant eingestuft"),
    "legacy": msg("Altbestand – Ablauf nicht vollständig erfasst"),
}

EVENTS: dict[str, str] = {
    "state": msg("Status geändert"),
    "edit": msg("Felder bearbeitet"),
    "relevance": msg("Relevanz entschieden"),
    "recheck": msg("Mail erneut geprüft"),
    "retry_mail": msg("Erneut versucht"),
    "file_mail": msg("Nicht verarbeitet – abgelegt"),
    "legacy": msg("Altbestand"),
    CommandKind.CONFIRM: msg("Bestätigt"),
    CommandKind.REMOVE_CREATED: msg("Angelegter Eintrag wieder entfernt"),
    CommandKind.CONFIRM_DUPLICATE: msg("Trotz möglicher Dublette bestätigt"),
    CommandKind.REJECT: msg("Verworfen"),
    CommandKind.REJECT_REASON: msg("Grund der Ablehnung gespeichert"),
    CommandKind.ALREADY_DONE: msg("Als schon erledigt erfasst"),
    CommandKind.START_CLARIFICATION: msg("Klärung begonnen"),
    CommandKind.ANSWER: msg("Rückfrage beantwortet"),
    CommandKind.CANCEL_CLARIFICATION: msg("Klärung abgebrochen"),
    CommandKind.RELEVANCE: msg("Relevanz entschieden"),
    CommandKind.EDIT: msg("Felder bearbeitet"),
    CommandKind.MERGE: msg("Vorschläge zusammengeführt"),
    CommandKind.SEPARATE: msg("Vorschläge getrennt"),
    CommandKind.RESTORE: msg("Vorschlag wiederhergestellt"),
    CommandKind.DEFAULTS: msg("Standardwerte übernommen"),
    CommandKind.RECHECK: msg("Vorschlag erneut geprüft"),
    CommandKind.RETARGET: msg("Ziel geändert"),
    CommandKind.RECHECK_MAIL: msg("Mail erneut geprüft"),
    CommandKind.RETRY_MAIL: msg("Erneut versucht"),
    CommandKind.FILE_MAIL: msg("Nicht verarbeitet – abgelegt"),
    CommandKind.SERIES_ANSWER: msg("Terminserie beantwortet"),
    CommandKind.SERIES_CONFIRM: msg("Terminserie bestätigt"),
    CommandKind.CHOOSE_EVENT: msg("Kalendereintrag gewählt"),
    CommandKind.VERIFY_ENTRY: msg("Eintrag beim Anbieter geprüft"),
    CommandKind.CHOOSE_VARIANT: msg("Wert aus einem Konflikt gewählt"),
}

SOURCES: dict[str, str] = {
    "system": "Mailhelp",
    "web": msg("Weboberfläche"),
    "telegram": "Telegram",
    "unknown": msg("unbekannt"),
}

KINDS: dict[str, str] = {"event": msg("Termin"), "task": msg("Aufgabe")}


# 6.2.7: one colour per meaning; the text always names the status, colour only repeats it.
BADGE_KINDS: dict[str, str] = {
    "created": "ok", "already_exists": "ok", "merged": "ok", "simulated": "ok", "relevant": "ok",
    "pending_confirmation": "accent", "confirmed": "accent", "writing": "accent", "verifying": "accent",
    "needs_clarification": "warn", "uncertain": "warn", "removed": "warn",
    "failed": "danger",
}


def status_badge(status: object, prefix: str = "") -> str:
    tr('The status as the same badge on every page, e.g. ``<span class="badge warn">Klärung nötig</span>``.')
    kind = BADGE_KINDS.get(str(status), "")
    return f'<span class="badge{" " + kind if kind else ""}">{escape(prefix + label(STATUSES, status))}</span>'


def label(names: Mapping[str, str], value: object) -> str:
    """The name of *value* in the active language; unknown values stay recognisable but are marked."""
    text = str(value)
    name = names.get(text)
    return tr(name) if name else tr("unbekannt ({value})", value=text)


def count_text(number: int, one: str, many: str) -> str:
    """ "1 Vorschlag", "2 Vorschläge", "1.234 Mails" – the noun agrees with the number."""
    return f"{german_number(number)} {one if number == 1 else many}"


__all__ = ["BADGE_KINDS", "EVENTS", "KINDS", "SOURCES", "STATUSES", "count_text", "label", "status_badge"]
