"""Form building blocks shared by every page; all values are escaped."""
from __future__ import annotations

import secrets
from collections.abc import Sequence

from .pages import e


def select(name: str, label: str, value: object, options: Sequence[tuple[object, str]]) -> str:
    rendered = "".join(f'<option value="{e(key)}"{" selected" if str(key) == str(value) else ""}>{e(text)}</option>'
                       for key, text in options)
    return f'<label>{e(label)}<select name="{e(name)}">{rendered}</select></label>'


def field(name: str, label: str, value: object = "", *, hidden: bool = False) -> str:
    if hidden:
        return f'<input type="hidden" name="{e(name)}" value="{e(value)}">'
    if name == "meeting_mode":
        choices = {"unknown": "Unklar", "video": "Videokonferenz", "in_person": "Präsenz", "hybrid": "Hybrid"}
        options = "".join(f'<option value="{key}"' + (' selected' if key == value else '') + f'>{text}</option>'
                          for key, text in choices.items())
        return f'<label>{e(label)}<select name="meeting_mode">{options}</select></label>'
    return (f'<label>{e(label)}<input type="text" name="{e(name)}" value="{e(value)}" '
            'maxlength="4000"></label>')


def post_form(route: str, csrf: str, body: str, label: str = "Speichern", **hidden) -> str:
    """A POST form with CSRF token and a fresh idempotency key."""
    inputs = field("csrf", "", csrf, hidden=True) + field("key", "", secrets.token_hex(16), hidden=True)
    inputs += "".join(field(name, "", value, hidden=True) for name, value in hidden.items())
    return (f'<form method="post" action="{e(route)}" class="stack">{inputs}{body}'
            f'<button class="button">{e(label)}</button></form>')


__all__ = ["field", "post_form", "select"]
