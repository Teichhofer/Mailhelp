"""Action forms on cards and the page that follows a submitted command.

Every form carries the CSRF token, the exact proposal version and a fresh
idempotency key generated when the page is rendered.  Submitting the same form
again (double tap, browser retry after a timeout) reuses that key and can
therefore never have a second effect.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable

from ..domain.proposal import ProposalKind, ProposalStatus
from ..i18n import msg, stored, tr
from ..review.commands import CommandKind, ReviewCommand
from ..review.inbox import CommandEntry, CommandStatus
from ..review.incoming import key_hash
from ..review.reject_reasons import REJECT_REASONS, USER_REJECT_REASONS
from ..review.results import ResultStatus
from ..review.views import ConflictChoice, ProposalView, RelevanceView
from .pages import e, layout, notice
from .reconciliation_pages import focus_link

_PROPOSAL_ACTIONS_TEXT_1 = msg(
    "Mailhelp hält diesen Vorschlag für möglicherweise dieselbe Sache wie einen anderen. "
    "Im Vorschlagsabgleich entscheidest du: zuordnen oder als eigenen Vorschlag behalten."
)

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


def conflict_boxes(view: ProposalView, csrf: str | None = None) -> str:
    """5.9.3: both values side by side; with *csrf* and the action, one form per value.

    No value is preselected or highlighted: the user decides. Choosing revises the proposal only.
    """
    forms = csrf is not None and CommandKind.CHOOSE_VARIANT in view.actions
    return "".join(_conflict_box(view, item, csrf if forms else None) for item in view.conflicts)


def _conflict_box(view: ProposalView, item: ConflictChoice, csrf: str | None) -> str:
    sides = []
    for option in item.options:
        button = ""
        if csrf is not None:
            label = f"{option.button} {tr('behalten' if option.keep else 'übernehmen')}"
            button = _button_form(csrf, view, CommandKind.CHOOSE_VARIANT, label, "",
                                  conflict_id=item.id, variant=option.id)
        sides.append(f'<div class="compare-side conflict-side"><p class="compare-tag">{e(stored(option.origin))}</p>'
                     f'<p class="conflict-value"><strong>{e(option.value)}</strong></p>{button}</div>')
    hint = ('<p class="meta">' + tr('Die Auswahl ändert nur den Vorschlag; angelegt wird erst nach deiner '
                                    'Bestätigung. Für einen anderen Wert den Vorschlag ändern.') + '</p>'
            if csrf is not None else "")
    ident = 'konflikt-{p0}-{p1}-{p2}'.format(p0=f'{view.mail_id}', p1=f'{view.proposal_id}', p2=f'{item.id}')
    return (f'<section class="conflict" aria-labelledby="{e(ident)}"><h4 id="{e(ident)}">'
            f'{e(tr("⚠️ Widerspruch: {field} – welcher Wert soll gelten?", field=stored(item.label)))}</h4>'
            f'<p class="visually-hidden">{e(stored(item.question))}</p>'
            f'<div class="compare">{"".join(sides)}</div>{hint}</section>')


def proposal_actions(csrf: str) -> Callable[[ProposalView], str]:
    """Renderer for the action area of a proposal card."""

    def render(view: ProposalView) -> str:
        return conflict_boxes(view, csrf) + _actions(view)

    def _actions(view: ProposalView) -> str:
        if view.verification is not None:
            return verification_block(csrf, view)
        if view.answer_saved:
            return notice(tr("Antwort gespeichert – der Vorschlag wird aktualisiert."), "info")
        if view.paused:
            return notice(tr("Die Verarbeitung ist pausiert. Bitte den Betreiber prüfen lassen."), "warn")
        if view.status == ProposalStatus.REJECTED:
            return reject_reason_block(csrf, view.mail_id, view.proposal_id, view.version, view.reject_reason)
        if not view.actions:
            return ""
        parts = []
        if CommandKind.CHOOSE_EVENT in view.actions:
            # 4.6: only the entries offered for this version can be chosen.
            choices = "".join(_button_form(csrf, view, CommandKind.CHOOSE_EVENT,
                                           tr("Diesen Termin meinen: {label}", label=label),
                                           "", candidate=str(index))
                              for index, label in enumerate(view.calendar_candidates))
            parts.append(f'<div class="actions">{choices}</div>')
        if view.reconciliation_required:
            # 5.0.3: decided by an explicit assignment, never by a text answer.
            parts.append(
                notice(
                    tr(_PROPOSAL_ACTIONS_TEXT_1),
                    "warn",
                )
                + '<p class="card-links"><a class="button primary" href="'
                + e(focus_link(view.mail_id, view.proposal_id))
                + '">'
                + tr("Im Vorschlagsabgleich entscheiden")
                + "</a></p>"
            )
        if CommandKind.ANSWER in view.actions and view.question:
            parts.append(_answer(csrf, view))
        buttons = []
        if CommandKind.RECHECK in view.actions:
            # A failed duplicate check blocks confirmation until it ran successfully.
            buttons.append(
                _button_form(csrf, view, CommandKind.RECHECK, msg("Dublettenprüfung wiederholen"), "primary")
            )
        if CommandKind.CONFIRM in view.actions:
            buttons.append(_button_form(csrf, view, CommandKind.CONFIRM, view.confirm_label, "primary"))
        # Every open proposal with actions can be rejected.
        buttons.append(_button_form(csrf, view, CommandKind.REJECT, msg("Verwerfen"), "danger"))
        buttons.append(_button_form(csrf, view, CommandKind.ALREADY_DONE, tr("Schon erledigt"), ""))
        if CommandKind.CANCEL_CLARIFICATION in view.actions:
            buttons.append(_button_form(csrf, view, CommandKind.CANCEL_CLARIFICATION,
                                        tr("Bearbeitung beenden"), ""))
        # 5.0.8: the decision row stays at the bottom edge of the detail pane while scrolling.
        # 6.3: without a confirmation the swipe to the right names what has to happen first.
        blocked = "" if CommandKind.CONFIRM in view.actions else f' data-swipe-blocked="{e(swipe_blocked(view))}"'
        parts.append(f'<div class="actions decision-bar"{blocked}>{"".join(buttons)}</div>')
        parts.append(_decision_help(view))
        if CommandKind.ANSWER in view.actions and not view.question:
            parts.append(f"<details><summary>{tr('Ändern')}</summary>{_answer(csrf, view, change=True)}</details>")
        return "".join(parts)

    return render


def _decision_help(view: ProposalView) -> str:
    help_items = []
    if CommandKind.CONFIRM in view.actions:
        help_items.append(f"<p><strong>{e(view.confirm_label)}</strong>: "
                          f"{tr('Legt den Eintrag beim Anbieter an.')}</p>")
    help_items.append(
        f"<p><strong>{msg('Verwerfen')}</strong>: {tr('Lehnt diesen Vorschlag ab; es wird nichts angelegt.')}</p>"
    )
    help_items.append(f"<p><strong>{tr('Schon erledigt')}</strong>: "
                      f"{tr('Relevant, aber bereits erledigt; es wird kein neuer Eintrag angelegt.')}</p>")
    return (
        f'<details class="decision-help"><summary>{tr("Was bedeuten diese Entscheidungen?")}</summary>'
        f"{''.join(help_items)}</details>"
    )


SWIPE_BLOCKED_DEFAULT = msg("Diese Aktion ist für diesen Vorgang nicht möglich.")


def swipe_blocked(view: ProposalView) -> str:
    """6.3: why a proposal without a confirmation cannot be swiped to the right, as a whole sentence."""
    if CommandKind.CHOOSE_VARIANT in view.actions:
        return tr("Erst den Widerspruch klären.")
    if CommandKind.ANSWER in view.actions and view.question:
        return tr("Erst die Rückfrage beantworten.")
    if view.reconciliation_required:
        return tr("Erst im Vorschlagsabgleich entscheiden.")
    if CommandKind.RECHECK in view.actions:
        return tr("Erst die Dublettenprüfung wiederholen.")
    if CommandKind.CHOOSE_EVENT in view.actions:
        return tr("Erst den gemeinten Termin wählen.")
    return tr(SWIPE_BLOCKED_DEFAULT)


def verification_block(csrf: str, view: ProposalView) -> str:
    """5.2: the check of a written entry with an expected/actual table and a read-only recheck."""
    item = view.verification
    assert item is not None
    detail = f'<p class="meta">{e(stored(item.detail))}</p>' if item.detail else ""
    table = ""
    if item.differences:
        rows = "".join(f"<tr><th scope=\"row\">{e(stored(label))}</th><td>{e(expected)}</td><td>{e(actual)}</td></tr>"
                       for label, expected, actual in item.differences)
        table = (
            f'<table class="verification-diff"><thead><tr><th scope="col">{tr("Angabe")}</th>'
            f'<th scope="col">{msg("Bestätigt")}</th><th scope="col">{tr("Beim Anbieter")}</th></tr></thead>'
            f"<tbody>{rows}</tbody></table>"
        )
    button = ""
    if CommandKind.VERIFY_ENTRY in view.actions:
        button = ('<div class="actions">'
                  + _button_form(csrf, view, CommandKind.VERIFY_ENTRY, tr("Erneut prüfen"), "")
                  + '</div><p class="meta">'
                  + tr("Liest den Eintrag nur erneut; es wird nichts geändert oder angelegt.")
                  + "</p>")
    return (f'<div class="verification verification-{e(item.state.value)}">'
            f"<p><strong>{e(stored(item.title))}</strong></p>{detail}{table}{button}</div>")


def _answer(csrf: str, view: ProposalView, change: bool = False) -> str:
    field = 'antwort-{p0}-{p1}'.format(p0=f'{view.mail_id}', p1=f'{view.proposal_id}')
    question = tr("Was soll geändert werden?") if change else view.question
    example = tr("„Titel: Elternabend“ oder „Ort: Raum 3“") if change else view.example
    hint = f'<p class="meta">{e(tr("z. B. {example}", example=example))}</p>' if example else ""
    quick = ""
    if view.yes_no:
        quick = (
            '<div class="quick">'
            + _button_form(csrf, view, CommandKind.ANSWER, tr("Ja"), "primary", text="ja")
            + _button_form(csrf, view, CommandKind.ANSWER, msg("Nein"), "", text="nein")
            + "</div>"
        )
    hidden = _hidden(csrf, CommandKind.ANSWER, view.mail_id, view.version, view.proposal_id)
    return f"""<div class="answer">
<label for="{e(field)}">{e(question)}</label>{hint}{quick}
<form method="post" action="/aktion" class="stack">{hidden}
<textarea id="{e(field)}" name="text" maxlength="4000" required rows="2"></textarea>
<button class="button" type="submit">{tr("Antwort senden")}</button>
</form>
</div>"""


def recheck_form(csrf: str, mail_id: str, analysis_round: int, *, small: bool = False) -> str:
    """Analyse a mail filed as irrelevant again, e.g. after adding a topic (3.6.2)."""
    hidden = _hidden(csrf, CommandKind.RECHECK_MAIL, mail_id, analysis_round)
    size = " small" if small else ""
    return (f'<form method="post" action="/aktion" class="recheck">{hidden}'
            f'<button class="button{size}" type="submit">{tr("Erneut prüfen")}</button></form>')


def failure_forms(csrf: str, mail_id: str, analysis_round: int, *, retryable: bool,
                  back_to_list: bool = False) -> str:
    """7.3: retry or file a failed mail, from the failure list or its mail page; works without JavaScript."""
    extra = {"zurueck": 'fehlerliste'} if back_to_list else {}
    kinds = [(CommandKind.RETRY_MAIL, tr("Erneut versuchen"), "primary")] if retryable else []
    kinds.append((CommandKind.FILE_MAIL, tr("Ignorieren"), ""))
    return '<div class="actions">' + "".join(
        f'<form method="post" action="/aktion">{_hidden(csrf, kind, mail_id, analysis_round, **extra)}'
        f'<button class="button small {style}" type="submit">{label}</button></form>'
        for kind, label, style in kinds) + "</div>"


def relevance_actions(csrf: str) -> Callable[[RelevanceView], str]:
    def render(view: RelevanceView) -> str:
        forms = []
        for decision, label, style in (("relevant", tr("Relevant"), "primary"),
                                       ("irrelevant", tr("Irrelevant"), "")):
            hidden = _hidden(csrf, CommandKind.RELEVANCE, view.mail_id, view.version,
                             decision=decision)
            forms.append(f'<form method="post" action="/aktion">{hidden}'
                         f'<button class="button {style}" type="submit">{label}</button></form>')
        return (f'<div class="actions">{"".join(forms)}</div>'
                # 6.9 U5: collapsed, and unlike the proposal help it stays in the list (app.css).
                '<details class="decision-help relevance-help"><summary>'
                + tr("Was bedeuten diese Entscheidungen?") + '</summary>'
                '<p class="meta">' + tr('Relevant: Mail weiter auswerten. Irrelevant: nicht weiter auswerten. '
                                        'Die Entscheidung kann später zum Regellernen verwendet werden.')
                + '</p></details>')
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
        body = notice(tr("Wird ausgeführt … Danach geht es automatisch zur Übersicht."), "info")
        if entry.command.kind in {CommandKind.CONFIRM, CommandKind.CONFIRM_DUPLICATE} and current is not None:
            event = current.card.kind.value == "event"
            destination = tr("Kalender" if event else "Aufgabenliste (z. B. Todoist)")
            body += f"<p>{e(tr('Die Anlage im Ziel {target} kann einen Moment dauern.', target=destination))}</p>"
        return layout(tr("Aktion läuft"), f"<h1>{tr('Aktion läuft')}</h1>{body}"
                      f'<div data-command-status="/api/aktion/{entry.id}" role="status" aria-live="polite"></div>'
                      f'<p><a class="button" href="/">{tr("Zur Übersicht")}</a></p>'
                      '<noscript><meta http-equiv="refresh" content="1"></noscript>')
    assert entry.result is not None
    result = entry.result
    # Every other result returns to the overview; only this one needs a choice.
    assert needs_choice(entry, current) and current is not None
    parts = [notice(result.message, _RESULT_KIND[result.status]),
             f"<p>{e(tr('„{title}“ wurde schon einmal angelegt.', title=current.card.title))}</p>",
             '<div class="actions">'
             + _button_form(csrf, current, CommandKind.CONFIRM_DUPLICATE, tr("Erneut anlegen"), "primary")
             + _button_form(csrf, current, CommandKind.REJECT, tr("Nicht erneut anlegen"), "")
             + "</div>"]
    parts.append(f'<p><a class="button" href="/">{tr("Zur Übersicht")}</a></p>')
    return layout(msg("Ergebnis"), f"<h1>{msg('Ergebnis')}</h1>" + "".join(parts))


def reject_reason_block(csrf: str, mail_id: str, proposal_id: str, version: int,
                        current_reason: str | None = None) -> str:
    """6.5.2: five reason buttons on the result card or detail page of a rejected proposal."""
    buttons = []
    for code, label in USER_REJECT_REASONS:
        selected = code == current_reason
        style = "small primary" if selected else "small"
        aria = ' aria-pressed="true"' if selected else ""
        hidden = _hidden(csrf, CommandKind.REJECT_REASON, mail_id, version, proposal_id, reason=code)
        buttons.append(f'<form method="post" action="/aktion">{hidden}'
                       f'<button class="button {style}" type="submit"{aria}>{e(tr(label))}</button></form>')
    hint = ""
    if current_reason:
        saved = tr("gespeichert: {reason}", reason=tr(REJECT_REASONS.get(current_reason, current_reason)))
        hint = f' <span class="meta">({e(saved)})</span>'
    return (f'<div class="reject-reasons"><p class="meta"><strong>{tr("Verworfen. Warum?")}</strong>'
            f' {tr("(freiwillig, verbessert künftige Vorschläge)")}{hint}</p>'
            f'<div class="actions reject-reasons-actions">{"".join(buttons)}</div></div>')


def stale_page(message: str, current: ProposalView | None) -> str:
    detail = (f'<p>{e(tr("Aktueller Stand: Version {number} – {state}.", number=current.version, state=current.state))}'
              '</p>'
              if current is not None else "")
    return layout(tr("Veraltet"), f"""<h1>{tr("Nicht mehr aktuell")}</h1>
{notice(message, "warn")}{detail}
<p><a class="button primary" href="/">{tr("Aktuellen Stand anzeigen")}</a></p>""")


def confirm_remove_page(view: ProposalView, csrf: str) -> str:
    """Bestätigungsseite für das Entfernen eines angelegten Eintrags (Planung 6.6 / D3)."""
    event = view.card.kind == ProposalKind.EVENT
    target_name = tr("Kalender" if event else "Aufgaben")
    explanation = tr(
        "Der Eintrag wird im Kalender gelöscht. Der Vorschlag bleibt als ‚wieder entfernt‘ im Verlauf."
        if event
        else "Der Eintrag wird in den Aufgaben gelöscht. Der Vorschlag bleibt als ‚wieder entfernt‘ im Verlauf."
    )
    time_val = view.card.when if event else view.card.due
    time_line = f'<p class="meta">{e(tr("Zeit: {value}", value=time_val))}</p>' if time_val else ""
    hidden = _hidden(csrf, CommandKind.REMOVE_CREATED, view.mail_id, view.version, view.proposal_id)
    form = (
        f'<form method="post" action="/aktion">{hidden}'
        f'<div class="actions">'
        f'<button class="button danger" type="submit">{tr("Eintrag wirklich entfernen")}</button>'
        f'<a class="button" href="/vorschlag/{e(view.mail_id)}/{e(view.proposal_id)}">{tr("Abbrechen")}</a>'
        f'</div></form>'
    )
    content = (
        f'<p><a href="/vorschlag/{e(view.mail_id)}/{e(view.proposal_id)}">← {tr("Zurück zum Vorschlag")}</a></p>'
        f'<h1>{tr("Eintrag wieder entfernen")}</h1>'
        f'<div class="card">'
        f'<h2>{e(view.card.title)}</h2>'
        f'{time_line}'
        f'<p class="meta">{e(tr("Ziel: {target}", target=target_name))}</p>'
        f'<div class="notice warn"><p>{e(explanation)}</p></div>'
        f'{form}'
        f'</div>'
    )
    return layout(tr("Eintrag entfernen"), content)


__all__ = ["command_page", "confirm_remove_page", "needs_choice", "new_key", "proposal_actions", "relevance_actions",
           "reject_reason_block", "result_kind", "stale_page"]
