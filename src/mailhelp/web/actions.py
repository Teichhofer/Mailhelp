"""Action forms on cards and the page that follows a submitted command.

Every form carries the CSRF token, the exact proposal version and a fresh
idempotency key generated when the page is rendered.  Submitting the same form
again (double tap, browser retry after a timeout) reuses that key and can
therefore never have a second effect.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable

from ..models import ProposalStatus
from ..review.commands import CommandKind, ReviewCommand
from ..review.inbox import CommandEntry, CommandStatus
from ..review.incoming import key_hash
from ..review.results import ResultStatus
from ..review.views import ProposalView, RelevanceView
from .pages import e, layout, notice
from .reconciliation_pages import focus_link

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
    fields["receipt_id"] = key_hash(fields["key"])[:32]
    return "".join(f'<input type="hidden" name="{name}" value="{e(value)}">'
                   for name, value in fields.items())


def _button_form(csrf: str, view: ProposalView, kind: CommandKind, label: str, style: str,
                 **extra: str) -> str:
    hidden = _hidden(csrf, kind, view.mail_id, view.version, view.proposal_id, **extra)
    return (f'<form method="post" action="/aktion">{hidden}'
            f'<button class="button {style}" type="submit">{e(label)}</button></form>')


def proposal_actions(csrf: str) -> Callable[[ProposalView], str]:
    """Renderer for the action area of a proposal card."""
    def render(view: ProposalView) -> str:
        if view.verification is not None:
            return verification_block(csrf, view)
        if view.answer_saved:
            return notice("Antwort gespeichert – der Vorschlag wird aktualisiert.", "info")
        if view.paused:
            return notice("Die Verarbeitung ist pausiert. Bitte den Betreiber prüfen lassen.", "warn")
        if not view.actions:
            return ""
        parts = []
        if CommandKind.CHOOSE_EVENT in view.actions:
            # 4.6: only the entries offered for this version can be chosen.
            choices = "".join(_button_form(csrf, view, CommandKind.CHOOSE_EVENT, f"Diesen Termin meinen: {label}",
                                           "", candidate=str(index))
                              for index, label in enumerate(view.calendar_candidates))
            parts.append(f'<div class="actions">{choices}</div>')
        if view.reconciliation_required:
            # 5.0.3: decided by an explicit assignment, never by a text answer.
            parts.append(notice("Mailhelp hält diesen Vorschlag für möglicherweise dieselbe Sache wie einen "
                                "anderen. Im Vorschlagsabgleich entscheidest du: zuordnen oder als eigenen "
                                "Vorschlag behalten.", "warn")
                         + '<p class="card-links"><a class="button primary" href="'
                         + e(focus_link(view.mail_id, view.proposal_id))
                         + '">Im Vorschlagsabgleich entscheiden</a></p>')
        if CommandKind.ANSWER in view.actions and view.question:
            parts.append(_answer(csrf, view))
        buttons = []
        if CommandKind.RECHECK in view.actions:
            # A failed duplicate check blocks confirmation until it ran successfully.
            buttons.append(_button_form(csrf, view, CommandKind.RECHECK, "Dublettenprüfung wiederholen", "primary"))
        if CommandKind.CONFIRM in view.actions:
            buttons.append(_button_form(csrf, view, CommandKind.CONFIRM, view.confirm_label, "primary"))
        # Every open proposal with actions can be rejected.
        buttons.append(_button_form(csrf, view, CommandKind.REJECT, "Verwerfen", "danger"))
        buttons.append(_button_form(csrf, view, CommandKind.ALREADY_DONE, "Schon erledigt", ""))
        if CommandKind.CANCEL_CLARIFICATION in view.actions:
            buttons.append(_button_form(csrf, view, CommandKind.CANCEL_CLARIFICATION,
                                        "Bearbeitung beenden", ""))
        # 5.0.8: the decision row stays at the bottom edge of the detail pane while scrolling.
        parts.append(f'<div class="actions decision-bar">{"".join(buttons)}</div>')
        parts.append('<details class="decision-help"><summary>Was bedeuten diese Entscheidungen?</summary>'
                     '<p>Verwerfen lehnt diesen Vorschlag ab. Schon erledigt bedeutet: relevant, '
                     'aber bereits erledigt; es wird kein neuer Eintrag angelegt. Diese Entscheidungen '
                     'können später ausdrücklich zur Verbesserung Ihrer Themenregeln ausgewertet werden.</p></details>')
        if CommandKind.ANSWER in view.actions and not view.question:
            parts.append(f"<details><summary>Ändern</summary>{_answer(csrf, view, change=True)}</details>")
        return "".join(parts)
    return render


def verification_block(csrf: str, view: ProposalView) -> str:
    """5.2: the check of a written entry with an expected/actual table and a read-only recheck."""
    item = view.verification
    assert item is not None
    detail = f'<p class="meta">{e(item.detail)}</p>' if item.detail else ""
    table = ""
    if item.differences:
        rows = "".join(f"<tr><th scope=\"row\">{e(label)}</th><td>{e(expected)}</td><td>{e(actual)}</td></tr>"
                       for label, expected, actual in item.differences)
        table = ('<table class="verification-diff"><thead><tr><th scope="col">Angabe</th>'
                 '<th scope="col">Bestätigt</th><th scope="col">Beim Anbieter</th></tr></thead>'
                 f"<tbody>{rows}</tbody></table>")
    button = ""
    if CommandKind.VERIFY_ENTRY in view.actions:
        button = ('<div class="actions">'
                  + _button_form(csrf, view, CommandKind.VERIFY_ENTRY, "Erneut prüfen", "")
                  + '</div><p class="meta">Liest den Eintrag nur erneut; es wird nichts geändert oder angelegt.</p>')
    return (f'<div class="verification verification-{e(item.state.value)}">'
            f"<p><strong>{e(item.title)}</strong></p>{detail}{table}{button}</div>")


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


def recheck_form(csrf: str, mail_id: str, analysis_round: int, *, small: bool = False) -> str:
    """Analyse a mail filed as irrelevant again, e.g. after adding a topic (3.6.2)."""
    hidden = _hidden(csrf, CommandKind.RECHECK_MAIL, mail_id, analysis_round)
    size = " small" if small else ""
    return (f'<form method="post" action="/aktion" class="recheck">{hidden}'
            f'<button class="button{size}" type="submit">Erneut prüfen</button></form>')


def relevance_actions(csrf: str) -> Callable[[RelevanceView], str]:
    def render(view: RelevanceView) -> str:
        forms = []
        for decision, label, style in (("relevant", "Relevant", "primary"),
                                       ("irrelevant", "Irrelevant", "")):
            hidden = _hidden(csrf, CommandKind.RELEVANCE, view.mail_id, view.version,
                             decision=decision)
            forms.append(f'<form method="post" action="/aktion">{hidden}'
                         f'<button class="button {style}" type="submit">{label}</button></form>')
        return (f'<div class="actions">{"".join(forms)}</div>'
                '<p class="meta">Relevant: Mail weiter auswerten. Irrelevant: nicht weiter auswerten. '
                'Die Entscheidung kann später zum Regellernen verwendet werden.</p>')
    return render


def result_kind(status: ResultStatus) -> str:
    """Notice style for a command result."""
    return _RESULT_KIND[status]


def needs_choice(entry: CommandEntry, current: ProposalView | None) -> bool:
    """Only a detected earlier creation needs a decision on the result page."""
    return (entry.result is not None
            and entry.result.status == ResultStatus.NEEDS_DUPLICATE_CONFIRMATION
            and isinstance(entry.command, ReviewCommand)
            and current is not None and current.version == entry.command.version
            and current is not None and current.status == ProposalStatus.PENDING_CONFIRMATION)


def command_page(entry: CommandEntry, csrf: str, current: ProposalView | None) -> str:
    """Progress of a submitted command; reloads itself until the result is there."""
    running = entry.status in {CommandStatus.QUEUED, CommandStatus.RUNNING}
    if running:
        body = notice("Wird ausgeführt … Danach geht es automatisch zur Übersicht.", "info")
        if entry.command.kind in {CommandKind.CONFIRM, CommandKind.CONFIRM_DUPLICATE} and current is not None:
            destination = "Kalender" if current.card.kind.value == "event" else "Aufgabenliste (z. B. Todoist)"
            body += f"<p>Die Anlage im Ziel {e(destination)} kann einen Moment dauern.</p>"
        return layout("Aktion läuft", f"<h1>Aktion läuft</h1>{body}"
                      f'<div data-command-status="/api/aktion/{entry.id}" role="status" aria-live="polite"></div>'
                      '<p><a class="button" href="/">Zur Übersicht</a></p>'
                      '<noscript><meta http-equiv="refresh" content="1"></noscript>')
    assert entry.result is not None
    result = entry.result
    # Every other result returns to the overview; only this one needs a choice.
    assert needs_choice(entry, current) and current is not None
    parts = [notice(result.message, _RESULT_KIND[result.status]),
             f"<p>„{e(current.card.title)}“ wurde schon einmal angelegt.</p>",
             '<div class="actions">'
             + _button_form(csrf, current, CommandKind.CONFIRM_DUPLICATE, "Erneut anlegen", "primary")
             + _button_form(csrf, current, CommandKind.REJECT, "Nicht erneut anlegen", "")
             + "</div>"]
    parts.append('<p><a class="button" href="/">Zur Übersicht</a></p>')
    return layout("Ergebnis", "<h1>Ergebnis</h1>" + "".join(parts))


def stale_page(message: str, current: ProposalView | None) -> str:
    detail = (f'<p>Aktueller Stand: Version {current.version} – {e(current.state)}.</p>'
              if current is not None else "")
    return layout("Veraltet", f"""<h1>Nicht mehr aktuell</h1>
{notice(message, "warn")}{detail}
<p><a class="button primary" href="/">Aktuellen Stand anzeigen</a></p>""")


__all__ = ["command_page", "needs_choice", "new_key", "result_kind", "proposal_actions", "relevance_actions",
           "stale_page"]
