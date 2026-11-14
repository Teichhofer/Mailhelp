"""Durable command feedback shared by every paired device of the same person."""
from __future__ import annotations

from collections.abc import Callable

from ..review.commands import CommandKind, ReviewCommand
from ..review.inbox import CommandEntry, CommandStatus
from ..review.incoming import requires_ack
from ..review.results import ResultStatus
from ..review.views import ProposalView, RelevanceView
from .actions import _button_form, needs_choice, proposal_actions, reject_reason_block, relevance_actions, result_kind
from .pages import e, notice


def visible(entry: CommandEntry, actor: str) -> bool:
    return entry.command.source.value == "web" and (
        isinstance(entry.command, ReviewCommand) or entry.command.actor == actor)


def anchor(entry: CommandEntry) -> str:
    command = entry.command
    assert isinstance(command, ReviewCommand)
    return f"v-{command.mail_id}-{command.proposal_id}" if command.proposal_id else f"r-{command.mail_id}"


def feedback(entry: CommandEntry, csrf: str, refresh: str) -> str:
    if entry.status in {CommandStatus.QUEUED, CommandStatus.RUNNING}:
        # An explicit target without fragment: refreshing to the current URL with its
        # card anchor would only scroll within the page instead of reloading it.
        return (f'<div data-card-command-status="/api/aktion/{entry.id}" role="status" aria-live="polite">'
                'Wird verarbeitet …</div><noscript>'
                f'<meta http-equiv="refresh" content="1; url={e(refresh)}"></noscript>')
    assert entry.result is not None
    content = '<div data-command-result>' + notice(entry.result.message, result_kind(entry.result.status)) + '</div>'
    if requires_ack(entry):
        content = '<div role="alert">' + content + (
            f'<form method="post" action="/aktion/{entry.id}/gesehen">'
            f'<input type="hidden" name="csrf" value="{e(csrf)}">'
            '<button class="button small" type="submit">Zur Kenntnis genommen</button></form></div>')
    return content


class CommandCards:
    def __init__(self, entries: list[CommandEntry], csrf: str, refresh: str,
                 sender_hint_lookup: Callable[[str], Any] | None = None,
                 views: Any | None = None):
        self.entries = [entry for entry in entries if isinstance(entry.command, ReviewCommand)
                        and entry.command.source.value == "web" and not entry.acknowledged]
        self.csrf, self.refresh = csrf, refresh
        self.sender_hint_lookup = sender_hint_lookup
        self.views = views

    def matching(self, mail_id: str, proposal_id: str | None) -> list[CommandEntry]:
        result = []
        for entry in self.entries:
            command = entry.command
            assert isinstance(command, ReviewCommand)
            members: set[str | None] = {item.proposal_id for item in command.members}
            if not members:
                members.add(command.proposal_id)
            if command.mail_id == mail_id and proposal_id in members:
                result.append(entry)
        return result

    def render(self, entries: list[CommandEntry], actions: Callable[[], str]) -> str:
        pending = next((entry for entry in entries if entry.result is None), None)
        if pending is not None:
            return feedback(pending, self.csrf, self.refresh)
        errors = [entry for entry in entries if requires_ack(entry)]
        shown = errors + [entry for entry in entries[-1:] if entry not in errors]
        return ''.join(feedback(entry, self.csrf, self.refresh) for entry in shown) + actions()

    def proposal(self, view: ProposalView) -> str:
        entries = self.matching(view.mail_id, view.proposal_id)
        def actions() -> str:
            if entries and needs_choice(entries[-1], view):
                return ('<div class="actions">'
                        + _button_form(self.csrf, view, CommandKind.CONFIRM_DUPLICATE, "Erneut anlegen", "primary")
                        + _button_form(self.csrf, view, CommandKind.REJECT, "Nicht erneut anlegen", "") + '</div>')
            return proposal_actions(self.csrf)(view)
        return self.render(entries, actions)

    def relevance(self, view: RelevanceView) -> str:
        return self.render(self.matching(view.mail_id, None), lambda: relevance_actions(self.csrf)(view))

    def _detached_actions(self, entry: CommandEntry) -> str:
        command = entry.command
        if (isinstance(command, ReviewCommand)
                and command.kind in {CommandKind.REJECT, CommandKind.REJECT_REASON}
                and entry.result is not None
                and entry.result.status == ResultStatus.DONE
                and command.proposal_id is not None):
            current_reason = command.reason if command.kind == CommandKind.REJECT_REASON else None
            parts = [reject_reason_block(self.csrf, command.mail_id, command.proposal_id, command.version, current_reason)]
            if self.sender_hint_lookup is not None:
                hint = self.sender_hint_lookup(command.mail_id)
                if hint is not None:
                    from urllib.parse import quote
                    parts.append(
                        f'<div class="sender-hint-notice notice warn" data-sender-hint>'
                        f'<p>{e(hint.trigger_sentence)}</p>'
                        f'<p class="card-links"><a class="button primary small" href="/lernen/absender-hinweis?sender={quote(hint.sender)}">Ansehen</a></p>'
                        f'</div>'
                    )
            return "".join(parts)
        if (isinstance(command, ReviewCommand)
                and command.kind == CommandKind.CONFIRM
                and entry.result is not None
                and entry.result.status in {ResultStatus.DONE, ResultStatus.WRITTEN}
                and command.proposal_id is not None
                and self.views is not None):
            view = self.views.proposal(command.mail_id, command.proposal_id)
            if view is not None and view.can_remove:
                return (f'<p class="card-links"><a class="button" '
                        f'href="/vorschlag/{e(command.mail_id)}/{e(command.proposal_id)}/entfernen">'
                        f'Eintrag wieder entfernen</a></p>')
        return ""

    def detached(self, references: set[tuple[str, str | None]]) -> str:
        """Keep outcomes visible when a decision removed the original open card."""
        parts = []
        grouped: dict[tuple[str, str | None], list[CommandEntry]] = {}
        for entry in self.entries:
            command = entry.command
            assert isinstance(command, ReviewCommand)
            reference = (command.mail_id, command.proposal_id)
            if reference not in references:
                grouped.setdefault(reference, []).append(entry)
        for entries in grouped.values():
            entry = entries[-1]
            command = entry.command
            assert isinstance(command, ReviewCommand)
            link = (f'/vorschlag/{command.mail_id}/{command.proposal_id}' if command.proposal_id
                    else f'/mail/{command.mail_id}')
            parts.append(f'<article class="card" id="{anchor(entry)}"><h2>Deine Aktion</h2>'
                         + self.render(entries, lambda e=entry: self._detached_actions(e))
                         + f'<p class="card-links"><a data-detail href="{link}">Details</a></p></article>')
        return ''.join(parts)
