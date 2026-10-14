"""Deterministic editing of an open proposal; saving creates a new unconfirmed version."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .. import state_names
from ..models import Proposal, ProposalStatus
from ..review.commands import CommandKind, CommandSource, ReviewCommand
from ..review.editing import ProposalEditPatch
from .forms import field, post_form
from .history_site import PROPOSAL_PATH
from .http import Response
from .pages import layout, notice

if TYPE_CHECKING:
    from .archive_site import ArchiveSite

EDIT_LABELS = {"title": "Titel", "description": "Beschreibung", "target": "Ziel", "due": "Frist",
               "start": "Beginn", "end": "Ende", "all_day": "Ganztägig (true/false)", "location": "Ort",
               "video_link": "Videolink (HTTPS)", "meeting_mode": "Teilnahmeart"}


class ProposalEditSite:
    def __init__(self, archive: ArchiveSite):
        self.archive, self.site = archive, archive.site
        for method, handler in (("GET", self.edit), ("POST", self.save_edit)):
            self.site.app.route(method, PROPOSAL_PATH + "/bearbeiten", self.site.signed_in(handler))

    def edit(self, request, session, mail_id, proposal_id, values=None, message=""):
        proposal = self.site.views.store.peek_model(state_names.proposal(mail_id, proposal_id), Proposal)
        if proposal is None:
            return self.site._reply(request, 404, "Vorschlag nicht gefunden.")
        if proposal.status not in {ProposalStatus.PENDING_CONFIRMATION, ProposalStatus.NEEDS_CLARIFICATION}:
            return self.site._reply(request, 409, "Nur offene Vorschläge sind bearbeitbar.")
        names = ["title", "description", "target"] + (["due"] if proposal.kind.value == "task" else
                 ["start", "end", "all_day", "location", "video_link", "meeting_mode"])
        data = values if values is not None else proposal.model_dump(mode="json")
        body = ('<h1>Vorschlag bearbeiten</h1><p>Zeiten als ISO-Datum oder ISO-Datum mit Uhrzeit eingeben. '
                'Bei Zeitumstellungen UTC-Offset angeben. Speichern legt nichts extern an.</p>')
        body += notice(message, "warn") if message else ""
        inputs = "".join(field(name, EDIT_LABELS[name], data.get(name) or "") for name in names)
        body += post_form(request.path, self.site.auth.csrf_token(session.id), inputs, version=proposal.version)
        return Response.html(422 if message else 200, layout("Bearbeiten", body))

    def save_edit(self, request, session, form, mail_id, proposal_id):
        try:
            raw = {key: value for key, value in form.items() if key not in {"csrf", "key", "version"}}
            if "all_day" in raw:
                raw["all_day"] = {"true": True, "false": False, "": False}[raw["all_day"].lower()]
            patch = ProposalEditPatch.model_validate(raw)
            command = ReviewCommand(kind=CommandKind.EDIT, source=CommandSource.WEB, actor=f"web:{session.id}",
                                    idempotency_key=form["key"], mail_id=mail_id, proposal_id=proposal_id,
                                    version=int(form["version"]), patch=patch)
        except (ValueError, KeyError):
            return self.edit(request, session, mail_id, proposal_id, form, "Ungültige Eingaben; bitte prüfen.")
        stale = self.site._stale(command)
        if stale is not None and not any(entry.command == command for entry in self.site.commands._entries()):
            return self.site._reply(request, 409, stale)
        return self.archive.queue(request, command)
