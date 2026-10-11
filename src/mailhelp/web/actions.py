"""Action forms on cards and the page that follows a submitted command.

Every form carries the CSRF token, the exact proposal version and a fresh
idempotency key generated when the page is rendered.  Submitting the same form
again (double tap, browser retry after a timeout) reuses that key and can
therefore never have a second effect.
"""

from __future__ import annotations

import secrets

from ..models import ProposalStatus
from ..review.commands import CommandKind
from ..review.inbox import CommandEntry, CommandStatus
from ..review.results import ResultStatus
from ..review.views import ProposalView, RelevanceView
from .pages import e, layout, notice

_RESULT_KIND = {
    ResultStatus.DONE: "ok", ResultStatus.WRITTEN: "ok", ResultStatus.NOT_WRITTEN: "warn",
    ResultStatus.WRITE_UNCERTAIN: "warn", ResultStatus.WRITE_FAILED: "error",
    ResultStatus.NEEDS_DUPLICATE_CONFIRMATION: "warn", ResultStatus.NEEDS_ANSWER: "warn",
    ResultStatus.STALE: "warn", ResultStatus.BUSY: "warn", ResultStatus.INVALID: "error",
    ResultStatus.UNAUTHORIZED: "error", ResultStatus.FAILED: "error",
}


def new_key() -> str:
    return secrets.token_hex(16)


def _hidden(csrf: str, kind: CommandKind, mail_id: str, version: int,
            proposal_id: str | None = None, **extra: str) -> str:
    fields = {"csrf": csrf, "key": new_key(), "kind": kind.value, "mail_id": mail_id,
              "version": str(version), **({"proposal_id": proposal_id} if proposal_id else {}),
              **extra}
    return "".join(f'<input type="hidden" name="{name}" value="{e(value)}">'
                   for name, value in fields.items())


def _button_form(csrf: str, view: ProposalView, kind: CommandKind, label: str, style: str,
                 **extra: str) -> str:
    hidden = _hidden(csrf, kind, view.mail_id, view.version, view.proposal_id, **extra)
    return (f'<form method="post" action="/aktion">{hidden}'
            f'<button class="button {style}" type="submit">{e(label)}</button></form>')


def proposal_actions(csrf: str):
    """Renderer for the action area of a proposal card."""
    def render(view: ProposalView) -> str:
        if view.answer_saved:
            return notice("Antwort gespeichert – der Vorschlag wird aktualisiert.", "info")
        if view.paused:
            return notice("Die Verarbeitung ist pausiert. Bitte den Betreiber prüfen lassen.", "warn")
        if not view.actions:
            return ""
        parts = []
        if CommandKind.ANSWER in view.actions and view.question:
            parts.append(_answer(csrf, view))
        buttons = []
        if CommandKind.CONFIRM in view.actions:
            buttons.append(_button_form(csrf, view, CommandKind.CONFIRM, view.confirm_label, "primary"))
        # Every open proposal with actions can be rejected.
        buttons.append(_button_form(csrf, view, CommandKind.REJECT, "Verwerfen", "danger"))
        if CommandKind.CANCEL_CLARIFICATION in view.actions:
            buttons.append(_button_form(csrf, view, CommandKind.CANCEL_CLARIFICATION,
                                        "Bearbeitung beenden", ""))
        parts.append(f'<div class="actions">{"".join(buttons)}</div>')
        if CommandKind.ANSWER in view.actions and not view.question:
            parts.append(f"<details><summary>Ändern</summary>{_answer(csrf, view, change=True)}</details>")
        return "".join(parts)
    return render


def _answer(csrf: str, view: ProposalView, change: bool = False) -> str:
    field = f"antwort-{view.mail_id}-{view.proposal_id}"
    question = "Was soll geändert werden?" if change else view.question
    example = "„Titel: Elternabend“ oder „Ort: Raum 3“" if change else view.example
    hint = f'<p class="meta">z. B. {e(example)}</p>' if example else ""
    quick = ""
    if view.yes_no:
        quick = ('<div class="quick">'
                 + _button_form(csrf, view, CommandKind.ANSWER, "Ja", "primary", text="ja")
                 + _button_form(csrf, view, CommandKind.ANSWER, "Nein", "", text="nein")
                 + "</div>")
    hidden = _hidden(csrf, CommandKind.ANSWER, view.mail_id, view.version, view.proposal_id)
    return f"""<div class="answer">
<label for="{e(field)}">{e(question)}</label>{hint}{quick}
<form method="post" action="/aktion" class="stack">{hidden}
<textarea id="{e(field)}" name="text" maxlength="4000" required rows="2"></textarea>
<button class="button" type="submit">Antwort senden</button>
</form>
</div>"""


def relevance_actions(csrf: str):
    def render(view: RelevanceView) -> str:
        forms = []
        for decision, label, style in (("relevant", "Relevant", "primary"),
                                       ("irrelevant", "Irrelevant", "")):
            hidden = _hidden(csrf, CommandKind.RELEVANCE, view.mail_id, view.version,
                             decision=decision)
            forms.append(f'<form method="post" action="/aktion">{hidden}'
                         f'<button class="button {style}" type="submit">{label}</button></form>')
        return f'<div class="actions">{"".join(forms)}</div>'
    return render


def command_page(entry: CommandEntry, csrf: str, current: ProposalView | None) -> str:
    """Progress of a submitted command; reloads itself until the result is there."""
    running = entry.status in {CommandStatus.QUEUED, CommandStatus.RUNNING}
    if running:
        body = (notice("Wird ausgeführt … Mailhelp bearbeitet die Aktion, sobald die aktuelle "
                       "Mail analysiert ist. Diese Seite aktualisiert sich selbst.", "info"))
        return layout("Aktion läuft", f"<h1>Aktion läuft</h1>{body}"
                      '<p><a class="button" href="/">Zur Übersicht</a></p>', refresh=2)
    assert entry.result is not None
    result = entry.result
    parts = [notice(result.message, _RESULT_KIND[result.status])]
    if (result.status == ResultStatus.NEEDS_DUPLICATE_CONFIRMATION and current is not None
            and current.status == ProposalStatus.PENDING_CONFIRMATION):
        parts.append(f"<p>„{e(current.card.title)}“ wurde schon einmal angelegt.</p>")
        parts.append('<div class="actions">'
                     + _button_form(csrf, current, CommandKind.CONFIRM_DUPLICATE, "Erneut anlegen", "primary")
                     + _button_form(csrf, current, CommandKind.REJECT, "Nicht erneut anlegen", "")
                     + "</div>")
    parts.append('<p><a class="button" href="/">Zur Übersicht</a></p>')
    return layout("Ergebnis", "<h1>Ergebnis</h1>" + "".join(parts))


def stale_page(message: str, current: ProposalView | None) -> str:
    detail = (f'<p>Aktueller Stand: Version {current.version} – {e(current.state)}.</p>'
              if current is not None else "")
    return layout("Veraltet", f"""<h1>Nicht mehr aktuell</h1>
{notice(message, "warn")}{detail}
<p><a class="button primary" href="/">Aktuellen Stand anzeigen</a></p>""")


__all__ = ["command_page", "new_key", "proposal_actions", "relevance_actions", "stale_page"]
