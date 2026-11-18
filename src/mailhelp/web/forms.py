"""Form building blocks shared by every page; all values are escaped."""

from __future__ import annotations

import secrets
from collections.abc import Sequence

from ..i18n import Message, msg
from .pages import e


def select(name: str, label: str, value: object, options: Sequence[tuple[object, str]]) -> str:
    rendered = "".join(f'<option value="{e(_wire(key))}"'
                       f'{" selected" if _wire(key) == _wire(value) else ""}>{e(text)}</option>'
                       for key, text in options)
    return f'<label>{e(label)}<select name="{e(name)}">{rendered}</select></label>'


def field(name: str, label: str, value: object = "", *, hidden: bool = False) -> str:
    value = _wire(value)
    if hidden:
        return f'<input type="hidden" name="{e(name)}" value="{e(value)}">'
    if name == "meeting_mode":
        choices = {
            "unknown": msg("Unklar"),
            "video": msg("Videokonferenz"),
            "in_person": msg("Präsenz"),
            "hybrid": "Hybrid",
        }
        options = "".join(f'<option value="{key}"' + (' selected' if key == value else '') + f'>{text}</option>'
                          for key, text in choices.items())
        return f'<label>{e(label)}<select name="meeting_mode">{options}</select></label>'
    return (f'<label>{e(label)}<input type="text" name="{e(name)}" value="{e(value)}" '
            'maxlength="4000"></label>')


def post_form(
    route: str, csrf: str, body: str, label: str = msg("Speichern"), *, primary: bool = False, **hidden: object
) -> str:
    """A POST form with CSRF token and a fresh idempotency key."""
    inputs = field("csrf", "", csrf, hidden=True) + field("key", "", secrets.token_hex(16), hidden=True)
    inputs += "".join(field(name, "", value, hidden=True) for name, value in hidden.items())
    btn_class = "button primary" if primary else "button"
    return (f'<form method="post" action="{e(route)}" class="stack">{inputs}{body}'
            f'<button class="{btn_class}">{e(label)}</button></form>')


__all__ = ["field", "post_form", "select"]


def _wire(value: object) -> str:
    """A form value is canonical data, even when its visible label carries a language marker."""
    return str.__str__(value) if isinstance(value, Message) else str(value)
