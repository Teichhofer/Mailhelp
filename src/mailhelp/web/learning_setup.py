"""Read-only learning preparation; displayed and submitted choices share one source."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

from ..i18n import msg, tr
from .pages import e, notice

_SETUP_FORM_TEXT_1 = msg(
    '<h2>Neuer Lernlauf</h2><form method="get" action="/lernen/postfach" '
    'class="learning-steps"><fieldset><legend>1. Postfach und Ordner</legend><label '
    'for="learning-mailbox">Postfach</label><select id="learning-mailbox" '
    'name="mailbox">{p0}</select><button class="button small" name="prepare" value="1" '
    'formnovalidate>Ordner laden</button><p class="meta">Nach einem Postfachwechsel '
    "zuerst dessen gespeicherte Ordner laden. Dabei werden keine Mails "
    "abgerufen.</p><fieldset><legend>Ordner auswählen</legend>"
)

_SETUP_FORM_TEXT_2 = msg(
    '</fieldset><label for="learning-folders">Weitere Ordner (ein Name je '
    'Zeile)</label><textarea id="learning-folders" '
    'name="folders">{p0}</textarea></fieldset><fieldset><legend>2. Umfang</legend>'
)

_SETUP_FORM_TEXT_3 = msg(
    "<p>Konfigurierte Modelle (einschließlich Ausweichrouten): {p0}.</p><p>Aktuelle "
    "Modellpreise einschließlich Ausgabe und Reasoning selbst prüfen. Die Preisobergrenze "
    "ist deine manuelle Annahme; Anbieterabrechnungen können abweichen. Gelesen wird ohne "
    "Änderung am Postfach. Es entstehen keine Termine oder Aufgaben.</p></fieldset><p>4. "
    "Die Schätzung zeigt Tokens und Kosten, bevor du den Lauf ausdrücklich "
    'startest.</p><button class="button">Schätzung anzeigen</button></form>'
)

# 8.7.4: customers choose a points limit; models, prices and tokens are the operator's.
_CUSTOMER_FORM_TEXT = msg(
    '</fieldset><fieldset><legend>3. Punktegrenze</legend><label>Punktegrenze für diesen Lauf'
    '<input name="points" type="number" min="1" max="10000000" step="1" value="{p0}" required></label>'
    "<p>Der Lauf hält an, bevor er die Grenze überschreiten würde. Gelesen wird ohne Änderung am "
    "Postfach. Es entstehen keine Termine oder Aufgaben.</p></fieldset><p>4. Die Schätzung zeigt den "
    "Verbrauch in Punkten, bevor du den Lauf ausdrücklich startest.</p>"
    '<button class="button">Schätzung anzeigen</button></form>'
)


# Chrome and WebKit submit through a hidden default button too (checked 26.11.2026).
DEFAULT_SUBMIT = "<button hidden></button>"


def setup_form(worker: Any, query_string: str, *, customer: bool = False) -> tuple[str, dict[str, list[str]]]:
    try:
        query = parse_qs(query_string, keep_blank_values=True, max_num_fields=120)
    except ValueError:
        query = {"invalid": [""]}
    boxes = worker.app.settings.imap.enabled_mailboxes()
    if not boxes:
        return notice(tr("Kein aktives Postfach. Bitte zuerst ein Postfach aktivieren."), "warn"), {}
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
        options += tr('<option value="{p0}" selected>Postfach nicht verfügbar</option>', p0=e(mailbox))
    body = tr(
        (_SETUP_FORM_TEXT_1),
        p0=options,
    )
    # 8.7.6 bugfix: Enter submits through the first submit button, which must be the estimate, not
    # "Ordner laden". The hidden default button is neither shown, focusable nor announced.
    body = body.replace('class="learning-steps">', 'class="learning-steps">' + DEFAULT_SUBMIT, 1)
    for name in names:
        body += (f'<label><input type="checkbox" name="folder" value="{e(name)}"'
                 f'{" checked" if name in selected else ""}> {e(name)}</label>')
    body += tr(
        (_SETUP_FORM_TEXT_2),
        p0=e(extra),
    )
    fields = (("count", "Anzahl Mails", "20", "1000"),) if customer else (
        ("count", "Anzahl Mails", "20", "1000"),
        ("price", msg("Preisobergrenze USD je Million Tokens"), "", "10000"),
        ("budget", "Budget USD", "", "1000"),
    )
    for key, title, default, maximum in fields:
        if key == "price":
            body += tr("</fieldset><fieldset><legend>3. Kosten und Budget</legend>")
        minimum, step = ("1", "1") if key == "count" else ("0.000001", "any")
        body += (f'<label>{title}<input name="{key}" type="number" min="{minimum}" max="{maximum}" '
                 f'step="{step}" value="{e(query.get(key, [default])[0])}" required></label>')
    if customer:
        return body + tr(_CUSTOMER_FORM_TEXT, p0=e(query.get("points", [""])[0])), query
    models = sorted({route.model for stage in ("relevance", "learning_classification", "learning_abstraction")
                     for route in worker.app.analyzer.prompts.resolved_routes(stage)[0]})
    body += tr(
        (_SETUP_FORM_TEXT_3),
        p0=e(", ".join(models)),
    )
    return body, query
