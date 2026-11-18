"""HTML of the proposal reconciliation; the site supplies the already selected data."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode

from ..domain.mail import MailState
from ..domain.proposal import Proposal
from ..external.providers import CALENDAR_LABELS, TASK_LABELS
from ..i18n import msg, tr
from ..proposals.proposal_reconciliation import OPEN
from ..review.cards import display_date, event_time, shorten
from ..review.views import STATUS_LABELS
from .forms import post_form
from .labels import status_badge
from .pages import e, notice, page_head
from .rows import row

INTRO = msg(
    "Lokale Vorschläge und Quellen vergleichen. Übernehmen legt nichts "
    "extern an; eine neue Version muss separat bestätigt werden.",
)


FOCUS_INTRO = msg(
    "Nur dieser Vorschlag und die Vorschläge, mit denen Mailhelp ihn "
    "verwechseln könnte. Übernehmen legt nichts extern an; eine neue Version muss separat bestätigt werden.",
)
ALL_LINK = msg('<p><a href="/abgleich">Alle Vorschläge im Abgleich anzeigen</a></p>')


def intro(*, focus: bool = False) -> str:
    return '<div class="setup-page">' + page_head(
        msg("Vorschlagsabgleich"), msg("Arbeitsbereich"), str(FOCUS_INTRO if focus else INTRO)
    )


def focus_link(mail_id: str, proposal_id: str) -> str:
    """5.0.5: the reconciliation restricted to one proposal and its comparison candidates."""
    return "/abgleich?" + urlencode({"mail": mail_id, "vorschlag": proposal_id})


def focus_missing() -> str:
    return notice(tr("Dieser Vorschlag steht nicht mehr zum Abgleich an."), "info") + ALL_LINK


def no_comparison() -> str:
    return notice(tr("Kein anderer Vorschlag steht mehr zum Vergleich an."), "info")


def proposal_link(proposal: Proposal) -> str:
    return '/vorschlag/{p0}/{p1}'.format(p0=f'{proposal.source_mail_id}', p1=f'{proposal.id}')


def sources_fragment(proposal: Proposal, linked: list[Proposal], zone: str) -> str:
    """Source mails and related proposals shown on a proposal's detail page."""
    body = tr("<section><h2>Quellen und zugehörige Vorgänge</h2><ul>")
    for source in proposal.sources:
        body += (f'<li><a href="/mail/{e(source.mail_id)}">Quellenmail</a> · {e(source.subject)} '
                 f'· {e(source.sent_at or "Zeit nicht mehr gespeichert")}</li>')
    for item in linked:
        status = msg("bereits im Kalender/bei den Aufgaben") if item.status == "already_exists" else msg("Vorschlag")
        body += (f'<li><a href="{e(proposal_link(item))}">{e(item.title)}</a> · '
                 f'{e(event_time(item, zone) or msg('Aufgabe'))} · {status}</li>')
    return body + tr('</ul><p><a href="/abgleich">Zusammenführungen und Dauerannahmen prüfen</a></p></section>')


def mail_summary(mail: MailState, other_profile: bool) -> str:
    body = tr("<section><h2>Erkannte Vorgänge</h2><ul>")
    if other_profile:
        body += tr(
            "<li>Die Kopie gehört zu einem anderen Zielprofil. Es gilt die "
            "zuerst verarbeitete Mail; hier wurde kein weiterer Vorschlag "
            "erzeugt.</li>"
        )
    for item in mail.proposals:
        body += f'<li><a href="{e(proposal_link(item))}">{e(item.title)}</a> · {e(STATUS_LABELS[item.status])}</li>'
    return body + tr('</ul><p><a href="/abgleich">Gespeicherte Befunde prüfen</a></p></section>')


def target_text(item: Proposal) -> str:
    labels = CALENDAR_LABELS if item.kind == "event" else TASK_LABELS
    # 6.2.4: older proposals have no stored service; the target profile decides when confirming.
    return (
        f"{labels.get(item.target_provider, item.target_provider)} · {item.target}"
        if item.target_provider
        else tr("Zielprofil „{p0}“", p0=f"{item.target}")
    )


def proposal_row(item: Proposal) -> str:
    """6.2.7: a proposal without comparison or offer is one row: title, version, target, status."""
    return row(
        proposal_link(item),
        item.title,
        tr("Version {p0} · Ziel: {p1}", p0=f"{item.version}", p1=f"{target_text(item)}"),
        status_badge(item.status),
    )


def section_head(item: Proposal, csrf: str) -> str:
    body = (f'<section class="card"><h2 class="row-heading"><a href="{e(proposal_link(item))}">{e(item.title)}</a> '
            f'{status_badge(item.status)}</h2>')
    body += tr('<p class="meta">Version {p0} · Ziel: {p1}</p>', p0=item.version, p1=e(target_text(item)))
    if item.duplicate_check_failed and item.status in OPEN:
        body += post_form(
            "/abgleich",
            csrf,
            "",
            msg("Dublettenprüfung wiederholen"),
            kind="recheck_proposal",
            mail_id=item.source_mail_id,
            proposal_id=item.id,
            version=item.version,
        )
    return body


def _when(proposal: Proposal, zone: str) -> str:
    if proposal.kind == "event":
        return event_time(proposal, zone) or msg("Zeit nicht angegeben")
    return tr("Fällig: {p0}", p0=display_date(proposal.due, zone)) if proposal.due else msg("Ohne Frist")


def compare_side(this: bool, proposal: Proposal, origin: str, zone: str) -> str:
    """5.0.6: one proposal of a comparison with everything needed to tell it apart.

    5.0.7: the proposal in question stands out by frame, tint and label at a glance."""
    rows = [
        (msg("Titel"), f'<a href="{e(proposal_link(proposal))}">{e(proposal.title)}</a>'),
        (msg("Art"), msg("📅 Termin") if proposal.kind == "event" else msg("✅ Aufgabe")),
        (msg("Zeit") if proposal.kind == "event" else msg("Frist"), e(_when(proposal, zone))),
    ]
    if proposal.location:
        rows.append((msg("Ort"), e(proposal.location)))
    rows += [
        (msg("Beschreibung"), e(proposal.description or "—")),
        (msg("Beleg"), e(shorten(proposal.evidence, 300))),
        ("Herkunft", e(origin)),
        (msg("Stand"), f"Version {proposal.version} · {e(STATUS_LABELS[proposal.status])}"),
    ]
    cells = "".join(f"<dt>{name}</dt><dd>{value}</dd>" for name, value in rows)
    variant, label = (
        ("compare-this", msg("Um diesen Vorschlag geht es"))
        if this
        else ("compare-other", msg("Möglicherweise dasselbe"))
    )
    return (f'<div class="compare-side {variant}"><h3><span class="compare-tag">{label}</span></h3>'
            f'<dl>{cells}</dl></div>')


def comparison(item: Proposal, target: Proposal, zone: str, csrf: str,
               origin: Callable[[Proposal], str]) -> str:
    fields: dict[str, Any] = dict(mail_id=item.source_mail_id, proposal_id=item.id, version=item.version,
                  target_mail_id=target.source_mail_id, target_proposal_id=target.id,
                  target_version=target.version)
    body = ('<div class="compare">' + compare_side(True, item, origin(item), zone)
            + compare_side(False, target, origin(target), zone) + '</div>')
    item_title = shorten(item.title, 80)
    target_title = shorten(target.title, 80)
    if target.status in OPEN:
        body += tr(
            (
                "<p>Fügt die Angaben aus „{p0}“ zu „{p1}“ hinzu. Es entsteht kein "
                "zweiter Eintrag; den ergänzten Vorschlag bestätigst du danach "
                "unter Offen.</p>"
            ),
            p0=e(item_title),
            p1=e(target_title),
        ) + post_form(
            "/abgleich",
            csrf,
            "",
            msg("Zu diesem Eintrag hinzufügen"),
            primary=item.merge_review_required,
            kind="merge_proposals",
            **fields,
        )
    if item.merge_review_required or item.matching_candidates:
        body += tr("<p>Beide bleiben getrennte Vorschläge unter Offen.</p>")
        body += post_form(
            "/abgleich", csrf, "", msg("Als eigenen Vorschlag behalten"), kind="separate_proposals", **fields
        )
    return body


def defaults_offer(item: Proposal, candidate: Proposal, defaults_hash: str, zone: str, csrf: str) -> str:
    """A changed default duration is offered for explicit adoption, never applied silently."""
    return (
        "<p>Dauerannahme: "
        + e(event_time(candidate, zone))
        + "</p>"
        + post_form(
            "/abgleich",
            csrf,
            "",
            msg("Dauerannahme übernehmen"),
            kind="reapply_defaults",
            mail_id=item.source_mail_id,
            proposal_id=item.id,
            version=item.version,
            proposal_hash=defaults_hash,
        )
    )


def missing_record(item: Proposal, record_hash: str, csrf: str) -> str:
    """A finding stored in a mail state whose separate proposal file is missing."""
    return (
        tr(
            ('<section class="card"><h2>{p0}</h2><p>Einzelakte fehlt; Befund {p1}.</p>'),
            p0=e(item.title),
            p1=e(STATUS_LABELS[item.status]),
        )
        + post_form(
            "/abgleich",
            csrf,
            "",
            msg("Gespeicherten Befund wiederherstellen"),
            kind="restore_proposal",
            mail_id=item.source_mail_id,
            proposal_id=item.id,
            version=item.version,
            proposal_hash=record_hash,
        )
        + "</section>"
    )
