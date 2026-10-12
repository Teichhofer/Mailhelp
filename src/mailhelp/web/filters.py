"""Shared server-side quick filters, also usable without JavaScript."""
from urllib.parse import urlencode

from .pages import e

FILTERS = {"": "Alle", "events": "Termine", "tasks": "Aufgaben", "clarification": "Klärung nötig",
           "attachments": "Mit Anhängen", "duplicates": "Duplikate"}


def matches(selected, kinds, statuses, attachments, duplicate=False):
    return {"": True, "events": "event" in kinds, "tasks": "task" in kinds,
            "clarification": "needs_clarification" in statuses or "unclear" in statuses,
            "attachments": bool(attachments),
            "duplicates": duplicate or "already_exists" in statuses}[selected]


def chips(path, selected=""):
    return '<nav class="filter-chips" aria-label="Schnellfilter">' + "".join(
        f'<a class="button small" data-filter="{key}" aria-current="{str(selected == key).lower()}" '
        f'href="{path}?{e(urlencode({"filter": key}))}">{label}</a>' for key, label in FILTERS.items()) + '</nav>'
