"""Read-only learning preparation; displayed and submitted choices share one source."""
from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

from .pages import e, notice


def setup_form(worker: Any, query_string: str) -> tuple[str, dict[str, list[str]]]:
    try:
        query = parse_qs(query_string, keep_blank_values=True, max_num_fields=120)
    except ValueError:
        query = {"invalid": [""]}
    boxes = worker.app.settings.imap.enabled_mailboxes()
    if not boxes:
        return notice("Kein aktives Postfach. Bitte zuerst ein Postfach aktivieren.", "warn"), {}
    mailbox = query.get("mailbox", [str(boxes[0].id)])[0]
    box = next((box for box in boxes if str(box.id) == mailbox), None)
    catalog = worker.jobs.store.load("mailbox-folders", {}).get("mailboxes", {})
    names = list(dict.fromkeys(entry["name"] for entry in catalog.get(mailbox, {}).get("folders", [])))
    names = names or (box.folders if box is not None else [])
    selected = list(dict.fromkeys(query.get("folder", []) + query.get("folders", [""])[0].splitlines()))
    if not query_string:
        selected = list(boxes[0].folders)
    extra = "\n".join(name for name in selected if name not in names)
    options = "".join(f'<option value="{item.id}"{" selected" if str(item.id) == mailbox else ""}>'
                      f'{e(item.label)}</option>' for item in boxes)
    if box is None:
        options += f'<option value="{e(mailbox)}" selected>Postfach nicht verfügbar</option>'
    body = ('<h2>Neuer Lernlauf</h2><form method="get" action="/lernen/postfach" class="learning-steps">'
            '<fieldset><legend>1. Postfach und Ordner</legend><label for="learning-mailbox">Postfach</label>'
            f'<select id="learning-mailbox" name="mailbox">{options}</select>'
            '<button class="button small" name="prepare" value="1" formnovalidate>Ordner laden</button>'
            '<p class="meta">Nach einem Postfachwechsel zuerst dessen gespeicherte Ordner laden. '
            'Dabei werden keine Mails abgerufen.</p><fieldset><legend>Ordner auswählen</legend>')
    for name in names:
        body += (f'<label><input type="checkbox" name="folder" value="{e(name)}"'
                 f'{" checked" if name in selected else ""}> {e(name)}</label>')
    body += ('</fieldset><label for="learning-folders">Weitere Ordner (ein Name je Zeile)</label>'
             f'<textarea id="learning-folders" name="folders">{e(extra)}</textarea></fieldset>'
             '<fieldset><legend>2. Umfang</legend>')
    for key, title, default, maximum in (("count", "Anzahl Mails", "20", "1000"),
                                        ("price", "Preisobergrenze USD je Million Tokens", "", "10000"),
                                        ("budget", "Budget USD", "", "1000")):
        if key == "price":
            body += '</fieldset><fieldset><legend>3. Kosten und Budget</legend>'
        minimum, step = ("1", "1") if key == "count" else ("0.000001", "any")
        body += (f'<label>{title}<input name="{key}" type="number" min="{minimum}" max="{maximum}" '
                 f'step="{step}" value="{e(query.get(key, [default])[0])}" required></label>')
    models = sorted({route.model for stage in ("relevance", "learning_classification", "learning_abstraction")
                     for route in worker.app.analyzer.prompts.resolved_routes(stage)[0]})
    body += (f'<p>Konfigurierte Modelle (einschließlich Ausweichrouten): {e(", ".join(models))}.</p>'
             '<p>Aktuelle Modellpreise einschließlich Ausgabe und Reasoning selbst prüfen. '
             'Die Preisobergrenze ist deine manuelle Annahme; Anbieterabrechnungen können abweichen. '
             'Gelesen wird ohne Änderung am Postfach. Es entstehen keine Termine oder Aufgaben.</p></fieldset>'
             '<p>4. Die Schätzung zeigt Tokens und Kosten, bevor du den Lauf ausdrücklich startest.</p>'
             '<button class="button">Schätzung anzeigen</button></form>')
    return body, query
