"""5.7.3 (S4): one comparison of a topic rule before and after, shared by topic edits and rule learning.

Changed fields are shown first with a text badge, list fields line by line (added / removed /
kept); unchanged fields are folded away. Everything is escaped and works without scripts.
"""
from __future__ import annotations

from typing import Any

from .pages import e

FIELDS = (("name", "Name"), ("description", "Beschreibung"), ("examples", "Beispiele"),
          ("exclusions", "Ausschlüsse"), ("enabled", "Aktiv"), ("mailboxes", "Geltungsbereich"))


def shown(key: str, value: Any) -> str:
    if key == "enabled":
        return "Ja" if value else "Nein"
    if key == "mailboxes":
        return "alle Postfächer" if value is None else ", ".join(f"Postfach {item}" for item in value) or "keine"
    if isinstance(value, list):
        return "\n".join(value) or "Keine"
    return str(value)


def lines(before: list[str], after: list[str]) -> str:
    """The proposed list with each entry marked as kept or added, followed by the removed ones."""
    items = []
    for entry in after:
        if entry in before:
            items.append(f"<li>{e(entry)}</li>")
        else:
            items.append(f'<li class="diff-added"><span class="diff-mark">+ neu:</span> {e(entry)}</li>')
    items += [f'<li class="diff-removed"><span class="diff-mark">− entfernt:</span> <del>{e(entry)}</del></li>'
              for entry in before if entry not in after]
    return '<ul class="line-diff">' + ("".join(items) or "<li>Keine</li>") + "</ul>"


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
        status = "neu" if before is None else "geändert"
        if isinstance(new, list) and key != "mailboxes":
            value = lines(old or [], new)
        else:
            value = f'<span class="compare-text">{e(shown(key, new))}</span>'
        previous = "—" if before is None else f'<span class="compare-text">{e(shown(key, old))}</span>'
        changed.append(f'<tr><th scope="row">{label} {badge(status)}</th>'
                       f'<td data-label="Bisher">{previous}</td><td data-label="Neu">{value}</td></tr>')
    caption = "Neues Thema: alle Felder" if before is None else f"Geänderte Felder ({len(changed)})"
    body = '<div class="rule-compare">'
    if changed:
        body += (f'<table class="compare-table"><caption>{caption}</caption><thead><tr><th scope="col">Feld</th>'
                 '<th scope="col">Bisher</th><th scope="col">Neu</th></tr></thead><tbody>'
                 + "".join(changed) + "</tbody></table>")
    else:
        body += "<p>Keine Feldänderung gegenüber der bisherigen Regel.</p>"
    if unchanged:
        body += (f'<details class="compare-unchanged"><summary>Unveränderte Felder anzeigen ({len(unchanged)})'
                 f'</summary><dl>{"".join(unchanged)}</dl></details>')
    return body + "</div>"
