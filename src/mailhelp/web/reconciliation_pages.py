"""HTML of the proposal reconciliation; the site supplies the already selected data."""
from __future__ import annotations

from ..external.providers import CALENDAR_LABELS, TASK_LABELS
from ..proposal_reconciliation import OPEN
from ..review.cards import event_time
from ..review.views import STATUS_LABELS
from .forms import post_form
from .pages import e

INTRO = ('<div class="setup-page"><h1>Vorschlagsabgleich</h1><p>Lokale Vorschläge und Quellen vergleichen. '
         'Übernehmen legt nichts extern an; eine neue Version muss separat bestätigt werden.</p>')


def proposal_link(proposal) -> str:
    return f"/vorschlag/{proposal.source_mail_id}/{proposal.id}"


def sources_fragment(proposal, linked: list, zone: str) -> str:
    """Source mails and related proposals shown on a proposal's detail page."""
    body = '<section><h2>Quellen und zugehörige Vorgänge</h2><ul>'
    for source in proposal.sources:
        body += (f'<li><a href="/mail/{e(source.mail_id)}">Quellenmail</a> · {e(source.subject)} '
                 f'· {e(source.sent_at or "Zeit nicht mehr gespeichert")}</li>')
    for item in linked:
        status = "bereits im Kalender/bei den Aufgaben" if item.status == "already_exists" else "Vorschlag"
        body += (f'<li><a href="{e(proposal_link(item))}">{e(item.title)}</a> · '
                 f'{e(event_time(item, zone) or "Aufgabe")} · {status}</li>')
    return body + '</ul><p><a href="/abgleich">Zusammenführungen und Dauerannahmen prüfen</a></p></section>'


def mail_summary(mail, other_profile: bool) -> str:
    body = '<section><h2>Erkannte Vorgänge</h2><ul>'
    if other_profile:
        body += ('<li>Die Kopie gehört zu einem anderen Zielprofil. Es gilt die zuerst verarbeitete Mail; '
                 'hier wurde kein weiterer Vorschlag erzeugt.</li>')
    for item in mail.proposals:
        body += f'<li><a href="{e(proposal_link(item))}">{e(item.title)}</a> · {e(STATUS_LABELS[item.status])}</li>'
    return body + '</ul><p><a href="/abgleich">Gespeicherte Befunde prüfen</a></p></section>'


def section_head(item, csrf: str) -> str:
    body = (f'<section class="card"><h2><a class="button" href="{e(proposal_link(item))}">'
            f'{e(item.title)}</a></h2>')
    body += f'<p>Version {item.version} · {e(STATUS_LABELS[item.status])}</p>'
    labels = CALENDAR_LABELS if item.kind == "event" else TASK_LABELS
    provider = labels.get(item.target_provider, item.target_provider or "Anbieter nicht gespeichert")
    body += f'<p>Ziel: {e(provider)} · {e(item.target)}</p>'
    if item.duplicate_check_failed and item.status in OPEN:
        body += post_form("/abgleich", csrf, '', 'Dublettenprüfung wiederholen',
            kind="recheck_proposal", mail_id=item.source_mail_id, proposal_id=item.id, version=item.version)
    return body


def comparison(item, target, zone: str, csrf: str) -> str:
    fields = dict(mail_id=item.source_mail_id, proposal_id=item.id, version=item.version,
                  target_mail_id=target.source_mail_id, target_proposal_id=target.id,
                  target_version=target.version)
    body = ('<p>Vergleich mit <a href="' + e(proposal_link(target)) + '">' + e(target.title)
            + f'</a> · Zielversion {target.version}</p><dl><dt>Quelle</dt><dd>{e(item.description)} '
            + e(event_time(item, zone) or item.due or "")
            + f'</dd><dt>Bisher</dt><dd>{e(target.description)} '
            + e(event_time(target, zone) or target.due or "") + '</dd></dl>')
    if target.status in OPEN:
        body += post_form("/abgleich", csrf, '', 'Zusatz ausdrücklich zuordnen', kind="merge_proposals", **fields)
    if item.merge_review_required or item.matching_candidates:
        body += post_form("/abgleich", csrf, '', 'Als eigenen Vorschlag behalten', kind="separate_proposals", **fields)
    return body


def defaults_offer(item, candidate, defaults_hash: str, zone: str, csrf: str) -> str:
    """A changed default duration is offered for explicit adoption, never applied silently."""
    return ('<p>Dauerannahme: ' + e(event_time(candidate, zone)) + '</p>'
            + post_form("/abgleich", csrf, '', 'Dauerannahme ausdrücklich übernehmen',
                        kind="reapply_defaults", mail_id=item.source_mail_id, proposal_id=item.id,
                        version=item.version, proposal_hash=defaults_hash))


def missing_record(item, record_hash: str, csrf: str) -> str:
    """A finding stored in a mail state whose separate proposal file is missing."""
    return (f'<section class="card"><h2>{e(item.title)}</h2>'
            f'<p>Einzelakte fehlt; Befund {e(STATUS_LABELS[item.status])}.</p>'
            + post_form("/abgleich", csrf, '', 'Gespeicherten Befund wiederherstellen',
                        kind="restore_proposal", mail_id=item.source_mail_id, proposal_id=item.id,
                        version=item.version, proposal_hash=record_hash) + '</section>')
