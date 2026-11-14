"""6.0.6: one compact tool row for the open decisions – count, quick filters, search, sort and grouping.

Everything is a GET parameter and works without JavaScript; the tool row only changes what is shown.
It never confirms a proposal and never writes to Google Calendar or Todoist.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlencode

from ..models import ProposalStatus
from ..review.commands import CommandKind
from ..review.filters import FILTERS
from ..review.views import ProposalView, RelevanceView
from .pages import e

SORTS = {"neu": "Neueste Mail zuerst", "alt": "Älteste Mail zuerst", "datum": "Nächster Termin / nächste Frist zuerst"}
GROUP = "bedarf"
MAX_QUERY = 80
NO_MATCH = '<p class="empty">Keine passenden Entscheidungen. <a href="{path}">Zurücksetzen</a></p>'
OLDEST = datetime.min.replace(tzinfo=UTC)
LATEST = datetime.max.replace(tzinfo=UTC)


@dataclass(frozen=True)
class OpenView:
    filter: str = ""
    q: str = ""
    sort: str = "neu"
    group: bool = False

    @property
    def narrowed(self) -> bool:
        return bool(self.filter or self.q)

    def params(self, **changes: str) -> dict[str, str]:
        """The non-default settings as URL parameters; *changes* replace single values."""
        values = {"filter": self.filter, "q": self.q, "sort": "" if self.sort == "neu" else self.sort,
                  "gruppe": GROUP if self.group else "", **changes}
        return {key: value for key, value in values.items() if value}


def parse(query: str) -> OpenView:
    """An unknown quick filter is an error (422, as before); unknown sort or grouping fall back."""
    values = parse_qs(query, max_num_fields=20)
    selected = values.get("filter", [""])[0]
    if selected not in FILTERS:
        raise ValueError("Ungültiger Filter")
    text = " ".join(values.get("q", [""])[0].split())[:MAX_QUERY]
    sort = values.get("sort", ["neu"])[0]
    return OpenView(selected, text, sort if sort in SORTS else "neu", values.get("gruppe", [""])[0] == GROUP)


def found(texts: Iterable[str], query: str) -> bool:
    """Every word of the query occurs in title, subject or sender (case-insensitive)."""
    haystack = " ".join(texts).casefold()
    return all(word in haystack for word in query.casefold().split())


def search_open(views: Sequence[ProposalView], query: str) -> tuple[ProposalView, ...]:
    return tuple(view for view in views if not query or found((view.card.title, view.subject, view.sender), query))


def search_relevance(views: Sequence[RelevanceView], query: str) -> tuple[RelevanceView, ...]:
    return tuple(view for view in views if not query or found((view.subject, view.sender), query))


def ordered[Item: (ProposalView, RelevanceView)](views: Sequence[Item], sort: str) -> tuple[Item, ...]:
    """Stable: equal keys keep their order. Without a date an item goes to the end."""
    if sort == "datum":
        def due(view: Item) -> datetime:
            value = view.due_at if isinstance(view, ProposalView) else None
            return value or LATEST
        return tuple(sorted(views, key=due))
    arrived: Callable[[Item], datetime] = lambda view: view.arrived_at or OLDEST
    if sort == "alt":
        return tuple(sorted(views, key=lambda view: view.arrived_at or LATEST))
    return tuple(sorted(views, key=arrived, reverse=True))


def needs_answer(view: ProposalView) -> bool:
    return view.status == ProposalStatus.NEEDS_CLARIFICATION or bool(view.conflicts) or bool(view.card.questions)


def ready(view: ProposalView) -> bool:
    return CommandKind.CONFIRM in view.actions and not needs_answer(view)


def groups(relevance: Sequence[RelevanceView], views: Sequence[ProposalView]
           ) -> list[tuple[str, tuple[RelevanceView, ...], tuple[ProposalView, ...]]]:
    """Every decision exactly once: questions first, then what can be confirmed, then the rest."""
    asking = tuple(view for view in views if needs_answer(view))
    confirmable = tuple(view for view in views if ready(view))
    rest = tuple(view for view in views if not needs_answer(view) and not ready(view))
    return [(title, people, items) for title, people, items in (
        ("Rückfrage nötig", tuple(relevance), asking), ("Bereit zum Bestätigen", (), confirmable),
        ("Weitere Prüfung nötig", (), rest)) if people or items]


def count(shown: int, total: int, view: OpenView) -> str:
    return f"{shown} von {total}" if view.narrowed else str(total)


def toolbar(path: str, view: OpenView) -> str:
    """Quick filters keep search, sort and grouping; the form keeps the quick filter."""
    chips = "".join(
        f'<a class="button small" data-filter="{key}" aria-current="{str(view.filter == key).lower()}" '
        f'href="{e(path + "?" + urlencode(view.params(filter=key)))}">{label}</a>' for key, label in FILTERS.items())
    sorts = "".join(f'<option value="{key}"{" selected" if key == view.sort else ""}>{label}</option>'
                    for key, label in SORTS.items())
    filter_field = f'<input type="hidden" name="filter" value="{e(view.filter)}">' if view.filter else ""
    # 6.2.8: on phones search, sort and grouping fold under one control (app.js closes it there unless
    # something is set); from 900 px the summary is hidden and the form always shown.
    active = [text for text in (f"„{view.q}“" if view.q else "",
                                SORTS[view.sort] if view.sort != "neu" else "",
                                "gruppiert" if view.group else "") if text]
    state = f' <span class="open-more-state">({e(", ".join(active))})</span>' if active else ""
    return ('<div class="open-toolbar"><nav class="filter-chips" aria-label="Schnellfilter">' + chips + '</nav>'
            f'<details class="open-more" open data-open-more{" data-set" if active else ""}>'
            f'<summary>Suchen und sortieren{state}</summary>'
            f'<form method="get" action="{e(path)}" class="open-search" role="search">{filter_field}'
            '<div class="open-field"><label for="open-q">Suchen</label>'
            f'<input id="open-q" type="search" name="q" maxlength="{MAX_QUERY}" value="{e(view.q)}" '
            'placeholder="Titel, Betreff oder Absender"></div>'
            f'<div class="open-field"><label for="open-sort">Sortierung</label><select id="open-sort" name="sort">'
            f'{sorts}</select></div>'
            f'<label class="open-group"><input type="checkbox" name="gruppe" value="{GROUP}"'
            f'{" checked" if view.group else ""}> Nach Bearbeitungsbedarf gruppieren</label>'
            '<button class="button primary" type="submit">Anzeigen</button>'
            f'<a class="button link" href="{e(path)}">Zurücksetzen</a></form></details></div>')


__all__ = ["OpenView", "count", "groups", "ordered", "parse", "search_open", "search_relevance", "toolbar"]
