"""6.2.5: one tool row for every list – search and the most used choices next to one primary action.

Further filters sit under "Mehr Filter", which names how many of them are active and is open while any
is. Everything is a plain GET form: the address keeps the filters, and it works without JavaScript.
"""
from __future__ import annotations

from collections.abc import Sequence

from .pages import e


def date_field(name: str, label: str, value: object) -> str:
    return f'<label>{e(label)}<input type="date" name="{e(name)}" value="{e(value or "")}"></label>'


def search_field(name: str, label: str, value: str, *, hint_id: str = "", placeholder: str = "",
                 maxlength: int = 200) -> str:
    described = f' aria-describedby="{e(hint_id)}"' if hint_id else ""
    shown = f' placeholder="{e(placeholder)}"' if placeholder else ""
    return (f'<label class="toolbar-search">{e(label)}<input type="search" name="{e(name)}" value="{e(value)}" '
            f'maxlength="{maxlength}"{described}{shown}></label>')


def toolbar(action: str, main: Sequence[str], *, submit: str, more: Sequence[str] = (), active: int = 0,
            reset: str = "", hidden: str = "", below: str = "") -> str:
    """*main* fields share the row with the primary button; *more* go under "Mehr Filter".

    *active* is the number of non-default values among *more*; *below* follows the row (e.g. a search hint).
    """
    extra = ""
    if more:
        state = f" ({active} aktiv)" if active else ""
        extra = (f'<details class="toolbar-more"{" open" if active else ""}><summary>Mehr Filter{state}</summary>'
                 f'<div class="filters">{"".join(more)}</div></details>')
    link = f'<a class="button link" href="{e(reset)}">Zurücksetzen</a>' if reset else ""
    return (f'<form method="get" action="{e(action)}" class="toolbar" role="search">{hidden}'
            f'<div class="toolbar-row">{"".join(main)}'
            f'<button class="button primary" type="submit">{e(submit)}</button>{link}</div>{below}{extra}</form>')


__all__ = ["date_field", "search_field", "toolbar"]
