"""Shared, script-free presentation of the learning area."""

from __future__ import annotations

from ..i18n import msg, tr
from .pages import page_head

UPDATED = msg("Seite wurde aktualisiert, bitte erneut bestätigen.")


def heading(title: str, introduction: str, *, back: bool = True) -> str:
    """Subpages name the learning area above the title; the overview names its navigation group."""
    return page_head(
        title,
        msg("Lernen") if back else msg("Verwaltung"),
        introduction,
        back=("/lernen", msg("Zur Lernübersicht")) if back else None,
    )


def cost_hint() -> str:
    return tr(
        '<details class="help-cost-hint"><summary>Kostenpflichtig</summary'
        "><p>Eine Analyse überträgt die auf der Unterseite genannten "
        "Daten an den aktiven KI-Anbieter. Kosten entstehen erst nach "
        "deiner ausdrücklichen Startfreigabe. Das Öffnen dieser Seite "
        "startet keine Analyse.</p></details>"
    )
