"""Read-only previews and queued, version-bound local reconciliation commands."""
from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs

from .. import state_names
from ..config import EventDefaultsSettings
from ..domain.proposal import Proposal
from ..domain.proposal_sources import ProposalReference, ProposalRelation
from ..models import MailState
from ..proposals.event_defaults import reapply_defaults
from ..proposals.proposal_matching import compatible, relationship
from ..proposals.proposal_reconciliation import OPEN, ProposalReconciliationService
from ..review.commands import CommandKind, CommandSource, ReviewCommand
from ..storage import CorruptState
from .auth import WebSession
from .http import Request, Response
from .pages import layout
from .reconciliation_pages import (
    ALL_LINK,
    FOCUS_INTRO,
    INTRO,
    comparison,
    defaults_offer,
    focus_missing,
    mail_summary,
    missing_record,
    no_comparison,
    proposal_row,
    section_head,
    sources_fragment,
)

if TYPE_CHECKING:
    from .site import MailhelpSite


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()



def grouped(parts: list[str]) -> str:
    """Consecutive rows share one list; cards stand between them in their original order."""
    body, rows = "", ""
    for part in parts:
        if part.startswith("<li"):
            rows += part
            continue
        body += (f'<ul class="row-list">{rows}</ul>' if rows else "") + part
        rows = ""
    return body + (f'<ul class="row-list">{rows}</ul>' if rows else "")

class ReconciliationSite:
    def __init__(self, site: MailhelpSite):
        self.site = site
        self.service = ProposalReconciliationService(site.views.store)
        for method, path, handler in (("GET", "/abgleich", self.preview), ("POST", "/abgleich", self.apply)):
            site.app.route(method, path, site.signed_in(handler))

    def defaults(self, proposal: Proposal | None = None) -> EventDefaultsSettings:
        configuration = self.site.archive.configuration
        if configuration and proposal is not None:
            from ..mailbox.mailbox_settings import event_defaults_for
            found: EventDefaultsSettings = event_defaults_for(configuration.active, self.site.views.store, proposal,
                                                              self.site.views.mailboxes)
            return found
        return configuration.active.event_defaults if configuration else EventDefaultsSettings()

    def fragment(self, mail_id: str, proposal_id: str) -> str:
        store = self.site.views.store
        proposal = store.peek_model(f"proposal-{mail_id}-{proposal_id}", Proposal)
        if proposal is None:
            return ""
        return sources_fragment(proposal, self._linked(mail_id, proposal_id), self.site.configured_timezone)

    def _linked(self, mail_id: str, proposal_id: str) -> list[Proposal]:
        """Proposals related to this one by a stored relation, in either direction."""
        store, ref = self.site.views.store, ProposalReference(mail_id=mail_id, proposal_id=proposal_id)
        linked: list[Proposal] = []
        for name in store.names("reconciliation-relation-"):
            relation = store.peek_model(name, ProposalRelation)
            if relation is None:
                raise ValueError("Verknüpfung inzwischen geändert")
            if ref not in (relation.source, relation.target):
                continue
            other = self.service.resolve(relation.target if relation.source == ref else relation.source)
            if other is not None:
                linked.append(other)
        return linked

    def mail_summary(self, mail_id: str) -> str:
        store = self.site.views.store
        mail = store.peek_model(f"mail-{mail_id}", MailState)
        if mail is None:
            return ""
        other_profile = False
        if mail.duplicate is not None:
            previous = store.peek_model(f"mail-{mail.duplicate.previous_mail_id}", MailState)
            other_profile = previous is not None and (previous.proposal_policy or {}).get("target_profile", 1) != (
                mail.proposal_policy or {}).get("target_profile", 1)
        return mail_summary(mail, other_profile)

    def preview(self, request: Request, session: WebSession) -> Response:
        try:
            items = self.service.current()
            csrf = self.site.auth.csrf_token(session.id)
            query = parse_qs(request.query, max_num_fields=20)
            if "mail" in query and "vorschlag" in query:
                body = self._focus(query["mail"][0], query["vorschlag"][0], items, csrf)
            else:
                body = INTRO + grouped([self._proposal_section(item, items, csrf) for item in items])
                body += self._missing_records(items, csrf)
            return Response.html(200, layout("Vorschlagsabgleich", body + '</div>'))
        except (CorruptState, ValueError):
            return self.site._reply(request, 409, "Bestand beschädigt oder inzwischen geändert; Abgleich blockiert.")

    def _focus(self, mail_id: str, proposal_id: str, items: list[Proposal], csrf: str) -> str:
        """5.0.5: only the proposal from the card and the candidates it is compared with."""
        found = [item for item in items if (item.source_mail_id, item.id) == (mail_id, proposal_id)]
        if not found:
            return FOCUS_INTRO + focus_missing()
        return FOCUS_INTRO + self._proposal_section(found[0], items, csrf, focused=True) + ALL_LINK

    def _proposal_section(self, item: Proposal, items: list[Proposal], csrf: str, focused: bool = False) -> str:
        """A card with comparisons and offers; without any of them one row of a list (6.2.7)."""
        defaults = self.defaults(item)
        zone = self.site.configured_timezone
        targets = [target for target in self._targets(item, items) if target is not None]
        extra = "".join(comparison(item, target, zone, csrf, self._origin) for target in targets)
        if focused and not targets:
            extra += no_comparison()
        if item.status in OPEN:
            candidate = reapply_defaults(item, defaults)
            if candidate.version != item.version:
                extra += defaults_offer(item, candidate, digest(defaults.model_dump()), zone, csrf)
        if not extra and not (item.duplicate_check_failed and item.status in OPEN):
            return proposal_row(item)
        return section_head(item, csrf) + extra + '</section>'

    def _origin(self, proposal: Proposal) -> str:
        """Sender and subject of the mail a proposal came from, as shown on its card."""
        mail = self.site.views.store.peek_model(f"mail-{proposal.source_mail_id}", MailState)
        if mail is None or mail.display_headers is None:
            return "Herkunftsmail nicht mehr gespeichert"
        return f"{mail.display_headers.sender} · {mail.display_headers.subject}"

    def _targets(self, item: Proposal, items: list[Proposal]) -> list[Proposal | None]:
        """The canonical proposal of an unchecked addition, or the open matching candidates."""
        if item.merge_review_required:
            assert item.canonical_ref is not None
            return [self.service.resolve(item.canonical_ref)]
        if item.status not in OPEN:
            return []
        remembered = {(r.mail_id, r.proposal_id) for r in item.matching_candidates}
        return [p for p in items if compatible(item, p) and (
                (p.source_mail_id, p.id) in remembered or p.status in OPEN
                and relationship(self.service.store, item, p) != "different")]

    def _missing_records(self, items: list[Proposal], csrf: str) -> str:
        """Findings stored in a mail state whose separate proposal file is missing."""
        known = {(p.source_mail_id, p.id) for p in items}
        body = ""
        for name in state_names.mail_state_names(self.site.views.store):
            mail = self.site.views.store.peek_model(name, MailState)
            if mail is None:
                raise ValueError("Mailzustand fehlt")
            body += "".join(missing_record(item, digest(item.model_dump(mode="json")), csrf)
                            for item in mail.proposals if (item.source_mail_id, item.id) not in known)
        return body

    def apply(self, request: Request, session: WebSession, form: dict[str, str]) -> Response:
        try:
            target = (ProposalReference(mail_id=form['target_mail_id'], proposal_id=form['target_proposal_id'])
                      if 'target_mail_id' in form else None)
            command = ReviewCommand(kind=form['kind'], source=CommandSource.WEB, actor=f"web:{session.id}",
                mail_id=form['mail_id'], proposal_id=form['proposal_id'], version=int(form['version']),
                idempotency_key=form['key'], target_ref=target,
                target_version=int(form['target_version']) if target is not None else None,
                proposal_hash=form.get('proposal_hash'))
            if command.kind not in {CommandKind.MERGE, CommandKind.SEPARATE, CommandKind.RESTORE,
                                    CommandKind.DEFAULTS, CommandKind.RECHECK}:
                raise ValueError("Ungültiger Abgleichbefehl")
        except (ValueError, KeyError):
            return self.site._reply(request, 422, "Ungültiger Abgleichbefehl oder Versionsstand.")
        return self.site.archive.queue(request, command)
