"""Shared, script-free presentation of the learning area."""
from __future__ import annotations

from .pages import e


def heading(title: str, introduction: str, *, back: bool = True) -> str:
    return ('<div class="page-heading"><p class="eyebrow">Lernen</p>'
            f'<h1>{e(title)}</h1><p>{e(introduction)}</p></div>'
            + ('<p><a href="/lernen">Zur Lernübersicht</a></p>' if back else ""))


def cost_hint() -> str:
    return ('<details class="help-cost-hint"><summary>Kostenpflichtig</summary>'
            '<p>Eine Analyse überträgt die auf der Unterseite genannten Daten an den aktiven KI-Anbieter. '
            'Kosten entstehen erst nach Ihrer ausdrücklichen Startfreigabe. Das Öffnen dieser Seite '
            'startet keine Analyse.</p></details>')
