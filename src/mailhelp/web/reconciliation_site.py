"""Read-only previews and queued, version-bound local reconciliation commands."""
import hashlib
import json

from .. import state_names
from ..config import EventDefaultsSettings
from ..domain.proposal import Proposal
from ..domain.proposal_sources import ProposalReference, ProposalRelation
from ..event_defaults import reapply_defaults
from ..external.providers import CALENDAR_LABELS, TASK_LABELS
from ..models import MailState
from ..proposal_matching import compatible, relationship
from ..proposal_reconciliation import OPEN, ProposalReconciliationService
from ..review.cards import event_time
from ..review.commands import CommandKind, CommandSource, ReviewCommand
from ..review.views import STATUS_LABELS
from ..storage import CorruptState
from .http import Response
from .pages import e, layout
from .setup_site import post_form


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def proposal_link(proposal):
    return f"/vorschlag/{proposal.source_mail_id}/{proposal.id}"


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
        body = '<section><h2>Quellen und zugehörige Vorgänge</h2><ul>'
        for source in proposal.sources:
            body += (f'<li><a href="/mail/{e(source.mail_id)}">Quellenmail</a> · {e(source.subject)} '
                     f'· {e(source.sent_at or "Zeit nicht mehr gespeichert")}</li>')
        for name in store.names("reconciliation-relation-"):
            relation = store.peek_model(name, ProposalRelation)
            if relation is None:
                raise ValueError("Verknüpfung inzwischen geändert")
            ref = ProposalReference(mail_id=mail_id, proposal_id=proposal_id)
            if relation.source == ref:
                other = relation.target
            elif relation.target == ref:
                other = relation.source
            else:
                continue
            linked = self.service.resolve(other)
            if linked is not None:
                status = "bereits im Kalender/bei den Aufgaben" if linked.status == "already_exists" else "Vorschlag"
                body += (f'<li><a href="{e(proposal_link(linked))}">{e(linked.title)}</a> · '
                         f'{e(event_time(linked, self.site.configured_timezone) or "Aufgabe")} · {status}</li>')
        return body + '</ul><p><a href="/abgleich">Zusammenführungen und Dauerannahmen prüfen</a></p></section>'

    def mail_summary(self, mail_id):
        mail = self.site.views.store.peek_model(f"mail-{mail_id}", MailState)
        if mail is None:
            return ""
        body = '<section><h2>Erkannte Vorgänge</h2><ul>'
        if mail.duplicate is not None:
            previous = self.site.views.store.peek_model(f"mail-{mail.duplicate.previous_mail_id}", MailState)
            if previous is not None and (previous.proposal_policy or {}).get("target_profile", 1) != (
                mail.proposal_policy or {}
            ).get("target_profile", 1):
                body += ('<li>Die Kopie gehört zu einem anderen Zielprofil. Es gilt die zuerst verarbeitete Mail; '
                         'hier wurde kein weiterer Vorschlag erzeugt.</li>')
        for item in mail.proposals:
            status = STATUS_LABELS[item.status]
            body += f'<li><a href="{e(proposal_link(item))}">{e(item.title)}</a> · {e(status)}</li>'
        return body + '</ul><p><a href="/abgleich">Gespeicherte Befunde prüfen</a></p></section>'

    def preview(self, request, session):
        try:
            items = self.service.current()
            csrf = self.site.auth.csrf_token(session.id)
            defaults = self.defaults()
            body = ('<div class="setup-page"><h1>Vorschlagsabgleich</h1><p>Lokale Vorschläge und Quellen vergleichen. '
                    'Übernehmen legt nichts extern an; eine neue Version muss separat bestätigt werden.</p>')
            for item in items:
                defaults = self.defaults(item)
                body += (f'<section class="card"><h2><a class="button" href="{e(proposal_link(item))}">'
                         f'{e(item.title)}</a></h2>')
                body += f'<p>Version {item.version} · {e(STATUS_LABELS[item.status])}</p>'
                labels = CALENDAR_LABELS if item.kind == "event" else TASK_LABELS
                provider = labels.get(item.target_provider, item.target_provider or "Anbieter nicht gespeichert")
                body += f'<p>Ziel: {e(provider)} · {e(item.target)}</p>'
                if item.duplicate_check_failed and item.status in OPEN:
                    body += post_form("/abgleich", csrf, '', 'Dublettenprüfung wiederholen',
                        kind="recheck_proposal", mail_id=item.source_mail_id, proposal_id=item.id, version=item.version)
                if item.merge_review_required:
                    assert item.canonical_ref is not None
                    targets = [self.service.resolve(item.canonical_ref)]
                elif item.status in OPEN:
                    remembered = {(r.mail_id, r.proposal_id) for r in item.matching_candidates}
                    targets = [p for p in items if compatible(item, p) and (
                               (p.source_mail_id, p.id) in remembered or p.status in OPEN
                               and relationship(self.service.store, item, p) != "different")]
                else:
                    targets = []
                for target in targets:
                    if target is None:
                        continue
                    fields = dict(mail_id=item.source_mail_id, proposal_id=item.id, version=item.version,
                                  target_mail_id=target.source_mail_id, target_proposal_id=target.id,
                                  target_version=target.version)
                    body += ('<p>Vergleich mit <a href="' + e(proposal_link(target)) + '">' + e(target.title)
                             + f'</a> · Zielversion {target.version}</p><dl><dt>Quelle</dt><dd>{e(item.description)} '
                             + e(event_time(item, self.site.configured_timezone) or item.due or "")
                             + f'</dd><dt>Bisher</dt><dd>{e(target.description)} '
                             + e(event_time(target, self.site.configured_timezone) or target.due or "") + '</dd></dl>')
                    if target.status in OPEN:
                        body += post_form("/abgleich", csrf, '', 'Zusatz ausdrücklich zuordnen',
                                          kind="merge_proposals", **fields)
                    if item.merge_review_required or item.matching_candidates:
                        body += post_form("/abgleich", csrf, '', 'Als eigenen Vorschlag behalten',
                                          kind="separate_proposals", **fields)
                if item.status in OPEN:
                    candidate = reapply_defaults(item, defaults)
                    if candidate.version != item.version:
                        body += '<p>Dauerannahme: ' + e(event_time(candidate, self.site.configured_timezone)) + '</p>'
                        body += post_form("/abgleich", csrf, '', 'Dauerannahme ausdrücklich übernehmen',
                            kind="reapply_defaults", mail_id=item.source_mail_id, proposal_id=item.id,
                            version=item.version, proposal_hash=digest(defaults.model_dump()))
                body += '</section>'
            known = {(p.source_mail_id, p.id) for p in items}
            for name in state_names.mail_state_names(self.site.views.store):
                mail = self.site.views.store.peek_model(name, MailState)
                if mail is None:
                    raise ValueError("Mailzustand fehlt")
                for item in mail.proposals:
                    if (item.source_mail_id, item.id) in known:
                        continue
                    body += (f'<section class="card"><h2>{e(item.title)}</h2>'
                             f'<p>Einzelakte fehlt; Befund {e(STATUS_LABELS[item.status])}.</p>')
                    body += post_form("/abgleich", csrf, '', 'Gespeicherten Befund wiederherstellen',
                        kind="restore_proposal", mail_id=item.source_mail_id, proposal_id=item.id,
                        version=item.version, proposal_hash=digest(item.model_dump(mode="json"))) + '</section>'
            return Response.html(200, layout("Vorschlagsabgleich", body + '</div>'))
        except (CorruptState, ValueError):
            return self.site._reply(request, 409, "Bestand beschädigt oder inzwischen geändert; Abgleich blockiert.")

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
