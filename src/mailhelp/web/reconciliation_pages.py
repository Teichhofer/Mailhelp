"""HTML of the proposal reconciliation; the site supplies the already selected data."""
from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urlencode

from ..external.providers import CALENDAR_LABELS, TASK_LABELS
from ..models import MailState, Proposal
from ..proposals.proposal_reconciliation import OPEN
from ..review.cards import display_date, event_time, shorten
from ..review.views import STATUS_LABELS
from .forms import post_form
from .pages import e, notice

INTRO = ('<div class="setup-page"><h1>Vorschlagsabgleich</h1><p>Lokale Vorschläge und Quellen vergleichen. '
         'Übernehmen legt nichts extern an; eine neue Version muss separat bestätigt werden.</p>')


FOCUS_INTRO = ('<div class="setup-page"><h1>Vorschlagsabgleich</h1><p>Nur dieser Vorschlag und die Vorschläge, '
               'mit denen Mailhelp ihn verwechseln könnte. Übernehmen legt nichts extern an; eine neue Version '
               'muss separat bestätigt werden.</p>')
ALL_LINK = '<p><a href="/abgleich">Alle Vorschläge im Abgleich anzeigen</a></p>'


def focus_link(mail_id: str, proposal_id: str) -> str:
    """5.0.5: the reconciliation restricted to one proposal and its comparison candidates."""
    return "/abgleich?" + urlencode({"mail": mail_id, "vorschlag": proposal_id})


def focus_missing() -> str:
    return notice("Dieser Vorschlag steht nicht mehr zum Abgleich an.", "info") + ALL_LINK


def no_comparison() -> str:
    return notice("Kein anderer Vorschlag steht mehr zum Vergleich an.", "info")


def proposal_link(proposal: Proposal) -> str:
    return f"/vorschlag/{proposal.source_mail_id}/{proposal.id}"


def sources_fragment(proposal: Proposal, linked: list[Proposal], zone: str) -> str:
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


def mail_summary(mail: MailState, other_profile: bool) -> str:
    body = '<section><h2>Erkannte Vorgänge</h2><ul>'
    if other_profile:
        body += ('<li>Die Kopie gehört zu einem anderen Zielprofil. Es gilt die zuerst verarbeitete Mail; '
                 'hier wurde kein weiterer Vorschlag erzeugt.</li>')
    for item in mail.proposals:
        body += f'<li><a href="{e(proposal_link(item))}">{e(item.title)}</a> · {e(STATUS_LABELS[item.status])}</li>'
    return body + '</ul><p><a href="/abgleich">Gespeicherte Befunde prüfen</a></p></section>'


def section_head(item: Proposal, csrf: str) -> str:
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


def _when(proposal: Proposal, zone: str) -> str:
    if proposal.kind == "event":
        return event_time(proposal, zone) or "Zeit nicht angegeben"
    return f"Fällig: {display_date(proposal.due, zone)}" if proposal.due else "Ohne Frist"


def compare_side(this: bool, proposal: Proposal, origin: str, zone: str) -> str:
    """5.0.6: one proposal of a comparison with everything needed to tell it apart.

    5.0.7: the proposal in question stands out by frame, tint and label at a glance."""
    rows = [("Titel", f'<a href="{e(proposal_link(proposal))}">{e(proposal.title)}</a>'),
            ("Art", "📅 Termin" if proposal.kind == "event" else "✅ Aufgabe"),
            ("Zeit" if proposal.kind == "event" else "Frist", e(_when(proposal, zone)))]
    if proposal.location:
        rows.append(("Ort", e(proposal.location)))
    rows += [("Beschreibung", e(proposal.description or "—")),
             ("Beleg", e(shorten(proposal.evidence, 300))),
             ("Herkunft", e(origin)),
             ("Stand", f"Version {proposal.version} · {e(STATUS_LABELS[proposal.status])}")]
    cells = "".join(f"<dt>{name}</dt><dd>{value}</dd>" for name, value in rows)
    variant, label = ("compare-this", "Um diesen Vorschlag geht es") if this else (
        "compare-other", "Möglicherweise dasselbe")
    return (f'<div class="compare-side {variant}"><h3><span class="compare-tag">{label}</span></h3>'
            f'<dl>{cells}</dl></div>')


def comparison(item: Proposal, target: Proposal, zone: str, csrf: str,
               origin: Callable[[Proposal], str]) -> str:
    fields = dict(mail_id=item.source_mail_id, proposal_id=item.id, version=item.version,
                  target_mail_id=target.source_mail_id, target_proposal_id=target.id,
                  target_version=target.version)
    body = ('<div class="compare">' + compare_side(True, item, origin(item), zone)
            + compare_side(False, target, origin(target), zone) + '</div>')
    if target.status in OPEN:
        body += post_form("/abgleich", csrf, '', 'Zusatz ausdrücklich zuordnen', kind="merge_proposals", **fields)
    if item.merge_review_required or item.matching_candidates:
        body += post_form("/abgleich", csrf, '', 'Als eigenen Vorschlag behalten', kind="separate_proposals", **fields)
    return body


def defaults_offer(item: Proposal, candidate: Proposal, defaults_hash: str, zone: str, csrf: str) -> str:
    """A changed default duration is offered for explicit adoption, never applied silently."""
    return ('<p>Dauerannahme: ' + e(event_time(candidate, zone)) + '</p>'
            + post_form("/abgleich", csrf, '', 'Dauerannahme ausdrücklich übernehmen',
                        kind="reapply_defaults", mail_id=item.source_mail_id, proposal_id=item.id,
                        version=item.version, proposal_hash=defaults_hash))


def missing_record(item: Proposal, record_hash: str, csrf: str) -> str:
    """A finding stored in a mail state whose separate proposal file is missing."""
    return (f'<section class="card"><h2>{e(item.title)}</h2>'
            f'<p>Einzelakte fehlt; Befund {e(STATUS_LABELS[item.status])}.</p>'
            + post_form("/abgleich", csrf, '', 'Gespeicherten Befund wiederherstellen',
                        kind="restore_proposal", mail_id=item.source_mail_id, proposal_id=item.id,
                        version=item.version, proposal_hash=record_hash) + '</section>')
