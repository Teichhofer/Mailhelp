"""7.3.3: retry or ignore every failed mail at once, after a confirmation that names the count.

The confirmation page binds the batch to exactly the mails and analysis rounds the user saw. Each
mail then gets its own version-bound command through the normal queue: a mail changed or processed
meanwhile is skipped as stale, a repeated submission is recognised by its key, and nothing new is
needed at the execution boundary.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs

from ..i18n import msg, tr
from ..review.commands import CommandKind, CommandSource, ReviewCommand
from ..review.inbox import CommandConflict, CommandInboxFull
from .auth import WebSession
from .forms import post_form
from .http import Request, Response
from .pages import e, layout, notice

if TYPE_CHECKING:
    from .archive_site import ArchiveSite

PATH = "/mails/fehler/alle"
MAX_BATCH = 200
ACTIONS = {
    "retry": (
        CommandKind.RETRY_MAIL,
        msg("Alle erneut versuchen"),
        msg("Möchtest du alle {n} fehlgeschlagenen Mails erneut zur Verarbeitung einreihen?"),
    ),
    "ignore": (
        CommandKind.FILE_MAIL,
        msg("Alle ignorieren"),
        msg("Möchtest du alle {n} fehlgeschlagenen Mails als nicht verarbeitet ablegen?"),
    ),
}
_ENTRY = re.compile(r"^([a-f0-9]{24}):(\d{1,9})$")


def batch_links(items: list[dict[str, Any]]) -> str:
    """The two batch actions above a non-empty failure list."""
    if not any(item["failed"] for item in items):
        return ""
    return ('<p class="actions">' + "".join(
        f'<a class="button small" href="{PATH}?aktion={action}">{label}</a>'
        for action, (_kind, label, _question) in ACTIONS.items()) + "</p>")


class FailureBatchSite:
    def __init__(self, archive: ArchiveSite) -> None:
        self.archive, self.site = archive, archive.site
        self.site.app.route("GET", PATH, self.site.signed_in(self.confirm))
        self.site.app.route("POST", PATH, self.site.signed_in(self.run))

    def _targets(self, action: str) -> list[dict[str, Any]]:
        """Every failed mail the action applies to: a retry skips requested and non-retryable ones."""
        return [item for item in self.archive.queries.items() if item["failed"] and (
            action == "ignore" or item["retryable"] and not item["retry_pending"])][:MAX_BATCH]

    def confirm(self, request: Request, session: WebSession) -> Response:
        action = parse_qs(request.query, max_num_fields=2).get("aktion", [""])[0]
        if action not in ACTIONS:
            return self.site._reply(request, 422, "Unbekannte Sammelaktion.")
        _kind, label, question = ACTIONS[action]
        targets = self._targets(action)
        if not targets:
            body = notice(tr("Keine fehlgeschlagene Mail ist für diese Aktion offen."), "info")
        else:
            listed = "".join(f"<li>{e(item['subject'])}</li>" for item in targets[:20])
            more = tr('<p class="meta">… und {p0} weitere.</p>', p0=len(targets) - 20) if len(targets) > 20 else ""
            body = (f"<p>{e(question.format(n=len(targets)))}</p><ul>{listed}</ul>{more}"
                    + post_form(PATH, self.site.auth.csrf_token(session.id), "", label, primary=True,
                                aktion=action,
                                mails=",".join(f"{item['id']}:{item['analysis_round']}" for item in targets)))
        body += tr('<p><a href="/mails?state=failed">Zurück zur Fehlerliste</a></p>')
        return Response.html(200, layout(label, f"<h1>{e(label)}</h1>{body}", active="/mails"))

    def run(self, request: Request, session: WebSession, form: dict[str, str]) -> Response:
        action, key = form.get("aktion", ""), form.get("key", "")
        entries = [_ENTRY.match(value) for value in form.get("mails", "").split(",") if value]
        if (
            action not in ACTIONS
            or not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", key)
            or not entries
            or len(entries) > MAX_BATCH
            or not all(entries)
        ):
            return self.site._reply(request, 422, msg("Die Sammelaktion ist unvollständig oder ungültig."))
        kind, queued = ACTIONS[action][0], 0
        for index, match in enumerate(entry for entry in entries if entry is not None):
            mail_id, version = match.group(1), int(match.group(2))
            command = ReviewCommand(kind=kind, source=CommandSource.WEB, actor=f"web:{session.id}",
                                    mail_id=mail_id, version=version, idempotency_key=f"{key}-{index}")
            if self.site._stale(command) is not None:
                continue  # changed or already handled since the confirmation
            try:
                _entry, new = self.site.commands.submit(command)
            except (CommandConflict, CommandInboxFull):
                break
            queued += new  # a repeated batch finds its commands and queues nothing twice
        return Response.redirect(
            '/mails?state=failed&eingereiht={p0}&von={p1}'.format(p0=f'{queued}', p1=f'{len(entries)}')
        )
