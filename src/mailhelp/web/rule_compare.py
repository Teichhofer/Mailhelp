"""5.7.3 (S4): one comparison of a topic rule before and after, shared by topic edits and rule learning.

Changed fields are shown first with a text badge, list fields line by line (added / removed /
kept); unchanged fields are folded away. Everything is escaped and works without scripts.
"""

from __future__ import annotations

from typing import Any

from ..i18n import msg, tr
from .pages import e

FIELDS = (
    ("name", msg("Name")),
    ("description", msg("Beschreibung")),
    ("examples", msg("Beispiele")),
    ("exclusions", msg("Ausschlüsse")),
    ("enabled", msg("Aktiv")),
    ("mailboxes", msg("Geltungsbereich")),
)


def shown(key: str, value: Any) -> str:
    if key == "enabled":
        return "Ja" if value else msg("Nein")
    if key == "mailboxes":
        return (
            msg("alle Postfächer")
            if value is None
            else ", ".join(tr("Postfach {p0}", p0=item) for item in value) or msg("keine")
        )
    if isinstance(value, list):
        return "\n".join(value) or msg("Keine")
    return str(value)


def lines(before: list[str], after: list[str]) -> str:
    """The proposed list with each entry marked as kept or added, followed by the removed ones."""
    items = []
    for entry in after:
        if entry in before:
            items.append(f"<li>{e(entry)}</li>")
        else:
            items.append(tr('<li class="diff-added"><span class="diff-mark">+ neu:</span> {p0}</li>', p0=f"{e(entry)}"))
    items += [
        tr(
            ('<li class="diff-removed"><span class="diff-mark">− entfernt:</span> <del>{p0}</del></li>'),
            p0=e(entry),
        )
        for entry in before
        if entry not in after
    ]
    return '<ul class="line-diff">' + ("".join(items) or tr("<li>Keine</li>")) + "</ul>"


def badge(status: str) -> str:
    classes = {"neu": "accent", "geändert": "warn", "unverändert": "info"}
    return f'<span class="badge {classes[status]}">{status}</span>'


def compare(before: dict[str, Any] | None, after: dict[str, Any]) -> str:
    """Changed (or, for a new topic, all) fields as a table, unchanged fields folded."""
    changed, unchanged = [], []
    for key, label in FIELDS:
        old, new = (before or {}).get(key), after.get(key)
        if before is not None and key in before and old == new:
            unchanged.append(f"<dt>{label} {badge('unverändert')}</dt><dd>{e(shown(key, new))}</dd>")
            continue
        status = msg("neu") if before is None else msg("geändert")
        if isinstance(new, list) and key != "mailboxes":
            value = lines(old or [], new)
        else:
            value = f'<span class="compare-text">{e(shown(key, new))}</span>'
        previous = "—" if before is None else f'<span class="compare-text">{e(shown(key, old))}</span>'
        changed.append(f'<tr><th scope="row">{label} {badge(status)}</th>'
                       f'<td data-label="Bisher">{previous}</td><td data-label="Neu">{value}</td></tr>')
    caption = msg("Neues Thema: alle Felder") if before is None else tr("Geänderte Felder ({p0})", p0=len(changed))
    body = '<div class="rule-compare">'
    if changed:
        body += (
            tr(
                (
                    '<table class="compare-table"><caption>{p0}</caption><thead><tr><th '
                    'scope="col">Feld</th><th scope="col">Bisher</th><th '
                    'scope="col">Neu</th></tr></thead><tbody>'
                ),
                p0=f"{caption}",
            )
            + "".join(changed)
            + "</tbody></table>"
        )
    else:
        body += tr("<p>Keine Feldänderung gegenüber der bisherigen Regel.</p>")
    if unchanged:
        body += tr(
            (
                '<details class="compare-unchanged"><summary>Unveränderte Felder '
                "anzeigen ({p0})</summary><dl>{p1}</dl></details>"
            ),
            p0=len(unchanged),
            p1="".join(unchanged),
        )
    return body + "</div>"
