"""Shared server-side quick filters, also usable without JavaScript."""

from __future__ import annotations

from urllib.parse import urlencode

from ..i18n import tr
from ..review.filters import FILTERS, matches  # noqa: F401  (re-exported for web callers)
from .pages import e


def chips(path: str, selected: str = "") -> str:
    return (
        tr('<nav class="filter-chips" aria-label="Schnellfilter">')
        + "".join(
            f'<a class="button small" data-filter="{key}" aria-current="{str(selected == key).lower()}" '
            f'href="{path}?{e(urlencode({"filter": key}))}">{label}</a>'
            for key, label in FILTERS.items()
        )
        + "</nav>"
    )
