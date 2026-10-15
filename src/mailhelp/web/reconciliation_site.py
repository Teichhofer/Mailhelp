"""Read-only previews and queued, version-bound local reconciliation commands."""
import hashlib
import json

from .. import state_names
from ..config import EventDefaultsSettings
from ..domain.proposal import Proposal
from ..domain.proposal_sources import ProposalReference, ProposalRelation
from ..event_defaults import reapply_defaults
from ..models import MailState
from ..proposal_matching import compatible, relationship
from ..proposal_reconciliation import OPEN, ProposalReconciliationService
from ..review.commands import CommandKind, CommandSource, ReviewCommand
from ..storage import CorruptState
from .http import Response
from .pages import layout
from .reconciliation_pages import (
    INTRO,
    comparison,
    defaults_offer,
    mail_summary,
    missing_record,
    section_head,
    sources_fragment,
)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


class ReconciliationSite:
    def __init__(self, site):
        self.site = site
        self.service = ProposalReconciliationService(site.views.store)
        for method, path, handler in (("GET", "/abgleich", self.preview), ("POST", "/abgleich", self.apply)):
            site.app.route(method, path, site.signed_in(handler))

    def defaults(self, proposal=None):
        configuration = self.site.archive.configuration
        if configuration and proposal is not None:
            from ..mailbox_settings import event_defaults_for
            return event_defaults_for(configuration.active, self.site.views.store, proposal, self.site.views.mailboxes)
        return configuration.active.event_defaults if configuration else EventDefaultsSettings()

    def fragment(self, mail_id, proposal_id):
        store = self.site.views.store
        proposal = store.peek_model(f"proposal-{mail_id}-{proposal_id}", Proposal)
        if proposal is None:
            return ""
        return sources_fragment(proposal, self._linked(mail_id, proposal_id), self.site.configured_timezone)

    def _linked(self, mail_id, proposal_id):
        """Proposals related to this one by a stored relation, in either direction."""
        store, ref = self.site.views.store, ProposalReference(mail_id=mail_id, proposal_id=proposal_id)
        linked = []
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

    def mail_summary(self, mail_id):
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

    def preview(self, request, session):
        try:
            items = self.service.current()
            csrf = self.site.auth.csrf_token(session.id)
            body = INTRO + "".join(self._proposal_section(item, items, csrf) for item in items)
            body += self._missing_records(items, csrf)
            return Response.html(200, layout("Vorschlagsabgleich", body + '</div>'))
        except (CorruptState, ValueError):
            return self.site._reply(request, 409, "Bestand beschädigt oder inzwischen geändert; Abgleich blockiert.")

    def _proposal_section(self, item, items, csrf):
        defaults = self.defaults(item)
        zone = self.site.configured_timezone
        body = section_head(item, csrf)
        body += "".join(comparison(item, target, zone, csrf)
                        for target in self._targets(item, items) if target is not None)
        if item.status in OPEN:
            candidate = reapply_defaults(item, defaults)
            if candidate.version != item.version:
                body += defaults_offer(item, candidate, digest(defaults.model_dump()), zone, csrf)
        return body + '</section>'

    def _targets(self, item, items):
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

    def _missing_records(self, items, csrf):
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

    def apply(self, request, session, form):
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
